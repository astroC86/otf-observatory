"""On-demand source activity and upstream completion prerequisites.

Recorded location order explains where an enabling operation was delayed. It
does not prove how much sooner that operation would execute if a prerequisite
were removed. Branches overlap in time and must never be summed as costs.
"""

from __future__ import annotations

import bisect
import collections
import functools
import json
import math

from .operations import clipped
from . import activity

TASK_EVENTS = (
    "OmpTaskSwitch",
    "OmpTaskCreate",
    "OmpTaskComplete",
    "ThreadTaskSwitch",
    "ThreadTaskCreate",
    "ThreadTaskComplete",
)
SPAN_LIMIT = 20000
LINK_LIMIT = 2000
TASK_LINK_LIMIT = 20000  # Direct causes or compressed groups sharing one target.


class Context:
    def __init__(self, trace, analyses, depth, nodes):
        self.trace = trace
        self.analyses = analyses
        self.max_depth = depth
        self.max_nodes = nodes
        self.nodes = []
        self.diagnostics = collections.Counter()
        self.span_budget = SPAN_LIMIT
        self.link_budget = LINK_LIMIT
        self.intervals = {}
        self.tasks = {}
        self.execution = None
        self.propagated_analyses = set()
        for kind, analysis in self.analyses.items():
            self.propagate_diagnostics(kind, analysis)

    def propagate_diagnostics(self, kind, analysis):
        if kind in self.propagated_analyses:
            return
        self.propagated_analyses.add(kind)
        if analysis.get("partial"):
            self.diagnostics["upstream-analysis-" + kind + "-partial"] += 1
        for code, count in analysis["diagnostics"].items():
            if count and ("limit" in code or "truncat" in code):
                self.diagnostics["upstream-analysis-" + code] += count

    @functools.cached_property
    def by_location(self):
        from ..mpi.wait_analysis import _analysis as mpi_analysis
        from ..threads.synchronization import _analysis as thread_analysis

        for kind, analyze in [
            ("waits", mpi_analysis),
            ("synchronization", thread_analysis),
        ]:
            if kind not in self.analyses:
                self.analyses[kind] = analyze(self.trace)
        rows = collections.defaultdict(list)
        for kind, analysis in self.analyses.items():
            self.propagate_diagnostics(kind, analysis)
            for record in analysis["records"]:
                if record.causes:
                    rows[record.span.location].append((kind, record))
        return rows

    @functools.cached_property
    def by_task(self):
        tasks = collections.defaultdict(list)
        work = 0
        limited = False
        for records in self.by_location.values():
            for kind, record in records:
                for cause in (
                    record.causes.query_entries()
                    if hasattr(record.causes, "query_entries")
                    else record.causes
                ):
                    work += 1
                    if work > TASK_LINK_LIMIT:
                        limited = True
                        break
                    execution = self.execution.identify(cause.target)
                    if execution is not None and cause.end > cause.start:
                        tasks[execution["taskInstance"]].append((kind, cause))
                if limited:
                    break
            if limited:
                break
        if limited:
            self.diagnostics["task-order-link-limit"] += 1
        for key, rows in tasks.items():
            rows.sort(key=lambda row: (row[1].start, row[1].id))
            tasks[key] = self.interval_index(rows)
        return tasks

    @staticmethod
    def interval_index(rows):
        high = -math.inf
        maximum = []
        for _, cause in rows:
            high = max(high, cause.end)
            maximum.append(high)
        return rows, [cause.start for _, cause in rows], maximum

    def candidates(self, location, start, end, task=None):
        if self.link_budget <= 0:
            self.diagnostics["upstream-link-limit"] += 1
            return []
        if location not in self.intervals:
            # A barrier can have millions of logical peer links. Index its
            # target view once, then expand only the requested traversal page.
            rows = [
                (kind, c)
                for kind, r in self.by_location.get(location, ())
                for c in (
                    r.causes.query_entries()
                    if hasattr(r.causes, "query_entries")
                    else r.causes
                )
                if c.end > c.start
            ]
            rows.sort(key=lambda row: (row[1].start, row[1].end, row[1].id))
            self.intervals[location] = self.interval_index(rows)
        indexes = [self.intervals[location]]
        if task is not None and task["taskInstance"] in self.by_task:
            indexes.append(self.by_task[task["taskInstance"]])
        result = []
        seen = set()
        for rows, starts, maximum in indexes:
            i = bisect.bisect_left(starts, end) - 1
            while i >= 0 and maximum[i] > start:
                kind, entry = rows[i]
                i -= 1
                if entry.end <= start:
                    continue
                causes = (
                    entry.overlapping(start, end, self.link_budget - len(result) + 1)
                    if hasattr(entry, "overlapping")
                    else (entry,)
                )
                for cause in causes:
                    if (kind, cause.id) in seen:
                        continue
                    seen.add((kind, cause.id))
                    result.append((kind, cause))
                    if len(result) > self.link_budget:
                        break
                if len(result) > self.link_budget:
                    self.diagnostics["upstream-link-limit"] += 1
                    break
            if len(result) > self.link_budget:
                break
        result = result[: self.link_budget]
        self.link_budget -= len(result)
        return sorted(result, key=lambda row: (row[1].start, row[1].id))

    def has_task_scheduling(self, location, start, end):
        key = (location, start, end)
        if key not in self.tasks:
            marks = ",".join("?" for _ in TASK_EVENTS)
            rows = self.trace.rows(
                f"SELECT id FROM events WHERE location=? AND time>=? AND time<=? AND kind IN ({marks}) LIMIT 1",
                [location, start, end, *TASK_EVENTS],
            )
            self.tasks[key] = bool(rows)
        return self.tasks[key]

    def ordered(self, upstream, cause):
        end = upstream.target.end
        if end is None or end > cause.ready:
            return False
        if end < cause.ready:
            return True
        if upstream.target.location != cause.source.location:
            # A merged same-tick order across locations is not an actual
            # local Leave-before-Enter observation, even for a migrating task.
            return False
        # Equality of timestamps is insufficient. Require a unique actual
        # Leave before the source event that establishes readiness.
        if cause.source.event is None or upstream.target.region is None:
            return False
        rows = self.trace.rows(
            "SELECT id,location,time FROM events WHERE id=?", [cause.source.event]
        )
        if (
            not rows
            or rows[0]["location"] != cause.source.location
            or rows[0]["time"] != cause.ready
        ):
            return False
        leaves = self.trace.rows(
            "SELECT id,data FROM events WHERE location=? AND time=? AND kind='Leave' LIMIT 1025",
            [cause.source.location, end],
        )
        if len(leaves) > 1024:
            self.diagnostics["same-tick-order-limit"] += 1
            return False
        matching = [
            r["id"]
            for r in leaves
            if str(json.loads(r["data"]).get("region")) == upstream.target.region
        ]
        return len(matching) == 1 and matching[0] < cause.source.event

    def expand(self, kind, cause, start, end, parent=None, path=frozenset(), depth=0):
        a = min(end, max(start, cause.start))
        b = max(a, min(end, cause.end))
        ident = len(self.nodes)
        node = dict(
            id=ident,
            parent=parent,
            depth=depth,
            analysis=kind,
            cause=clipped([cause], a, b)[0],
            upstream=[],
            alternatives=[],
            stops=[],
        )
        self.nodes.append(node)
        location = cause.source.location
        segments, used, truncated = (
            activity._partition(self.trace, location, a, b, self.span_budget)
            if location is not None
            else (
                [
                    dict(
                        start=a,
                        end=b,
                        duration=b - a,
                        status="unknown-location",
                        operations=[],
                    )
                ],
                0,
                False,
            )
        )
        self.span_budget -= used
        coverage = collections.defaultdict(float)
        for segment in segments:
            coverage[segment["status"]] += segment["duration"]
        node["context"] = dict(
            location=location,
            start=a,
            end=b,
            duration=b - a,
            segments=segments,
            coverage=dict(coverage),
            interpretation="Recorded activity on the enabling location during this prerequisite-unavailable interval. Activity is context, not a counterfactual delay allocation.",
        )
        if truncated:
            self.diagnostics["source-span-limit"] += 1
            node["stops"].append("source-span-limit")
        if b <= a or location is None:
            return ident
        key = (kind, cause.id)
        if key in path:
            node["stops"].append("cycle")
            self.diagnostics["cycle"] += 1
            return ident
        # A task switch can put unrelated tasks between the waiting operation
        # and the enabling event. Location order alone cannot connect them.
        scheduled = self.has_task_scheduling(location, a, cause.ready)
        node["context"]["taskSchedulingRecorded"] = scheduled
        if self.execution is None:
            from ..tasks.execution import TaskExecutionIndex

            self.execution = TaskExecutionIndex(self.trace)
        source_execution = self.execution.identify(cause.source)
        if source_execution is not None:
            node["context"]["taskExecution"] = source_execution
        for upstream_kind, upstream in self.candidates(
            location, a, b, source_execution
        ):
            ua = max(a, upstream.start)
            ub = min(b, upstream.end)
            if (upstream_kind, upstream.id) == key:
                continue
            item = dict(analysis=upstream_kind, cause=clipped([upstream], ua, ub)[0])
            target_execution = (
                self.execution.identify(upstream.target)
                if source_execution is not None
                else None
            )
            same_identity = (
                source_execution is not None
                and target_execution is not None
                and source_execution["taskInstance"] == target_execution["taskInstance"]
            )
            clock_conflict = (
                same_identity
                and source_execution["beginEvent"] != target_execution["beginEvent"]
                and target_execution["end"] > source_execution["start"]
            )
            same_task = (
                same_identity
                and not clock_conflict
                and (
                    source_execution["beginEvent"] == target_execution["beginEvent"]
                    or target_execution["endEvent"] <= source_execution["beginEvent"]
                )
            )
            reason = None
            if not upstream.required:
                reason = "conditional-precondition"
            elif not self.ordered(upstream, cause):
                reason = "operation-order-unresolved"
            elif clock_conflict:
                reason = "task-clock-order-unresolved"
                self.diagnostics[reason] += 1
            elif (scheduled or source_execution is not None) and not same_task:
                reason = "task-order-unresolved"
            if reason:
                item["reason"] = reason
                node["alternatives"].append(item)
                continue
            reason = (
                "depth-limit"
                if depth >= self.max_depth
                else "node-limit" if len(self.nodes) >= self.max_nodes else None
            )
            if reason:
                node["stops"].append(reason)
                self.diagnostics[reason] += 1
                break
            child = self.expand(
                upstream_kind, upstream, ua, ub, ident, path | {key}, depth + 1
            )
            self.nodes[child]["relationship"] = (
                "required-prerequisite-in-recorded-task-order"
                if same_task
                else "required-prerequisite-in-source-location-order"
            )
            if same_task:
                self.nodes[child]["taskOrder"] = dict(
                    taskInstance=source_execution["taskInstance"],
                    task=source_execution["task"],
                    predecessorExecution=target_execution,
                    enablingExecution=source_execution,
                    interpretation="Recorded execution order of the same task instance; not an application data dependency between tasks.",
                )
            node["upstream"].append(child)
        return ident


