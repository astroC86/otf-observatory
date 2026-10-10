"""Inspectable trace-semantic completion prerequisites and delay accounting.

These edges identify why an operation could not complete before another recorded
operation. Their durations are prerequisite-unavailable intervals, not measured
scheduler sleep or CPU idle time, and are not claimed to be recovered formulas.
"""

from __future__ import annotations
import collections
import dataclasses
import functools
import math
import json
import itertools

_MISSING = object()
_CACHE_SIZE = 1024
_BOUNDARY_KINDS = "('Enter','Leave','CallingContextEnter','CallingContextLeave')"
_PREFETCH_BATCH = 256  # 3 variables per key; stays below SQLite's historical 999 limit.


def tied(candidates, time):
    # Inclusive timestamps alone cannot distinguish the Leave of one call
    # from the Enter of its successor at exactly the same clock tick.
    for s in candidates:
        if s.start == time or s.end == time:
            return True
    return False


@functools.lru_cache(maxsize=4096)
def _region(data):
    # Boundary payloads repeat heavily (one per region), so parse each once.
    return str(json.loads(data).get("region"))


class BoundaryOrder:
    """Resolve adjacent same-tick invocations using original boundary order."""

    def __init__(self, trace, max_boundaries=None):
        self.trace = trace
        self.cache = collections.OrderedDict()
        self.prefetched = {}
        self.ambiguous = 0
        self.max_boundaries = max_boundaries
        self.limited = 0

    def _rows(self, sql, args):
        with self.trace.connect() as db:
            cursor = db.cursor()
            cursor.row_factory = None
            return cursor.execute(sql, args).fetchall()

    def _boundaries(self, rows):
        """(id, kind, region) per boundary; None beyond max_boundaries."""
        if self.max_boundaries is not None and len(rows) > self.max_boundaries:
            return None
        return [
            (ident, kind, _region(data) if kind in ("Enter", "Leave") else None)
            for ident, kind, data in rows
        ]

    def prefetch(self, keys):
        """Load boundaries for upcoming (location, time) keys in batched queries.

        Only the most recent prefetch is retained, bounding memory by its keys.
        """
        keys = list(dict.fromkeys(keys))
        self.prefetched = {}
        for offset in range(0, len(keys), _PREFETCH_BATCH):
            batch = keys[offset : offset + _PREFETCH_BATCH]
            found = [[] for _ in batch]
            # INDEXED BY: some batch sizes otherwise build an automatic
            # index over every boundary event.
            for slot, *row in self._rows(
                "WITH k(slot,location,time) AS (VALUES "
                + ",".join("(?,?,?)" for _ in batch)
                + ") SELECT k.slot,e.id,e.kind,e.data FROM k JOIN events e"
                " INDEXED BY ev_loc ON e.location=k.location AND e.time=k.time"
                " WHERE e.kind IN " + _BOUNDARY_KINDS + " ORDER BY e.id",
                [value for slot, key in enumerate(batch) for value in (slot, *key)],
            ):
                found[slot].append(row)
            self.prefetched.update(zip(batch, map(self._boundaries, found)))

    def filter(self, candidates, location, time, event):
        if event is None or not tied(candidates, time):
            return candidates
        key = (location, time)
        boundaries = self.cache.get(key, _MISSING)
        if boundaries is _MISSING:
            boundaries = self.prefetched.get(key, _MISSING)
        if boundaries is _MISSING:
            sql = (
                "SELECT id,kind,data FROM events WHERE location=? AND time=? AND kind IN "
                + _BOUNDARY_KINDS
                + " ORDER BY id"
            )
            args = key
            if self.max_boundaries is not None:
                sql += " LIMIT ?"
                args = (*key, self.max_boundaries + 1)
            boundaries = self.cache[key] = self._boundaries(self._rows(sql, args))
            while len(self.cache) > _CACHE_SIZE:
                self.cache.popitem(last=False)
        if boundaries is None:
            self.limited += 1
            return []
        relevant = {s.region for s in candidates}
        if not any(
            region in relevant for _, k, region in boundaries if k in ("Enter", "Leave")
        ):
            if len(candidates) > 1 or any(
                k.startswith("CallingContext") for _, k, _ in boundaries
            ):
                self.ambiguous += 1
                return []
            # Legacy/manual indexes may have one normalized interval and
            # no original boundary records. Preserve that unique match;
            # any actual contradictory boundary below takes precedence.
            return candidates
        active = {s.id: s for s in candidates if s.start < time}
        unentered = sorted(
            (s for s in candidates if s.start == time), key=lambda s: s.id
        )
        for ident, kind, region in boundaries:
            # Attributes on Enter belong to its newly entered invocation;
            # attributes on Leave belong to the invocation before pop.
            if ident > event or ident == event and kind != "Enter":
                break
            if kind.startswith("CallingContext"):
                # The importer can synthesize multiple context transitions
                # from one record; do not infer their invocation ordering.
                self.ambiguous += 1
                return []
            if kind == "Enter":
                entered = next((s for s in unentered if s.region == region), None)
                if entered:
                    active[entered.id] = entered
                    unentered.remove(entered)
            else:
                leaving = max(
                    (s for s in active.values() if s.region == region),
                    key=lambda s: (s.depth, s.start, s.id),
                    default=None,
                )
                if leaving:
                    active.pop(leaving.id)
        return list(active.values())


