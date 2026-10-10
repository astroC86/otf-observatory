"""Recorded task execution prerequisites of a completed OpenMP team join.

Score-P OMPT omits some task identities. A team join nevertheless drains its
bound task team; unlike ordinary taskwait this does not require reconstruction
of an elided immediate parent. Ordinary cancellable barriers are not promoted.
"""

import bisect
import collections
import math

from .contracts import scorep_ompt_recording
from .dependencies import TaskCollector
from .groups import TaskGroups
from .identity import process_scope, task_identity
from ..trace.event_spans import WorkBudget

KINDS = (
    "ThreadTaskCreate",
    "ThreadTaskSwitch",
    "ThreadTaskComplete",
    "ThreadTeamBegin",
    "ThreadTeamEnd",
    "ThreadFork",
    "ThreadJoin",
    "MeasurementOnOff",
)


class _Collector(TaskCollector):
    record_type = set

    def interval(
        self,
        begin,
        end,
        kind,
        label,
        data=None,
        confidence="recorded",
        status=None,
        **kwargs,
    ):
        if (
            kind == "task-execution"
            and end is not None
            and end["kind"] == "ThreadTaskComplete"
            and confidence == "recorded"
            and status is None
            and end["time"] >= begin["time"]
        ):
            self.records.add(end["id"])


