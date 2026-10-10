"""Per-query bounds, resource accounting and signal materialization."""

import ast
import contextlib
import json
import math
import re
import time

from . import cursors as metric_cursors
from . import limits
from .attributes import AttributeContext
from .expressions import evaluate_ast
from .function_sources import FunctionSources
from .operation_sources import OperationSources
from .patterns import function_matches, function_patterns
from .pixels import source_properties
from .serialization import ResultBuilder
from .series import Data, Series
from .sources import SourceRegistry
from .values import finite, number

# Rows per fetch_rows batch: few Python iterations, little overshoot of limits.
FETCH_BATCH = 4096


def decode(value, default, name):
    if value is None or value == "":
        return default
    if isinstance(value, str):
        if len(value) > 131072:
            raise ValueError(name + " is too large")
        try:
            return json.loads(value)
        except (ValueError, RecursionError) as error:
            raise ValueError("Invalid " + name + " JSON") from error
    return value


class Context(AttributeContext):
    """Own query bounds and budgets; source components own their caches."""

    def __init__(self, trace, q):
        super().__init__(trace)
        self.q = q
        self.start, self.end, _, _ = trace.scope(q, regions=False)
        # Native hierarchy requests retain the chart's Timeline bounds even
        # when an enclosing temporal operator seeks its child back to zero.
        self.timeline_start, self.timeline_end = self.start, self.end
        self.deadline = time.monotonic() + limits.MAX_SECONDS
        self.inputs = 0
        self.work = 0
        self.source_names = []
        self.source_diagnostics = []
        self.bins = max(1, min(2000, int(q.get("bins", 800))))
        self.sources = decode(q.get("sources"), None, "sources")
        if self.sources is None:
            metrics = trace.meta.get("metrics", [])
            self.sources = {
                "x": dict(
                    type="counter",
                    metric=q.get("metric", metrics[0].get("id", "") if metrics else ""),
                    mode=q.get("mode", "value"),
                ),
                "y": dict(
                    type="counter",
                    metric=q.get("metricY", q.get("metric", "")),
                    mode=q.get("mode", "value"),
                ),
            }
        if not isinstance(self.sources, dict) or len(self.sources) > limits.MAX_SOURCES:
            raise ValueError("Configure at most 32 named sources")
        if any(
            not isinstance(k, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", k)
            for k in self.sources
        ):
            raise ValueError("Source names must be simple identifiers")
        self.formulas = decode(q.get("formulas"), {}, "formulas")
        if not isinstance(self.formulas, dict) or len(self.formulas) > 64:
            raise ValueError("Invalid formulas library")
        requested = (
            str(q.get("locations", "")).split(",")
            if q.get("locations")
            else list(trace.locations)
        )
        self.locations = [
            loc for loc in dict.fromkeys(requested) if loc in trace.locations
        ]
        if len(self.locations) > limits.MAX_LOCATIONS:
            raise ValueError("Select at most 2048 locations for custom metrics")
        self.members = {loc: frozenset([loc]) for loc in self.locations}
        self.names = {
            loc: trace.locations[loc].get("name", loc) for loc in self.locations
        }
        self.groups = {str(g["id"]): g for g in trace.meta.get("groups", [])}
        self.nodes = {str(n["id"]): n for n in trace.meta.get("nodes", [])}
        self.source = SourceRegistry(self)
        self.functions = FunctionSources(self)
        self.operations = OperationSources(self)
        self.output = ResultBuilder(self)

    def charge(self, n, inputs=False):
        self.work += n
        if inputs:
            self.inputs += n
        if self.inputs > limits.MAX_INPUT_POINTS or self.work > limits.MAX_WORK_POINTS:
            raise ValueError(
                "Custom metric input/operation limit reached; narrow the time range or select fewer locations"
            )
        if time.monotonic() > self.deadline:
            raise ValueError(
                "Custom metric evaluation exceeded 30 seconds; narrow the selection"
            )

    @contextlib.contextmanager
    def _connect(self):
        """A pooled connection that interrupts queries at the deadline."""
        with self.trace.connect() as db:
            db.set_progress_handler(
                lambda: int(time.monotonic() > self.deadline), 10000
            )
            try:
                yield db
            except Exception as error:
                if time.monotonic() > self.deadline:
                    raise ValueError(
                        "Custom metric query exceeded 30 seconds; narrow the selection"
                    ) from error
                raise

    def fetch(self, sql, args=()):
        with self._connect() as db:
            for row in db.execute(sql, args):
                self.charge(1, True)
                yield dict(row)

    def fetch_rows(self, sql, args=(), inputs=True):
        """Fetch plain tuples eagerly with fetch's input charges and deadline.

        ``inputs=False`` re-reads rows that were already charged as inputs.
        """
        rows = []
        with self._connect() as db:
            cursor = db.cursor()
            cursor.row_factory = None
            cursor.execute(sql, args)
            # Charging a batch at once reaches the same totals and errors.
            while batch := cursor.fetchmany(FETCH_BATCH):
                self.charge(len(batch) if inputs else 0, inputs)
                rows += batch
        return rows

    def constant(self, value, unit=""):
        if not finite(value):
            raise ValueError("Constants must be finite numbers")
        # The end boundary is for drawing, not a second measurement. Counting
        # it makes cumulative/nested formulas change when the window end moves.
        return Data(
            {
                loc: Series(
                    [(0.0, value), (self.end, value)],
                    "constant",
                    observed={0.0},
                    flags=0x200 | source_properties([(0.0, value)]),
                )
                for loc in self.locations
            },
            unit,
            True,
        )

    def scoped(self, spec):
        q = dict(self.q)
        q.update(
            {
                k: v
                for k, v in spec.items()
                if k
                in (
                    "region",
                    "group",
                    "exclude",
                    "tag",
                    "comm",
                    "status",
                    "minBytes",
                    "maxBytes",
                )
            }
        )
        locs = self.locations
        if spec.get("locations"):
            selected = (
                set(map(str, spec["locations"]))
                if isinstance(spec["locations"], list)
                else set(str(spec["locations"]).split(","))
            )
            locs = [loc for loc in locs if loc in selected]
        q["locations"] = ",".join(locs) or "__none__"
        return q, locs

    def selected_regions(self, q, spec):
        patterns = (
            function_patterns(spec["functionPattern"])
            if "functionPattern" in spec
            else None
        )
        self.charge(
            len(self.trace.meta["regions"]) * (len(patterns) if patterns else 1)
        )
        return {
            r["id"]
            for r in self.trace.meta["regions"]
            if (
                not q.get("region")
                or str(q["region"]).casefold() in r["name"].casefold()
            )
            and (
                not q.get("exclude")
                or str(q["exclude"]).casefold() not in r["name"].casefold()
            )
            and (not q.get("group") or q["group"] == r["group"])
            and (patterns is None or function_matches(r["name"], patterns))
        }

    def expression(self, source, sources=None, linear=False):
        if not isinstance(source, str) or len(source) > 8192:
            raise ValueError("Expression is too large")
        try:
            tree = ast.parse(source, mode="eval")
        except (SyntaxError, RecursionError) as error:
            raise ValueError("Invalid custom metric expression") from error
        if sum(1 for _ in ast.walk(tree)) > limits.MAX_NODES:
            raise ValueError("Expression has too many operations")
        sources = self.sources if sources is None else sources
        return evaluate_ast(self, tree.body, sources, linear)

    def cursor_series(
        self,
        factory,
        *,
        flags,
        display_interpolation="previous",
        sample_display=False,
        integral=False,
    ):
        """Materialize display observations without erasing the native cursor.

        Pixel requests and enclosing operators still seek the composed factory.
        Retained snapshots evaluate the display's existing state without a fresh
        seek (which can have different filtering semantics).
        """
        cursor = factory(self.start)
        states = []
        while True:
            self.charge(1)
            states.append(
                (
                    cursor.current_time,
                    number(cursor.current_value()),
                    metric_cursors.snapshot(cursor, self.charge),
                )
            )
            # The factory retains the full source and each wrapper's lookahead;
            # only chart snapshots are bounded by this request. Enclosing prefix,
            # interpolation and hierarchy operations reuse the factory directly.
            if not math.isfinite(cursor.next_time) or cursor.next_time > self.end:
                break
            cursor.advance()
        states.sort(key=lambda state: state[0])
        points = [(t, value) for t, value, _ in states]
        if integral and states and states[0][0] > 0:
            # The native zero query is a value request, not an extra child state.
            points.extend(
                [
                    (0.0, 0),
                    (
                        math.nextafter(0.0, math.inf),
                        states[0][2].value(math.nextafter(0.0, math.inf)),
                    ),
                ]
            )
        observed = {t for t, _, _ in states}
        result = Series(
            points,
            observed=observed,
            flags=flags,
            evaluate_cursor=lambda index, t: states[index][2].value(t),
            display_interpolation=display_interpolation,
            sample_display=sample_display,
        )
        result.native_cursor = factory
        result.pixel_cursor = factory
        result.native_context = self
        reset = factory(0.0)
        result.reset_state = (reset.current_time, number(reset.current_value()))
        for t in (self.start, self.end):
            if t not in observed and not any(a == t for a, _ in result.points):
                result.points.append((t, result.at(t)))
        result.points.sort(key=lambda point: point[0])
        return result

    def state_source_series(self, source):
        # SignalInterpol seeks its child, then advances once to cache the next
        # value regardless of the display end (1115790). Nested operators can
        # require further states: interpolate(differentiate(f)) needs the slope
        # at that next state too. The factory retains the complete source tail;
        # the display only needs observations in its request. All enclosing
        # native operators use that factory, including their own lookahead.
        series = Series(source.points(self.start, self.end), flags=source.flags)
        series.pixel_cursor = source.cursor
        series.native_cursor = source.cursor
        series.native_context = self
        reset = source.cursor(0.0)
        series.reset_state = (reset.current_time, number(reset.current_value()))
        return series
