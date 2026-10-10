"""Conditional taskwait membership, bounded independently of lifecycle replay.

TaskWaits owns open boundaries and membership budgets while retaining references
to the lifecycle's task records so later completions update candidate evidence.
"""

import bisect
import collections
import itertools
import json

from .identity import task_data


def wait_events(out, extra_regions=()):
    regions = {
        str(ref)
        for ref, definition in out.trace.defs.get("Region", {}).items()
        if definition.get("regionRole") == 22
    } | set(extra_regions)
    contexts = {
        str(ref)
        for ref, definition in out.trace.defs.get("CallingContext", {}).items()
        if str(definition.get("region")) in regions
    }
    if not regions:
        return []
    # Match only explicit boundaries. Samples cannot establish a wait entry.
    clauses, args = [], []
    for field, refs in (("region", regions), ("callingContext", contexts)):
        if refs:
            clauses.append(
                f"CAST(json_extract(data,'$.{field}') AS TEXT) IN ({','.join('?' for _ in refs)})"
            )
            args.extend(sorted(refs))
    predicate = (
        "kind IN ('Enter','Leave','CallingContextEnter','CallingContextLeave') AND ("
        + " OR ".join(clauses)
        + ")"
    )
    if extra_regions:
        predicate = "(" + predicate + ") OR kind='MeasurementOnOff'"
    rows = out.trace.rows(
        "SELECT id,location,time,kind,data FROM events WHERE "
        + predicate
        + " ORDER BY id LIMIT ?",
        [*args, out.cap + 1],
    )
    if len(rows) > out.cap:
        out.scan_truncated = True
        out.warn(
            "task-wait-context-truncated",
            "Taskwait boundary scanning reached its limit; candidate lists may be incomplete.",
        )
        rows = rows[: out.cap]
    out.scanned += len(rows)
    for event in rows:
        event["data"] = json.loads(event["data"])
        if "region" not in event["data"]:
            event["data"]["region"] = (
                out.trace.defs.get("CallingContext", {})
                .get(str(event["data"].get("callingContext")), {})
                .get("region")
            )
    return rows


