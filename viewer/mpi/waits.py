"""Evidence-based MPI dependency delays, distinct from measured routine time.

OTF2 records initiation/completion observations, not the instant a process blocks
inside MPI. Consequently every inferred blocked-time bound starts at zero. The
reported inferred value is a trace-based dependency-arrival estimate, not an
additional measurement. Request lifetimes are never counted as blocked time.
"""

import collections

from ..causality.operations import (
    clipped as clip_causes,
    totals as causal_totals,
    union,
)
from . import wait_analysis
from .wait_models import TEST

DIAGNOSTIC_MESSAGES = dict(
    request_reused_while_active="A request ID was reused before an observed completion.",
    completion_without_initiation="Completion has no matching initiation record.",
    send_request_released="Request_free releases a send request without proving completion.",
    collective_missing_participants="A collective ordinal lacks expected communicator participants.",
    collective_sequence_uncertain="Different per-rank collective counts make ordinal matching uncertain.",
    clock_inverted_messages="Clock-inverted messages were excluded from dependency estimates.",
    dependency_entry_not_observed="A matched message lacks an observed sender entry or receiver posting.",
    collective_unknown_membership="Communicator membership is unavailable; complete participation cannot be established.",
    matched_probe_scope_unverified="Matched-probe lifecycle and envelope candidates use an unverified process-scoped message-handle assumption; all resulting causes remain conditional.",
    collective_recording_gap="Recording suspension can hide collective calls and invalidate per-rank ordinal alignment; no dependency or overlap is assigned to affected cohorts.",
    message_recording_gap="Recording suspension can hide matching sends or receives; the indexed message is retained without causal attribution.",
    send_request_recording_gap="Recording suspension can hide request completion or reuse; no receive-posting prerequisite is assigned to this send wait.",
    matched_probe_recording_gap="Recording suspension can hide matched-probe handles, request generations or sends; candidate observations remain inspectable without dependency delay.",
    mpi_recording_scan_limit="The bounded measurement-state scan is incomplete; MPI associations cannot establish causal prerequisites.",
    collective_payload_zero_or_unrecorded="Optional zero collective payload sizes do not prove positive-count communication; directed prerequisites remain unresolved.",
    collective_payload_unavailable="Original collective payload fields are missing, malformed, or undefined; no directed payload proof is applied.",
    collective_payload_inconsistent="Payload sizes conflict with a consistent fixed-count sender or receiver role; no directed payload proof is applied.",
    collective_root_inconsistent="Collective participants disagree on the root or use an invalid rootless sentinel.",
    collective_root_domain_unresolved="The recorded root cannot be mapped unambiguously into a supported intracommunicator rank domain.",
    collective_payload_clock_inversion="A required payload source starts after the affected receiver completes; all directed prerequisites for that receiver were suppressed.",
    collective_initiation_class_mismatch="Blocking and nonblocking collective initiations do not match; this ordinal does not establish a complete collective cohort.",
    collective_api_family_unresolved="Complete exact initiating MPI invocations and original typed MPI paradigms are unavailable. Some operation codes also describe neighborhood APIs; an indexed label or positive aggregate bytes cannot establish the missing API contract.",
    collective_intercomm_domain_unresolved="The original intercommunicator does not establish two disjoint typed MPI groups with unique declared process membership.",
    collective_intercomm_operation_unresolved="This intercommunicator operation requires a contract beyond the supported remote-group prerequisites; per-destination or local-output count vectors are not inferred.",
    intercommunicator_collective="Intercommunicator cohorts use separate group and root semantics; supported causes identify only remote-group prerequisites.",
    collective_producer_contract_unverified="The recorded creator and original MPI API declarations do not establish the audited producer-specific collective byte contract.",
    collective_producer_payload_inconsistent="The complete recorded byte profile is inconsistent with the audited producer formulas; no required local-output prerequisites are inferred.",
    collective_producer_payload_overflow="The producer byte expression exceeds the audited arithmetic range; wrapped values are not treated as required payload evidence.",
    collective_no_remote_participants="This collective has one participant and no remote payload prerequisites.",
)