def task_join_prerequisites(trace, native, *, cap=150000):
    """Return bounded, source-qualified task members by native JOIN ordinal.

    Each cohort targets the primary's original ThreadJoin operation. Its member
    list is an explicitly incomplete recorded subset, including already-completed
    zero-delay prerequisites. No region duration or exact blocked time is inferred.
    """
    result = dict(cohorts={}, diagnostics=collections.Counter(), partial=False)
    if not scorep_ompt_recording(trace):
        return result
    if not trace.rows("SELECT id FROM events WHERE kind='ThreadTaskCreate' LIMIT 1"):
        return result
    if len(native.get("operations", ())) > max(1000, cap * 4):
        result["partial"] = True
        result["diagnostics"]["task_join_native_context_limit"] += 1
        return result
    joins = collections.defaultdict(list)
    begins = {}
    for operation in native.get("operations", ()):
        if operation["operation"] == "JOIN":
            joins[(operation["comm"], operation["sequence"])].append(operation)
        elif operation["operation"] == "FORK":
            begins[operation["event"]] = operation
    if not joins:
        return result
    rows = trace.rows(
        "SELECT id,location,time,kind,data FROM events WHERE kind IN ("
        + ",".join("?" for _ in KINDS)
        + ") ORDER BY id LIMIT ?",
        [*KINDS, cap + 1],
    )
    if len(rows) > cap:
        result["partial"] = True
        result["diagnostics"]["task_join_context_limit"] += 1
        return result
    collector = _Collector(trace, cap, rows, lambda loc: process_scope(trace.defs, loc))
    if collector.model is None:
        return result
    result["diagnostics"].update(collector.diagnostics)
    scope = TaskGroups(collector, {}, collector.model["instances"])
    stacks = collections.defaultdict(list)
    contexts = {}
    invalid = set()
    gap = None
    by_identity = collections.defaultdict(list)
    raw_by_id = {row["id"]: row for row in rows}
    for row in rows:
        kind, data, loc = row["kind"], row["data"], str(row["location"])
        if kind == "MeasurementOnOff":
            mode = data.get("measurementMode")
            if (type(mode) is not int or mode != 1) and gap is None:
                gap = row["id"]
            continue
        if kind in ("ThreadFork", "ThreadJoin"):
            if type(data.get("model")) is not int or data["model"] != 3:
                invalid.update(item["key"] for item in stacks[loc])
            continue
        if kind == "ThreadTeamBegin":
            op = begins.get(row["id"])
            team = data.get("threadTeam")
            members = scope.team_locations(str(team)) if type(team) is int else None
            if op is None or members is None or loc not in members:
                invalid.update(item["key"] for item in stacks[loc])
                stacks[loc].append(dict(key=None, comm=None))
                result["diagnostics"]["task_join_team_context_unresolved"] += 1
            else:
                stacks[loc].append(
                    dict(key=(op["comm"], op["teamInvocation"]), comm=str(team))
                )
        elif kind == "ThreadTeamEnd":
            team = data.get("threadTeam")
            if (
                type(team) is int
                and stacks[loc]
                and stacks[loc][-1]["comm"] == str(team)
            ):
                stacks[loc].pop()
            else:
                invalid.update(item["key"] for item in stacks[loc])
                stacks[loc].clear()
                result["diagnostics"]["task_join_team_context_unresolved"] += 1
        else:
            key = task_identity(
                kind, data, loc, lambda loc: process_scope(trace.defs, loc)
            )
            current = stacks[loc][-1] if stacks[loc] else None
            context = (
                current["key"]
                if key is not None and current and current["comm"] == key[1]
                else None
            )
            contexts[row["id"]] = context
            if key is not None:
                by_identity[key].append((row["id"], context))

    instances = collections.defaultdict(list)
    team_owners = {}
    for task in collector.model["instances"].values():
        created, first, completed = task["created"], task["first"], task["completed"]
        if created is None or first is None or completed is None:
            continue
        key = tuple(task["task"])
        epoch = contexts.get(created["id"])
        if (
            task["ambiguous"]
            or epoch is None
            or epoch in invalid
            or completed["id"] not in collector.records
        ):
            continue
        if contexts.get(first["id"]) != epoch or contexts.get(completed["id"]) != epoch:
            continue
        members = scope.team_locations(key[1])
        creator = int(key[2])
        if (
            members is None
            or creator >= len(members)
            or members[creator] != str(created["location"])
        ):
            result["diagnostics"]["task_join_creator_scope_unresolved"] += 1
            continue
        events = (created, first, completed)
        if any(str(event["location"]) not in members for event in events):
            continue
        if key[1] not in team_owners:
            owners = {process_scope(trace.defs, loc) for loc in members}
            team_owners[key[1]] = len(owners) == 1 and not next(
                iter(owners)
            ).startswith("unresolved-location:")
        if not team_owners[key[1]]:
            continue
        if (
            not all(math.isfinite(event["time"]) for event in events)
            or not created["time"] <= first["time"] <= completed["time"]
        ):
            result["diagnostics"]["task_join_task_clock_conflict"] += 1
            continue
        history = by_identity[key]
        lo = bisect.bisect_left(history, (created["id"],))
        hi = bisect.bisect_right(history, (completed["id"] + 1,))
        if any(context != epoch for _, context in history[lo:hi]):
            continue
        instances[epoch].append(task)

    for (comm, ordinal), operations in joins.items():
        members = scope.team_locations(comm)
        if members is None:
            continue
        expected = set(members)
        observed = {op["location"] for op in operations}
        primaries = [op for op in operations if op["location"] == op["primary"]]
        epochs = {op["teamInvocation"] for op in operations}
        totals = [native.get("counts", {}).get((loc, comm), 0) for loc in members]
        if (
            len(primaries) != 1
            or expected != observed
            or len(operations) != len(expected)
            or len(epochs) != 1
            or len(set(totals)) != 1
        ):
            result["diagnostics"]["task_join_cohort_unresolved"] += 1
            continue
        target = primaries[0]
        epoch = (comm, target["teamInvocation"])
        target_record = raw_by_id.get(target["event"])
        if (
            target_record is None
            or target_record["kind"] != "ThreadJoin"
            or type(target_record["data"].get("model")) is not int
            or target_record["data"]["model"] != 3
        ):
            continue
        if epoch in invalid or any(
            not math.isfinite(op["start"])
            or not math.isfinite(op["end"])
            or op["end"] < op["start"]
            or op["end"] > target["end"]
            for op in operations
        ):
            continue
        if gap is not None and gap <= target["event"]:
            result["diagnostics"]["task_join_recording_gap"] += 1
            continue
        starts = {op["location"]: op["teamBeginTime"] for op in operations}
        begin_events = {op["location"]: op["teamBeginEvent"] for op in operations}
        ends = {
            op["location"]: op.get("boundaryEvent", op["event"]) for op in operations
        }
        team_proof = dict(
            id=f"task-join:{comm}:{ordinal}",
            teamBeginEvents=list(begin_events.values()),
            teamEndEvents=list(ends.values()),
            joinEvent=target["event"],
        )
        evidence_preview = dict(
            recordingContract="Score-P 10.0 OMPT team join",
            cohortProof=team_proof["id"],
            teamBeginEventCount=len(begin_events),
            teamEndEventCount=len(ends),
            teamBeginEventsPreview=team_proof["teamBeginEvents"][:32],
            teamEndEventsPreview=team_proof["teamEndEvents"][:32],
            teamEvidencePreviewTruncated=len(operations) > 32,
            joinEvent=target["event"],
        )
        required = []
        for task in instances.get(epoch, ()):
            created, first, completed = (
                task["created"],
                task["first"],
                task["completed"],
            )
            if any(
                event["time"] < starts[str(event["location"])]
                or event["id"] >= ends[str(event["location"])]
                for event in (created, first, completed)
            ):
                continue
            if completed["time"] > target["end"] or completed["id"] >= target["event"]:
                result["diagnostics"]["task_join_completion_after_return"] += 1
                continue
            # Score-P writes the primary TeamEnd after the terminal implicit
            # barrier has drained its task team. A later TaskComplete cannot
            # be charged as time spent waiting in the native JOIN interval.
            if completed["time"] > target["start"]:
                result["diagnostics"]["task_join_completion_after_team_end"] += 1
                continue
            if (
                completed["time"] == target["end"]
                and str(completed["location"]) != target["location"]
            ):
                result["diagnostics"]["task_join_completion_order_unresolved"] += 1
                continue
            # Team-wide proof is stored once below. Per-member evidence stays
            # constant-size even for many tasks in a large team.
            evidence = list(
                dict.fromkeys(
                    [created["id"], first["id"], completed["id"], target["event"]]
                    + [
                        begin_events[str(event["location"])]
                        for event in (created, first, completed)
                    ]
                    + [ends[str(event["location"])] for event in (created, completed)]
                )
            )
            source = dict(
                kind="task-lifetime",
                taskInstance=task["instance"],
                task=task["task"],
                location=str(completed["location"]),
                event=completed["id"],
                createEvent=created["id"],
                start=created["time"],
                end=completed["time"],
                routine="Recorded task execution",
                evidence=evidence,
            )
            required.append(
                dict(
                    taskInstance=task["instance"],
                    task=task["task"],
                    source=source,
                    ready=completed["time"],
                    evidence=evidence,
                    createLocation=str(created["location"]),
                    completionLocation=str(completed["location"]),
                    createTime=created["time"],
                    completionTime=completed["time"],
                    required=True,
                    completionRecord=completed,
                )
            )
        if required:
            result["cohorts"][(comm, ordinal)] = dict(
                teamInvocation=target["teamInvocation"],
                targetOperation=target,
                targetRecord=target_record,
                members=required,
                requiredCount=len(required),
                completeAwaitedSet=False,
                blockedTime=None,
                evidence=evidence_preview,
                teamProof=team_proof,
                interpretation="Known bound task executions must finish before the team join returns. This is an incomplete recorded subset, not a full awaited set, detached fulfillment time or CPU blocked duration.",
            )
    return result


