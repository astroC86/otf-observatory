"""Render metric charts, reductions and optional pixel attribution."""

import bisect
import math
import operator
from operator import itemgetter

from .engine import capabilities
from .hierarchy import aggregate, members_of
from .pixels import pixel_reduce
from .series import Data, selected_points
from .temporal import temporal
from .values import finite, json_number, reduce_values, reducer_valid

_time = itemgetter(0)
_value = itemgetter(1)


class ResultBuilder:
    """Own output geometry and pixel-attribution records for one query."""

    def __init__(self, context):
        self.context = context
        q = context.q
        trace = context.trace
        self.pixel_details = q.get("pixelDetails") in (True, 1, "1", "true")
        self.pixel_sources = {}
        self.pixel_source_keys = {}
        self.pixel_timelines = []
        self.pixel_detail_count = 0
        self.pixel_next_id = len(trace.locations)
        if self.pixel_details:
            for ident, loc in enumerate(trace.locations):
                if loc in context.locations:
                    self.pixel_sources[str(ident)] = dict(
                        location=loc, name=context.names[loc], members=[loc]
                    )
                    self.pixel_source_keys[(loc, (loc,))] = ident

    def pixel_source(self, key, members):
        ctx = self.context
        if not self.pixel_details:
            return None
        entry = (key, tuple(sorted(members)))
        if entry not in self.pixel_source_keys:
            ident = self.pixel_next_id
            self.pixel_next_id += 1
            self.pixel_source_keys[entry] = ident
            self.pixel_sources[str(ident)] = dict(
                location=key, name=ctx.names.get(key, key), members=list(entry[1])
            )
        return self.pixel_source_keys[entry]

    def record_pixels(self, key, members, pixels, stage, operation):
        ctx = self.context
        if not self.pixel_details:
            return
        self.pixel_detail_count += len(pixels)
        if self.pixel_detail_count > 20000:
            raise ValueError(
                "Pixel attribution details exceed 20000 pixels; reduce bins or select fewer locations"
            )
        records = [
            dict(
                start=p.start,
                end=p.end,
                min=json_number(p.minimum),
                max=json_number(p.maximum),
                mean=json_number(p.select("mean")),
                sum=json_number(p.select("sum")),
                contributors=p.count,
                selectedValue=(
                    json_number(p.select_hierarchy(operation))
                    if stage == "hierarchy"
                    else None
                ),
                rawMin=json_number(p.raw_minimum),
                rawMax=json_number(p.raw_maximum),
                rawSum=json_number(p.raw_total),
                rawSamples=p.raw_count,
                firstTime=json_number(p.first_time),
                lastTime=json_number(p.last_time),
                duration=json_number(p.duration),
                area=json_number(p.area),
                attribution58=p.attribution_58,
                attribution70=p.attribution_70,
            )
            for p in pixels
        ]
        self.pixel_timelines.append(
            dict(
                location=key,
                name=ctx.names.get(key, key),
                members=sorted(members),
                stage=stage,
                operation=operation,
                pixels=records,
            )
        )

    def display_points(self, series):
        """Build bounded chart geometry without changing observations or statistics.

        Composed interpolated operands can produce nonlinear curves between their
        recorded states. Evaluate those curves on the visible pixel grid. Retain
        both sides of an original discontinuity, including the finite left limit
        at a missing boundary, so linear drawing cannot bridge a step or a gap.
        """
        ctx = self.context
        points = selected_points(series, ctx.start, ctx.end, True)
        if series.display_interpolation == "linear":
            left = []
            for t in sorted(set(series.times)):
                if not ctx.start < t <= ctx.end:
                    continue
                index = bisect.bisect_left(series.times, t)
                before = series.cursor_value(index - 1, t)
                near = series.cursor_value(index - 1, math.nextafter(t, -math.inf))
                # Interpol's exact right endpoint returns the next reading even
                # when the preceding open interval is missing. Preserve that gap
                # (and branch changes) while avoiding rounding-only duplicate knots.
                same_limit = (
                    before == near
                    or finite(before)
                    and finite(near)
                    and abs(before - near)
                    <= 4 * max(math.ulp(float(before)), math.ulp(float(near)))
                )
                if not same_limit:
                    before = near
                after = series.knots[index][1]
                if before != after:
                    left.append((t, before))
            ctx.charge(len(series.knots))
            # Stable sorting places the incoming limit before all equal-time
            # source states. Raw duplicate measurements remain in their order.
            points = left + points
        if series.sample_display:
            times = {t for t, _ in points}
            width = (ctx.end - ctx.start) / ctx.bins
            ctx.charge(ctx.bins)
            for i in range(1, ctx.bins):
                t = ctx.start + i * width
                if t not in times:
                    points.append((t, series.at(t)))
        return sorted(points, key=_time)

    def evaluate(self):
        ctx = self.context
        q = ctx.q
        bins = ctx.bins
        expression = q.get("expression", "x")
        if ctx.start == ctx.end or not ctx.locations:
            return dict(
                metric=dict(name=q.get("name", expression), unit=q.get("unit", "")),
                series=[],
                capabilitiesVersion=1,
            )
        if q.get("reduction") == "integral":
            saved_start, saved_q = ctx.start, ctx.q
            ctx.start = 0.0
            ctx.q = dict(ctx.q, start=0.0)
            try:
                data = ctx.expression(expression)
            finally:
                ctx.start, ctx.q = saved_start, saved_q
        else:
            data = ctx.expression(expression)
        aggregation = q.get("aggregation", "none")
        if isinstance(aggregation, dict):
            scope = aggregation.get("scope", "all")
            aggregation = aggregation.get("operation", "none")
        else:
            scope = q.get("scope", "all")
        if aggregation and aggregation != "none":
            data = aggregate(ctx, data, str(aggregation), str(scope))
        reduction = q.get("reduction", "none")
        if reduction not in ("none", "", None, "integral"):
            reducer_valid(reduction)
        output = []
        output_points = 0
        for key, series in data.series.items():
            if self.pixel_details and series.pixels is None:
                ctx.charge(len(series.points) + ctx.bins)
                pixels = pixel_reduce(
                    series,
                    ctx.start,
                    ctx.end,
                    ctx.bins,
                    flags=series.flags,
                    source_id=self.pixel_source(key, members_of(ctx, data, key)),
                )
                self.record_pixels(
                    key, members_of(ctx, data, key), pixels, "output", "value"
                )
            points = self.display_points(series)
            actual = selected_points(series, ctx.start, ctx.end)
            values = [v for _, v in actual if v is not None]
            value = None
            if reduction == "integral":
                integrated = temporal(
                    ctx,
                    Data({key: series}, data.unit, members=data.members),
                    "integrate",
                ).series[key]
                value = integrated.at(ctx.end)
            elif reduction and reduction != "none":
                value = reduce_values(values, reduction)
            shown = reduce_display(points, ctx.start, ctx.end, bins)
            output_points += len(shown)
            if output_points > 250000:
                raise ValueError(
                    "Metric has too many visible gap boundaries; narrow the time range or select fewer locations"
                )
            # Preserve raw integer arithmetic internally; charts require finite doubles.
            converted = [[t, json_number(v)] for t, v in shown]
            output.append(
                dict(
                    location=key,
                    name=ctx.names.get(key, key),
                    points=converted,
                    interpolation=series.display_interpolation,
                    min=json_number(min(values)) if values else None,
                    max=json_number(max(values)) if values else None,
                    samples=len(actual),
                    validSamples=len(values),
                    missingSamples=len(actual) - len(values),
                    members=sorted(members_of(ctx, data, key)),
                    summary=dict(
                        operation=reduction,
                        value=json_number(value),
                        validSamples=len(values),
                        missingSamples=len(actual) - len(values),
                    ),
                )
            )
        result = dict(
            metric=dict(
                name=q.get("name", expression), unit=q.get("unit") or data.unit
            ),
            series=output,
            expression=expression,
            alignment="explicit-linear-or-previous-sample",
            aggregation=aggregation,
            scope=scope,
            reduction=reduction,
            capabilitiesVersion=1,
            evaluatedInputPoints=ctx.inputs,
            evaluatedWorkPoints=ctx.work,
            semantics=capabilities()["semantics"],
        )
        if self.pixel_details:
            result["pixelDetails"] = dict(
                sources=self.pixel_sources, timelines=self.pixel_timelines
            )
        if ctx.source_diagnostics:
            result["sourceDiagnostics"] = ctx.source_diagnostics
        return result


