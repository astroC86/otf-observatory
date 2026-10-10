"""Fit affine and piecewise display-time maps from anchor correspondences."""

from __future__ import annotations

import bisect
import collections
import math
import statistics


def _percentile(values, fraction):
    if not values:
        return 0.0
    values = sorted(values)
    at = (len(values) - 1) * fraction
    lo = int(at)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (at - lo)


def _fit(matches, tolerance):
    pairs = [(m["timeB"], m["timeA"]) for m in matches]
    if not pairs:
        return 0.0, 1.0, [], False
    if len(pairs) == 1:
        return pairs[0][1] - pairs[0][0], 1.0, [True], False
    sample = (
        pairs
        if len(pairs) <= 100
        else [pairs[round(i * (len(pairs) - 1) / 99)] for i in range(100)]
    )
    slopes = []
    for i, (x, y) in enumerate(sample):
        for xx, yy in sample[i + 1 :]:
            if xx > x and yy > y:
                slope = (yy - y) / (xx - x)
                if 0.001 <= slope <= 1000:
                    slopes.append(slope)
    if not slopes:
        shift = statistics.median(y - x for x, y in pairs)
        return shift, 1.0, [abs(y - x - shift) <= tolerance for x, y in pairs], False
    scale = statistics.median(slopes)
    shift = statistics.median(y - scale * x for x, y in pairs)
    # Robust reweighting refines the median-slope estimate while keeping one
    # inserted/deleted phase from dragging all other anchors off their times.
    for _ in range(4):
        errors = [y - (shift + scale * x) for x, y in pairs]
        center = statistics.median(errors)
        mad = statistics.median(abs(e - center) for e in errors)
        cut = max(tolerance, 3 * 1.4826 * mad)
        weighted = [
            (x, y, 1 if abs(e) <= cut else cut / abs(e))
            for (x, y), e in zip(pairs, errors)
        ]
        weight = sum(w for x, y, w in weighted)
        mx = sum(x * w for x, y, w in weighted) / weight
        my = sum(y * w for x, y, w in weighted) / weight
        variance = sum(w * (x - mx) ** 2 for x, y, w in weighted)
        if variance <= 1e-30:
            break
        candidate = sum(w * (x - mx) * (y - my) for x, y, w in weighted) / variance
        if not 0.001 <= candidate <= 1000:
            break
        scale = candidate
        shift = my - scale * mx
    errors = [abs(y - (shift + scale * x)) for x, y in pairs]
    return (
        shift,
        scale,
        [e <= max(tolerance, 3 * _percentile(errors, 0.5)) for e in errors],
        True,
    )


def _piecewise(matches, tolerance, maximum=200):
    grouped = collections.defaultdict(list)
    fixed = {m["timeB"]: m["timeA"] for m in matches if m.get("explicit")}
    for m in matches:
        grouped[m["timeB"]].append(m["timeA"])
    points = []
    for b, values in sorted(grouped.items()):
        a = fixed.get(b, statistics.median(values))
        if points and a <= points[-1]["a"]:
            continue
        points.append(dict(a=a, b=b))
    if len(points) < 2:
        return points
    # Iterative vertical-error simplification preserves discontinuities in
    # performance while avoiding a huge collection of redundant linear points.
    retained = {0, len(points) - 1} | {
        i for i, p in enumerate(points) if p["b"] in fixed
    }
    boundaries = sorted(retained)
    stack = list(zip(boundaries, boundaries[1:]))
    while stack and len(retained) < maximum:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        p, q = points[first], points[last]
        slope = (q["a"] - p["a"]) / (q["b"] - p["b"])
        error, index = max(
            (abs(points[i]["a"] - (p["a"] + slope * (points[i]["b"] - p["b"]))), i)
            for i in range(first + 1, last)
        )
        if error > tolerance:
            retained.add(index)
            stack.extend(((first, index), (index, last)))
    return [points[i] for i in sorted(retained)]


def map_time(time, result, mode="affine"):
    """Map a comparison-run timestamp into the baseline run's coordinate system."""
    time = float(time)
    if not math.isfinite(time):
        raise ValueError("Time must be finite")
    if mode not in ("affine", "piecewise"):
        raise ValueError("Alignment mode must be affine or piecewise")
    points = result.get("piecewise", []) if mode == "piecewise" else []
    if len(points) < 2:
        return result["shift"] + result["scale"] * time
    index = bisect.bisect_right([p["b"] for p in points], time)
    if index == 0:
        return points[0]["a"] + (time - points[0]["b"]) * result["scale"]
    if index == len(points):
        return points[-1]["a"] + (time - points[-1]["b"]) * result["scale"]
    p, q = points[index - 1], points[index]
    return p["a"] + (time - p["b"]) * (q["a"] - p["a"]) / (q["b"] - p["b"])


def inverse_time(time, result, mode="affine"):
    """Map baseline coordinates back to a comparison run for coupled zoom."""
    scale = float(result["scale"])
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Alignment scale must be positive and finite")
    inverse = dict(
        shift=-float(result["shift"]) / scale,
        scale=1 / scale,
        piecewise=[dict(a=p["b"], b=p["a"]) for p in result.get("piecewise", [])],
    )
    return map_time(time, inverse, mode)
