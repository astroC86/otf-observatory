"""Completion prerequisites for native thread, team, and task joins."""

import collections

from ..causality.lazy_causes import BarrierCohort, CauseCollection
from ..causality.operations import (
    BoundaryOrder,
    operation as cause_operation,
    prerequisite,
)
from ..tasks.barrier import task_join_prerequisites
from ..trace.event_spans import WorkBudget
from .lifecycle import native_thread_lifecycle
from .lock_waits import LOCK_KINDS
from .synchronization_model import team_members


def attribute_team_joins(trace, native, records, spans, diagnostics):
    """Attribute instrumented fork/join completion from native JOIN cohorts.

    The primary's native interval is ThreadTeamEnd -> ThreadJoin. Other team
    members contribute their observed ThreadTeamEnd points. This is separate
    from Pthread-style ThreadWait/ThreadEnd contingent/sequence matching.
    """
    candidates = collections.defaultdict(list)
    for span in spans:
        if span.category == "thread_join":
            candidates[span.location].append(span)
    if not candidates:
        return
    cohorts = collections.defaultdict(list)
    for op in native["operations"]:
        if op["operation"] == "JOIN":
            cohorts[(op["comm"], op["sequence"])].append(op)
    assigned = {}
    boundary_order = BoundaryOrder(trace)
    for (comm, sequence), participants in cohorts.items():
        primaries = [p for p in participants if p["location"] == p["primary"]]
        if len(primaries) != 1:
            continue
        primary = primaries[0]
        compatible = [
            s
            for s in candidates.get(primary["location"], ())
            if s.start <= primary["start"]
            and s.end >= primary["end"]
            and trace.defs.get("Region", {}).get(s.region, {}).get("paradigm")
            == primary["paradigm"]
        ]
        if not compatible:
            continue
        compatible = boundary_order.filter(
            compatible,
            primary["location"],
            primary["start"],
            primary.get("boundaryEvent"),
        )
        compatible = boundary_order.filter(
            compatible, primary["location"], primary["end"], primary["event"]
        )
        if not compatible:
            diagnostics["team_join_routine_boundary_unresolved"] += 1
            continue
        deepest = max(s.depth for s in compatible)
        compatible = [s for s in compatible if s.depth == deepest]
        if len(compatible) != 1:
            diagnostics["team_join_routine_ambiguous"] += 1
            continue
        span = compatible[0]
        record = records[span.id]
        if span.id in assigned:
            assigned[span.id].append(primary["event"])
            record.start = span.start
            record.end = span.end
            record.upper_end = span.end
            record.deadline = span.start
            record.causes = CauseCollection()
            record.confidence = "observed-routine"
            record.peer = None
            record.evidence.update(
                nativeJoinOperation=None,
                ambiguousJoinEvents=list(assigned[span.id]),
                completeCohort=False,
                sequenceReliable=False,
            )
            diagnostics["team_join_routine_ambiguous"] += 1
            continue
        assigned[span.id] = [primary["event"]]
        record.start = primary["start"]
        record.end = primary["end"]
        record.upper_end = record.end
        record.deadline = record.start
        expected = set(team_members(trace, comm) or ())
        observed = {p["location"] for p in participants}
        counts = [native["counts"].get((loc, comm), 0) for loc in expected]
        complete = (
            bool(expected)
            and expected == observed
            and len(participants) == len(expected)
        )
        consistent = bool(counts) and len(set(counts)) == 1
        epochs = {p["teamInvocation"] for p in participants}
        valid = all(
            p["end"] >= p["start"] and p["end"] <= primary["end"] for p in participants
        )
        record.evidence.update(
            nativeJoinOperation=primary,
            team=comm,
            teamInvocation=primary["teamInvocation"],
            expectedParticipants=len(expected),
            observedParticipants=len(observed),
            completeCohort=complete,
            sequenceReliable=consistent,
            memberEndEvents=[p["event"] for p in participants],
        )
        if (
            not complete
            or not consistent
            or len(epochs) != 1
            or not valid
            or span.incomplete
            or span.sampled
            or diagnostics["routine_limit"]
        ):
            diagnostics["team_join_unresolved"] += 1
            continue
        others = [p for p in participants if p["location"] != primary["location"]]
        if not others:
            continue
        latest = max(p["end"] for p in others)
        record.deadline = max(record.start, latest)
        record.confidence = "conditional-team-completion"
        record.peer = max(others, key=lambda p: p["end"])["location"]
        for peer in others:
            source = cause_operation(
                location=peer["location"],
                event=peer["event"],
                time=peer["end"],
                routine="Thread team execution",
            )
            source.update(
                start=peer["teamBeginTime"], teamBeginEvent=peer["teamBeginEvent"]
            )
            edge = prerequisite(
                f"team:{comm}:join:{sequence}:peer:{peer['location']}:span:{span.id}",
                "team_join",
                source,
                cause_operation(span, event=primary["event"]),
                peer["end"],
                communicator=comm,
                target_start=record.start,
                target_end=record.end,
                reason="The primary thread cannot finish joining this complete matched team before its members reach their recorded ThreadTeamEnd.",
            )
            if edge:
                edge["teamInvocation"] = primary["teamInvocation"]
                edge["nativeOperationOrdinal"] = sequence
                record.causes.append(edge)


