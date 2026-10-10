"""OTF2 thread-lock ownership overlapping an instrumented acquisition.

Acquisition ordinals match ownership, even when clocks disagree. They do not
measure blocking. Timing attribution additionally needs consistent endpoints.
"""

import re
import bisect
import json

from ..causality.operations import operation, prerequisite
from ..mpi.rma_lock_intervals import _index, _overlap
from ..tasks.identity import process_scope
from .nested_locks import annotate_nested_locks, nested_ownership
from ..trace.event_spans import WorkBudget
from .synchronization_model import Record

WORK_LIMIT = 2_000_000
LOCK_KINDS = (
    "ThreadAcquireLock",
    "ThreadReleaseLock",
    "OmpAcquireLock",
    "OmpReleaseLock",
)
MEASUREMENT_LIMIT = 100_000


def _recording_gaps(trace, locks, diagnostics):
    """A balanced endpoint pair cannot prove ownership through lost recording."""
    if not locks:
        return
    markers = trace.rows(
        "SELECT id,location,data FROM events WHERE kind='MeasurementOnOff' ORDER BY id LIMIT ?",
        [MEASUREMENT_LIMIT + 1],
    )
    limited = len(markers) > MEASUREMENT_LIMIT
    by_location = {}
    for marker in markers:
        data = json.loads(marker["data"])
        mode = data.get("measurementMode")
        by_location.setdefault(str(marker["location"]), []).append(
            (marker["id"], type(mode) is int and mode == 1)
        )
    if limited:
        diagnostics["lock_recording_scan_limit"] += 1
    for orders in locks.values():
        for events in orders.values():
            endpoints = events["acquire"] + events["release"]
            gap = limited
            for location in {str(event["location"]) for event in endpoints}:
                local = [
                    event["id"]
                    for event in endpoints
                    if str(event["location"]) == location
                ]
                values = by_location.get(location, [])
                first, last = min(local), max(local)
                index = bisect.bisect_left(values, (first,))
                # OFF/unknown before acquisition remains unresolved until ON.
                # Any resume inside ownership also implies a missing section,
                # even when its preceding OFF record is absent.
                gap |= bool(index and not values[index - 1][1]) or bool(
                    index < len(values) and values[index][0] <= last
                )
            if gap:
                diagnostics["lock_recording_gap"] += 1
                for action in ("acquire", "release"):
                    events[action] = [
                        dict(event, _lockRecordingGap=True) for event in events[action]
                    ]


def collect_locks(trace, events, diagnostics, *, complete=True):
    """Use the same validated identity namespace in wait and graph analysis."""
    from collections import defaultdict

    locks = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for event in events:
        if event["kind"] not in LOCK_KINDS:
            continue
        data = event["data"]
        lock, order, model = (
            data.get("lockID"),
            data.get("acquisitionOrder"),
            data.get("model", 3),
        )
        if order is None:
            diagnostics["lock_order_missing"] += 1
            continue
        if any(
            type(value) is not int or not 0 <= value < 2**32
            for value in (lock, order, model)
        ):
            diagnostics["lock_identity_invalid"] += 1
            continue
        key = (process_scope(trace.defs, event["location"]), str(model), str(lock))
        locks[key][order][
            "acquire" if "Acquire" in event["kind"] else "release"
        ].append(event)
    _recording_gaps(trace, locks, diagnostics)
    if complete:
        annotate_nested_locks(trace, locks, diagnostics)
    return locks