class _EvidenceFields:
    """Mapping access shared by slotted identities and causal evidence."""

    __slots__ = ()

    def __getitem__(self, key):
        if key in self.__slots__ and key != "extra":
            return getattr(self, key)
        return self._extra_value(key)

    def _extra_value(self, key):
        if self.extra is not None and key in self.extra:
            return self.extra[key]
        raise KeyError(key)

    def __setitem__(self, key, value):
        if key in self.__slots__ and key != "extra":
            setattr(self, key, value)
        else:
            if self.extra is None:
                self.extra = {}
            self.extra[key] = value


@dataclasses.dataclass(slots=True)
class Operation(_EvidenceFields):
    location: str | None
    span: int | None
    event: int | None
    region: str | None
    routine: str | None
    start: float | None
    end: float | None
    extra: dict | None = None

    def update(self, **values):
        for key, value in values.items():
            self[key] = value

    def as_dict(self):
        return dict(
            location=self.location,
            span=self.span,
            event=self.event,
            region=self.region,
            routine=self.routine,
            start=self.start,
            end=self.end,
            **(self.extra or {}),
        )


@dataclasses.dataclass(slots=True)
class Cause(_EvidenceFields):
    id: str
    type: str
    source: Operation
    target: Operation
    start: float
    end: float
    ready: float
    required: bool
    confidence: str
    reason: str
    message: int | None
    request: tuple | None
    communicator: str | None
    extra: dict | None = None
    # Full target-record context for individually inspected lazy prerequisites.
    # These hints are internal and never expand the public evidence schema.
    limiting_ready: float | None = None
    limiting_eligible: bool | None = None

    def _extra_value(self, key):
        if key == "dependency":
            return dict(start=self.start, end=self.end, duration=self.end - self.start)
        if key == "readinessTime":
            return self.ready
        if key == "relation":
            return (
                "required-precondition" if self.required else "conditional-precondition"
            )
        return _EvidenceFields._extra_value(self, key)

    def as_dict(self, start, end):
        return dict(
            id=self.id,
            type=self.type,
            source=self.source.as_dict(),
            target=self.target.as_dict(),
            relation=(
                "required-precondition" if self.required else "conditional-precondition"
            ),
            confidence=self.confidence,
            reason=self.reason,
            message=self.message,
            request=(
                dict(id=self.request[0], generation=self.request[1])
                if self.request
                else None
            ),
            communicator=self.communicator,
            readinessTime=self.ready,
            dependency=dict(start=start, end=end, duration=end - start),
            **(self.extra or {}),
        )