def reduce_display(points, start, end, bins):
    """Retain extrema and gap boundaries without allowing a line across nulls.

    Points are time ordered, so every pixel bucket is one contiguous run.
    """
    if not points:
        return []
    width = max((end - start) / bins, 1e-30)
    times = list(map(_time, points))
    values = list(map(_value, points))

    def bucket_of(t):
        return min(bins, max(0, int((t - start) / width)))

    result = []
    low = 0
    while low < len(points):
        high = bisect.bisect_right(times, bucket_of(times[low]), low, key=bucket_of)
        bucket = values[low:high]
        if None in bucket or any(
            map(operator.eq, times[low : high - 1], times[low + 1 : high])
        ):
            indices = _gap_indices(points[low:high])
        else:
            # Without gaps or equal times only the ends and first extrema
            # remain; list.index finds the selected element even if NaN.
            indices = {
                0,
                len(bucket) - 1,
                bucket.index(min(bucket)),
                bucket.index(max(bucket)),
            }
        result.extend(points[low + i] for i in sorted(indices))
        low = high
    return result


def _gap_indices(entries):
    """Ends, first extrema, equal-time pairs and missing/present run starts."""
    indices = {0, len(entries) - 1}
    present = [i for i, (_, v) in enumerate(entries) if v is not None]
    if present:
        indices.add(min(present, key=lambda i: entries[i][1]))
        indices.add(max(present, key=lambda i: entries[i][1]))
    for i in range(1, len(entries)):
        (s, u), (t, v) = entries[i - 1], entries[i]
        if s == t:
            indices.update((i - 1, i))
        if (u is None) != (v is None):
            indices.add(i)
    return indices