def attribute_task_joins(trace, native, records, diagnostics, *, cap):
    """Attach a shared, incomplete task set to an already validated JOIN."""
    candidates = {}
    if diagnostics["context_limit"] or diagnostics["routine_limit"]:
        return
    for record in records.values():
        op = record.evidence.get("nativeJoinOperation")
        if (
            op
            and record.evidence.get("completeCohort")
            and record.evidence.get("sequenceReliable")
            and not record.span.incomplete
            and not record.span.sampled
        ):
            candidates[(op["comm"], op["sequence"])] = record
    if not candidates:
        return
    result = task_join_prerequisites(trace, native, cap=min(cap, 150000))
    diagnostics.update(result["diagnostics"])
    if result["partial"]:
        return
    for key, cohort in result["cohorts"].items():
        record = candidates.get(key)
        if record is None:
            continue
        op = record.evidence["nativeJoinOperation"]
        target = cohort["targetOperation"]
        if (
            op["event"] != target["event"]
            or op["teamInvocation"] != cohort["teamInvocation"]
        ):
            continue
        peers = []
        for member in cohort["members"]:
            source = cause_operation(
                location=member["completionLocation"],
                event=member["source"]["event"],
                time=member["ready"],
                routine="Recorded task execution",
            )
            source.update(**member["source"])
            peers.append((member["taskInstance"], source, member["ready"]))
        shared = BarrierCohort(
            f"team:{key[0]}:join:{key[1]}:tasks",
            key[0],
            peers,
            kind="task_join",
            expected_prerequisites=cohort["requiredCount"],
            reason=cohort["interpretation"],
            extra=dict(
                teamInvocation=cohort["teamInvocation"],
                nativeOperationOrdinal=key[1],
                completeAwaitedSet=False,
                blockedTime=None,
                recordingContract="Score-P 10.0 OMPT team join",
                evidence=cohort["evidence"],
            ),
        )
        record.causes.append(
            shared.view(
                "join:" + str(record.span.id),
                cause_operation(record.span, event=op["event"]),
                record.span.id,
                target_start=record.start,
                target_end=record.end,
            )
        )
        record.deadline = max(
            record.deadline, max(member["ready"] for member in cohort["members"])
        )
        record.evidence["taskPrerequisites"] = dict(
            requiredCount=cohort["requiredCount"],
            completeAwaitedSet=False,
            blockedTime=None,
            membersPreview=[
                dict(
                    taskInstance=m["taskInstance"],
                    task=m["task"],
                    source=m["source"],
                    ready=m["ready"],
                )
                for m in cohort["members"][:20]
            ],
            previewTruncated=cohort["requiredCount"] > 20,
            interpretation=cohort["interpretation"],
        )