def _select(trace, analysis, key):
    """Build one immutable selection shared by all of its independently paged tables."""
    start, end, locations, include, exclude, group, category = key
    selected = []
    summaries = {}
    observed = collections.defaultdict(list)
    inferred = collections.defaultdict(list)
    upper = collections.defaultdict(list)
    for record in analysis["records"]:
        s = record.span
        if (
            start == end
            or s.start >= end
            or s.end <= start
            or (locations and s.location not in locations)
        ):
            continue
        if (
            (include and include not in s.name.casefold())
            or (exclude and exclude in s.name.casefold())
            or (group and group != trace.regions.get(s.region, {}).get("group"))
            or (category and record.category != category)
        ):
            continue
        a = max(start, s.start)
        b = min(end, s.end)
        intervals = [
            (max(a, left), min(b, right))
            for left, right in record.inferred_intervals
            or [(s.start, record.inferred_end)]
        ]
        intervals = [(left, right) for left, right in intervals if right > left]
        delay = union(intervals)
        selected.append((record, a, b, delay))
        summary = summaries.get(record.category)
        if summary is None:
            summary = summaries[record.category] = dict(
                category=record.category,
                count=0,
                observed=0.0,
                inferred=0.0,
                lowerBound=0.0,
                upperBound=0.0,
            )
        summary["count"] += 1
        summary["observed"] += b - a
        summary["inferred"] += delay
        summary["upperBound"] += 0 if s.routine in TEST else b - a
        interval = (a, b)
        observed[s.location].append(interval)
        if s.routine not in TEST:
            upper[s.location].append(interval)
        if delay:
            inferred[s.location].extend(intervals)
    selected.sort(key=lambda r: (-r[3], -(r[2] - r[1]), r[0].span.location, r[1]))
    requests = []
    request_states = collections.Counter()
    for request in analysis["requests"]:
        a = request.start if request.start is not None else request.end
        b = request.end if request.end is not None else trace.meta["duration"]
        if (
            start == end
            or a is None
            or a > end
            or b < start
            or (
                locations
                and request.location not in locations
                and request.completion_location not in locations
            )
        ):
            continue
        requests.append(request)
        request_states[request.status] += 1
    collective_rows = [
        c
        for c in analysis["collectives"]
        if start < end
        and c["start"] < end
        and c["end"] >= start
        and (
            not locations or any(p["location"] in locations for p in c["participants"])
        )
    ]
    probe_rows = []
    for probe in analysis["matchedProbes"]:
        endpoints = [
            probe[k] for k in ("probe", "receive", "completion") if probe.get(k)
        ]
        a = min((p["start"] for p in endpoints), default=start)
        b = max((p["end"] for p in endpoints), default=end)
        if probe["status"] in ("pending-receive", "pending-at-trace-end"):
            b = trace.meta["duration"]
        if (
            start == end
            or a > end
            or b < start
            or (locations and not any(p["location"] in locations for p in endpoints))
        ):
            continue
        probe_rows.append(probe)
    rma_selected = []
    for attempt in analysis["rmaLockAttempts"]:
        request = attempt.get("request")
        grant = attempt.get("grant")
        endpoints = [event for event in (request, grant) if event]
        left = min((event["time"] for event in endpoints), default=start)
        right = grant["time"] if grant else trace.meta["duration"]
        if (
            start == end
            or left > end
            or right < start
            or (
                locations
                and not any(str(event["location"]) in locations for event in endpoints)
            )
        ):
            continue
        rma_selected.append(attempt)
    diagnostic_messages = DIAGNOSTIC_MESSAGES | analysis["messages"]
    diagnostics = [
        dict(
            code=code,
            count=count,
            message=diagnostic_messages.get(code, code.replace("_", " ")),
        )
        for code, count in sorted(analysis["diagnostics"].items())
        if count
    ]
    if not analysis["records"]:
        diagnostics.append(
            dict(
                code="no_wait_routines",
                count=1,
                message="No instrumented MPI blocking, Wait/Test, or collective intervals were recorded.",
            )
        )
    measured = sum(union(v) for v in observed.values())
    estimated = sum(union(v) for v in inferred.values())
    return dict(
        records=selected,
        requests=requests,
        collectives=collective_rows,
        probes=probe_rows,
        rmaLocks=rma_selected,
        diagnostics=diagnostics,
        summary=sorted(summaries.values(), key=lambda r: r["observed"], reverse=True),
        totals=dict(
            partial=analysis["partial"],
            count=len(selected),
            observed=measured,
            inferred=estimated,
            lowerBound=0,
            upperBound=sum(union(v) for v in upper.values()),
            requestCount=len(requests),
            requestStates=dict(request_states),
            collectiveCount=len(collective_rows),
        ),
        causalTotals=causal_totals(
            ((r.causes, a, b) for r, a, b, _ in selected), selected=True
        ),
        rmaLockCausalTotals=causal_totals(
            ((a["causes"], start, end) for a in rma_selected), selected=True
        ),
    )


