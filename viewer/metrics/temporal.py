"""Prefix, derivative, integration and moving-window signal operations."""

import collections
import math

from . import cursors as metric_cursors
from .series import Data, Series, selected_points
from .signal_flags import temporal_flags
from .values import finite, number, reduce_values


def prefix_points(series, operation, end):
    """Reset at zero, then replay each recorded observation exactly once."""
    reset_time, previous = (
        series.reset_state if series.reset_state is not None else (0.0, series.at(0.0))
    )
    cumulative = operation == "cumsum"
    if cumulative:
        total = previous if previous is not None else 0
    else:
        total = number(previous - previous) if previous is not None else None
    result = [(reset_time, total)]
    reset_index = series.seek_index(reset_time)
    for index, (t, value) in enumerate(series.knots):
        if index <= reset_index or t < 0 or cumulative and t > end:
            continue
        if cumulative:
            if value is not None:
                total += value
        else:
            total = (
                value - previous if value is not None and previous is not None else None
            )
            if value is not None:
                previous = value
        result.append((t, total))
    return result


def temporal(ctx, data, operation, argument=None):
    output = {}
    unit = data.unit
    if operation in ("differentiate", "derivative"):
        unit = unit + "/s" if unit else "1/s"
    elif operation in ("integrate", "integral"):
        unit = unit + "*s" if unit else "s"
    for key, series in data.series.items():
        if getattr(series, "native_cursor", None) is not None and (
            operation
            in (
                "difference",
                "diff",
                "cumsum",
                "differentiate",
                "derivative",
                "shift",
            )
            or operation in ("integrate", "integral")
            and argument is None
        ):
            child = metric_cursors.factory(series)
            if operation in ("difference", "diff", "cumsum"):
                factory = lambda start, child=child, operation=operation: metric_cursors.PrefixCursor(
                    child(0.0), operation, start, ctx.charge
                )
            elif operation in ("integrate", "integral"):
                factory = lambda start, child=child: metric_cursors.IntegralCursor(
                    child(0.0), start, ctx.charge
                )
            elif operation in ("differentiate", "derivative"):
                # Recursive expression evaluation may already have supplied
                # the public factory's outer Interpol wrapper.
                def factory(start, child=child):
                    cursor = child(start)
                    if not isinstance(cursor, metric_cursors.InterpolCursor):
                        cursor = metric_cursors.InterpolCursor(cursor, ctx.charge)
                    return metric_cursors.DerivativeCursor(cursor, ctx.charge)

            else:
                delta = float(argument)
                if not finite(delta):
                    raise ValueError("Shift must be finite seconds")
                factory = (
                    lambda start, child=child, delta=delta: metric_cursors.ShiftCursor(
                        child(start - delta), delta
                    )
                )
            output[key] = ctx.cursor_series(
                factory,
                flags=temporal_flags(operation, series.flags),
                display_interpolation=(
                    series.display_interpolation if operation == "shift" else "previous"
                ),
                sample_display=(
                    series.sample_display if operation == "shift" else False
                ),
                integral=operation in ("integrate", "integral"),
            )
            continue
        points = series.knots
        result = []
        if operation in ("difference", "diff", "cumsum"):
            # Difference preserves a missing zero baseline; cumsum initializes
            # NaN to zero. Neither treats a zoom boundary as a new observation.
            result = prefix_points(series, operation, ctx.end)
        elif operation in ("differentiate", "derivative"):
            # All recovered expression factories wrap SignalInterpol. Its
            # cached current/next values give the forward interval slope.
            if not points or points[0][0] > 0:
                result.append((0.0, None if not data.literal else 0))
            for index, (t, value) in enumerate(points):
                if index + 1 < len(points):
                    after, other = points[index + 1]
                    # Seek skips zero-width Interpol intervals. Keep the
                    # preceding interval's first endpoint reading, however.
                    if after == t:
                        continue
                    v = (
                        (other - value) / (after - t)
                        if value is not None and other is not None and after > t
                        else None
                    )
                else:
                    v = 0 if value is not None else None
                result.append((t, v))
        elif operation in ("integrate", "integral") and argument is None:
            result = integrated_points(series)
        elif operation in ("integrate", "integral"):
            method = argument
            if method not in ("right", "linear", "left"):
                raise ValueError("Integral method must be right, left or linear")
            points = selected_points(series, ctx.start, ctx.end, boundaries=True)
            total = 0
            broken = False
            previous = None
            for t, value in points:
                if previous is None:
                    if value is None:
                        broken = True
                        result.append((t, None))
                        continue
                elif value is None or previous[1] is None:
                    broken = True
                elif not broken:
                    density = (
                        value
                        if method == "right"
                        else (
                            previous[1]
                            if method == "left"
                            else (value + previous[1]) / 2
                        )
                    )
                    total += density * (t - previous[0])
                result.append((t, None if broken else total))
                previous = (t, value)
        elif operation.startswith("moving_"):
            width = float(argument)
            if not finite(width) or width <= 0:
                raise ValueError("Moving-window size must be positive seconds")
            reducer = operation[7:]
            window = collections.deque()
            for t, value in points:
                window.append((t, value))
                while window and window[0][0] < t - width:
                    window.popleft()
                ctx.charge(len(window))
                result.append(
                    (
                        t,
                        (
                            None
                            if any(v is None for _, v in window)
                            else reduce_values([v for _, v in window], reducer)
                        ),
                    )
                )
        elif operation == "shift":
            delta = float(argument)
            if not finite(delta):
                raise ValueError("Shift must be finite seconds")
            result = [(t + delta, v) for t, v in points]
            ctx.charge(len(result))
            # Retain the child's cursor and evaluator, including continuous
            # composed expressions and gap limits, under time translation.
            output[key] = Series(
                result,
                series.interpolation,
                series.max_gap,
                evaluate_cursor=lambda index, t, child=series, offset=delta: child.cursor_value(
                    index, t - offset
                ),
                flags=temporal_flags(operation, series.flags),
                display_interpolation=series.display_interpolation,
                sample_display=series.sample_display,
            )
            continue
        else:
            raise ValueError("Unknown temporal operation")
        ctx.charge(len(result))
        # Integration inserts display boundaries to evaluate partial intervals.
        # They are not new input observations for an enclosing cumsum/difference.
        observed = (
            series.observed
            if operation in ("integrate", "integral") and argument is not None
            else None
        )
        output[key] = Series(
            result,
            observed=observed,
            flags=temporal_flags(operation, series.flags),
            reset_state=(
                result[0]
                if series.reset_state is not None
                and operation in ("difference", "diff", "cumsum")
                else None
            ),
        )
    return Data(output, unit, members=data.members)