def wait_cause(trace, q):
    kind = q.get("analysis", "waits")
    if kind not in ("waits", "synchronization"):
        raise ValueError("Unknown wait analysis")
    ident = q.get("cause", "")
    if not ident or len(ident) > 512:
        raise ValueError("A valid cause identifier is required")
    start, end, _, _ = trace.scope(q, regions=False)
    depth = max(0, min(12, int(q.get("depth", 4))))
    nodes = max(1, min(128, int(q.get("nodes", 48))))
    if kind == "waits":
        from ..mpi.wait_analysis import _analysis
    else:
        from ..threads.synchronization import _analysis
    analysis = _analysis(trace)
    cause = None
    for record in analysis["records"]:
        cause = (
            record.causes.resolve(ident)
            if hasattr(record.causes, "resolve")
            else next((c for c in record.causes if c.id == ident), None)
        )
        if cause is not None:
            break
    if cause is None:
        cause = next(
            (
                c
                for attempt in analysis.get("rmaLockAttempts", [])
                for c in attempt["causes"]
                if c.id == ident
            ),
            None,
        )
    if cause is None:
        raise ValueError("Wait cause not found")
    context = Context(trace, {kind: analysis}, depth, nodes)
    context.expand(kind, cause, start, end)
    if context.execution is not None:
        context.diagnostics.update(context.execution.diagnostics)
    return dict(
        root=0,
        nodes=context.nodes,
        diagnostics=[
            dict(code=k, count=v) for k, v in sorted(context.diagnostics.items())
        ],
        traversalComplete=not context.diagnostics,
        limits=dict(
            depth=depth,
            nodes=nodes,
            spans=SPAN_LIMIT,
            upstreamLinks=LINK_LIMIT,
            taskTargetGroups=TASK_LINK_LIMIT,
        ),
        exactBlockedTime=None,
        interpretation="Required and conditional completion prerequisites retain their evidence labels. Upstream links use recorded task execution order when established, otherwise source-location order. They do not make a conditional root proven or establish dataflow between tasks. Concurrent branches overlap and are not additive. Unrecorded work, unresolved task order and traversal limits remain explicit. No counterfactual speedup or exact CPU blocked time is inferred.",
    )
