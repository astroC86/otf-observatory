"""Compile the bounded metric expression language into signal operations."""

import ast
import math
import operator

from .hierarchy import aggregate
from .pointwise import pointwise
from .series import Data, interpolated
from .temporal import temporal
from .values import compare_nan, finite, positive, safe_power, signed_log, unit_join

BINARY = {
    ast.Add: (operator.add, "add", "add"),
    ast.Sub: (operator.sub, "sub", "subtract"),
    ast.Mult: (operator.mul, "multiply", "multiply"),
    ast.Div: (operator.truediv, "divide", "divide"),
    ast.Mod: (operator.mod, "add", None),
}

COMPARISONS = {
    ast.Lt: (operator.lt, "lt"),
    ast.LtE: (operator.le, "le"),
    ast.Gt: (operator.gt, "gt"),
    ast.GtE: (operator.ge, "ge"),
    ast.Eq: (operator.eq, "eq"),
    ast.NotEq: (operator.ne, "ne"),
}

UNARY = {
    ast.UAdd: (lambda value: value, "identity", False),
    ast.USub: (operator.neg, "negate", False),
    ast.Not: (lambda value: int(not positive(value)), "logical_not", True),
}

PREDICATES = {
    "isnan",
    "logical_and",
    "logical_or",
    "logical_xor",
    "logical_not",
    *(name for _, name in COMPARISONS.values()),
}

SCALARS = {
    "abs": (1, 1, abs),
    "sqrt": (1, 1, math.sqrt),
    "exp": (1, 1, math.exp),
    "floor": (1, 1, math.floor),
    "ceil": (1, 1, math.ceil),
    "round": (1, 1, round),
    "pow": (2, 2, safe_power),
    "log": (1, 2, signed_log),
    "min": (2, 16, min),
    "max": (2, 16, max),
    "logical_and": (2, 16, lambda *v: int(all(positive(x) for x in v))),
    "logical_or": (2, 16, lambda *v: int(any(positive(x) for x in v))),
    "logical_xor": (2, 2, lambda x, y: int(positive(x) != positive(y))),
    "logical_not": (1, 1, UNARY[ast.Not][0]),
    "isnan": (1, 1, lambda x: int(x is None)),
    "replace_nan": (2, 2, lambda x, y: y if x is None else x),
    "combine_max": (
        2,
        2,
        lambda x, y: y if x is None else x if y is None else max(x, y),
    ),
    "combine_min": (
        2,
        2,
        lambda x, y: y if x is None else x if y is None else min(x, y),
    ),
    "clamp": (3, 3, lambda x, lo, hi: min(max(x, lo), hi) if lo <= hi else None),
    "where": (
        3,
        3,
        lambda condition, a, b: (
            None if condition is None else a if condition > 0 else b
        ),
    ),
}
SCALARS["lower_limit"] = SCALARS["combine_max"]
SCALARS["upper_limit"] = SCALARS["combine_min"]
SCALARS.update(
    (name, (2, 2, lambda x, y, compare=compare: int(compare_nan(compare, x, y))))
    for compare, name in COMPARISONS.values()
)

ALIASES = {
    "is_nan": "isnan",
    "replace_not_a_number": "replace_nan",
    "combine_maxima": "combine_max",
    "combine_minima": "combine_min",
    "enforce_lower_limit": "lower_limit",
    "enforce_upper_limit": "upper_limit",
    "logarithm": "log",
    "difference_to_last": "difference",
    "cumulative_sum": "cumsum",
    "hierarchical_aggregation": "aggregate",
}


def literal(node, expected=None):
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (str, int, float))
        and not isinstance(node.value, bool)
    ):
        value = node.value
    elif (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.UAdd, ast.USub))
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) in (int, float)
    ):
        value = node.operand.value * (-1 if isinstance(node.op, ast.USub) else 1)
    else:
        raise ValueError("This option must be a literal number or quoted string")
    if expected is not None and not isinstance(value, expected):
        raise ValueError("Invalid literal option")
    return value


