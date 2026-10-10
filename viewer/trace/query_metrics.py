"""Recorded counter sampling, reduction, and derived arithmetic queries."""

import bisect
import heapq
import itertools
import math
from operator import itemgetter

from .query_expressions import compile_expression

_time = itemgetter(0)
_value = itemgetter(1)


class MetricQueries:
    def metric_definition(self, member):
        md = next((m for m in self.meta["metrics"] if m["id"] == member), None)
        if md is None:
            raise ValueError("Metric not found")
        timing = {0: "START", 16: "POINT", 32: "LAST", 48: "NEXT"}.get(
            md.get("modeValue", 16) & 240, "POINT"
        )
        return dict(md, timing=timing)

    def metric_points(self, member, loc, start, end, mode, md, context=False):
        """Finite time-ordered samples; context also keeps the two before start."""
        # Subtract raw integers before scaling: float64 rounds distinct uint64 samples.
        scale = (2 if md.get("base", 1) == 0 else 10) ** md.get("exponent", 0)
        columns = "time,value" if mode == "value" else "time,value,raw"
        with self.connect() as db:
            cursor = db.cursor()
            cursor.row_factory = None
            previous = cursor.execute(
                f"SELECT {columns} FROM metrics WHERE metric=? AND location=? AND time<? ORDER BY time DESC,id DESC LIMIT 2",
                (member, loc, start),
            ).fetchall()
            previous.reverse()
            current = cursor.execute(
                f"SELECT {columns} FROM metrics WHERE metric=? AND location=? AND time>=? AND time<=? ORDER BY time,id",
                (member, loc, start, end),
            ).fetchall()
        rows = previous + current
        if mode == "value":
            # isfinite raises on NULL values, including unused context rows.
            if all(map(math.isfinite, map(_value, rows))):
                return rows if context else current
            return [
                (t, value)
                for t, value in rows
                if math.isfinite(value) and (t >= start or context)
            ]
        points = []
        prev = None
        for row in rows:
            t, value, raw = row
            if prev is None or t <= prev[0]:
                prev = row
                continue
            try:
                delta = (int(raw) - int(prev[2])) * scale
            except (ValueError, TypeError):
                delta = value - prev[1]
            value = delta / (t - prev[0]) if mode == "rate" else delta
            prev = row
            if not math.isfinite(value):
                continue
            if t >= start or context:
                points.append((t, value))
        return points

    @staticmethod
    def reduce_points(values, start, end, bins):
        """Keep each bin's first, last, minimum and maximum time-ordered sample."""
        step = max((end - start) / bins, 1e-15)
        samples = list(values)
        if not samples:
            return dict(points=[], min=None, max=None, samples=0)

        def bin_of(t):
            return int((t - start) / step)

        # Time order makes every bin a contiguous run; min/max/index select
        # the first extreme sample of each bin.
        times = list(map(_time, samples))
        values = list(map(_value, samples))
        points = []
        low = 0
        while low < len(samples):
            high = bisect.bisect_right(times, bin_of(times[low]), low, key=bin_of)
            bucket = values[low:high]
            indices = {
                low,
                high - 1,
                low + bucket.index(min(bucket)),
                low + bucket.index(max(bucket)),
            }
            points.extend(samples[i] for i in sorted(indices))
            low = high
        return dict(
            points=points, min=min(values), max=max(values), samples=len(samples)
        )

    def counter_scope(self, q):
        start, end, _, _ = self.scope(q, regions=False)
        mode = q.get("mode", "value")
        if mode not in ("value", "delta", "rate"):
            raise ValueError("Counter mode must be value, delta or rate")
        bins = max(50, min(2000, int(q.get("bins", 800))))
        return start, end, mode, bins

    def metric_locations(self, member):
        """Locations sampling member, in index order, by one index seek each.

        A NULL location is skipped: ``location=?`` never selects its samples.
        """
        locations = []
        with self.connect() as db:
            row = db.execute(
                "SELECT location FROM metrics WHERE metric=? AND location IS NOT NULL ORDER BY location LIMIT 1",
                (member,),
            ).fetchone()
            while row is not None:
                locations.append(row[0])
                row = db.execute(
                    "SELECT location FROM metrics WHERE metric=? AND location>? ORDER BY location LIMIT 1",
                    (member, row[0]),
                ).fetchone()
        return locations

    def counters(self, q):
        start, end, mode, bins = self.counter_scope(q)
        if not self.meta["metrics"]:
            return dict(metric={}, mode=mode, series=[])
        member = str(q.get("metric", self.meta["metrics"][0]["id"]))
        md = self.metric_definition(member)
        locs = (
            q["locations"].split(",")
            if q.get("locations")
            else self.metric_locations(member)
        )
        output = []
        for loc in (locs if start < end else []):
            series = self.reduce_points(
                self.metric_points(member, loc, start, end, mode, md), start, end, bins
            )
            if series["points"]:
                output.append(dict(location=loc, **series))
        # Value is the recorded quantity. Delta/rate are explicit user transformations,
        # never an implicit reinterpretation of OTF2 ABSOLUTE/RELATIVE metric modes.
        shown = dict(
            md,
            unit=(md.get("unit", "") + "/s" if mode == "rate" else md.get("unit", "")),
        )
        return dict(metric=shown, mode=mode, series=output)

    def derived(self, q):
        source = q.get("expression", "x")
        evaluate, variables = compile_expression(source)
        start, end, mode, bins = self.counter_scope(q)
        if not self.meta["metrics"]:
            return dict(metric=dict(name=source, unit="derived"), mode=mode, series=[])
        xmember = str(q.get("metric", self.meta["metrics"][0]["id"]))
        ymember = str(q.get("metricY", xmember))
        xm = self.metric_definition(xmember)
        ym = self.metric_definition(ymember) if "y" in variables else xm
        anchor_member = ymember if variables == {"y"} else xmember
        locs = (
            q["locations"].split(",")
            if q.get("locations")
            else self.metric_locations(anchor_member)
        )
        output = []
        for loc in (locs if start < end else []):
            xpoints = self.metric_points(xmember, loc, start, end, mode, xm, True)
            ypoints = (
                self.metric_points(ymember, loc, start, end, mode, ym, True)
                if "y" in variables
                else iter(())
            )

            def evaluated():
                latest = {}
                streams = heapq.merge(
                    ((t, 0, v) for t, v in xpoints), ((t, 1, v) for t, v in ypoints)
                )
                for t, updates in itertools.groupby(streams, key=lambda p: p[0]):
                    for _, which, value in updates:
                        latest["x" if which == 0 else "y"] = value
                    if t < start or not variables.issubset(latest):
                        continue
                    try:
                        value = evaluate(latest.get("x", 0), latest.get("y", 0))
                    except (ZeroDivisionError, ValueError, OverflowError):
                        continue
                    if math.isfinite(value):
                        yield t, value

            series = self.reduce_points(evaluated(), start, end, bins)
            if series["points"]:
                output.append(dict(location=loc, **series))
        return dict(
            metric=dict(name=source, unit="derived"),
            series=output,
            mode=mode,
            alignment="previous-sample",
        )