def bounded_derivative(evaluator, t, current_time, next_time, time_scale=1):
    """SignalDiffQuot's recovered non-Interpol fallback (0x11159d0).

    Normal expression constructors wrap an Interpol child and use the
    exact interval slope instead. This branch is retained for signal producers
    which supply their own continuous evaluator without that wrapper.
    """
    if not finite(time_scale) or time_scale <= 0:
        raise ValueError("Derivative time scale must be positive")
    if next_time == math.inf:
        return 0 if evaluator(current_time) is not None else None
    if t < current_time or t > next_time:
        return None
    step = (next_time - current_time) / 20
    left = max(current_time, t - step)
    right = min(next_time, t + step)
    a = evaluator(left)
    b = evaluator(right)
    if a is None or b is None or right <= left:
        return None
    return number((b - a) / ((right - left) * time_scale))


def integrated_points(series):
    """Port of SignalIntegrate reset/advance/value, in seconds.

    The child cursor starts at zero, skips NaNs when finding its next state,
    and commits the previous-value rectangle only when that state is reached.
    There is no area extrapolation after the last recorded child state.
    """
    events = series.knots
    cursor = series.seek_index(0.0)
    last_advanced = False

    def state():
        return events[cursor] if cursor >= 0 else (0.0, None)

    def next_finite():
        nonlocal cursor, last_advanced
        previous_cursor = cursor
        if cursor + 1 < len(events):
            cursor += 1
        while state()[1] is None and cursor + 1 < len(events):
            cursor += 1
        last_advanced = cursor != previous_cursor
        return state()

    current_time, current_value = state()
    if current_value is None:
        current_time, current_value = next_finite()
    next_time, next_value = next_finite()
    total = 0
    result = [(0.0, 0)]
    # The native value method rejects a positive query before current_time
    # when it has a finite next value. Represent that absent domain as a gap.
    if current_time > 0 and next_value is not None:
        result.append((math.nextafter(0.0, math.inf), None))
    if current_time > 0:
        result.append((current_time, 0))
    while next_time != math.inf:
        transition = (
            next_time
            if next_time > current_time or last_advanced
            else math.nextafter(current_time, math.inf)
        )
        total = (
            number(total + (next_time - current_time) * current_value)
            if total is not None and current_value is not None
            else None
        )
        current_time, current_value = next_time, next_value
        if transition >= 0:
            result.append((transition, total))
        if cursor + 1 < len(events):
            next_time, next_value = next_finite()
        else:
            next_time = math.inf
    return result