@wait_analysis.paused_gc()
def waits(trace, q):
    """Analyze full causal context; select once and paginate without reaggregation."""
    start, end, _, _ = trace.scope(q, regions=False)
    analysis = wait_analysis._analysis(trace)
    key = (
        start,
        end,
        frozenset(q["locations"].split(",")) if q.get("locations") else frozenset(),
        q.get("region", "").casefold(),
        q.get("exclude", "").casefold(),
        q.get("group", ""),
        q.get("category", ""),
    )
    # One selection per analysis bounds memory and shares its index invalidation.
    # Publish only a complete selection; page rendering never mutates it.
    with analysis["selectionLock"]:
        cached = analysis["selection"]
        if cached is None or cached[0] != key:
            selection = _select(trace, analysis, key)
            analysis["selection"] = (key, selection)
        else:
            selection = cached[1]
    limit = max(1, min(2000, int(q.get("limit", 500))))
    offset = max(0, int(q.get("offset", 0)))
    request_offset = max(0, int(q.get("requestOffset", 0)))
    collective_offset = max(0, int(q.get("collectiveOffset", 0)))
    probe_offset = max(0, int(q.get("probeOffset", 0)))
    rma_offset = max(0, int(q.get("rmaLockOffset", 0)))
    selected = selection["records"]
    request_total = len(selection["requests"])
    collective_rows = selection["collectives"]
    probe_rows = selection["probes"]
    rma_selected = selection["rmaLocks"]
    page = selected[offset : offset + limit]
    cause_total = sum(len(record.causes) for record, _, _, _ in page)
    cause_limit = max(1, min(2000, int(q.get("causeLimit", 500))))
    cause_offset = min(
        max(0, int(q.get("causeOffset", 0))),
        max(0, ((cause_total - 1) // cause_limit) * cause_limit),
    )
    cause_skip = cause_offset
    cause_remaining = cause_limit
    causes_returned = 0
    rows = []
    for record, a, b, delay in page:
        s = record.span
        count = len(record.causes)
        causes = (
            clip_causes(record.causes, a, b, offset=cause_skip, limit=cause_remaining)
            if cause_skip < count and cause_remaining
            else []
        )
        cause_skip = max(0, cause_skip - count)
        cause_remaining -= len(causes)
        causes_returned += len(causes)
        rows.append(
            dict(
                causes=causes,
                causeCount=count,
                unresolvedReason=(
                    None
                    if count
                    else "No valid recorded prerequisite is associated with this routine; its observed duration is retained."
                ),
                id=str(s.id),
                category=record.category,
                location=s.location,
                peer=record.peer,
                start=a,
                end=b,
                routine=s.name,
                region=s.region,
                span=s.id if s.id > 0 else record.evidence.get("span"),
                observed=b - a,
                inferred=delay,
                lowerBound=0,
                upperBound=0 if s.routine in TEST else b - a,
                confidence=record.confidence,
                evidence=dict(
                    record.evidence,
                    routineStart=s.start,
                    routineEnd=s.end,
                    sampled=bool(s.sampled),
                    incomplete=bool(s.incomplete),
                    interpretation="Observed routine time and conditional dependency-arrival estimate; no exact blocked duration is recorded.",
                ),
            )
        )
    request_rows = []
    for request in selection["requests"][request_offset : request_offset + limit]:
        request_rows.append(
            dict(
                location=request.location,
                completionLocation=request.completion_location,
                request=request.request,
                generation=request.generation,
                kind=request.kind,
                start=request.start,
                end=request.end,
                status=request.status,
                tests=request.tests,
                completionSpan=(
                    request.completion_span.id if request.completion_span else None
                ),
                evidence=dict(
                    initiationEvent=request.initiation_event,
                    completionEvent=request.completion_event,
                    lastFailedTest=request.last_test,
                    interpretation="Request lifetime is not blocked time; MpiRequestTest denotes an unsuccessful test.",
                ),
            )
        )
    rma_rows = [
        dict(
            attempt,
            causes=clip_causes(attempt["causes"], start, end),
            selectedUnavailableSeconds=union(
                (max(start, c.start), min(end, c.end))
                for c in attempt["causes"]
                if min(end, c.end) > max(start, c.start)
            ),
        )
        for attempt in rma_selected[rma_offset : rma_offset + limit]
    ]
    return dict(
        causeTotal=cause_total,
        causeOffset=cause_offset,
        causeLimit=cause_limit,
        causesReturned=causes_returned,
        causesMore=cause_offset + causes_returned < cause_total,
        rmaLocks=rma_rows,
        rmaLockTotal=len(rma_selected),
        rmaLocksMore=rma_offset + limit < len(rma_selected),
        rmaLockOffset=rma_offset,
        rmaLockPartial=analysis["partial"],
        rmaLockCausalTotals=dict(selection["rmaLockCausalTotals"]),
        matchedProbes=probe_rows[probe_offset : probe_offset + limit],
        matchedProbeTotal=len(probe_rows),
        matchedProbesMore=probe_offset + limit < len(probe_rows),
        probeOffset=probe_offset,
        causalTotals=dict(selection["causalTotals"]),
        rows=rows,
        summary=[dict(row) for row in selection["summary"]],
        totals=dict(
            selection["totals"],
            requestStates=dict(selection["totals"]["requestStates"]),
        ),
        collectives=collective_rows[collective_offset : collective_offset + limit],
        requests=request_rows,
        diagnostics=[dict(row) for row in selection["diagnostics"]],
        total=len(selected),
        more=offset + len(rows) < len(selected),
        offset=offset,
        collectiveTotal=len(collective_rows),
        collectiveOffset=collective_offset,
        requestTotal=request_total,
        requestOffset=request_offset,
        collectivesMore=collective_offset + limit < len(collective_rows),
        requestsMore=request_offset + limit < request_total,
        semantics=dict(
            observed="Routine intervals clipped to selection; total is their union per location.",
            inferred="Conditional time before dependency arrival, clipped to the affected routine.",
            bounds="Blocked-time lower bound is zero; upper bound is observed potentially blocking routine time.",
            context="Peer entries and complete request histories are analyzed beyond the selected window.",
            clock="Dependency estimates assume synchronized location clocks; the trace does not provide an error bound.",
        ),
    )