class TaskWaits:
    def __init__(self, out, contracts):
        self.out = out
        self.contracts = contracts
        self.candidate_budget = min(1000000, out.cap * 4)
        self.open = collections.defaultdict(list)
        self.finished = []

    def boundary(self, event, parent, confidence, children):
        out = self.out
        kind, raw, loc = event["kind"], event["data"], str(event["location"])
        region = str(raw.get("region"))
        key = (parent, region) if parent is not None else ("unresolved:" + loc, region)
        if kind.endswith("Enter"):
            contract = self.contracts.get(region)
            pending = (
                {}
                if contract and contract["completionOnly"]
                else children.get(parent, {})
            )
            candidates = list(
                itertools.islice(pending.values(), max(0, self.candidate_budget))
            )
            self.candidate_budget -= len(candidates)
            truncated = len(candidates) < len(pending)
            if truncated:
                out.scan_truncated = True
                out.warn(
                    "task-wait-candidates-truncated",
                    "Taskwait candidate membership reached its work limit; the reported task list is incomplete.",
                )
            wait = dict(
                begin=event,
                end=None,
                parent=parent,
                parentConfidence=confidence,
                candidates=candidates,
                candidateTotal=len(pending),
                candidateSetTruncated=truncated,
                region=region,
                contract=contract,
            )
            self.open[key].append(wait)
        elif self.open[key]:
            wait = self.open[key].pop()
            wait["end"] = event
            self.finished.append(wait)
        else:
            out.warn(
                "task-wait-entry-missing",
                "A taskwait return has no matching entry in its recorded task context.",
            )

    def finish(self, instances):
        out = self.out
        for values in self.open.values():
            self.finished.extend(values)
        # The global reader merges per-location streams. An equal timestamp on
        # another location does not establish whether a completion preceded the
        # wait entry. Recover those children even when merge order removed them
        # from the outstanding set before the entry was visited.
        simultaneous_completions = collections.defaultdict(list)
        for task in instances.values():
            if task["created"] and task["completed"] and task["parent"] is not None:
                simultaneous_completions[
                    (task["parent"], task["completed"]["time"])
                ].append(task)
        for key, tasks in simultaneous_completions.items():
            tasks.sort(key=lambda task: task["completed"]["id"])
            by_location = collections.defaultdict(list)
            for task in tasks:
                by_location[task["completed"]["location"]].append(
                    task["completed"]["id"]
                )
            simultaneous_completions[key] = (
                tasks,
                [task["completed"]["id"] for task in tasks],
                by_location,
            )
        candidate_scan_budget = min(1000000, out.cap * 4)
        for wait in self.finished:
            begin, end = wait["begin"], wait["end"]
            contract = wait["contract"]
            completion_only = bool(contract and contract["completionOnly"])
            simultaneous = (
                None
                if completion_only
                else simultaneous_completions.get((wait["parent"], begin["time"]))
            )
            if simultaneous:
                tasks, ids, local_ids = simultaneous
                stop = bisect.bisect_left(ids, begin["id"])
                count = stop - bisect.bisect_left(
                    local_ids.get(begin["location"], ()), begin["id"]
                )
                wait["candidateTotal"] += count
                added = 0
                if count:
                    for task in itertools.islice(tasks, stop):
                        if self.candidate_budget <= 0 or candidate_scan_budget <= 0:
                            break
                        candidate_scan_budget -= 1
                        if task["completed"]["location"] == begin["location"]:
                            continue
                        wait["candidates"].append(task)
                        self.candidate_budget -= 1
                        added += 1
                if added < count:
                    wait["candidateSetTruncated"] = True
                    out.scan_truncated = True
                    out.warn(
                        "task-wait-candidates-truncated",
                        "Taskwait candidate membership reached its work limit; the reported task list is incomplete.",
                    )
            wait["candidates"].sort(key=lambda task: task["created"]["id"])
            candidates = []
            for task in wait["candidates"]:
                completion = task["completed"]
                entry_order_unknown = (
                    completion is not None
                    and completion["time"] == begin["time"]
                    and completion["location"] != begin["location"]
                )
                return_order_unknown = (
                    completion is not None
                    and end is not None
                    and completion["time"] == end["time"]
                    and completion["location"] != end["location"]
                )
                status = (
                    "ambiguous identity"
                    if task["ambiguous"]
                    else (
                        "completion missing"
                        if completion is None
                        else (
                            "completion order unresolved at wait entry"
                            if entry_order_unknown
                            else (
                                "completion order unresolved at wait return"
                                if return_order_unknown
                                else (
                                    "completed after wait return"
                                    if end and completion["id"] > end["id"]
                                    else (
                                        "clock inversion"
                                        if completion["time"] < begin["time"]
                                        or end
                                        and completion["time"] > end["time"]
                                        else (
                                            "completion observed; wait return missing"
                                            if end is None
                                            else "completed during wait"
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
                source = dict(
                    kind="task-lifetime",
                    taskInstance=task["instance"],
                    location=(
                        str(completion["location"])
                        if completion
                        else str(task["created"]["location"])
                    ),
                    event=completion["id"] if completion else None,
                    createEvent=task["created"]["id"],
                    start=task["created"]["time"],
                    end=completion["time"] if completion else None,
                )
                target = dict(
                    kind="task-wait",
                    taskInstance=wait["parent"],
                    location=str(end["location"]) if end else str(begin["location"]),
                    event=end["id"] if end else None,
                    entryEvent=begin["id"],
                    region=wait["region"],
                    start=begin["time"],
                    end=end["time"] if end else None,
                )
                candidates.append(
                    dict(
                        **task_data(task),
                        createEvent=task["created"]["id"],
                        createLocation=str(task["created"]["location"]),
                        createTime=task["created"]["time"],
                        completionEvent=completion["id"] if completion else None,
                        completionTime=completion["time"] if completion else None,
                        completionLocation=(
                            str(completion["location"]) if completion else None
                        ),
                        status=status,
                        parentConfidence=task["parentConfidence"],
                        parentTaskInstance=task["parent"],
                        parentEvent=task["parentEvent"],
                        source=source,
                        target=target,
                    )
                )
                if end and status == "completed during wait":
                    out.edge(
                        completion,
                        end,
                        "task-wait-candidate",
                        "Direct child completed during taskwait (conditional)",
                        "conditional-ordinary-taskwait",
                        dict(
                            **candidates[-1],
                            waitEntryEvent=begin["id"],
                            interpretation="This is an awaited-task edge only if this is an ordinary all-direct-children taskwait.",
                        ),
                    )
                if status == "completed after wait return":
                    out.warn(
                        "ordinary-taskwait-contradiction",
                        "A candidate direct child completes after the wait returns; this may be a depend-clause wait, missing context, or conflicting event evidence.",
                    )
                elif entry_order_unknown or return_order_unknown:
                    out.warn(
                        "task-wait-completion-order-unresolved",
                        "A child completion and a taskwait boundary have equal timestamps on different locations; merged event order does not establish their execution order.",
                    )
            data = dict(
                region=wait["region"],
                source=str(begin["location"]),
                target=str(end["location"]) if end else None,
                waitingTaskInstance=wait["parent"],
                parentConfidence=wait["parentConfidence"],
                awaitedTasks=None,
                candidateTasks=candidates,
                candidateCount=len(candidates),
                candidateTotal=wait["candidateTotal"],
                candidateSetTruncated=wait["candidateSetTruncated"],
                completeAwaitedSet=False,
                blockedTime=None,
                interpretation="Recorded direct children that may be outstanding at entry; equal-time remote completions retain unresolved boundary order. TaskWait role alone does not distinguish depend clauses; these are conditional candidates, not proven task data dependencies.",
            )
            status = "complete" if end else "missing return"
            confidence = "recorded-region"
            if contract:
                data.update(
                    waitSemantics=contract["semantics"], recordingContract=contract
                )
                if completion_only:
                    data["interpretation"] = (
                        "Score-P OMPT records this dependency-clause construct only at completion. Its begin time, duration and dependency list are not recorded; outstanding-child candidates do not describe its awaited set."
                    )
                    confidence = "recorded-completion-observation"
                    status = (
                        "completion observed; wait duration unrecorded"
                        if end and end["time"] == begin["time"]
                        else "producer encoding mismatch" if end else "missing return"
                    )
                    if end and end["time"] != begin["time"]:
                        out.warn(
                            "task-wait-producer-encoding-mismatch",
                            "A Score-P OMPT dependency-clause completion observation has unequal entry/exit timestamps; its recorded interval cannot establish the missing wait duration.",
                        )
                else:
                    data["interpretation"] = (
                        "Score-P OMPT identifies an ordinary all-direct-children taskwait. The recorded parent context can omit undeferred/merged tasks, so these remain conditional child candidates rather than a complete awaited set."
                    )
                out.warn("task-producer-context-incomplete", contract["limitation"])
            out.interval(
                begin,
                end,
                "task-wait",
                "Taskwait",
                data,
                confidence=confidence,
                status=status,
            )
        unknown_waits = sum(wait["contract"] is None for wait in self.finished)
        if unknown_waits:
            out.warn(
                "task-wait-semantics-unrecorded",
                "Taskwait regions do not record whether an all-children or depend-clause wait occurred; candidate task lists are separate from proven awaited sets.",
                unknown_waits,
            )
        return len(self.finished)
