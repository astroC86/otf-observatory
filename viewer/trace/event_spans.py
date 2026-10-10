"""Bounded recorded-operation lookup and replay work accounting."""

from types import SimpleNamespace
from ..causality.operations import BoundaryOrder


class WorkBudget:
    """Stop replay before incomplete evidence can be accepted as complete."""

    def __init__(self, limit):
        self.limit = limit
        self.work = 0

    def __call__(self, amount=1):
        self.work += amount
        if self.work > self.limit:
            raise OverflowError


class EventSpans:
    def __init__(self, trace, diagnostics, prefix="source"):
        self.trace = trace
        self.diagnostics = diagnostics
        self.prefix = prefix
        self.order = BoundaryOrder(trace, max_boundaries=2048)

    def at(self, event):
        # Outward-rounded R-tree coordinates are only the coarse filter.
        time, location = event["time"], str(event["location"])
        rows = self.trace.rows(
            """SELECT s.id,s.location,s.region,s.start,s.end,s.depth,s.sampled,s.incomplete
            FROM spans s JOIN span_time ix ON ix.id=s.id
            WHERE ix.start<=? AND ix.end>=? AND s.location=? AND s.start<=? AND s.end>=?
            LIMIT 513""",
            [time, time, location, time, time],
        )
        if len(rows) > 512:
            self.diagnostics[self.prefix + "_operation_limit"] += 1
            return None
        spans = [
            SimpleNamespace(
                **row,
                name=self.trace.regions.get(row["region"], {}).get(
                    "name", row["region"]
                )
            )
            for row in rows
        ]
        limited = self.order.limited
        spans = self.order.filter(spans, location, time, event["id"])
        if self.order.limited > limited:
            self.diagnostics[self.prefix + "_boundary_limit"] += 1
        if not spans:
            return None
        depth = max(span.depth for span in spans)
        deepest = [span for span in spans if span.depth == depth]
        if len(deepest) != 1:
            self.diagnostics[self.prefix + "_operation_ambiguous"] += 1
            return None
        span = deepest[0]
        return span if not span.sampled and not span.incomplete else None
