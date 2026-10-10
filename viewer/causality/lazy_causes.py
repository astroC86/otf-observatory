"""Exact shared collective prerequisites, expanded only for inspected pages.

A complete N-member barrier has N*(N-1) logical edges. Store its N source
operations once and one target view per waiting operation. Neither accounting
nor overlap queries need to construct the complete edge set.
"""

from __future__ import annotations

import bisect
import math

from .operations import Cause


class BarrierCohort:
    __slots__ = (
        "id",
        "communicator",
        "peers",
        "ready",
        "positions",
        "kind",
        "reason",
        "expected_prerequisites",
        "extra",
    )

    def __init__(
        self,
        ident,
        communicator,
        peers,
        *,
        kind="barrier_arrival",
        reason="A barrier cannot complete before every communicator participant enters.",
        expected_prerequisites=None,
        extra=None,
    ):
        # Stable time order permits O(log N + returned edges) overlap queries.
        self.id = ident
        self.communicator = communicator
        self.peers = tuple(sorted(peers, key=lambda p: p[2]))
        self.ready = tuple(p[2] for p in self.peers)
        self.positions = {str(p[0]): i for i, p in enumerate(self.peers)}
        if len(self.positions) != len(self.peers):
            raise ValueError("A collective cohort must have unique participants")
        if any(not math.isfinite(t) for t in self.ready):
            raise ValueError("Collective readiness times must be finite")
        self.kind = kind
        self.reason = reason
        self.expected_prerequisites = (
            len(self.peers) - 1
            if expected_prerequisites is None
            else expected_prerequisites
        )
        self.extra = extra or {}

    @property
    def storage_weight(self):
        return 1 + len(self.peers)

    def view(
        self,
        participant,
        target,
        target_id,
        *,
        required=True,
        request=None,
        target_start=None,
        target_end=None,
    ):
        return BarrierView(
            self,
            participant,
            target,
            target_id,
            required=required,
            request=request,
            target_start=target_start,
            target_end=target_end,
        )


class BarrierView:
    __slots__ = (
        "cohort",
        "target",
        "target_id",
        "excluded",
        "stop",
        "required",
        "request",
        "id",
        "start",
        "end",
        "ready",
        "_limiting",
    )

    def __init__(
        self,
        cohort,
        participant,
        target,
        target_id,
        *,
        required=True,
        request=None,
        target_start=None,
        target_end=None,
    ):
        self.cohort = cohort
        self.target = target
        self.target_id = str(target_id)
        self.id = f"{cohort.id}:target:{self.target_id}"
        self.required = required
        self.request = (request["id"], request["generation"]) if request else None
        # Native thread-barrier accounting may start at a later nested-region
        # boundary. Keep the original routine identity for navigation/context.
        self.start = target.start if target_start is None else target_start
        end = target.end if target_end is None else target_end
        valid = (
            self.start is not None
            and end is not None
            and math.isfinite(self.start)
            and math.isfinite(end)
            and end >= self.start
        )
        self._select(participant, end, valid)
        self.end = max(self.start, self.ready) if self.ready is not None else self.start
        self._limiting = [
            self.ready if required else None,
            None if required else self.ready,
        ]

    def _select(self, participant, end, valid):
        cohort = self.cohort
        self.stop = bisect.bisect_right(cohort.ready, end) if valid else 0
        self.excluded = cohort.positions.get(str(participant), -1)
        last = self.stop - 1
        if last == self.excluded:
            last -= 1
        self.ready = cohort.ready[last] if last >= 0 else None

    def __len__(self):
        return self.stop - (0 <= self.excluded < self.stop)

    def _cause(self, position):
        participant, source, ready = self.cohort.peers[position]
        required_ready, conditional_ready = self._limiting
        return Cause(
            f"{self.cohort.id}:peer:{participant}:target:{self.target_id}",
            self.cohort.kind,
            source,
            self.target,
            self.start,
            max(self.start, ready),
            ready,
            self.required,
            "recorded-dependency" if self.required else "conditional",
            self.cohort.reason,
            None,
            self.request,
            self.cohort.communicator,
            dict(
                cohort=self.cohort.id,
                expectedPrerequisites=self.cohort.expected_prerequisites,
                **self.cohort.extra,
            ),
            limiting_ready=(
                required_ready if required_ready is not None else conditional_ready
            ),
            limiting_eligible=self.required or required_ready is None,
        )

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return self._cause(index + (0 <= self.excluded <= index))

    def __iter__(self):
        return (self._cause(i) for i in range(self.stop) if i != self.excluded)

    def resolve(self, ident):
        prefix = self.cohort.id + ":peer:"
        suffix = ":target:" + self.target_id
        if not ident.startswith(prefix) or not ident.endswith(suffix):
            return None
        participant = ident[len(prefix) : -len(suffix)]
        index = self.cohort.positions.get(participant)
        if index is None or index == self.excluded or index >= self.stop:
            return None
        return self._cause(index)

    def overlapping(self, start, end, limit):
        """Positive intersections only, latest readiness first, bounded output."""
        if (
            not self
            or limit <= 0
            or end <= start
            or self.start >= end
            or self.end <= start
        ):
            return
        for count, index in enumerate(self._overlap_indices(max(start, self.start)), 1):
            yield self._cause(index)
            if count >= limit:
                return

    def _overlap_indices(self, threshold):
        first = bisect.bisect_right(self.cohort.ready, threshold)
        return (
            index
            for index in range(self.stop - 1, first - 1, -1)
            if index != self.excluded
        )


