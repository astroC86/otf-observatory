"""Observed non-MPI synchronization routines and conditional dependency delays.

OTF2 specifies identity, ownership and lifecycle records, not the exact instant
that a thread blocks. Inferred delays are therefore conditional estimates with
zero lower bound; recorded acquire/release gaps are never treated as lock waits.
"""

import collections
import pathlib
import threading

from ..causality.operations import clipped as clip_causes, totals as causal_totals
from .synchronization_build import build

_CACHE = collections.OrderedDict()
_LOCK = threading.RLock()


def _analysis(trace):
    stat = pathlib.Path(trace.path).stat()
    key = (trace.path, stat.st_mtime_ns, stat.st_size)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        result = build(trace)
        _CACHE[key] = result
        while len(_CACHE) > 2:
            _CACHE.popitem(last=False)
        return result


def _union(intervals):
    total = 0.0
    end = -1.0
    for a, b in sorted(intervals):
        if b > max(a, end):
            total += b - max(a, end)
        end = max(end, b)
    return total


_MESSAGES = {
    "thread_identity_invalid": "A thread contingent or sequence identity has an invalid unsigned value; no completion match is inferred.",
    "thread_lifecycle_context_limit": "Thread lifecycle replay exceeded its bounded context; completion attribution is suppressed.",
    "thread_join_context_incomplete": "Incomplete thread context prevents a reliable end-to-wait prerequisite.",
    "thread_join_same_location": "A thread cannot establish a join prerequisite from its own recorded end on the same location.",
    "thread_join_membership_unresolved": "The waiting and ending locations are not both established members of their recorded thread contingent.",
    "team_join_unresolved": "The native thread-team join lacks a complete, consistently ordered cohort or valid recorded routine.",
    "team_join_routine_ambiguous": "A native team join has multiple instrumented routines at the same nesting depth.",
    "barrier_operation_unavailable": "No valid native barrier operation was reconstructed for this routine; its recorded duration remains visible without arrival attribution.",
    "task_group_wait_entry_unrecorded": "Score-P OMPT records the whole taskgroup body but not its terminal wait entry. No team-barrier arrival or whole-body dependency delay is assigned.",
    "barrier_incomplete_cohort": "A barrier operation cohort lacks expected participants; no arrival-delay estimate is made.",
    "barrier_sequence_uncertain": "Participant native operation counts differ, making ordinal matching uncertain.",
    "barrier_membership_unresolved": "The thread team lacks a unique, valid communicator-to-location membership; no complete barrier prerequisite is established.",
    "barrier_team_invocation_mismatch": "The same native operation ordinal belongs to different recorded team invocations; no common barrier prerequisite is established.",
    "barrier_entry_clock_conflict": "A recorded barrier return precedes a peer original region entry; no required entry prerequisites are assigned.",
    "barrier_clock_or_sequence_conflict": "A barrier return precedes a peer arrival; clock or cohort matching is inconsistent.",
    "native_barrier_paradigm_mismatch": "The barrier region paradigm does not match the active thread team.",
    "native_barrier_entry_missing": "A barrier leave has no remembered entry boundary, possibly consumed by a nested barrier.",
    "native_barrier_region_nesting_invalid": "A region leave does not match the active region stack during barrier replay.",
    "native_barrier_context_unknown": "A calling-context record references an undefined context during barrier replay.",
    "native_thread_team_membership_invalid": "A thread team does not identify this executing location among its members.",
    "native_thread_paradigm_membership_invalid": "The executing location has no membership in the recorded threading paradigm world.",
    "native_thread_fork_missing": "A primary thread begins a team without a recorded pending fork boundary.",
    "native_thread_fork_reused": "A thread fork attempts to overwrite a pending fork/join boundary.",
    "native_thread_team_end_invalid": "A thread-team end does not match the active team stack.",
    "native_thread_team_end_reused": "A primary thread-team end attempts to overwrite a pending fork/join boundary.",
    "native_thread_join_missing_team_end": "A thread join has no active team or no pending team-end boundary.",
    "task_dependency_set_unrecorded": "Taskwait routine duration is observed, but the awaited task set is not explicitly recorded.",
    "gpu_sync_dependency_unrecorded": "GPU synchronization routine duration is observed; its device/event dependency is not explicitly identified.",
    "gpu_sync_nonunique_identifier": "Callsites and external correlation ranges do not establish a waited device activity without a recorded mapping contract.",
    "gpu_identifier_limit": "The GPU invocation or identifier scan was incomplete; omitted duplicates could change matching, so conditional completion attribution is suppressed.",
    "gpu_sync_identifier_ambiguous": "Several synchronization calls or kernels share an identifier; no unique completion association is established.",
    "gpu_sync_identifier_conflict": "Sampled/incomplete GPU intervals or a kernel completion after the synchronization return prevent completion attribution.",
    "gpu_sync_failed_api": "A recorded failed GPU API call does not establish a device-completion prerequisite.",
    "gpu_sync_api_result_unresolved": "Conflicting or invalid GPU return values prevent completion attribution.",
    "condition_dependency_unrecorded": "Condition/semaphore wait duration is observed without a recorded condition identity or wakeup dependency.",
    "lock_overlapping_owners": "Mutually exclusive recorded owners overlap; affected lock attribution is suppressed.",
    "lock_identity_invalid": "A lock identity, paradigm or acquisition ordinal has an invalid unsigned integer value.",
    "lock_recording_gap": "Suspended or unknown recording prevents proof of continuous lock ownership.",
    "lock_recording_scan_limit": "The measurement-state scan reached its limit; lock ownership proof is suppressed.",
    "lock_order_missing": "A lock event lacks its acquisition ordinal and cannot be reliably paired.",
    "lock_order_ambiguous": "Duplicate acquisition ordinals prevent an unambiguous ownership history.",
    "lock_routine_multiple_acquisitions": "Several lock acquisitions share one instrumented invocation; its individual attempt boundaries are unresolved.",
    "lock_clock_conflict": "Lock timestamps or event order conflict with recorded ownership; affected timing attribution is suppressed.",
    "lock_release_operation_limit": "Too many overlapping spans surround a lock release; its raw ownership evidence is retained.",
    "lock_release_operation_ambiguous": "Several deepest operations contain a lock release; the enclosing operation is unresolved.",
    "lock_release_boundary_limit": "Too many same-tick boundaries surround a lock release; the enclosing operation is unresolved.",
    "lock_owner_mismatch": "A lock acquire/release pair has different recorded owner threads.",
    "lock_attribution_limit": "Lock attribution exceeded its bounded work; no partial ownership timing is treated as complete.",
    "lock_context_incomplete": "Lock context is incomplete; ownership timing attribution is suppressed.",
    "lock_acquire_without_routine": "Lock acquisition records lack an instrumented entry boundary; they cannot yield lock wait duration.",
    "context_limit": "Synchronization context exceeded the bounded scan; uncertain barrier inferences are suppressed.",
    "routine_limit": "Synchronization routine scan reached its bound; selected totals cover scanned records only.",
    "sampled_routine_excluded": "Sampled synchronization contexts are estimates and are excluded from observed routine time.",
    "thread_wait_without_routine": "ThreadWait has no instrumented join routine boundary; no wait interval is invented.",
}


