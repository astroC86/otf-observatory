"""Named source dispatch, recursive-source guards and counter caching."""

from fractions import Fraction
import json
import math
from operator import itemgetter

from . import limits
from .catalog import SOURCE_LABELS
from .pixels import CounterMode, counter_source
from .series import Data, Series, interpolated
from .temporal import temporal
from .values import finite, number


class SourceRegistry:
    """Own the memoized sources and dependency stack for one query."""

    def __init__(self, context):
        self.context = context
        self.cache = {}
        self.stack = []
        self.counter_cache = {}

    def __call__(self, name, sources=None, linear=False):
        ctx = self.context
        sources = ctx.sources if sources is None else sources
        if name not in sources:
            raise ValueError("Unknown metric source: " + name)
        spec = sources[name]
        if not isinstance(spec, dict):
            raise ValueError("Each metric source must be an object")
        key = json.dumps(spec, sort_keys=True, separators=(",", ":"))
        if len(key) > 131072:
            raise ValueError("Metric source is too complex")
        if key in self.stack:
            raise ValueError("Cyclic custom metric dependency")
        if len(self.stack) >= 16:
            raise ValueError("Custom metric nesting exceeds 16 levels")
        cache_key = (key, linear, ctx.start, ctx.end)
        if cache_key in self.cache:
            return self.cache[cache_key]
        self.stack.append(key)
        ctx.source_names.append(name)
        try:
            kind = spec.get("type", "counter")
            if kind not in SOURCE_LABELS:
                raise ValueError("Unknown metric source type: " + str(kind))
            if kind == "custom":
                custom = spec
                if spec.get("formula"):
                    custom = ctx.formulas.get(spec["formula"])
                    if not isinstance(custom, dict):
                        raise ValueError(
                            "Unknown custom formula: " + str(spec["formula"])
                        )
                nested = custom.get("sources", sources)
                if not isinstance(nested, dict) or len(nested) > limits.MAX_SOURCES:
                    raise ValueError("Invalid nested sources")
                if spec.get("locations"):
                    # Restrict inputs before a nested hierarchy reduction; filtering
                    # an already-aggregated output cannot remove contributions.
                    _, allowed = ctx.scoped(spec)
                    restricted = {}
                    for variable, operand in nested.items():
                        if not isinstance(operand, dict):
                            raise ValueError("Each metric source must be an object")
                        _, inner = ctx.scoped(operand)
                        restricted[variable] = dict(
                            operand,
                            locations=[loc for loc in inner if loc in allowed]
                            or ["__none__"],
                        )
                    nested = restricted
                data = ctx.expression(custom.get("expression", "x"), nested, linear)
            elif kind == "constant":
                data = ctx.constant(spec.get("value", 0), str(spec.get("unit", "")))
                if spec.get("locations"):
                    _, allowed = ctx.scoped(spec)
                    data = Data(
                        {loc: s for loc, s in data.series.items() if loc in allowed},
                        data.unit,
                        True,
                    )
            elif kind == "counter":
                data = self.counter(spec)
            elif kind.startswith("function_"):
                data = ctx.functions.function_source(kind, spec)
            else:
                data = ctx.operations.load(kind, spec)
            if spec.get("unit") is not None:
                data = Data(data.series, str(spec["unit"]), data.literal, data.members)
            if linear and not data.literal:
                data = Data(
                    {key: interpolated(s) for key, s in data.series.items()},
                    data.unit,
                    data.literal,
                    data.members,
                )
            ctx.charge(sum(len(s.points) for s in data.series.values()))
            self.cache[cache_key] = data
            return data
        finally:
            self.stack.pop()
            ctx.source_names.pop()

    def counter(self, spec):
        ctx = self.context
        member = str(spec.get("metric", ""))
        md = ctx.trace.metric_definition(member)
        mode = spec.get("mode", "value")
        if mode not in ("value", "delta", "rate"):
            raise ValueError("Counter mode must be value, delta or rate")
        _, locs = ctx.scoped(spec)
        exponent = md.get("exponent", 0)
        if not isinstance(exponent, int) or not -308 <= exponent <= 308:
            raise ValueError(
                "Metric scaling exponent is outside the supported numeric range"
            )
        base = 2 if md.get("base", 1) == 0 else 10
        scale = base**exponent if exponent >= 0 else Fraction(1, base ** (-exponent))
        max_gap = spec.get("maxGap")
        if max_gap is not None:
            max_gap = float(max_gap)
            if not finite(max_gap) or max_gap <= 0:
                raise ValueError("maxGap must be positive seconds")
        counter_mode = md.get("modeValue", 0)
        cache = self.counter_cache
        unread = [loc for loc in locs if (member, loc, scale, max_gap) not in cache]
        _check_read_budget(ctx, member, unread, counter_mode)
        for loc in unread:
            # Source-property flags inspect the entire deque in the executable.
            # Window-local monotonicity would change terminal pixel behavior
            # when zooming. This full read remains subject to input/time limits.
            points = _counter_samples(ctx, member, loc, scale)
            points, flags, checked = counter_source(points, counter_mode)
            if max_gap is not None:
                gaps = []
                for (t, _), (u, _) in zip(points, points[1:]):
                    if u - t > max_gap:
                        gaps.append((math.nextafter(t + max_gap, math.inf), None))
                if points:
                    gaps.append(
                        (math.nextafter(points[-1][0] + max_gap, math.inf), None)
                    )
                points += gaps
                checked = False
            cache[member, loc, scale, max_gap] = Series(
                points, max_gap=max_gap, flags=flags, checked=checked
            )
        data = Data(
            {loc: cache[member, loc, scale, max_gap] for loc in locs},
            md.get("unit", ""),
        )
        return (
            temporal(ctx, data, "difference" if mode == "delta" else "differentiate")
            if mode != "value"
            else data
        )