def collect_thread_joins(events, diagnostics):
    """Index valid contingent/sequence identities without inventing matches."""
    waits = collections.defaultdict(list)
    ends = collections.defaultdict(list)
    for e in events:
        k = e["kind"]
        d = e["data"]
        if k in LOCK_KINDS:
            continue
        elif k in ("ThreadWait", "ThreadBegin", "ThreadEnd"):
            comm, sequence = d.get("threadContingent"), d.get("sequenceCount")
            if (
                type(comm) is not int
                or not 0 <= comm < 2**32 - 1
                or type(sequence) is not int
                or not 0 <= sequence < 2**64
            ):
                diagnostics["thread_identity_invalid"] += 1
                continue
            if sequence == 2**64 - 1:
                continue
            key = (str(comm), str(sequence))
            if k == "ThreadWait":
                waits[key].append(e)
            elif k == "ThreadEnd":
                ends[key].append(e)
    return waits, ends


def attribute_thread_joins(trace, waits, ends, lookup, records, diagnostics, *, cap):
    """Match contingent completion points to instrumented ThreadWait routines."""
    lifecycle = None
    if waits and not diagnostics["context_limit"]:
        try:
            lifecycle = native_thread_lifecycle(
                trace, charge=WorkBudget(cap), diagnostics=diagnostics
            )
        except OverflowError:
            diagnostics["thread_lifecycle_context_limit"] += 1
    for key, wait_events in waits.items():
        matching = ends.get(key, [])
        if len(wait_events) != 1:
            diagnostics["thread_join_unresolved"] += 1
            continue
        wait = wait_events[0]
        s = lookup.at(wait["location"], wait["time"], {"thread_join"}, event=wait["id"])
        if not s:
            diagnostics["thread_wait_without_routine"] += 1
            continue
        record = records[s.id]
        record.evidence.update(
            threadContingent=key[0], sequenceCount=key[1], waitEvent=wait["id"]
        )
        # The OTF2 reader's THREAD_WAIT operation is entry -> ThreadWait,
        # not entry -> the enclosing region's subsequent Leave. See the
        # binary's interval construction at 0x101757d..0x101760f.
        record.end = wait["time"]
        record.upper_end = wait["time"]
        record.evidence["waitCompletionTime"] = wait["time"]
        if lifecycle is None:
            diagnostics["thread_join_context_incomplete"] += 1
            continue
        if len(matching) != 1:
            diagnostics["thread_join_unresolved"] += 1
            continue
        ended = matching[0]
        record.evidence.update(threadEndEvent=ended["id"], threadEndTime=ended["time"])
        scope = [
            lifecycle["observations"].get(event["id"], {}) for event in (wait, ended)
        ]
        if not all(
            observation.get("scopeValid") and observation.get("membershipValid")
            for observation in scope
        ):
            record.evidence["threadScope"] = scope
            diagnostics["thread_join_membership_unresolved"] += 1
            continue
        if ended["location"] == wait["location"]:
            diagnostics["thread_join_same_location"] += 1
            continue
        if ended["time"] <= wait["time"] and not s.incomplete and not s.sampled:
            record.deadline = max(s.start, ended["time"])
            record.confidence = "conditional-thread-completion"
            record.peer = ended["location"]
            source = cause_operation(
                location=ended["location"],
                event=ended["id"],
                time=ended["time"],
                routine="Thread execution",
            )
            lifetime = lifecycle["lifetimesByEndEvent"].get(ended["id"])
            if lifetime is not None:
                source.update(
                    start=lifetime["start"],
                    beginEvent=lifetime["beginEvent"],
                    createSequenceCount=lifetime["createSequenceCount"],
                    waitSequenceCount=lifetime["waitSequenceCount"],
                )
                record.evidence["threadLifetime"] = lifetime
            else:
                record.evidence["threadLifetimeIssues"] = lifecycle[
                    "lifecycleIssuesByEndEvent"
                ].get(ended["id"], [])
            native_pair = lifecycle["waitPairs"].get(wait["id"])
            if native_pair and native_pair["endEvent"] == ended["id"]:
                record.evidence["nativeThreadWait"] = native_pair
            edge = prerequisite(
                f"thread:{key}:wait:{wait['id']}",
                "thread_completion",
                source,
                cause_operation(s, event=wait["id"]),
                ended["time"],
                target_start=record.start,
                target_end=record.end,
                reason="The recorded ThreadWait joins the matching contingent/sequence ThreadEnd.",
            )
            if edge:
                record.causes.append(edge)
        else:
            diagnostics["thread_end_after_join"] += 1
