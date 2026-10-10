"""Recording continuity needed by MPI ordinal and envelope associations.

ON resumes observations, not the missing communicator/request histories.
Observed intervals preceding a suspension remain usable. A suspension on any
thread of an MPI process can hide operations in that process's shared context.
"""

from __future__ import annotations

import json
import math
import bisect
from .communicators import Communicators

MARKER_LIMIT = 100_000


class MpiRecordingContinuity:
    def __init__(self, trace, brackets=None):
        self.trace = trace
        self.brackets = brackets or {}
        self.resolver = Communicators(trace.defs)
        self.first = {}
        self.gaps = {}
        self.open = {}
        self.births = {}
        rows = trace.rows(
            "SELECT id,location,time,data FROM events WHERE kind='MeasurementOnOff' ORDER BY time,id LIMIT ?",
            [MARKER_LIMIT + 1],
        )
        self.partial = len(rows) > MARKER_LIMIT
        for row in rows[:MARKER_LIMIT]:
            data = json.loads(row["data"])
            mode = data.get("measurementMode")
            if not isinstance(row["time"], (int, float)) or not math.isfinite(
                row["time"]
            ):
                self.partial = True
                continue
            if type(mode) is int and mode == 1:
                gap = self.open.pop(str(row["location"]), None)
                if gap is not None:
                    gap["resumedAt"] = row["time"]
                continue
            scope = self.resolver.request_scope(row["location"])
            if str(row["location"]) not in self.open:
                gap = dict(
                    event=row["id"],
                    location=str(row["location"]),
                    time=row["time"],
                    measurementMode=mode,
                    scope=scope,
                    resumedAt=None,
                )
                self.first.setdefault(scope, gap)
                self.gaps.setdefault(scope, []).append(gap)
                self.open[str(row["location"])] = gap
        if not self.first:
            self.brackets = {}
        self.gap_index = {}
        for scope, gaps in self.gaps.items():
            maximum = -math.inf
            prefix = []
            for gap in gaps:
                maximum = max(
                    maximum,
                    gap["resumedAt"] if gap["resumedAt"] is not None else math.inf,
                )
                prefix.append(maximum)
            self.gap_index[scope] = ([gap["time"] for gap in gaps], prefix)

    def _creation_candidates(self, create):
        if not hasattr(self, "creation_ops"):
            self.creation_ops = {}
            rows = self.trace.rows(
                """SELECT c.*,e.kind event_kind,e.data event_data FROM collectives c
                JOIN events e ON e.id=c.event WHERE c.operation='CREATE_HANDLE' ORDER BY c.start,c.id LIMIT ?""",
                [MARKER_LIMIT + 1],
            )
            if len(rows) > MARKER_LIMIT:
                return []
            for row in rows:
                bracket = self.brackets.get(row["event"], {})
                raw = json.loads(row["event_data"])
                if (
                    not bracket.get("valid")
                    or not all(math.isfinite(row[k]) for k in ("start", "end"))
                    or type(raw.get("collectiveOp")) is not int
                    or raw["collectiveOp"] != 17
                    or row["event_kind"]
                    not in ("MpiCollectiveEnd", "NonBlockingCollectiveComplete")
                ):
                    continue
                row["beginEvent"] = bracket["event"]
                starts, prefix, values = self.creation_ops.setdefault(
                    bracket["location"], ([], [], [])
                )
                starts.append(row["start"])
                prefix.append(max(prefix[-1] if prefix else -math.inf, row["end"]))
                values.append(row)
        starts, prefix, values = self.creation_ops.get(create["location"], ([], [], []))
        index = bisect.bisect_right(starts, create["time"]) - 1
        candidates = []
        work = 0
        while index >= 0 and prefix[index] >= create["time"]:
            work += 1
            if work > 1024:
                return []
            row = values[index]
            if (
                row["end"] >= create["time"]
                and row["beginEvent"] < create["id"] < row["event"]
            ):
                candidates.append(row)
            index -= 1
        return candidates

    def birth(self, scope, comm):
        """Only a unique, bracketed CREATE_HANDLE gives a fresh MPI context."""
        key = (scope, str(comm))
        if key in self.births:
            return self.births[key]
        self.births[key] = None
        definition = self.trace.defs.get("Comm", {}).get(
            str(comm)
        ) or self.trace.defs.get("InterComm", {}).get(str(comm), {})
        flags = definition.get("flags")
        if type(flags) is not int or flags != 1:
            return None
        if not hasattr(self, "creations"):
            self.creations = {}
            self.destructions = {}
            self.unknown_lifecycle = {}
            rows = self.trace.rows(
                "SELECT id,location,time,kind,data FROM events WHERE kind IN ('CommCreate','CommDestroy') ORDER BY id LIMIT ?",
                [MARKER_LIMIT + 1],
            )
            if len(rows) > MARKER_LIMIT:
                return None
            for row in rows:
                data = json.loads(row["data"])
                reference = data.get("communicator")
                owner = self.resolver.request_scope(row["location"])
                if (
                    type(reference) is not int
                    or not 0 <= reference < 2**32 - 1
                    or not isinstance(row["time"], (int, float))
                    or not math.isfinite(row["time"])
                ):
                    self.unknown_lifecycle[owner] = min(
                        self.unknown_lifecycle.get(owner, math.inf),
                        (
                            row["time"]
                            if isinstance(row["time"], (int, float))
                            and math.isfinite(row["time"])
                            else -math.inf
                        ),
                    )
                    continue
                target = (
                    self.creations if row["kind"] == "CommCreate" else self.destructions
                )
                target.setdefault((owner, str(reference)), []).append(row)
        rows = self.creations.get(key, [])
        if len(rows) != 1:
            return None
        create = rows[0]
        matches = self._creation_candidates(create)
        if len(matches) == 1:
            row = matches[0]
            self.births[key] = dict(
                start=row["start"],
                end=row["end"],
                event=create["id"],
                beginEvent=row["beginEvent"],
                endEvent=row["event"],
                location=create["location"],
                destroyedAt=min(
                    (row["time"] for row in self.destructions.get(key, [])),
                    default=math.inf,
                ),
            )
        return self.births[key]

    def issue(self, locations, end, *, comm=None, start=None):
        if self.partial:
            return dict(reason="measurement-scan-incomplete", complete=False)
        if not self.first:
            return None
        # Remote same-tick ordering is unknown; retain the conservative equal
        # boundary, without treating the global reader order as causality.
        found = []
        for scope in {self.resolver.request_scope(location) for location in locations}:
            marker = self.first.get(scope)
            if marker is not None and marker["time"] <= end:
                birth = self.birth(scope, comm) if comm is not None else None
                times, prefix = self.gap_index[scope]
                last = bisect.bisect_right(times, end) - 1
                if (
                    birth is not None
                    and start is not None
                    and birth["end"] < start
                    and prefix[last] < birth["start"]
                    and birth["destroyedAt"] > end
                    and self.unknown_lifecycle.get(scope, math.inf) > end
                ):
                    continue
                found.append(marker)
        if not found:
            return None
        return dict(
            reason="recording-suspended-or-unknown",
            complete=False,
            firstGap=min(found, key=lambda marker: (marker["time"], marker["event"])),
            interpretation="Unrecorded MPI operations can change collective ordinals, message envelopes and request generations. Resuming recording does not reconstruct those histories.",
        )

    def proof(self, locations, end, comm):
        """Inspectable fresh-context evidence after issue() accepted the input."""
        if not self.first:
            return dict(complete=True)
        births = []
        for scope in sorted(
            {self.resolver.request_scope(location) for location in locations}
        ):
            marker = self.first.get(scope)
            if marker is not None and marker["time"] <= end:
                birth = self.births.get((scope, str(comm)))
                if birth:
                    births.append(
                        dict(
                            scope=scope,
                            **{
                                key: value
                                for key, value in birth.items()
                                if key != "destroyedAt"
                            },
                        )
                    )
        return (
            dict(complete=True, freshCommunicatorEvidence=births)
            if births
            else dict(complete=True)
        )
