"""Conditional arrival prerequisites for complete native barrier cohorts."""

import collections
import dataclasses

from ..causality.lazy_causes import BarrierCohort
from ..causality.operations import operation as cause_operation
from ..tasks.cancellation import barrier_cancellation
from .synchronization_model import team_members


def attribute_barriers(trace, native, records, spans, diagnostics):
    """Attach conditional arrivals and return the native barrier cohorts."""
    # The native operation sequence includes FORK, BARRIER and JOIN and is
    # monotone per location/communicator across repeated team invocations.
    barriers = collections.defaultdict(list)
    for span in spans:
        if span.category not in ("openmp_barrier", "thread_barrier"):
            continue
        operation = native["by_span"].get(span.id)
        if operation is None:
            records[span.id].evidence["nativeBarrierOperation"] = None
            diagnostics["barrier_operation_unavailable"] += 1
            continue
        record = records[span.id]
        record.start = operation["start"]
        record.end = operation["end"]
        record.deadline = record.start
        record.evidence["nativeBarrierOperation"] = operation
        effective = dataclasses.replace(
            span, start=operation["start"], end=operation["end"]
        )
        barriers[(operation["comm"], operation["sequence"])].append(
            (effective, operation)
        )
    cohorts = []
    cancellation = barrier_cancellation(trace, native)
    if cancellation["partial"]:
        diagnostics["barrier_cancellation_context_limit"] += 1
    for (comm, sequence), participants in barriers.items():
        membership = team_members(trace, comm)
        expected = set(membership or ())
        observed = {s.location for s, _ in participants}
        if membership is None:
            diagnostics["barrier_membership_unresolved"] += 1
        totals = [native["counts"].get((loc, comm), 0) for loc in expected]
        epochs = {op["teamInvocation"] for _, op in participants}
        epoch = next(iter(epochs)) if len(epochs) == 1 else None
        consistent = bool(expected) and len(set(totals)) == 1 and len(epochs) == 1
        complete = (
            bool(expected)
            and observed == expected
            and len(participants) == len(expected)
            and all(not s.incomplete and not s.sampled for s, _ in participants)
        )
        arrivals = [s.start for s, _ in participants]
        last = max(arrivals)
        first = min(arrivals)
        causal = all(s.end >= last for s, _ in participants)
        latest_entry = max(records[p.id].span.start for p, _ in participants)
        entry_causal = all(s.end >= latest_entry for s, _ in participants)
        reliable = (
            complete
            and consistent
            and causal
            and entry_causal
            and not diagnostics["routine_limit"]
        )
        cancel = cancellation["byTeam"].get((comm, epoch))
        cancel = (
            cancel
            if cancel
            and cancel["firstEvent"] <= max(op["event"] for _, op in participants)
            else None
        )
        peer_proof = reliable and cancel is None and not cancellation["partial"]
        if cancel:
            diagnostics["barrier_recorded_cancellation"] += 1
        if not complete:
            diagnostics["barrier_incomplete_cohort"] += 1
        if not consistent:
            diagnostics["barrier_sequence_uncertain"] += 1
        if len(epochs) != 1:
            diagnostics["barrier_team_invocation_mismatch"] += 1
        if not causal:
            diagnostics["barrier_clock_or_sequence_conflict"] += 1
        if not entry_causal:
            diagnostics["barrier_entry_clock_conflict"] += 1
        cohort_id = f"team:{comm}:operation:{sequence}"
        peer_set = (
            BarrierCohort(
                cohort_id,
                comm,
                [
                    (
                        str(peer.id),
                        cause_operation(
                            records[peer.id].span, event=op.get("entryEvent")
                        ),
                        records[peer.id].span.start,
                    )
                    for peer, op in participants
                ],
                reason="The complete matched thread barrier requires every participant to enter; nested work inside an already entered barrier is not another arrival.",
                extra=dict(teamInvocation=epoch, nativeOperationOrdinal=sequence),
            )
            if peer_proof
            else None
        )
        latest_participant = max(participants, key=lambda x: x[0].start)[0]
        overall = max(s.end for s, _ in participants) - first
        overlap = (
            max(0.0, min(s.end for s, _ in participants) - last)
            if complete and consistent
            else None
        )
        item = dict(
            id=cohort_id,
            comm=comm,
            sequence=sequence,
            teamInvocation=epoch,
            operation="BARRIER",
            start=first,
            end=first + overall,
            arrivalSkew=last - first,
            expectedParticipants=len(expected),
            missingParticipants=sorted(expected - observed),
            complete=complete,
            sequenceReliable=consistent,
            confidence="conditional" if reliable else "low",
            participants=[],
            overallDuration=overall,
            participantOverlap=overlap,
            participantOverlapPercent=(
                (100 * overlap / overall if overall > 0 else 0)
                if overlap is not None
                else None
            ),
            evidence=dict(
                matching="native per-location/communicator operation ordinal, including FORK and JOIN",
                intervalSemantics="Native barrier interval begins at the latest nested region boundary remembered by the reader; routine bounds remain in participant evidence.",
            ),
        )
        for span, operation in participants:
            record = records[span.id]
            record.evidence.update(
                cohort=cohort_id,
                team=comm,
                teamInvocation=operation["teamInvocation"],
                teamEvents=[operation["teamBeginEvent"]],
                expectedParticipants=len(expected),
                observedParticipants=len(observed),
                completeCohort=complete,
                sequenceReliable=consistent,
                arrivalSkew=last - first,
            )
            if cancel:
                record.evidence["recordedCancellation"] = cancel
            if cancellation["partial"]:
                record.evidence["cancellationContextIncomplete"] = True
            if reliable:
                record.deadline = last
                record.confidence = "conditional-barrier-arrival"
                record.peer = latest_participant.location
                # The native remembered boundary can advance inside a barrier.
                # A mandatory arrival prerequisite uses the actual region entry,
                # never a later nested task boundary mistaken for arrival.
                if peer_set is not None:
                    record.causes.append(
                        peer_set.view(
                            str(span.id),
                            cause_operation(record.span, event=operation["event"]),
                            span.id,
                            target_start=record.start,
                            target_end=record.end,
                        )
                    )
            item["participants"].append(
                dict(
                    location=span.location,
                    start=span.start,
                    end=span.end,
                    span=span.id,
                    arrivalDelay=last - span.start,
                    nativeOperation=operation,
                )
            )
        cohorts.append(item)
    return cohorts
