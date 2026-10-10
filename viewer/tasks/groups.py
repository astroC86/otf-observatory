"""Recorded Score-P OMPT taskgroup membership and completion prerequisites.

The region contains the body as well as its terminal synchronization. It does
not reveal wait entry, detached fulfillment, or a complete application task set.
"""

import collections
from .identity import process_scope


class TaskGroups:
    def __init__(self, out, contracts, instances):
        self.out = out
        self.contracts = contracts
        self.instances = instances
        self.open = collections.defaultdict(list)
        self.groups = []
        self.budget = min(1000000, out.cap * 4)
        self.teams = {}
        self.recording_gap = None

    def measurement(self, event):
        mode = event["data"].get("measurementMode")
        if (type(mode) is not int or mode != 1) and self.recording_gap is None:
            self.recording_gap = event["id"]
            self.out.warn(
                "task-group-recording-gap",
                "A disabled or unknown recording interval can omit task switches, identities and group boundaries; later taskgroup membership cannot establish required prerequisites.",
            )

    def team_locations(self, team):
        if team in self.teams:
            return self.teams[team]
        defs = self.out.trace.defs
        result = None
        comm = defs.get("Comm", {}).get(team, {})
        ref = comm.get("group")
        group = defs.get("Group", {}).get(str(ref), {})
        flags = group.get("groupFlags", 0)
        worlds = [
            world
            for world in defs.get("Group", {}).values()
            if type(world.get("groupType")) is int
            and world["groupType"] in (4, 7)
            and type(world.get("paradigm")) is int
            and world["paradigm"] == 3
        ]
        if (
            team not in defs.get("InterComm", {})
            and type(ref) is int
            and 0 <= ref < 2**32 - 1
            and type(group.get("groupType")) is int
            and group["groupType"] == 5
            and type(group.get("paradigm")) is int
            and group["paradigm"] == 3
            # Score-P's OPENMP_THREAD_TEAM/LOCATIONS encoder uses NONE,
            # not the SHMEM-only GLOBAL_MEMBERS rank representation.
            and type(flags) is int
            and flags == 0
            and len(worlds) == 1
            and worlds[0]["groupType"] == 4
            and type(worlds[0].get("groupFlags", 0)) is int
            and worlds[0].get("groupFlags", 0) == 0
        ):
            world = worlds[0].get("members")
            members = group.get("members")
            if (
                isinstance(world, (list, tuple))
                and isinstance(members, (list, tuple))
                and all(
                    type(value) is int and 0 <= value < 2**64 - 1 for value in world
                )
                and len(set(world)) == len(world)
                and all(
                    type(rank) is int and 0 <= rank < len(world) for rank in members
                )
                and len(set(members)) == len(members)
            ):
                locations = tuple(str(world[rank]) for rank in members)
                if all(
                    type(defs.get("Location", {}).get(loc, {}).get("locationType"))
                    is int
                    and defs["Location"][loc]["locationType"] == 1
                    for loc in locations
                ):
                    result = locations
        self.teams[team] = result
        return result

    def scoped(self, group, lineage):
        """Only the producer's modern task records in one declared team bind."""
        events = [group["begin"]] + ([group["end"]] if group["end"] else [])
        team = group["team"]
        for key in lineage:
            task = self.instances[key]
            if task["task"][0] != "thread":
                return False
            current = task["task"][1]
            if team is not None and current != team:
                return False
            team = current
            if task.get("creationTeam") is not None and task["creationTeam"] != team:
                return False
            events.extend(
                event
                for event in (task["created"], task["first"], task["completed"])
                if event is not None
            )
        locations = self.team_locations(team)
        if locations is None or any(
            str(event["location"]) not in locations for event in events
        ):
            return False
        for key in lineage:
            task = self.instances[key]
            if task["created"] is not None:
                creator = int(task["task"][2])
                if creator >= len(locations) or locations[creator] != str(
                    task["created"]["location"]
                ):
                    return False
        scopes = {
            process_scope(self.out.trace.defs, event["location"]) for event in events
        }
        return len(scopes) == 1 and not next(iter(scopes)).startswith(
            "unresolved-location:"
        )

    def invalidate_location(self, loc):
        # A lost team boundary can change the implicit task or resume an outer
        # one; retain observations but do not preserve membership through it.
        for group in self.groups:
            if group["end"] is None and str(group["begin"]["location"]) == loc:
                group["invalid"] = True

    def boundary(self, event, parent, confidence, team=None):
        region = str(event["data"].get("region"))
        if region not in self.contracts:
            return False
        key = parent if parent is not None else "unresolved:" + str(event["location"])
        if event["kind"].endswith("Enter"):
            group = dict(
                begin=event,
                end=None,
                parent=parent,
                parentConfidence=confidence,
                region=region,
                members=[],
                invalid=parent is None,
                team=team,
            )
            self.open[key].append(group)
            self.groups.append(group)
        elif self.open[key] and self.open[key][-1]["region"] == region:
            self.open[key].pop()["end"] = event
        else:
            # A malformed nested return cannot preserve an apparently valid
            # outer group for later membership or proof.
            for group in self.open[key]:
                group["invalid"] = True
            self.out.warn(
                "task-group-entry-missing",
                "A taskgroup return has no matching nested entry in its recorded task context.",
            )
        return True

    def created(self, task, parent):
        bindings = {}
        if parent is not None:
            parent_task = self.instances.get(parent)
            if parent_task is not None:
                bindings.update(parent_task.get("groupBindings", {}))
            for group in self.open.get(parent, ()):
                bindings[group["begin"]["id"]] = (
                    group,
                    (parent,) if parent_task is not None else (),
                )
        inherited = {}
        for ident, (group, lineage) in bindings.items():
            # Charge inherited ancestry too: a deep chain must not expand
            # quadratically while paying only one unit per newly born task.
            cost = len(lineage) + 1
            if self.budget < cost:
                self.out.scan_truncated = True
                self.out.warn(
                    "task-group-members-truncated",
                    "Taskgroup membership reached its work limit; no required taskgroup prerequisites are assigned.",
                )
                break
            self.budget -= cost
            if group["end"] is not None:
                self.out.warn(
                    "task-group-lifetime-conflict",
                    "A recorded descendant creates another task after its inherited taskgroup returned.",
                )
                group["invalid"] = True
                continue
            path = lineage + (task["instance"],)
            group["members"].append((task, path))
            inherited[ident] = (group, path)
        task["groupBindings"] = inherited

    def finish(self):
        proved = 0
        for group in self.groups:
            begin, end = group["begin"], group["end"]
            members = []
            required = []
            valid = (
                not self.out.scan_truncated
                and not group["invalid"]
                and end is not None
                and end["time"] >= begin["time"]
                and (self.recording_gap is None or end["id"] < self.recording_gap)
            )
            for task, lineage in group["members"]:
                created, completed = task["created"], task["completed"]
                ambiguous = any(self.instances[key]["ambiguous"] for key in lineage)
                equal_remote = bool(
                    completed
                    and end
                    and completed["time"] == end["time"]
                    and str(completed["location"]) != str(end["location"])
                )
                status = (
                    "ambiguous task lineage"
                    if ambiguous
                    else (
                        "completion missing"
                        if completed is None
                        else (
                            "group return missing"
                            if end is None
                            else (
                                "completion order unresolved at group return"
                                if equal_remote
                                else (
                                    "completion outside group lifetime"
                                    if completed["time"] < created["time"]
                                    or completed["time"] > end["time"]
                                    or completed["id"] > end["id"]
                                    else "completion observed before group return"
                                )
                            )
                        )
                    )
                )
                scoped = self.scoped(group, lineage)
                if not scoped and status == "completion observed before group return":
                    status = "task team or process scope unresolved"
                proof = (
                    valid
                    and scoped
                    and status == "completion observed before group return"
                )
                evidence = (
                    [begin["id"], created["id"]]
                    + ([completed["id"]] if completed else [])
                    + ([end["id"]] if end else [])
                )
                for key in lineage:
                    parent = self.instances[key]
                    evidence.extend(
                        e["id"]
                        for e in (parent.get("created"), parent.get("first"))
                        if e is not None
                    )
                    if parent.get("parentEvent") is not None:
                        evidence.append(parent["parentEvent"])
                member = dict(
                    task=task["task"],
                    taskInstance=task["instance"],
                    createEvent=created["id"],
                    createTime=created["time"],
                    createLocation=str(created["location"]),
                    completionEvent=completed["id"] if completed else None,
                    completionTime=completed["time"] if completed else None,
                    completionLocation=(
                        str(completed["location"]) if completed else None
                    ),
                    parentConfidence=task["parentConfidence"],
                    lineage=list(lineage),
                    status=status,
                    required=proof,
                    source=dict(
                        kind="task-lifetime",
                        taskInstance=task["instance"],
                        location=(
                            str(completed["location"])
                            if completed
                            else str(created["location"])
                        ),
                        event=completed["id"] if completed else None,
                        createEvent=created["id"],
                        start=created["time"],
                        end=completed["time"] if completed else None,
                    ),
                    target=dict(
                        kind="task-group",
                        taskInstance=group["parent"],
                        location=(
                            str(end["location"]) if end else str(begin["location"])
                        ),
                        event=end["id"] if end else None,
                        entryEvent=begin["id"],
                        region=group["region"],
                        start=begin["time"],
                        end=end["time"] if end else None,
                    ),
                    evidence=list(dict.fromkeys(evidence)),
                )
                members.append(member)
                if proof:
                    required.append(member)
                    edge_data = dict(
                        member,
                        groupEntryEvent=begin["id"],
                        groupReturnEvent=end["id"],
                        completeAwaitedSet=False,
                        waitEntryUnrecorded=True,
                        blockedTime=None,
                        interpretation="This bound descendant must finish its recorded execution before the taskgroup returns. Score-P may emit TaskComplete at detach; detached fulfillment and the terminal wait entry are not recorded.",
                    )
                    self.out.edge(
                        completed,
                        end,
                        "task-group-prerequisite",
                        "Bound descendant execution → taskgroup return",
                        "recorded-scorep-taskgroup-contract",
                        edge_data,
                    )
                    self.out.edges[-1]["evidence"] = member["evidence"]
                    proved += 1
            data = dict(
                region=group["region"],
                source=str(begin["location"]),
                target=str(end["location"]) if end else None,
                waitingTaskInstance=group["parent"],
                parentConfidence=group["parentConfidence"],
                recordingContract=self.contracts[group["region"]],
                awaitedTasks=None,
                completeAwaitedSet=False,
                memberTasks=members,
                recordedMemberCount=len(members),
                requiredTasks=required,
                requiredTaskCount=len(required),
                waitEntryUnrecorded=True,
                blockedTime=None,
                interpretation="The recorded interval is the whole taskgroup construct, including useful body execution. Required members are only the proved recorded subset; no terminal wait duration or complete awaited set is inferred.",
            )
            self.out.interval(
                begin,
                end,
                "task-group",
                "Taskgroup construct",
                data,
                confidence=(
                    "recorded-scorep-taskgroup-contract"
                    if valid
                    else "incomplete-taskgroup-context"
                ),
                status=(
                    "complete construct; wait entry unrecorded"
                    if end
                    else "group return missing"
                ),
            )
        return dict(taskGroups=len(self.groups), taskGroupRequiredPrerequisites=proved)