def ownership_pairs(orders, diagnostics):
    """Preserve incomplete/ambiguous records without inventing ownership."""
    pairs = []
    for ordinal, events in sorted(orders.items()):
        acquisitions, releases = events["acquire"], events["release"]
        acquire = acquisitions[0] if len(acquisitions) == 1 else None
        release = releases[0] if len(releases) == 1 else None
        ambiguous = len(acquisitions) > 1 or len(releases) > 1
        nesting = nested_ownership(acquisitions, releases) if ambiguous else None
        if nesting:
            acquire, release, nested_pairs, nested_evidence = nesting
            ambiguous = False
        valid = bool(acquire and release and not ambiguous)
        status = (
            "complete"
            if valid
            else (
                "ambiguous ownership"
                if ambiguous
                else "missing release" if acquire else "missing acquire"
            )
        )
        if ambiguous:
            diagnostics["lock_order_ambiguous"] += 1
        if valid and acquire["location"] != release["location"]:
            diagnostics["lock_owner_mismatch"] += 1
            valid = False
            status = "owner mismatch"
        if valid and (
            acquire["time"] > release["time"] or acquire["id"] >= release["id"]
        ):
            diagnostics["lock_clock_conflict"] += 1
            valid = False
            status = "clock or event-order conflict"
        if any(event.get("_lockRecordingGap") for event in acquisitions + releases):
            valid = False
            status = "recording gap during ownership"
        pairs.append(
            dict(
                order=ordinal,
                acquire=acquire,
                release=release,
                valid=valid,
                ambiguous=ambiguous,
                status=status,
                acquisitions=acquisitions,
                releases=releases,
                contradictory=False,
                nestedPairs=nested_pairs if nesting else [],
                nestedOwnership=nested_evidence if nesting else None,
            )
        )
    return pairs


def _mode(span):
    # OTF2 has no mode field. A recognized routine can establish its contract;
    # a raw ownership record or an unrecognized shared-lock wrapper cannot.
    if span is None or span.sampled or span.incomplete:
        return None
    name = span.name
    if re.search(r"pthread_rwlock_rdlock|::lock_shared\b", name, re.I):
        return "shared"
    if re.search(
        r"pthread_rwlock_wrlock|shared_(?:timed_)?mutex.*::lock(?:\(|$)", name, re.I
    ):
        return "exclusive"
    if re.search(r"rwlock|shared_mutex|shared_lock", name, re.I):
        return None
    return "exclusive"


def _exclusive(span):
    return _mode(span) == "exclusive"