def operation(span=None, *, location=None, event=None, time=None, routine=None):
    """Keep compact operation identities; expand dictionaries only for a page."""
    location = span.location if span is not None else location
    return Operation(
        str(location) if location is not None else None,
        span.id if span is not None and span.id > 0 else None,
        event,
        span.region if span is not None else None,
        span.name if span is not None else routine,
        span.start if span is not None else time,
        span.end if span is not None else time,
    )


def prerequisite(
    ident,
    kind,
    source,
    target,
    ready,
    *,
    required=True,
    confidence=None,
    reason="",
    message=None,
    request=None,
    communicator=None,
    target_start=None,
    target_end=None,
):
    """Construct an edge without inventing a duration for inconsistent clocks."""
    start = target["start"] if target_start is None else target_start
    end = target["end"] if target_end is None else target_end
    for value in (start, end, ready):
        if value is None or not math.isfinite(value):
            return None
    if end < start or ready > end:
        return None
    stop = max(start, ready)
    return Cause(
        ident,
        kind,
        source,
        target,
        start,
        stop,
        ready,
        required,
        confidence or ("recorded-dependency" if required else "conditional"),
        reason,
        message,
        (request["id"], request["generation"]) if request else None,
        communicator,
    )


def clipped(causes, start, end, *, offset=0, limit=None):
    """Clip dependency time only; preserve the original operation identities."""
    if hasattr(causes, "limiting"):
        has_required, latest = causes.limiting()
    else:
        required = [c for c in causes if c is not None and c.required]
        candidates = required or causes
        has_required = bool(required)
        latest = max((c.ready for c in candidates if c is not None), default=None)
    page = (
        causes.page(offset, limit)
        if hasattr(causes, "page")
        else itertools.islice(causes, offset, None if limit is None else offset + limit)
    )
    result = []
    for cause in page:
        if cause is None:
            continue
        a = min(end, max(start, cause.start))
        b = max(a, min(end, cause.end))
        item = cause.as_dict(a, b)
        eligible = (
            cause.limiting_eligible
            if not hasattr(causes, "limiting") and cause.limiting_eligible is not None
            else cause.required or not has_required
        )
        threshold = (
            cause.limiting_ready
            if not hasattr(causes, "limiting") and cause.limiting_ready is not None
            else latest
        )
        item["limiting"] = eligible and cause.ready == threshold and b > a
        result.append(item)
    return result


def union(pairs):
    """Total length covered by (start, end) pairs."""
    end = -math.inf
    duration = 0.0
    for a, b in sorted(pairs):
        gap = b - (end if end > a else a)
        if gap > 0.0:
            duration += gap
        if b > end:
            end = b
    return duration


def totals(rows, *, selected=False):
    """Count union time per waiting location, never sum overlapping causes."""
    intervals = collections.defaultdict(lambda: collections.defaultdict(list))
    edges = 0
    for row in rows:
        causes, start, end = row if selected else (row, -math.inf, math.inf)
        if hasattr(causes, "summary_for_totals"):
            for count, relation, location, a, b in causes.summary_for_totals(
                start, end
            ):
                edges += count
                if b > a:
                    intervals[relation][location].append((a, b))
            continue
        for cause in causes:
            edges += 1
            if isinstance(cause, Cause):
                a = min(end, max(start, cause.start))
                b = max(a, min(end, cause.end))
                relation = (
                    "required-precondition"
                    if cause.required
                    else "conditional-precondition"
                )
                location = cause.target.location
            else:
                d = cause["dependency"]
                a = max(start, d["start"])
                b = min(end, d["end"])
                relation = cause["relation"]
                location = cause["target"]["location"]
            if b > a:
                intervals[relation][location].append((a, b))
    return dict(
        causeCount=edges,
        required=sum(union(p) for p in intervals["required-precondition"].values()),
        conditional=sum(
            union(p) for p in intervals["conditional-precondition"].values()
        ),
        interpretation="Union of pre-prerequisite intervals per waiting location. Required means completion dependency, not measured CPU blocked time; conditional edges additionally depend on protocol or unavailable posting details.",
    )
