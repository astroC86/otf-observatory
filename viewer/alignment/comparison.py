"""Compare physical profile costs across aligned trace windows."""

import math


def comparison(trace, other, q, shift=0, scale=1, anchors=None, baseline_summary=None):
    if not math.isfinite(shift) or not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid comparison time mapping")
    start, end, _, _ = trace.scope(q)
    q2 = dict(q)
    q2.pop("locations", None)
    piecewise = False
    if anchors is not None:
        if not isinstance(anchors, list) or len(anchors) > 10000:
            raise ValueError("Invalid alignment anchors")
        points = [(float(p["a"]), float(p["b"])) for p in anchors]
        if any(not math.isfinite(a) or not math.isfinite(b) for a, b in points) or any(
            a2 <= a1 or b2 <= b1 for (a1, b1), (a2, b2) in zip(points, points[1:])
        ):
            raise ValueError("Alignment anchors must increase strictly in both traces")
        if len(points) > 1:
            piecewise = True
            import bisect

            times = [p[0] for p in points]

    def inverse(t):
        if not piecewise:
            return (t - shift) / scale
        if t < points[0][0]:
            return points[0][1] + (t - points[0][0]) / scale
        if t > points[-1][0]:
            return points[-1][1] + (t - points[-1][0]) / scale
        i = max(0, min(len(points) - 2, bisect.bisect_right(times, t) - 1))
        a, b = points[i]
        aa, bb = points[i + 1]
        return b + (t - a) * (bb - b) / (aa - a)

    q2["start"] = max(0, min(other.meta["duration"], inverse(start)))
    q2["end"] = max(0, min(other.meta["duration"], inverse(end)))

    def by_name(rows):
        # Multiple source regions may share a display name. Aggregate every one.
        result = {}
        for r in rows:
            item = result.setdefault(r["name"], dict(exclusive=0, calls=0, regions=0))
            item["exclusive"] += r["exclusive"]
            item["calls"] += r["calls"]
            item["regions"] += 1
        return result

    a = by_name(trace.summary(q) if baseline_summary is None else baseline_summary)
    b = by_name(other.summary(q2))
    rows = []
    for name in a.keys() | b.keys():
        x = a.get(name, {})
        y = b.get(name, {})
        av = x.get("exclusive", 0)
        bv = y.get("exclusive", 0)
        rows.append(
            dict(
                name=name,
                a=av,
                b=bv,
                delta=bv - av,
                ratio=bv / av if av else None,
                callsA=x.get("calls", 0),
                callsB=y.get("calls", 0),
                regionsA=x.get("regions", 0),
                regionsB=y.get("regions", 0),
            )
        )
    return dict(
        rows=sorted(rows, key=lambda r: abs(r["delta"]), reverse=True),
        a=trace.meta["name"],
        b=other.meta["name"],
        rangeA=[start, end],
        rangeB=[q2["start"], q2["end"]],
        shift=shift,
        scale=scale,
        mapping="piecewise" if piecewise else "affine",
        durationSemantics="Physical seconds in each selected run; time mapping does not rescale profile costs.",
    )


def comparison_many(trace, baseline_id, mappings, q, get_trace):
    if not isinstance(mappings, list) or not 1 <= len(mappings) <= 15:
        raise ValueError("Select between 1 and 15 comparison runs")
    seen = {baseline_id}
    rows = {}
    runs = []
    baseline = trace.summary(q)
    window = None
    for mapping in mappings:
        if not isinstance(mapping, dict) or not isinstance(mapping.get("id"), str):
            raise ValueError("Each comparison mapping needs a trace id")
        ident = mapping["id"]
        if ident in seen:
            raise ValueError(
                "Comparison trace IDs must be distinct from each other and the baseline"
            )
        seen.add(ident)
        other = get_trace(ident)
        result = comparison(
            trace,
            other,
            q,
            float(mapping.get("shift", 0)),
            float(mapping.get("scale", 1)),
            mapping.get("anchors"),
            baseline,
        )
        window = result["rangeA"]
        runs.append(
            dict(
                id=ident,
                name=other.meta["name"],
                range=result["rangeB"],
                shift=result["shift"],
                scale=result["scale"],
                mapping=result["mapping"],
            )
        )
        for item in result["rows"]:
            row = rows.setdefault(
                item["name"],
                dict(
                    name=item["name"],
                    baseline=item["a"],
                    baselineCalls=item["callsA"],
                    values={},
                ),
            )
            row["values"][ident] = dict(
                time=item["b"],
                delta=item["delta"],
                ratio=item["ratio"],
                calls=item["callsB"],
            )
    for row in rows.values():
        for run in runs:
            row["values"].setdefault(
                run["id"],
                dict(
                    time=0,
                    delta=-row["baseline"],
                    ratio=0 if row["baseline"] else None,
                    calls=0,
                ),
            )
    return dict(
        baseline=dict(id=baseline_id, name=trace.meta["name"]),
        range=window,
        runs=runs,
        rows=sorted(
            rows.values(),
            key=lambda row: max(abs(v["delta"]) for v in row["values"].values()),
            reverse=True,
        ),
        durationSemantics="Physical seconds in each run; alignment changes the selected window, not measured durations.",
    )