def attribute_locks(
    locks,
    lookup,
    records,
    diagnostics,
    *,
    complete=True,
    release_lookup=None,
):
    """Populate wait records without extending delay across unowned gaps.

    ``locks`` is scoped by process/paradigm/lock, then acquisition ordinal.
    The bounded interval index includes every complete earlier owner, not only
    the immediately preceding ordinal. Incomplete history never fabricates an
    owner or a required release.
    """
    charge = WorkBudget(WORK_LIMIT)
    staged = []
    try:
        # One routine may contain several acquisition records, including
        # different lock identities. Resolve multiplicity across all resources
        # before assigning a single acquire boundary to that routine.
        matched_spans = {}
        invocations = {}
        ambiguous_routines = set()
        for orders in locks.values():
            for events in orders.values():
                for acquire in events["acquire"]:
                    charge()
                    span = lookup.at(
                        acquire["location"],
                        acquire["time"],
                        {"lock_acquire", "lock_test", "critical_acquire"},
                        event=acquire["id"],
                    )
                    matched_spans[acquire["id"]] = span
                    if span is not None:
                        invocations[span.id] = invocations.get(span.id, 0) + 1
        for key, orders in locks.items():
            pairs = ownership_pairs(orders, diagnostics)
            for pair in pairs:
                ordinal, acquire = pair["order"], pair["acquire"]
                span = matched_spans.get(acquire["id"]) if acquire else None
                pair["span"] = span
                if not acquire:
                    continue
                if span is None:
                    diagnostics["lock_acquire_without_routine"] += 1
                    continue
                record = records.get(span.id)
                if invocations[span.id] > 1:
                    if span.id not in ambiguous_routines:
                        diagnostics["lock_routine_multiple_acquisitions"] += 1
                        ambiguous_routines.add(span.id)
                    if record is not None:
                        record.inferred_intervals = []
                        record.confidence = "ambiguous-lock-acquisition"
                        record.evidence["lockAttributionUnavailable"] = (
                            "Several acquisitions share one instrumented invocation"
                        )
                        record.evidence.setdefault("lockAcquisitions", []).append(
                            dict(
                                event=acquire["id"],
                                time=acquire["time"],
                                process=key[0],
                                model=key[1],
                                lock=key[2],
                                acquisitionOrder=ordinal,
                            )
                        )
                    # Critical regions have no separate attempt boundary here;
                    # keep their raw lock records without charging their body.
                    continue
                if span.category == "critical_acquire":
                    record = records.setdefault(
                        span.id,
                        Record(
                            span,
                            span.start,
                            acquire["time"],
                            "lock_acquire",
                            span.start,
                            upper_end=acquire["time"],
                        ),
                    )
                record.evidence.update(
                    lock=key[2],
                    process=key[0],
                    model=key[1],
                    acquisitionOrder=ordinal,
                    acquireEvent=acquire["id"],
                    acquireTime=acquire["time"],
                )
                record.inferred_intervals = (
                    []
                    if record.inferred_intervals is None
                    else record.inferred_intervals
                )
                if record.category != "lock_test":
                    record.upper_end = min(record.upper_end, acquire["time"])
                pair["record"] = record
                if pair["valid"] and pair["nestedOwnership"] is not None:
                    record.evidence["nestedOwnership"] = pair["nestedOwnership"]

            if not complete:
                continue
            ambiguous_history = any(p["ambiguous"] for p in pairs)
            owners = [p for p in pairs if p["valid"]]
            index = _index(owners)
            exclusive_index = _index([p for p in owners if _exclusive(p["span"])])
            # Different owners cannot overlap when either known acquisition is
            # exclusive. Same-thread nesting may represent a recursive lock.
            for owner in owners:
                for peer in _overlap(
                    index if _exclusive(owner["span"]) else exclusive_index,
                    owner["acquire"]["time"],
                    owner["release"]["time"],
                ):
                    charge()
                    if (
                        peer["order"] <= owner["order"]
                        or peer["acquire"]["location"] == owner["acquire"]["location"]
                    ):
                        continue
                    owner["contradictory"] = peer["contradictory"] = True
                    diagnostics["lock_overlapping_owners"] += 1

            for pair in pairs:
                if ambiguous_history or not pair["valid"] or pair["contradictory"]:
                    continue
                for nested_acquire, nested_release, depth in pair["nestedPairs"]:
                    if depth == 1:
                        continue
                    nested_span = matched_spans.get(nested_acquire["id"])
                    nested_record = records.get(nested_span.id) if nested_span else None
                    if nested_record is not None and invocations[nested_span.id] == 1:
                        nested_record.upper_end = nested_record.start
                        nested_record.confidence = "recorded-recursive-acquisition"
                        nested_record.evidence.update(
                            lock=key[2],
                            process=key[0],
                            model=key[1],
                            acquisitionOrder=pair["order"],
                            acquireEvent=nested_acquire["id"],
                            acquireTime=nested_acquire["time"],
                            recursionDepth=depth,
                            matchingNestedRelease=nested_release["id"],
                            outerAcquireEvent=pair["acquire"]["id"],
                            outerReleaseEvent=pair["release"]["id"],
                            contentionPossible=False,
                        )

            previous = None
            for pair in pairs:
                record = pair.get("record")
                acquire, span = pair["acquire"], pair["span"]
                if (
                    record is None
                    or span.sampled
                    or span.incomplete
                    or record.category == "lock_test"
                    or ambiguous_history
                ):
                    previous = pair
                    continue
                candidates = []
                for owner in _overlap(index, record.start, acquire["time"]):
                    charge()
                    candidates.append(owner)
                # Retain the immediate predecessor even if already released,
                # so the inspector can show the zero-delay prerequisite.
                if (
                    previous
                    and previous["valid"]
                    and all(owner is not previous for owner in candidates)
                ):
                    candidates.append(previous)
                causes = []
                conflict = False
                for owner in candidates:
                    charge()
                    if (
                        owner is pair
                        or owner["acquire"]["location"] == acquire["location"]
                    ):
                        continue
                    target_mode, owner_mode = _mode(span), _mode(owner["span"])
                    # Compatible readers may keep ownership beyond this
                    # reader's successful acquisition without a clock conflict.
                    if target_mode == owner_mode == "shared":
                        continue
                    if (
                        owner["order"] >= pair["order"]
                        or owner["release"]["time"] > acquire["time"]
                        or owner["contradictory"]
                    ):
                        conflict = True
                        continue
                    if "release_span" not in owner:
                        owner["release_span"] = (
                            release_lookup.at(owner["release"])
                            if release_lookup
                            else None
                        )
                    source_span = owner["release_span"]
                    if (
                        source_span is None
                        and owner["span"]
                        and owner["span"].category == "critical_acquire"
                        and not owner["span"].sampled
                        and not owner["span"].incomplete
                    ):
                        source_span = owner["span"]
                    source = operation(
                        source_span,
                        location=owner["release"]["location"],
                        event=owner["release"]["id"],
                        time=owner["release"]["time"],
                        routine="Lock ownership",
                    )
                    if source_span is None:
                        source.update(
                            start=owner["acquire"]["time"], end=owner["release"]["time"]
                        )
                    source["acquireEvent"] = owner["acquire"]["id"]
                    source["ownershipStart"] = owner["acquire"]["time"]
                    source["ownershipEnd"] = owner["release"]["time"]
                    if owner["nestedOwnership"] is not None:
                        source["nestedOwnership"] = owner["nestedOwnership"]
                    required = target_mode == "exclusive" or owner_mode == "exclusive"
                    cause = prerequisite(
                        f"lock:{key}:{pair['order']}:owner:{owner['order']}:span:{span.id}",
                        "lock_handoff",
                        source,
                        operation(span, event=acquire["id"]),
                        owner["release"]["time"],
                        required=required,
                        target_start=max(record.start, owner["acquire"]["time"]),
                        target_end=record.upper_end,
                        reason=(
                            "Recorded incompatible ownership of this lock must end before this acquisition can succeed."
                            if required
                            else "The acquisition has an unspecified shared-lock mode; recorded owner release is a conditional prerequisite."
                        ),
                    )
                    if cause:
                        cause["lock"] = key[2]
                        cause["acquisitionOrder"] = pair["order"]
                        cause["ownerAcquisitionOrder"] = owner["order"]
                        causes.append(cause)
                if conflict:
                    diagnostics["lock_clock_conflict"] += 1
                    record.evidence["lockAttributionUnavailable"] = (
                        "Contradictory ownership or acquisition order"
                    )
                    causes = []
                if causes:
                    staged.append((record, causes))
                previous = pair
    except OverflowError:
        diagnostics["lock_attribution_limit"] += 1
        # A partial traversal can miss contradictory owners. Commit no cause.
        return False
    if not complete:
        diagnostics["lock_context_incomplete"] += bool(locks)
    for record, causes in staged:
        record.causes.extend(causes)
        record.inferred_intervals.extend(
            (c.start, c.end) for c in causes if c.end > c.start
        )
        latest = max(causes, key=lambda c: c.ready)
        record.deadline = max(record.deadline, latest.ready)
        record.peer = latest.source.location
        record.confidence = "conditional-lock-availability"
        record.evidence.update(
            previousReleaseEvent=latest.source.event,
            previousReleaseTime=latest.ready,
            ownerReleases=[
                dict(
                    event=c.source.event,
                    location=c.source.location,
                    acquisitionOrder=c.extra["ownerAcquisitionOrder"],
                    start=c.start,
                    end=c.end,
                )
                for c in causes
            ],
            completeOwnerSet=False,
            blockedTime=None,
        )
    return complete
