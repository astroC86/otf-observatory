"""Recorded OTF2 task lifecycle and parent contexts in original event order.

TaskGroups and TaskWaits own group membership and conditional wait evidence;
this replay owns task generations and scheduling transitions. Raw task IDs
stay integers/strings, not doubles.
"""

import collections
import json
from .identity import task_identity, task_data
from .contracts import (
    scorep_ompt_taskwait_contracts,
    scorep_ompt_taskgroup_contracts,
)
from .groups import TaskGroups
from .waits import TaskWaits, wait_events


class TaskCollector:
    """Decode and replay evidence; subclasses choose storage and intervals."""

    record_type = list

    def __init__(self, trace, cap, events, owner):
        self.trace, self.cap, self.end = trace, cap, trace.meta["duration"]
        self.scan_truncated, self.scanned = False, 0
        self.extra, self.diagnostics = {}, collections.Counter()
        self.records = self.record_type()
        for event in events:
            event["data"] = json.loads(event["data"])
        self.model = analyze_tasks(self, events, owner, include_waits=False)

    def warn(self, code, message, count=1):
        self.diagnostics[code] += count

    def edge(self, *args, **kwargs):
        pass


def analyze_tasks(out, events, owner, *, include_waits=True):
    """Append task scheduling and conditional wait membership to ``out``.

    Input retains original event IDs; traversal follows that recorded sequence.
    Repeated identities after a completed instance create separate generations.
    Duplicate creations before completion remain ambiguous, rather than silently
    joining unrelated tasks. ``owner(location)`` supplies OmpTask process scope.
    """
    relevant = [
        event
        for event in events
        if "Task" in event["kind"]
        or event["kind"] in ("ThreadTeamBegin", "ThreadTeamEnd")
    ]
    group_contracts = (
        scorep_ompt_taskgroup_contracts(out.trace) if include_waits else {}
    )
    waits = wait_events(out, group_contracts) if include_waits else []
    if not relevant and not waits:
        return
    records = sorted(relevant + waits, key=lambda event: event["id"])
    instances, current, active, last_execution = {}, {}, {}, {}
    children = collections.defaultdict(dict)
    team_stack = collections.defaultdict(list)
    unresolved_teams = set()
    unresolved_locations = set()
    contracts = scorep_ompt_taskwait_contracts(out.trace) if include_waits else {}
    task_waits = TaskWaits(out, contracts)
    task_groups = TaskGroups(out, group_contracts, instances)

    def identity(event):
        key = task_identity(event["kind"], event["data"], event["location"], owner)
        if key is not None:
            return key
        out.warn(
            "task-identity-invalid",
            "A task record has missing or out-of-range identity fields; it is not joined to another task.",
        )
        return None

    def new_task(key, event, created):
        instance = ":".join(key) + ":event:" + str(event["id"])
        task = dict(
            instance=instance,
            task=list(key),
            created=event if created else None,
            first=None,
            completed=None,
            ambiguous=False,
            parent=None,
            parentConfidence=None,
            parentEvent=None,
        )
        instances[instance] = task
        current[key] = task
        return task

    def stop(loc, event):
        running = active.pop(loc, None)
        if running:
            task, begin = running
            out.interval(
                begin,
                event,
                "task-execution",
                "Task " + " / ".join(task["task"][1:]),
                task_data(task),
                confidence=(
                    "ambiguous-task-identity" if task["ambiguous"] else "recorded"
                ),
                status="ambiguous task identity" if task["ambiguous"] else None,
            )
            last_execution[task["instance"]] = event

    def invalidate_active(loc, event, reason):
        task, begin = active.pop(loc)
        unresolved_locations.add(loc)
        # A completion/switch on a different location does not supply this
        # location's missing suspension boundary. Keep its observation point
        # and conflict evidence, without charging an invented running interval.
        out.interval(
            begin,
            None,
            "task-execution",
            "Task " + " / ".join(task["task"][1:]),
            dict(
                **task_data(task),
                conflictingEvent=event["id"],
                executionEndUnrecorded=True,
            ),
            confidence="conflicting-lifecycle",
            status=reason,
            end=begin["time"],
        )

    def parent_at(loc):
        if loc in unresolved_teams:
            return None, "unresolved-team-context"
        running = active.get(loc)
        team = team_stack[loc][-1] if team_stack[loc] else None
        # A nested team's implicit task is a separate parent context until an
        # explicit switch in that team identifies the active task.
        if running and (team is None or running[1]["id"] > team["event"]["id"]):
            if running[0]["completed"] is not None:
                return None, "completed-task-context"
            if running[0]["ambiguous"]:
                return None, "ambiguous-task-context"
            return running[0]["instance"], "recorded-task-switch"
        if loc in unresolved_locations:
            return None, "unresolved-task-resumption"
        if team:
            return (
                "implicit:" + loc + ":team-event:" + str(team["event"]["id"]),
                "recorded-team-context",
            )
        return "implicit:" + loc + ":trace-context", "implicit-location-context"

    for event in records:
        kind, raw, loc = event["kind"], event["data"], str(event["location"])
        if kind == "MeasurementOnOff":
            task_groups.measurement(event)
            continue
        if kind == "ThreadTeamBegin":
            ref = raw.get("threadTeam")
            team = str(ref)
            valid = type(ref) is int and 0 <= ref < 2**32 - 1
            # This stricter producer-scope gate is relevant only to the new
            # Score-P group proof; other task observations retain their scope.
            if group_contracts:
                locations = task_groups.team_locations(team)
                valid = valid and locations is not None and loc in locations
            team_stack[loc].append(dict(team=team, event=event))
            if not valid:
                unresolved_teams.add(loc)
                task_groups.invalidate_location(loc)
                out.warn(
                    "task-team-context-mismatch",
                    "Task parent context has an invalid or unresolved thread-team boundary.",
                )
            unresolved_locations.discard(loc)
            continue
        if kind == "ThreadTeamEnd":
            if team_stack[loc] and team_stack[loc][-1]["team"] == str(
                raw.get("threadTeam")
            ):
                team_stack[loc].pop()
            else:
                unresolved_teams.add(loc)
                task_groups.invalidate_location(loc)
                out.warn(
                    "task-team-context-mismatch",
                    "Task parent context has unmatched thread-team boundaries.",
                )
            continue
        if "Task" not in kind:
            parent, confidence = parent_at(loc)
            team = team_stack[loc][-1]["team"] if team_stack[loc] else None
            if parent in instances and instances[parent]["task"][0] == "thread":
                team = instances[parent]["task"][1] if team is None else team
            if task_groups.boundary(event, parent, confidence, team):
                continue
            task_waits.boundary(event, parent, confidence, children)
            continue
        key = identity(event)
        if key is None:
            if kind.endswith(("Switch", "Complete")):
                # Even an unreadable identity records a scheduling transition.
                # Continuing the previous task would invent its resumption.
                if loc in active:
                    invalidate_active(
                        loc, event, "task transition has an invalid identity"
                    )
                unresolved_locations.add(loc)
            continue
        task = current.get(key)
        if kind.endswith("Create"):
            if task and task["completed"] is None:
                task["ambiguous"] = True
                out.warn(
                    "duplicate-task-identity",
                    "An uncompleted task identity is created again; its parentage and wait membership are ambiguous.",
                )
                continue
            task = new_task(key, event, True)
            parent, confidence = parent_at(loc)
            task["parent"], task["parentConfidence"] = parent, confidence
            task["creationTeam"] = (
                team_stack[loc][-1]["team"] if team_stack[loc] else None
            )
            task["parentEvent"] = (
                active[loc][1]["id"]
                if parent in instances
                else (
                    team_stack[loc][-1]["event"]["id"]
                    if parent and team_stack[loc]
                    else None
                )
            )
            task_groups.created(task, parent)
            if parent is not None:
                children[parent][task["instance"]] = task
            if parent in instances:
                parent_task = instances[parent]
                begin = active[loc][1]
                out.edge(
                    begin,
                    event,
                    "task-parent",
                    "Task created during parent execution",
                    "recorded-context",
                    dict(
                        parentTask=parent_task["task"],
                        parentTaskInstance=parent,
                        **task_data(task),
                    ),
                )
        elif kind.endswith("Switch"):
            if task is None or task["completed"] is not None:
                task = new_task(key, event, False)
                out.warn(
                    "task-create-missing",
                    "Task execution has no creation record for this instance in the scanned context.",
                )
            running = active.get(loc)
            if running and running[0] is task:
                continue
            stop(loc, event)
            simultaneous = [
                other_loc for other_loc, (other, _) in active.items() if other is task
            ]
            if simultaneous:
                task["ambiguous"] = True
                out.warn(
                    "task-concurrent",
                    "The same task instance executes on more than one location; its wait membership is ambiguous.",
                )
                for other_loc in simultaneous:
                    invalidate_active(
                        other_loc,
                        event,
                        "missing local suspension before conflicting task switch",
                    )
            previous = last_execution.get(task["instance"])
            if previous:
                out.edge(
                    previous, event, "task-resume", "Task resumes", data=task_data(task)
                )
            elif task["created"] and task["first"] is None:
                out.edge(
                    task["created"],
                    event,
                    "task-create",
                    "Creation → first execution",
                    data=task_data(task),
                )
            if task["first"] is None:
                task["first"] = event
            active[loc] = (task, event)
            unresolved_locations.discard(loc)
        elif kind.endswith("Complete"):
            # Even an unmatched completion is a local scheduling boundary;
            # it never identifies the implicit/explicit task that resumes.
            unresolved_locations.add(loc)
            running = active.get(loc)
            if running and running[0] is not task:
                # A different task completed here without its local switch.
                # That cannot establish how the old task was suspended, or
                # whether it resumed after completion. Do not attach later
                # children/waits to that stale parent until another switch.
                out.warn(
                    "task-completion-active-mismatch",
                    "A task completion identifies a different task from the last local switch; the previous execution and subsequent parent context lack a recorded transition.",
                )
                invalidate_active(
                    loc, event, "completion of another task without local suspension"
                )
            if task is None or task["completed"] is not None:
                out.warn(
                    "task-completion-unmatched",
                    "A task completion has no unique outstanding task instance.",
                )
                continue
            if loc in active and active[loc][0] is task:
                stop(loc, event)
            else:
                out.warn(
                    "task-switch-missing",
                    "Task completion has no matching active task on this location.",
                )
            stale = [
                other_loc for other_loc, (other, _) in active.items() if other is task
            ]
            if stale:
                task["ambiguous"] = True
                out.warn(
                    "task-completion-location-conflict",
                    "A completed task was still active on another location; its missing local suspension cannot establish parentage or execution duration.",
                )
                for other_loc in stale:
                    invalidate_active(
                        other_loc, event, "completion recorded on another location"
                    )
            task["completed"] = event
            if task["parent"] is not None:
                children[task["parent"]].pop(task["instance"], None)
            if task["created"]:
                confidence = (
                    "ambiguous-task-identity" if task["ambiguous"] else "recorded"
                )
                out.interval(
                    task["created"],
                    event,
                    "task-lifetime",
                    "Task " + " / ".join(task["task"][1:]),
                    task_data(task),
                    confidence=confidence,
                )
                out.edge(
                    task["created"],
                    event,
                    "task-complete",
                    "Task creation → completion",
                    confidence,
                    task_data(task),
                )

    for task, begin in active.values():
        out.interval(
            begin,
            None,
            "task-execution",
            "Task " + " / ".join(task["task"][1:]),
            task_data(task),
            confidence="ambiguous-task-identity" if task["ambiguous"] else "recorded",
            status="missing switch/completion",
        )
    wait_count = task_waits.finish(instances)
    group_summary = task_groups.finish()
    out.extra["taskAnalysis"] = dict(
        instances=len(instances),
        waits=wait_count,
        provenAwaitedSets=0,
        **group_summary,
        dataflow="unresolved",
        dataflowReason="No established producer contract for recorded application task dependencies.",
        executionCoverage="Recorded complete switch-to-switch/completion intervals; ambiguous and open intervals are excluded from taskExecutionSeconds.",
        completeContext=not out.scan_truncated,
    )
    return dict(instances=instances)
