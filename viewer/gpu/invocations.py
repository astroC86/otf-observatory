"""Resolve GPU invocation attributes without guessing at equal clock ticks."""

from __future__ import annotations

import collections
import json


class GpuInvocations:
    """Bounded indexed lookup, with recorded Enter/Leave ordering at boundaries.

    A parameter attaches to the active invocation; an Enter attribute attaches
    after its push, and a Leave attribute before its pop. Rounded timestamps
    alone cannot establish any of those choices at a shared boundary.
    """

    def __init__(self, trace, warn, limit=1024):
        self.trace, self.warn, self.limit = trace, warn, limit
        self.boundaries = collections.OrderedDict()

    def at(self, event):
        time, location = event["time"], str(event["location"])
        region = event["data"].get("region")
        if region is None and "callingContext" in event["data"]:
            region = (
                self.trace.defs.get("CallingContext", {})
                .get(str(event["data"]["callingContext"]), {})
                .get("region")
            )
        where = " AND s.region=?" if region is not None else ""
        rows = self.trace.rows(
            "SELECT s.* FROM spans s JOIN span_time ix ON ix.id=s.id "
            "WHERE ix.start<=? AND ix.end>=? AND s.location=? AND s.start<=? AND s.end>=?"
            + where
            + " ORDER BY s.depth DESC,s.start DESC,s.id LIMIT ?",
            [time, time, location, time, time]
            + ([str(region)] if region is not None else [])
            + [self.limit + 1],
        )
        if len(rows) > self.limit:
            self.warn(
                "gpu-invocation-limit",
                "Invocation nesting exceeded the lookup bound; the identifier remains unassigned.",
            )
            return None
        if not rows:
            return None
        if not any(row["start"] == time or row["end"] == time for row in rows):
            return rows[0]
        key = (location, time)
        if key not in self.boundaries:
            self.boundaries[key] = self.trace.rows(
                "SELECT id,kind,data FROM events WHERE location=? AND time=? "
                "AND kind IN ('Enter','Leave','CallingContextEnter','CallingContextLeave','CallingContextSample',"
                "'OmpTaskSwitch','OmpTaskComplete','ThreadTaskSwitch','ThreadTaskComplete') ORDER BY id LIMIT ?",
                [location, time, self.limit + 1],
            )
            while len(self.boundaries) > 1024:
                self.boundaries.popitem(last=False)
        boundaries = self.boundaries[key]
        if len(boundaries) > self.limit:
            self.warn(
                "gpu-invocation-limit",
                "Same-tick invocation transitions exceeded the lookup bound; the identifier remains unassigned.",
            )
            return None
        if not any(row["kind"] in ("Enter", "Leave") for row in boundaries):
            # Calling-context normalization can introduce several synthetic
            # frames. A unique recorded context boundary is still identifiable;
            # competing candidates require a producer-aware replay.
            if len(rows) == 1 and event["kind"].startswith("CallingContext"):
                return rows[0]
            self.warn(
                "gpu-invocation-boundary-unresolved",
                "An identifier at an invocation boundary lacks unambiguous recorded Enter/Leave brackets.",
            )
            return None
        active = {row["id"]: row for row in rows if row["start"] < time}
        unentered = sorted(
            (row for row in rows if row["start"] == time), key=lambda row: row["id"]
        )
        for boundary in boundaries:
            current = boundary["id"] == event["id"]
            if boundary["id"] > event["id"] or current and event["kind"] != "Enter":
                break
            if boundary["kind"] not in ("Enter", "Leave"):
                self.warn(
                    "gpu-invocation-boundary-unresolved",
                    "Calling-context or task transitions make this same-tick invocation assignment ambiguous.",
                )
                return None
            data = json.loads(boundary["data"])
            ref = str(data.get("region"))
            if boundary["kind"] == "Enter":
                entered = next(
                    (row for row in unentered if str(row["region"]) == ref), None
                )
                if entered:
                    active[entered["id"]] = entered
                    unentered.remove(entered)
            else:
                leaving = max(
                    (row for row in active.values() if str(row["region"]) == ref),
                    key=lambda row: (row["depth"], row["start"], row["id"]),
                    default=None,
                )
                if leaving:
                    active.pop(leaving["id"])
        return max(
            active.values(),
            key=lambda row: (row["depth"], row["start"], row["id"]),
            default=None,
        )


class GpuSubmissionOrder:
    """Call-return before call-entry, preserving original equal-tick brackets."""

    def __init__(self, trace, lookup, warn):
        self.trace = trace
        self.lookup = lookup
        self.warn = warn
        self.cache = {}

    def boundary(self, item, kind):
        key = (item["id"], kind)
        if key in self.cache:
            return self.cache[key]
        when = item["start"] if kind == "Enter" else item["end"]
        rows = self.trace.rows(
            "SELECT id,location,time,kind,data FROM events WHERE location=? AND time=? AND kind=? ORDER BY id LIMIT 1025",
            [item["location"], when, kind],
        )
        found = []
        if len(rows) <= 1024:
            for event in rows:
                event["data"] = json.loads(event["data"])
                if str(event["data"].get("region")) != item["data"].get("region"):
                    continue
                row = self.lookup.at(event)
                if row and row["id"] == item["data"].get("span"):
                    found.append(event["id"])
        self.cache[key] = found[0] if len(found) == 1 else None
        return self.cache[key]

    def before(self, source, target):
        if source["end"] < target["start"]:
            return True
        if source["end"] > target["start"]:
            return False
        if source["location"] == target["location"]:
            a = self.boundary(source, "Leave")
            b = self.boundary(target, "Enter")
            if a is not None and b is not None and a < b:
                return True
        self.warn(
            "gpu-wait-submission-order-unresolved",
            "Equal-time GPU calls lack a proved same-thread Leave-before-Enter order.",
        )
        return False