# Row count and first/last timestamps of one location; NULL times sort first.
_EXTENT = (
    "SELECT (SELECT count(*) FROM metrics WHERE metric=:m AND location=:l) AS n,"
    " (SELECT time FROM metrics WHERE metric=:m AND location=:l ORDER BY time LIMIT 1) AS first,"
    " (SELECT time FROM metrics WHERE metric=:m AND location=:l ORDER BY time DESC LIMIT 1) AS last"
)


def _check_read_budget(ctx, member, locs, counter_mode):
    """Raise the input/work limit error before reading rows that would reach it.

    Each read row costs one input and one work unit. Reading and converting a
    location can raise nothing else unless the counter mode is unknown or
    RELATIVE (overflowing sums) or a timestamp is not a finite nonnegative
    float (LAST prepends a zero-time sample). Index-only counts thus find the
    read that would cross a limit while no earlier read can fail differently.
    """
    try:
        if CounterMode.decode(counter_mode).value_property == "relative":
            return
    except (ValueError, TypeError):
        return
    reads = 0
    for loc in locs:
        extent = ctx.trace.rows(_EXTENT, dict(m=member, l=loc))[0]
        reads += extent["n"]
        if (
            ctx.inputs + reads > limits.MAX_INPUT_POINTS
            or ctx.work + reads > limits.MAX_WORK_POINTS
        ):
            ctx.charge(reads, True)
        first, last = extent["first"], extent["last"]
        if extent["n"] and not (
            type(first) is type(last) is float and 0 <= first and last < math.inf
        ):
            return


# Canonical int64 raw text arrives as an exact int; any other raw stays text.
_SAMPLES = (
    "SELECT time,CASE WHEN CAST(CAST(raw AS INTEGER) AS TEXT)=raw"
    " THEN CAST(raw AS INTEGER) ELSE raw END"
    " FROM metrics WHERE metric=? AND location=? ORDER BY time,id"
)


def _counter_samples(ctx, member, loc, scale):
    """(time, value) samples: raw integers stay exact, else float raw or value."""
    rows = ctx.fetch_rows(_SAMPLES, (member, loc))
    if set(map(type, map(itemgetter(1), rows))) <= {int}:
        # Integer or Fraction products neither overflow nor need number().
        return rows if scale == 1 else [(t, raw * scale) for t, raw in rows]
    stored = None
    points = []
    for index, (t, raw) in enumerate(rows):
        try:
            value = int(raw) * scale
        except (ValueError, TypeError, OverflowError):
            try:
                value = float(raw) * scale
            except (ValueError, TypeError, OverflowError):
                if stored is None:
                    stored = ctx.fetch_rows(
                        "SELECT value FROM metrics WHERE metric=? AND location=? ORDER BY time,id",
                        (member, loc),
                        inputs=False,
                    )
                value = stored[index][0]
        points.append((t, number(value)))
    return points
