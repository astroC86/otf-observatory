"""Statically recovered metric pixel arithmetic from the reference executable.

No target code is loaded or executed.  See docs/binary-reductions.md for the
instruction addresses and the distinction between point and interval statistics.
The input protocol is deliberately independent of the expression evaluator:
``points``, ``at(t)`` and optionally ``interval_value(start, end, t)`` or
``cursor_value(observed_index, t)``.  These evaluate at t while holding the
source cursor at the same record, including the right end and duplicate times.

MetricPixel owns accumulated fields and raw observations; pixel_reduce owns
cursor traversal, interval admission and the native arithmetic order.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from fractions import Fraction
from itertools import islice, repeat
import math
import operator
from operator import itemgetter
from typing import Iterable

NATIVE_MAX = float.fromhex("0x1.fffffffffffffp+1023")
_SAMPLE_VALUES = frozenset((int, float, Fraction, type(None)))


@dataclass(frozen=True)
class CounterMode:
    """OTF2 metric mode, decoded from the installed OTF2 definitions."""

    timing: str
    value_property: str

    @property
    def source_timing(self):
        # The OTF2 reader maps accumulated START to internal NEXT.
        return "next" if self.timing == "start" else self.timing

    @property
    def accumulated(self):
        return self.value_property == "accumulated"

    @property
    def source_flags(self):
        # "relative" in the internal definition is the accumulated flag,
        # not OTF2_METRIC_VALUE_RELATIVE; see the audited reader call chain.
        return {"last": 0x400, "next": 0x200, "point": 0x100}[self.source_timing] | (
            0x1000 if self.accumulated else 0
        )

    @classmethod
    def decode(cls, mode):
        if isinstance(mode, str) and not mode.isdigit():
            name = mode.upper().removeprefix("OTF2_METRIC_")
            value, separator, timing = name.partition("_")
            if (
                separator
                and value in ("ACCUMULATED", "ABSOLUTE", "RELATIVE")
                and timing in ("START", "POINT", "LAST", "NEXT")
            ):
                return cls(timing.lower(), value.lower())
            raise ValueError("Unknown OTF2 metric mode: " + mode)
        mode = int(mode)
        try:
            return cls(
                {0: "start", 16: "point", 32: "last", 48: "next"}[mode & 240],
                {0: "accumulated", 1: "absolute", 2: "relative"}[mode & 15],
            )
        except KeyError as error:
            raise ValueError("Unknown OTF2 metric mode: " + str(mode)) from error


def normalize_counter_points(points, mode, absolute=None):
    """The counter store update at 0xf40390, before SignalSourceCustom.

    Nonaccumulated LAST replaces the preceding stored value with each incoming
    value. Its first reading also creates a time-zero value when needed. For
    accumulated counters all timing modes retain their original samples. The
    OTF2 event adapter at 0xfee632 maps RELATIVE to transport delta encoding:
    incoming values are cumulatively added and LAST does not shift them.
    ``absolute`` can override that transport flag for already encoded records.
    """
    mode = mode if isinstance(mode, CounterMode) else CounterMode.decode(mode)
    if absolute is None:
        absolute = mode.value_property != "relative"
    result = []
    for t, value in points:
        if not math.isfinite(t):
            raise ValueError("Counter sample timestamps must be finite")
        if result and t < result[-1][0]:
            raise ValueError("Counter sample timestamps must be sorted")
        value = value if _valid(value) else None
        if not absolute:
            if result:
                previous = result[-1][1]
                value = value + previous if _valid(value) and _valid(previous) else None
        elif mode.source_timing == "last" and not mode.accumulated:
            if result:
                result[-1] = (result[-1][0], value)
            elif t != 0:
                result.append((0.0, value))
        result.append((float(t), value))
    return result


def sample_columns(points):
    """Times and values of a list already in sample form, else None.

    Sample form is 2-tuples of sorted finite float times and non-NaN int,
    float, Fraction or None values. Counter normalization and Series
    construction keep such points unchanged; every check runs at C speed.
    """
    if not (set(map(type, points)) <= {tuple} and set(map(len, points)) <= {2}):
        return None
    times = list(map(itemgetter(0), points))
    values = list(map(itemgetter(1), points))
    if (
        set(map(type, times)) <= {float}
        and all(map(math.isfinite, times))
        and all(map(operator.le, times, islice(times, 1, None)))
        and set(map(type, values)) <= _SAMPLE_VALUES
        # NaN is the only value unequal to itself.
        and all(map(operator.eq, values, values))
    ):
        return times, values
    return None


def counter_source(points, mode):
    """normalize_counter_points and counter_source_flags with one validation.

    Returns (points, flags, checked); checked points are in sample form.
    """
    mode = mode if isinstance(mode, CounterMode) else CounterMode.decode(mode)
    points = list(points)
    # Normalization retains absolute samples unless nonaccumulated LAST shifts them.
    retained = mode.value_property != "relative" and (
        mode.source_timing != "last" or mode.accumulated
    )
    columns = sample_columns(points) if retained else None
    if columns is None:
        points = normalize_counter_points(points, mode)
        return points, counter_source_flags(points, mode), False
    # Sample-form times are valid and sorted; a missing value disables flags.
    values = columns[1]
    flags = 0 if None in values else _value_flags(_doubles(values))
    return points, mode.source_flags | flags, True


def counter_source_flags(points, mode):
    """Combine timing/accumulation metadata with normalized source properties."""
    mode = mode if isinstance(mode, CounterMode) else CounterMode.decode(mode)
    return mode.source_flags | source_properties(points)


def source_properties(points):
    """Source data flags from 0x1117870; NaN disables inferred properties.

    0x1000/0x2000 mean nondecreasing/nonincreasing, 0x10000/0x20000
    mean nonnegative/nonpositive. Empty sources satisfy all four predicates.
    """
    points = list(points)
    if any(not _valid(t) or not _valid(v) for t, v in points):
        return 0
    if any(a[0] > b[0] for a, b in zip(points, points[1:])):
        raise ValueError("Counter sample timestamps must be sorted")
    return _value_flags(_doubles([v for _, v in points]))


def _value_flags(values):
    """Sign and monotonicity flags of valid double values."""
    return (
        (0x10000 if all(map(operator.ge, values, repeat(0))) else 0)
        | (0x20000 if all(map(operator.le, values, repeat(0))) else 0)
        | (0x1000 if all(map(operator.le, values, islice(values, 1, None))) else 0)
        | (0x2000 if all(map(operator.ge, values, islice(values, 1, None))) else 0)
    )


def _doubles(values):
    try:
        return list(map(float, values))
    except OverflowError:
        return list(map(_double, values))


def _valid(value):
    # The executable skips NaN, not infinity. Keep that distinction internally;
    # JSON consumers can serialize nonfinite output as null.
    if value is None:
        return False
    try:
        return not math.isnan(value)
    except OverflowError:
        # An exact integer/Fraction can exceed double range without being NaN.
        return True


def _double(value):
    if value is None:
        return None
    try:
        return float(value)
    except OverflowError:
        return math.inf if value > 0 else -math.inf


def merge_attribution_ranges(first, second):
    """Union compact inclusive location ranges, as the tie helper 0x13e00f0."""
    result = []
    for low, high in sorted((*first, *second)):
        if low > high:
            raise ValueError("Location attribution ranges must be ordered")
        if result and low <= result[-1][1] + 1:
            result[-1] = (result[-1][0], max(result[-1][1], high))
        else:
            result.append((low, high))
    return tuple(result)


@dataclass
class MetricPixel:
    start: float
    end: float
    minimum: float | None = None  # binary offset 0x30
    maximum: float | None = None  # 0x38
    total: float = 0.0  # 0x40: sum of source time averages
    count: int = 0  # 0x48: valid contributing sources
    raw_minimum: float | None = None  # 0x10
    raw_maximum: float | None = None  # 0x18
    raw_total: float = 0.0  # 0x20
    raw_count: int = 0  # 0x28: observations, not sources
    first_time: float | None = None  # 0x00
    last_time: float | None = None  # 0x08
    duration: float = 0.0  # audit information, not a pixel field
    area: float = 0.0  # audit information, not a pixel field
    sum_maximum: float = 0.0  # 0x50: sum of each source maximum
    attribution_58: tuple = ()  # 0x58: compact inclusive location ranges
    attribution_70: tuple = ()  # 0x70: raw native field; see merge branch

    def seed_attribution(self, source_id):
        """Optional location-range seed, added after production at 0xead310."""
        source_id = int(source_id)
        self.attribution_58 = self.attribution_70 = ((source_id, source_id),)
        return self

    def select(self, reducer="mean"):
        """The 1/min, 2/max, 4/mean, 8/sum selector at 0xb8bc00."""
        return self.select_hierarchy(reducer) if self.count else None

    def select_hierarchy(self, reducer="mean"):
        """Intermediate source selector at 0xb47fdd, before outer operators.

        Nonempty pixels share the chart selector's arithmetic. Empty sums stay
        zero; empty extrema expose the constructor's finite +/-DBL_MAX
        sentinels; the empty average is 0/0 (internal missing).
        """
        if reducer in (1, "min"):
            return self.minimum if self.count else NATIVE_MAX
        if reducer in (2, "max"):
            return self.maximum if self.count else -NATIVE_MAX
        if reducer in (4, "mean", "avg"):
            return self.total / self.count if self.count else None
        if reducer in (8, "sum"):
            return self.total
        raise ValueError("Unsupported binary pixel reduction: " + str(reducer))

    def _include_times(self, first, last):
        self.first_time = (
            first if self.first_time is None else min(self.first_time, first)
        )
        self.last_time = last if self.last_time is None else max(self.last_time, last)

    def _add_observation(self, time, value):
        """Accumulate an admitted observation using the native finite extrema."""
        self._include_times(time, time)
        if _valid(value):
            self.raw_minimum = min(
                NATIVE_MAX if self.raw_minimum is None else self.raw_minimum, value
            )
            self.raw_maximum = max(
                -NATIVE_MAX if self.raw_maximum is None else self.raw_maximum, value
            )
            self.raw_total += value
            self.raw_count += 1

    def add(self, other):
        """Merge a contributor without reweighting it by its sample count."""
        if self.start != other.start or self.end != other.end:
            raise ValueError("Pixel grids must match before reduction")
        if not self.count:
            self.attribution_58 = other.attribution_58
            self.attribution_70 = other.attribution_70
        elif other.count:
            if other.minimum < self.minimum:
                self.attribution_58 = other.attribution_58
            elif other.minimum == self.minimum:
                self.attribution_58 = merge_attribution_ranges(
                    self.attribution_58, other.attribution_58
                )
            # Both comparisons in 0x13c5350 branch on incoming < existing,
            # including the 0x38/0x70 pair at 0x13c5398. Retain that observed
            # behavior; do not silently label this vector maximum locations.
            if other.maximum < self.maximum:
                self.attribution_70 = other.attribution_70
            elif other.maximum == self.maximum:
                self.attribution_70 = merge_attribution_ranges(
                    self.attribution_70, other.attribution_70
                )
        if other.count:
            self.minimum = (
                other.minimum
                if self.minimum is None
                else min(self.minimum, other.minimum)
            )
            self.maximum = (
                other.maximum
                if self.maximum is None
                else max(self.maximum, other.maximum)
            )
            self.total += other.total
            self.count += other.count
            self.duration += other.duration
            self.area += other.area
        self.sum_maximum += other.sum_maximum
        if other.raw_count:
            self.raw_minimum = (
                other.raw_minimum
                if self.raw_minimum is None
                else min(self.raw_minimum, other.raw_minimum)
            )
            self.raw_maximum = (
                other.raw_maximum
                if self.raw_maximum is None
                else max(self.raw_maximum, other.raw_maximum)
            )
            self.raw_total += other.raw_total
            self.raw_count += other.raw_count
        if other.first_time is not None:
            self._include_times(other.first_time, other.last_time)
        return self


class _SeriesCursor:
    def __init__(self, series, start):
        self.series = series
        observed = getattr(series, "observed", None)
        self.points = [p for p in series.points if observed is None or p[0] in observed]
        self.times = [p[0] for p in self.points]
        # SignalSourceCustom::seek is lower_bound followed by ONE increment on
        # equality, not upper_bound. Preserve duplicate records when supplied.
        self.index = bisect.bisect_left(self.times, start)
        if self.index < len(self.times) and self.times[self.index] == start:
            self.index += 1

    @property
    def current_time(self):
        return self.times[self.index - 1] if self.index else 0.0

    @property
    def next_time(self):
        return self.times[self.index] if self.index < len(self.times) else math.inf

    def current_value(self):
        return _double(self.points[self.index - 1][1]) if self.index else None

    def value(self, t):
        if not self.index:
            return None
        # Timestamp-only callbacks cannot distinguish two recorded samples at
        # the same time. Preserve the cursor's exact record when supported.
        cursor_method = getattr(self.series, "cursor_value", None)
        if cursor_method is not None:
            return _double(cursor_method(self.index - 1, t))
        method = getattr(self.series, "interval_value", None)
        if method is not None:
            return _double(method(self.current_time, self.next_time, t))
        current = self.current_value()
        if getattr(self.series, "interpolation", "previous") in (
            "previous",
            "constant",
        ):
            return current
        if not _valid(current):
            return None
        if self.index == len(self.points):
            return current
        following = _double(self.points[self.index][1])
        if not _valid(following) or self.next_time == self.current_time:
            return current
        return current + (following - current) * (
            (t - self.current_time) / (self.next_time - self.current_time)
        )

    def advance(self):
        self.index = min(self.index + 1, len(self.points))


def pixel_reduce(
    series,
    start,
    end,
    bins,
    timing="next",
    relative=False,
    raw_points=True,
    flags=None,
    source_id=None,
):
    """Produce uniform metric pixels using the recovered 0x12166d0 loop.

    Each source contributes one time average per nonempty pixel. NaN intervals
    do not contribute duration. Flat partial leading intervals that end inside a
    pixel are omitted, matching the executable's explicit branch. LAST changes
    the timestamp attached to point statistics; callers must first construct the
    timing-aware source (LAST values apply to the preceding interval).

    Sources without flag 0x1000 stop at their final sample. ``relative=True``
    extends their last interval. ``flags`` overrides this option; combine mode
    flags with source_properties when constructing a raw source. Bins are [left,right), except
    the last bin includes the request end. Zero-width requests are supported.
    ``source_id`` optionally seeds both native location-attribution range fields.
    """
    if flags is not None:
        relative = bool(flags & 0x1000)
        timing = {0x100: "point", 0x200: "next", 0x400: "last"}.get(
            flags & 0x700, timing
        )
    bins = int(bins)
    if bins < 0:
        raise ValueError("Pixel count cannot be negative")
    if timing not in ("next", "last", "point", "start"):
        raise ValueError("Unknown counter timing: " + timing)
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError("Metric pixel bounds must be finite")
    if not bins or start > end:
        return []
    step = (end - start) / bins
    cursor_factory = getattr(series, "pixel_cursor", None)
    cursor = (
        cursor_factory(start)
        if cursor_factory is not None
        else _SeriesCursor(series, start)
    )
    result = []
    for i in range(bins):
        left = start + i * step
        right = end if i == bins - 1 else start + (i + 1) * step
        final = right == end
        pixel = MetricPixel(left, right)
        if source_id is not None:
            pixel.seed_attribution(source_id)
        result.append(pixel)
        if cursor.current_time > right:
            continue
        interval_count = 0
        # The native accumulator uses finite double extrema, not infinities
        # (12166d0 constants 2f74500/2f74508). This remains observable for
        # an all-infinite source and in an enclosing hierarchical expression.
        low, high = NATIVE_MAX, -NATIVE_MAX
        while True:
            next_time = cursor.next_time
            effective_end = (
                cursor.current_time
                if not relative and math.isinf(next_time)
                else next_time
            )
            current = cursor.current_value()
            a = max(left, cursor.current_time)
            b = min(right, effective_end)
            va, vb = cursor.value(a), cursor.value(b)
            # 0x1216d14-0x1216d63: an equal-valued leading partial interval is
            # not included if its next sample is inside this pixel.
            ends_inside = effective_end <= right if final else effective_end < right
            omit_leading = (
                va == vb and cursor.current_time < left <= effective_end and ends_inside
            )
            if _valid(current) and _valid(va) and _valid(vb) and not omit_leading:
                width = b - a
                pixel.duration += width
                low, high = min(low, va, vb), max(high, va, vb)
                pixel.area += width * (va if va == vb else (va + vb) * 0.5)
                interval_count += 1
            if raw_points:
                observation_time = (
                    next_time if timing == "last" else cursor.current_time
                )
                inside = left <= observation_time and (
                    observation_time <= right if final else observation_time < right
                )
                if inside and (observation_time > 0 or _valid(current)):
                    pixel._add_observation(observation_time, current)
            if effective_end < left or not ends_inside or math.isinf(next_time):
                break
            cursor.advance()
        effective_end = (
            cursor.current_time
            if not relative and math.isinf(cursor.next_time)
            else cursor.next_time
        )
        if interval_count and left <= effective_end and _valid(pixel.area):
            pixel.minimum, pixel.maximum, pixel.count = low, high, 1
            pixel.sum_maximum = high
            pixel.total = (
                pixel.area / pixel.duration
                if pixel.duration != 0
                else cursor.current_value()
            )
        else:
            # The executable never publishes its temporary area/duration for
            # invalid pixels; neither should our optional audit information.
            pixel.duration = pixel.area = 0.0
    return result


def merge_pixels(pixel_lists: Iterable[list[MetricPixel]]):
    """Merge matching grids, retaining the number of nonmissing descendants."""
    merged = []
    for index, pixels in enumerate(pixel_lists):
        # Even an empty first grid fixes the required size for later grids.
        if index == 0:
            merged = [MetricPixel(p.start, p.end) for p in pixels]
        if len(merged) != len(pixels):
            raise ValueError("Pixel grids must match before reduction")
        for target, source in zip(merged, pixels):
            target.add(source)
    return merged


def reduce_pixels(pixel_lists, reducer="mean"):
    """Return the intermediate (pixel-left-time, selected-value) signal."""
    return [(p.start, p.select_hierarchy(reducer)) for p in merge_pixels(pixel_lists)]