class CauseCollection:
    """Mutable list-compatible collection with exact compressed target views."""

    __slots__ = ("_entries", "_length", "_limiting")

    def __init__(self, causes=()):
        self._entries = []
        self._length = 0
        self._limiting = [None, None]
        self.extend(causes)

    def append(self, cause):
        if cause is None:
            return
        count = len(cause) if isinstance(cause, BarrierView) else 1
        if not count:
            return
        self._entries.append(cause)
        self._length += count
        index = 0 if cause.required else 1
        latest = self._limiting[index]
        self._limiting[index] = (
            cause.ready if latest is None else max(latest, cause.ready)
        )
        if isinstance(cause, BarrierView):
            cause._limiting = self._limiting

    def extend(self, causes):
        entries = (
            causes.query_entries() if isinstance(causes, CauseCollection) else causes
        )
        for cause in entries:
            self.append(cause)

    def __len__(self):
        return self._length

    @property
    def storage_weight(self):
        # Cohorts are accounted once separately by the analysis builder.
        return 1 + len(self._entries)

    def query_entries(self):
        return iter(self._entries)

    def __iter__(self):
        for entry in self._entries:
            if isinstance(entry, BarrierView):
                yield from entry
            else:
                yield entry

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        for entry in self._entries:
            count = len(entry) if isinstance(entry, BarrierView) else 1
            if index < count:
                return entry[index] if isinstance(entry, BarrierView) else entry
            index -= count
        raise IndexError(index)

    def page(self, offset=0, limit=None):
        remaining = len(self) if limit is None else max(0, limit)
        for entry in self._entries:
            if not remaining:
                return
            count = len(entry) if isinstance(entry, BarrierView) else 1
            if offset >= count:
                offset -= count
                continue
            take = min(remaining, count - offset)
            if isinstance(entry, BarrierView):
                for index in range(offset, offset + take):
                    yield entry[index]
            else:
                yield entry
            remaining -= take
            offset = 0

    def resolve(self, ident):
        for entry in self._entries:
            cause = (
                entry.resolve(ident)
                if isinstance(entry, BarrierView)
                else entry if entry.id == ident else None
            )
            if cause is not None:
                # The internal hint also preserves full-record limiting status
                # when a single resolved edge is inspected or exported.
                required_ready, conditional_ready = self._limiting
                cause.limiting_ready = (
                    required_ready if required_ready is not None else conditional_ready
                )
                cause.limiting_eligible = cause.required or required_ready is None
                return cause
        return None

    def limiting(self):
        required, conditional = self._limiting
        return required is not None, required if required is not None else conditional

    def summary_for_totals(self, start, end):
        for entry in self._entries:
            count = len(entry) if isinstance(entry, BarrierView) else 1
            a = min(end, max(start, entry.start))
            b = max(a, min(end, entry.end))
            yield count, (
                "required-precondition"
                if entry.required
                else "conditional-precondition"
            ), entry.target.location, a, b

    def overlapping(self, start, end, limit):
        if end <= start or limit <= 0:
            return
        remaining = limit
        for entry in self._entries:
            if remaining <= 0:
                return
            candidates = (
                entry.overlapping(start, end, remaining)
                if isinstance(entry, BarrierView)
                else (
                    (entry,)
                    if entry.start < end and entry.end > max(start, entry.start)
                    else ()
                )
            )
            for cause in candidates:
                yield cause
                remaining -= 1