def synchronization(trace, q):
    start, end, _, _ = trace.scope(q, regions=False)
    analysis = _analysis(trace)
    locations = set(q["locations"].split(",")) if q.get("locations") else None
    limit = max(1, min(2000, int(q.get("limit", 500))))
    offset = max(0, int(q.get("offset", 0)))
    include = q.get("region", "").casefold()
    exclude = q.get("exclude", "").casefold()
    group = q.get("group", "")
    category = q.get("category", "")
    summaries = {}
    selected = []
    observed = collections.defaultdict(list)
    inferred = collections.defaultdict(list)
    upper = collections.defaultdict(list)
    for record in analysis["records"]:
        s = record.span
        if s.sampled:
            continue
        if (
            start == end
            or record.start >= end
            or record.end <= start
            or (locations is not None and s.location not in locations)
        ):
            continue
        if (
            include
            and include not in s.name.casefold()
            or exclude
            and exclude in s.name.casefold()
            or group
            and group != trace.regions.get(s.region, {}).get("group")
            or category
            and record.category != category
        ):
            continue
        a = max(start, record.start)
        b = min(end, record.end)
        intervals = (
            [(a, min(b, record.deadline))]
            if record.inferred_intervals is None
            else [
                (max(a, left), min(b, right))
                for left, right in record.inferred_intervals
            ]
        )
        intervals = [(left, right) for left, right in intervals if right > left]
        delay = _union(intervals)
        bound = max(0, min(b, record.upper_end) - a)
        selected.append((record, a, b, delay, bound))
        row = summaries.setdefault(
            record.category,
            dict(
                category=record.category,
                count=0,
                observed=0.0,
                inferred=0.0,
                lowerBound=0.0,
                upperBound=0.0,
            ),
        )
        row["count"] += 1
        row["observed"] += b - a
        row["inferred"] += delay
        row["upperBound"] += bound
        observed[s.location].append((a, b))
        inferred[s.location].extend(intervals)
        if bound:
            upper[s.location].append((a, a + bound))
    selected.sort(key=lambda x: (-x[3], -(x[2] - x[1]), x[0].span.location, x[1]))
    page = selected[offset : offset + limit]
    cause_total = sum(len(record.causes) for record, _, _, _, _ in page)
    cause_limit = max(1, min(2000, int(q.get("causeLimit", 500))))
    cause_offset = min(
        max(0, int(q.get("causeOffset", 0))),
        max(0, ((cause_total - 1) // cause_limit) * cause_limit),
    )
    cause_skip = cause_offset
    cause_remaining = cause_limit
    causes_returned = 0
    rows = []
    for record, a, b, delay, bound in page:
        s = record.span
        interval = (
            "Recorded native thread operation interval"
            if record.evidence.get("nativeBarrierOperation")
            or record.evidence.get("nativeJoinOperation")
            else "Recorded synchronization interval"
        )
        count = len(record.causes)
        causes = (
            clip_causes(record.causes, a, b, offset=cause_skip, limit=cause_remaining)
            if cause_skip < count and cause_remaining
            else []
        )
        cause_skip = max(0, cause_skip - count)
        cause_remaining -= len(causes)
        causes_returned += len(causes)
        unresolved = {
            "task_wait": "The trace does not encode the complete awaited task set.",
            "condition_wait": "No condition-variable identity or wakeup relation is recorded.",
            "gpu_synchronization": "No validated device completion prerequisite is associated with this call.",
        }.get(
            record.category,
            "No complete, consistent prerequisite history is associated with this routine.",
        )
        no_external_prerequisite = record.evidence.get("contentionPossible") is False
        rows.append(
            dict(
                causes=causes,
                causeCount=count,
                prerequisiteStatus=(
                    "not-required"
                    if no_external_prerequisite
                    else "identified" if count else "unresolved"
                ),
                unresolvedReason=(
                    None if count or no_external_prerequisite else unresolved
                ),
                id="sync:" + str(s.id),
                span=s.id,
                location=s.location,
                peer=record.peer,
                region=s.region,
                routine=s.name,
                category=record.category,
                start=a,
                end=b,
                observed=b - a,
                inferred=delay,
                lowerBound=0.0,
                upperBound=bound,
                confidence=record.confidence,
                evidence=dict(
                    record.evidence,
                    routineStart=s.start,
                    routineEnd=s.end,
                    sampled=bool(s.sampled),
                    incomplete=bool(s.incomplete),
                    interpretation=interval
                    + "; inferred dependency availability is conditional and is not measured blocked time.",
                ),
            )
        )
    selected_ids = {r.span.id for r, _, _, _, _ in selected}
    cohorts = [
        c
        for c in analysis["cohorts"]
        if start < end
        and c["start"] < end
        and c["end"] > start
        and any(p["span"] in selected_ids for p in c["participants"])
        and (not category or category in ("openmp_barrier", "thread_barrier"))
    ]
    diagnostics = [
        dict(
            code=k,
            count=v,
            message=analysis["messages"].get(k, _MESSAGES.get(k, k.replace("_", " "))),
        )
        for k, v in sorted(analysis["diagnostics"].items())
        if v > 0
    ]
    if not analysis["records"]:
        diagnostics.append(
            dict(
                code="no_synchronization_routines",
                count=1,
                message="No instrumented non-MPI synchronization routines provide observable wait boundaries.",
            )
        )
    totals = dict(
        count=len(selected),
        observed=sum(_union(x) for x in observed.values()),
        inferred=sum(_union(x) for x in inferred.values()),
        lowerBound=0.0,
        upperBound=sum(_union(x) for x in upper.values()),
        requestCount=0,
        requestStates={},
        collectiveCount=len(cohorts),
        partial=bool(
            analysis["partial"]
            or analysis["diagnostics"].get("gpu_identifier_limit")
            or analysis["diagnostics"].get("routine_limit")
            or analysis["diagnostics"].get("context_limit")
        ),
    )
    collective_offset = max(0, int(q.get("collectiveOffset", 0)))
    return dict(
        causeTotal=cause_total,
        causeOffset=cause_offset,
        causeLimit=cause_limit,
        causesReturned=causes_returned,
        causesMore=cause_offset + causes_returned < cause_total,
        causalTotals=causal_totals(
            ((r.causes, a, b) for r, a, b, _, _ in selected), selected=True
        ),
        rows=rows,
        summary=sorted(summaries.values(), key=lambda s: s["observed"], reverse=True),
        totals=totals,
        total=len(selected),
        more=offset + len(rows) < len(selected),
        offset=offset,
        diagnostics=diagnostics,
        collectives=cohorts[collective_offset : collective_offset + limit],
        collectiveTotal=len(cohorts),
        collectivesMore=collective_offset + limit < len(cohorts),
        requests=[],
        requestTotal=0,
        requestsMore=False,
        semantics=dict(
            observed="Recorded synchronization intervals; recognized barriers use recovered native operation boundaries. Original routine bounds remain in evidence. Totals are unions per location.",
            inferred="Conditional dependency-arrival/availability estimates, clipped to the observed routine.",
            bounds="Blocked-time lower bounds are zero; upper bounds are the observed potentially blocking interval. Lock hold time is excluded when an acquire boundary is available.",
            context="Cohorts and identity matching use trace context outside the selected window. Taskwait and GPU synchronization are observed-only unless their dependency is explicitly identified.",
            clock="Arrival estimates require consistent synchronized timestamps; no clock-error bound is assumed.",
        ),
    )