def evaluate_ast(ctx, node, sources, linear=False, depth=0):
    if depth > 32:
        raise ValueError("Expression nesting exceeds 32 levels")
    ctx.charge(1)

    def run(child, force=linear):
        return evaluate_ast(ctx, child, sources, force, depth + 1)

    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return ctx.constant(node.value)
    if isinstance(node, ast.Name):
        return ctx.source(node.id, sources, linear)
    if isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
        data = run(node.operand)
        function, operation, allow_missing = UNARY[type(node.op)]
        return pointwise(
            ctx,
            [data],
            function,
            "" if allow_missing else data.unit,
            allow_missing=allow_missing,
            linear=linear,
            operation=operation,
        )
    if isinstance(node, ast.BinOp):
        a, b = run(node.left), run(node.right)
        if type(node.op) in BINARY:
            function, op, operation = BINARY[type(node.op)]
            unit = unit_join(a, b, op)
        elif isinstance(node.op, ast.Pow):
            function = safe_power
            operation = None
            unit = a.unit + "^" + str(literal(node.right)) if a.unit else ""
        else:
            raise ValueError("Unsupported arithmetic operator")
        return pointwise(
            ctx,
            [a, b],
            function,
            unit,
            linear=linear,
            operation=operation,
        )
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        args = [run(value) for value in node.values]
        operation = "logical_and" if isinstance(node.op, ast.And) else "logical_or"
        function = SCALARS[operation][2]
        return pointwise(
            ctx,
            args,
            function,
            allow_missing=True,
            linear=linear,
            operation=operation,
        )
    if isinstance(node, ast.Compare):
        args = [run(node.left)] + [run(n) for n in node.comparators]
        if any(type(op) not in COMPARISONS for op in node.ops):
            raise ValueError("Unsupported comparison")
        for a, b in zip(args, args[1:]):
            unit_join(a, b, "compare")
        return pointwise(
            ctx,
            args,
            lambda *v: int(
                all(
                    compare_nan(COMPARISONS[type(op)][0], a, b)
                    for op, a, b in zip(node.ops, v, v[1:])
                )
            ),
            allow_missing=True,
            linear=linear,
            operation=(
                COMPARISONS[type(node.ops[0])][1] if len(node.ops) == 1 else None
            ),
        )
    if (
        not isinstance(node, ast.Call)
        or not isinstance(node.func, ast.Name)
        or node.keywords
    ):
        raise ValueError("Use named sources and documented metric operations only")
    name = ALIASES.get(node.func.id, node.func.id)
    n = len(node.args)
    if n > 16:
        raise ValueError("Too many operation arguments")
    if name in (
        "differentiate",
        "derivative",
        "difference",
        "diff",
        "integrate",
        "integral",
        "cumsum",
        "shift",
        "moving_sum",
        "moving_mean",
        "moving_min",
        "moving_max",
        "moving_stddev",
        "moving_median",
    ):
        low, high = (
            (2, 2)
            if name == "shift" or name.startswith("moving_")
            else (1, 2) if name in ("integrate", "integral") else (1, 1)
        )
        if not low <= n <= high:
            raise ValueError("Wrong argument count for " + name)
        arg = literal(node.args[1]) if n > 1 else None
        if name == "shift":
            delta = float(arg)
            if not finite(delta):
                raise ValueError("Shift must be finite seconds")
            # A translated result needs source context around the translated
            # window, not merely the first sample after the displayed window.
            saved_start, saved_end, saved_q = ctx.start, ctx.end, ctx.q
            saved_timeline = ctx.timeline_start, ctx.timeline_end
            ctx.q = dict(ctx.q, start=ctx.start - delta, end=ctx.end - delta)
            ctx.start, ctx.end, _, _ = ctx.trace.scope(ctx.q, regions=False)
            ctx.timeline_start, ctx.timeline_end, _, _ = ctx.trace.scope(
                dict(
                    ctx.q,
                    start=saved_timeline[0] - delta,
                    end=saved_timeline[1] - delta,
                ),
                regions=False,
            )
            try:
                data = run(node.args[0])
            finally:
                ctx.start, ctx.end, ctx.q = saved_start, saved_end, saved_q
                ctx.timeline_start, ctx.timeline_end = saved_timeline
        elif (
            name in ("difference", "diff", "cumsum")
            or name in ("integrate", "integral")
            and arg is None
        ):
            # Reconstruct the operator state from trace start before clipping
            # the output. A window-local reset changes cumulative totals and
            # loses the previous valid sample across long gaps.
            saved_start, saved_q = ctx.start, ctx.q
            ctx.start = 0.0
            ctx.q = dict(ctx.q, start=0.0)
            try:
                data = run(node.args[0])
            finally:
                ctx.start, ctx.q = saved_start, saved_q
        else:
            data = run(
                node.args[0],
                name in ("differentiate", "derivative") or linear,
            )
        return temporal(ctx, data, name, arg)
    if name == "interpolate":
        if n != 1:
            raise ValueError("interpolate expects one input")
        data = run(node.args[0], linear)
        return Data(
            {key: interpolated(s) for key, s in data.series.items()},
            data.unit,
            members=data.members,
        )
    if name == "aggregate":
        if not 1 <= n <= 3:
            raise ValueError("aggregate expects input, reducer and optional scope")
        # Hierarchy is a separately materialized child request. Its source
        # seek and grid use the selected Timeline, not an outer zero reset.
        saved_start, saved_end, saved_q = ctx.start, ctx.end, ctx.q
        ctx.start, ctx.end = ctx.timeline_start, ctx.timeline_end
        ctx.q = dict(ctx.q, start=ctx.start, end=ctx.end)
        try:
            return aggregate(
                ctx,
                run(node.args[0]),
                literal(node.args[1], str) if n > 1 else "sum",
                literal(node.args[2], str) if n > 2 else "all",
            )
        finally:
            ctx.start, ctx.end, ctx.q = saved_start, saved_end, saved_q
    if name not in SCALARS:
        raise ValueError("Unknown metric operation: " + name)
    low, high, function = SCALARS[name]
    if not low <= n <= high:
        raise ValueError("Wrong argument count for " + name)
    data = [run(arg) for arg in node.args]
    unit = data[0].unit
    if name in PREDICATES or name in ("log", "exp"):
        unit = ""
    elif name == "sqrt":
        unit = "sqrt(" + unit + ")" if unit else ""
    elif name == "pow":
        unit = unit + "^" + str(literal(node.args[1])) if unit else ""
    elif name == "where":
        unit = unit_join(data[1], data[2], "replace")
    elif name in (
        "min",
        "max",
        "combine_max",
        "combine_min",
        "lower_limit",
        "upper_limit",
        "replace_nan",
        "clamp",
    ):
        for other in data[1:]:
            unit = unit_join(Data({}, unit), other, "replace")
    allow_missing = name in PREDICATES or name in (
        "replace_nan",
        "combine_max",
        "combine_min",
        "lower_limit",
        "upper_limit",
        "where",
    )
    return pointwise(ctx, data, function, unit, allow_missing, linear, operation=name)