def append_task_join_dependencies(out):
    """Append inspectable task completion → ThreadJoin graph edges, bounded."""
    if out.scan_truncated or not scorep_ompt_recording(out.trace):
        return
    if not out.trace.rows(
        "SELECT id FROM events WHERE kind='ThreadTaskCreate' LIMIT 1"
    ):
        return
    from ..threads.barriers import native_barriers

    diagnostics = collections.Counter()
    try:
        native = native_barriers(
            out.trace,
            diagnostics=diagnostics,
            charge=WorkBudget(max(1000, out.cap * 4)),
        )
    except OverflowError:
        out.scan_truncated = True
        out.warn(
            "task_join_native_context_limit",
            "Team operation replay reached its limit; task join prerequisites remain unresolved.",
        )
        return
    result = task_join_prerequisites(out.trace, native, cap=out.cap)
    for code, count in result["diagnostics"].items():
        out.warn(
            code,
            "Recorded task/team context is incomplete or contradictory; the affected team join prerequisites remain unresolved.",
            count,
        )
    if result["partial"]:
        out.scan_truncated = True
    count = 0
    for (comm, ordinal), cohort in result["cohorts"].items():
        for member in cohort["members"]:
            data = {
                key: value for key, value in member.items() if key != "completionRecord"
            }
            data.update(
                team=comm,
                teamInvocation=cohort["teamInvocation"],
                nativeOperationOrdinal=ordinal,
                targetOperation=cohort["targetOperation"],
                completeAwaitedSet=False,
                blockedTime=None,
                interpretation=cohort["interpretation"],
            )
            out.edge(
                member["completionRecord"],
                cohort["targetRecord"],
                "task-team-join-prerequisite",
                "Bound task execution → team join return",
                "recorded-scorep-team-join-contract",
                data,
            )
            out.edges[-1]["evidence"] = member["evidence"]
            count += 1
    out.extra["taskJoinAnalysis"] = dict(
        requiredPrerequisites=count,
        cohorts=len(result["cohorts"]),
        cohortProofs=[cohort["teamProof"] for cohort in result["cohorts"].values()],
        completeAwaitedSet=False,
        blockedTime=None,
        ordinaryBarrierCancellationUnresolved=True,
    )
