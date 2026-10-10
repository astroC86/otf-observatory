"""Recorded signal data, interpolation and selection boundaries."""

from dataclasses import InitVar, dataclass, field
import bisect
from itertools import compress
import math
from operator import itemgetter

from . import cursors as metric_cursors
from .pixels import sample_columns, source_properties
from .values import finite, number

_time = itemgetter(0)


@dataclass
class Series:
    points: list
    interpolation: str = "previous"
    max_gap: float | None = None
    observed: set | None = None
    evaluate_interval: object = None
    flags: int | None = None
    evaluate_cursor: object = None
    pixels: object = None
    display_interpolation: str | None = None
    sample_display: bool = False
    reset_state: tuple | None = None
    times: list = field(init=False)
    knots: list = field(init=False)
    # The caller already verified that points are in sample form.
    checked: InitVar[bool] = False

    def __post_init__(self, checked):
        # Stable ordering preserves equal-time records. Native seek selects
        # the first equal record; advancing can observe every later one.
        points = list(self.points)
        if not checked and sample_columns(points) is None:
            points = sorted(
                ((float(t), number(v)) for t, v in points if finite(t)), key=_time
            )
        self.points = points
        if self.observed is None:
            self.knots = list(points)
            self.times = list(map(_time, points))
            self.observed = set(self.times)
        else:
            self.knots = [p for p in points if p[0] in self.observed]
            self.times = [t for t, _ in self.knots]
        if self.flags is None:
            self.flags = source_properties(self.knots)
        if self.display_interpolation is None:
            self.display_interpolation = (
                "linear" if self.interpolation == "linear" else "previous"
            )

    def seek_index(self, t):
        index = bisect.bisect_left(self.times, t)
        return (
            index if index < len(self.times) and self.times[index] == t else index - 1
        )

    def event_index(self, t, occurrence=0):
        index = self.seek_index(t)
        if index >= 0 and self.times[index] == t:
            return min(index + occurrence, bisect.bisect_right(self.times, t) - 1)
        return index

    def at(self, t):
        if self.interpolation == "constant":
            return self.points[0][1] if self.points else None
        return self.cursor_value(self.seek_index(t), t)

    def cursor_value(self, index, t):
        """Value at t with an observed-knot cursor, including duplicates."""
        if self.interpolation == "constant":
            return self.points[0][1] if self.points else None
        if index < 0:
            return None
        a, value = self.knots[index]
        if self.max_gap is not None and t - a > self.max_gap:
            return None
        if self.evaluate_cursor is not None:
            return number(self.evaluate_cursor(index, t))
        if self.evaluate_interval is not None:
            end = self.knots[index + 1][0] if index + 1 < len(self.knots) else math.inf
            return number(self.evaluate_interval(a, end, t))
        if self.interpolation == "previous" or t == a or t == 0:
            return value
        b, other = (
            self.knots[index + 1] if index + 1 < len(self.knots) else (math.inf, value)
        )
        if other is None:
            return value
        if t == b:
            return other
        if value is None or b == a:
            return None
        return number(value + (other - value) * ((t - a) / (b - a)))

    def interval_value(self, start, end, t):
        """Evaluate with the source cursor retained at start, even at end.

        Pixel integration queries the right endpoint without advancing its
        cursor. Steps retain their old value; interpolation holds its current
        value if its next value is NaN.
        """
        return self.cursor_value(self.seek_index(start), t)


@dataclass
class Data:
    series: dict
    unit: str = ""
    literal: bool = False
    members: dict = field(default_factory=dict)


def interpolated(series):
    if getattr(series, "native_cursor", None) is not None:
        ctx = series.native_context
        child = metric_cursors.factory(series)
        return ctx.cursor_series(
            lambda start: metric_cursors.InterpolCursor(child(start), ctx.charge),
            flags=series.flags,
            display_interpolation="linear",
        )
    # Display-window boundaries are evaluations, not interpolation knots.
    # Keeping them changes nonlinear expressions' slope when the user zooms.
    return Series(
        series.knots,
        "linear",
        series.max_gap,
        series.observed,
        flags=series.flags,
        reset_state=series.reset_state,
    )


def selected_points(series, start, end, boundaries=False):
    # Series points are time ordered, so the window is one contiguous slice.
    low = bisect.bisect_left(series.points, start, key=_time)
    high = bisect.bisect_right(series.points, end, low, key=_time)
    points = series.points[low:high]
    if boundaries:
        if not points or points[0][0] > start:
            points.insert(0, (start, series.at(start)))
        if not points or points[-1][0] < end:
            points.append((end, series.at(end)))
    else:
        observed = map(series.observed.__contains__, map(_time, points))
        points = list(compress(points, observed))
    return points
