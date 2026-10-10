"""Compose aligned signal operands without changing native cursor order."""

import collections

from . import cursors as metric_cursors
from .hierarchy import corresponding, target_keys
from .series import Data, Series, interpolated
from .signal_flags import pointwise_flags
from .values import number


def pointwise(
    ctx,
    datasets,
    function,
    unit="",
    allow_missing=False,
    linear=False,
    operation=None,
):
    output = {}
    output_members = {}

    def evaluate_values(values):
        try:
            value = (
                function(*values)
                if allow_missing or all(v is not None for v in values)
                else None
            )
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            value = None
        return number(value)

    stepped = operation in (
        "lt",
        "le",
        "gt",
        "ge",
        "eq",
        "ne",
        "logical_and",
        "logical_or",
        "logical_xor",
        "logical_not",
        "isnan",
        "floor",
        "ceil",
        "round",
    )
    for key, members in target_keys(ctx, datasets):
        inputs = [corresponding(ctx, data, key, members) for data in datasets]
        output_members[key] = members
        continuous = any(
            s.display_interpolation == "linear" or s.sample_display for s in inputs
        )
        if any(getattr(series, "native_cursor", None) is not None for series in inputs):
            factories = tuple(metric_cursors.factory(series) for series in inputs)
            timed_indices = tuple(
                i for i, data in enumerate(datasets) if not data.literal
            ) or tuple(range(len(inputs)))

            def composed(
                start,
                factories=factories,
                timed_indices=timed_indices,
                evaluate=evaluate_values,
            ):
                return metric_cursors.ComposedCursor(
                    [factory(start) for factory in factories],
                    evaluate,
                    timed_indices,
                    ctx.charge,
                )

            output[key] = ctx.cursor_series(
                composed,
                flags=pointwise_flags(
                    operation, inputs, [data.literal for data in datasets]
                ),
                display_interpolation=(
                    "linear" if continuous and not stepped else "previous"
                ),
                sample_display=continuous,
            )
            if linear:
                output[key] = interpolated(output[key])
            continue
        timed = [s for s, data in zip(inputs, datasets) if not data.literal] or inputs
        # Scalar/unary operators delegate current/next/seek to their child.
        # A filtered Stack attribute can already be positioned after zero;
        # do not manufacture a time-zero observation in that delegated stream.
        reset_child = timed[0] if all(s is timed[0] for s in timed) else None
        reset = reset_child.reset_state if reset_child is not None else None
        observed = set().union(*(s.observed for s in timed))
        counts = {}
        for series in timed:
            for t, count in collections.Counter(series.times).items():
                counts[t] = max(counts.get(t, 0), count)
        if (not counts or min(counts) > 0) and reset is None:
            counts[0.0] = 1
            observed.add(0.0)
        ctx.charge((sum(counts.values()) + 2) * max(1, len(inputs)))
        events = [(t, i) for t, count in sorted(counts.items()) for i in range(count)]
        points = [
            (
                t,
                evaluate_values(
                    [s.cursor_value(s.event_index(t, i), t) for s in inputs]
                ),
            )
            for t, i in events
        ]
        if reset is not None:
            reset = (
                reset[0],
                evaluate_values(
                    [
                        s.at(0) if data.literal else s.reset_state[1]
                        for s, data in zip(inputs, datasets)
                    ]
                ),
            )
        for t in (ctx.start, ctx.end):
            if t not in counts:
                points.append((t, evaluate_values([s.at(t) for s in inputs])))

        def evaluate_cursor(index, t, inputs=tuple(inputs), events=tuple(events)):
            ctx.charge(max(1, len(inputs)))
            start, occurrence = events[index]
            values = [
                series.cursor_value(series.event_index(start, occurrence), t)
                for series in inputs
            ]
            return evaluate_values(values)

        # Recursive interpolation wraps each expression's sampled results.
        # Ordinary expressions retain continuous operand evaluation, so the
        # product of interpolated inputs is evaluated as a product in a pixel.
        output[key] = Series(
            [(t, v) for t, v in points if t in observed] if linear else points,
            (
                "constant"
                if all(d.literal for d in datasets)
                else "linear" if linear else "previous"
            ),
            observed=observed,
            evaluate_cursor=None if linear else evaluate_cursor,
            flags=pointwise_flags(
                operation, inputs, [data.literal for data in datasets]
            ),
            display_interpolation=(
                "linear" if linear or continuous and not stepped else "previous"
            ),
            sample_display=continuous and not linear,
            reset_state=reset,
        )
    return Data(output, unit, all(d.literal for d in datasets), output_members)
