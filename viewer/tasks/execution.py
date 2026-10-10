"""Bounded, recorded task execution identity for causal operation ordering.

Uses the task graph's lifecycle replay. Same-task program order is distinct
from application dataflow or an inferred taskwait membership set.
"""

import bisect
import collections
import json

from .dependencies import TaskCollector
from .identity import process_scope

TASK_CONTEXT_LIMIT = 150000
KINDS = (
    "OmpTaskCreate",
    "OmpTaskSwitch",
    "OmpTaskComplete",
    "ThreadTaskCreate",
    "ThreadTaskSwitch",
    "ThreadTaskComplete",
    "ThreadTeamBegin",
    "ThreadTeamEnd",
)


class _ExecutionCollector(TaskCollector):
    def interval(
        self,
        first,
        second,
        kind,
        label,
        data=None,
        confidence="recorded",
        status=None,
        end=None,
    ):
        if (
            kind != "task-execution"
            or second is None
            or confidence != "recorded"
            or status is not None
            or first["time"] >= second["time"]
        ):
            return
        self.records.append(
            dict(
                location=str(first["location"]),
                start=first["time"],
                end=second["time"],
                beginEvent=first["id"],
                endEvent=second["id"],
                task=data["task"],
                taskInstance=data["taskInstance"],
            )
        )


class TaskExecutionIndex:
    def __init__(self, trace, cap=None):
        if cap is None:
            cap = TASK_CONTEXT_LIMIT
        self.trace = trace
        self.diagnostics = collections.Counter()
        self.by_location = {}
        self.cache = {}
        self.boundaries = {}
        self.partial = False
        self.recorded = bool(
            trace.rows(
                "SELECT id FROM events WHERE kind IN ("
                + ",".join("?" for _ in KINDS[:6])
                + ") LIMIT 1",
                list(KINDS[:6]),
            )
        )
        if not self.recorded:
            return
        rows = trace.rows(
            "SELECT id,location,time,kind,data FROM events WHERE kind IN ("
            + ",".join("?" for _ in KINDS)
            + ") ORDER BY id LIMIT ?",
            [*KINDS, cap + 1],
        )
        if len(rows) > cap:
            self.partial = True
            self.diagnostics["task-order-context-limit"] += 1
            return
        if not rows:
            return
        collector = _ExecutionCollector(
            trace, cap, rows, lambda loc: process_scope(trace.defs, loc)
        )
        self.diagnostics.update(collector.diagnostics)
        transitions = collections.defaultdict(list)
        for event in rows:
            if event["kind"].startswith("ThreadTeam"):
                transitions[str(event["location"])].append(event["id"])
        grouped = collections.defaultdict(list)
        for segment in collector.records:
            task = collector.model["instances"][segment["taskInstance"]]
            if task["ambiguous"]:
                continue
            # Team entry can install an unnamed implicit task; neither an
            # enclosing explicit task nor its resumption may be assumed.
            boundaries = transitions[segment["location"]]
            lo = bisect.bisect_right(boundaries, segment["beginEvent"])
            if lo < len(boundaries) and boundaries[lo] <= segment["endEvent"]:
                continue
            grouped[segment["location"]].append(segment)
        for location, segments in grouped.items():
            segments.sort(key=lambda item: (item["start"], item["beginEvent"]))
            high = float("-inf")
            maxima = []
            for segment in segments:
                high = max(high, segment["end"])
                maxima.append(high)
            self.by_location[location] = (
                segments,
                [item["start"] for item in segments],
                maxima,
            )

    def _boundary(self, op, side):
        time = op.start if side == "Enter" else op.end
        if op.region is None:
            return None
        key = (op.location, time, side, op.region)
        if key not in self.boundaries:
            rows = self.trace.rows(
                "SELECT id,kind,data FROM events WHERE location=? AND time=? AND kind IN (?,?) ORDER BY id LIMIT 1025",
                [op.location, time, side, "CallingContext" + side],
            )
            if len(rows) > 1024:
                self.diagnostics["task-order-boundary-limit"] += 1
                self.boundaries[key] = None
            else:
                # Calling-context records may expand into several synthesized
                # boundaries; their task placement remains unresolved here.
                ids = [
                    row["id"]
                    for row in rows
                    if row["kind"] == side
                    and str(json.loads(row["data"]).get("region")) == op.region
                ]
                self.boundaries[key] = (
                    ids[0]
                    if len(ids) == 1
                    and not any(
                        row["kind"].startswith("CallingContext") for row in rows
                    )
                    else None
                )
        return self.boundaries[key]

    def identify(self, op):
        key = (op.location, op.span, op.event, op.region, op.start, op.end)
        if key in self.cache:
            return self.cache[key]
        result = None
        if (
            not self.partial
            and op.start is not None
            and op.end is not None
            and op.end >= op.start
        ):
            segments, starts, maxima = self.by_location.get(op.location, ([], [], []))
            pos = bisect.bisect_right(starts, op.start) - 1
            matches = []
            while pos >= 0 and maxima[pos] >= op.end:
                segment = segments[pos]
                pos -= 1
                if segment["start"] > op.start or segment["end"] < op.end:
                    continue
                if op.start == segment["start"]:
                    boundary = self._boundary(op, "Enter")
                    if boundary is None or boundary <= segment["beginEvent"]:
                        continue
                if op.end == segment["end"]:
                    boundary = self._boundary(op, "Leave")
                    if boundary is None or boundary >= segment["endEvent"]:
                        continue
                matches.append(segment)
            if len(matches) == 1:
                result = matches[0]
        self.cache[key] = result
        return result
