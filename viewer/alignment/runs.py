"""Semantic sequence alignment and explicitly qualified cross-run time maps.

Names and ordered occurrences provide evidence; absolute timestamps and reference
IDs do not identify iterations across runs. An affine fit estimates a convenient
display alignment, not a physical clock correction or equal work per second.
"""

from __future__ import annotations

import collections
import math

from . import anchors, mapping
from . import correspondence as matching


def _location(trace, requested=None, selected=None, reference=None):
    if requested is not None and str(requested) not in trace.locations:
        raise ValueError("Alignment location not found")
    if requested is not None:
        return str(requested)
    candidates = [
        r
        for r in trace.meta["locations"]
        if r.get("type") != "METRIC" and (not selected or r["id"] in selected)
    ]
    if not candidates:
        return None
    if reference:
        matching = [r for r in candidates if r.get("name") == reference.get("name")]
        if matching:
            candidates = matching
    return max(
        candidates,
        key=lambda r: (
            r.get("type") == "CPU_THREAD",
            r.get("events", 0),
            -len(r["id"]),
            r["id"],
        ),
    )["id"]


def _limits(trace, q, other=False):
    scope = (
        {k[:-1].lower(): v for k, v in q.items() if k in ("startB", "endB")}
        if other
        else q
    )
    return trace.scope(scope, regions=False)[:2]


def align(trace, other, q):
    """Match ordered semantic anchors, permitting inserted/deleted occurrences."""
    start, end = _limits(trace, q)
    start_b, end_b = _limits(other, q, True)
    maximum = max(32, min(2500, int(q.get("maxAnchors", 1500))))
    selected = set(q["locations"].split(",")) if q.get("locations") else None
    loc_a = _location(trace, q.get("locationA") or None, selected)
    loc_b = _location(
        other, q.get("locationB") or None, reference=trace.locations.get(loc_a)
    )
    anchor = q.get("anchor", "").casefold().strip()
    names_a, names_b, selection, selection_diagnostics = anchors._select_symbols(
        trace, other, q, loc_a, loc_b, (start, end), (start_b, end_b), anchor
    )
    # Retain unmatched symbols as well: they are gap evidence, and dropping
    # them before matching can hide inserted/deleted iterations or phases.
    aa, meta_a, diagnostics_a = anchors._anchors(
        trace, loc_a, start, end, names_a, anchor, maximum
    )
    bb, meta_b, diagnostics_b = anchors._anchors(
        other, loc_b, start_b, end_b, names_b, anchor, maximum
    )
    anchors._enrich(trace, aa, q, diagnostics_a)
    anchors._enrich(other, bb, q, diagnostics_b)
    matching._semantic_keys(aa, bb)
    keys_a = [a["matchKey"] for a in aa]
    keys_b = [b["matchKey"] for b in bb]
    constraints = matching._constraints(
        trace, other, q, [(start, end), (start_b, end_b)]
    )
    matches, blocks, ambiguities, ambiguity_count = matching._correspondence(
        aa, bb, constraints
    )
    duration = max(end - start, 1e-12)
    duration_b = max(end_b - start_b, 1e-12)
    tick_a = 1 / max(1, float(trace.meta.get("clock", {}).get("resolution", 1e9)))
    tick_b = 1 / max(1, float(other.meta.get("clock", {}).get("resolution", 1e9)))
    tolerance = float(q.get("tolerance", max(duration * 0.002, tick_a, tick_b)))
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("Alignment tolerance must be positive and finite")
    shift, scale, inliers, scale_identified = mapping._fit(matches, tolerance)
    if constraints:
        # One explicit anchor fixes the origin while the evidence estimates
        # scale. Multiple constraints define the affine fit themselves; their
        # individual points always remain exact in the piecewise map.
        if len(constraints) > 1:
            shift, scale, _, scale_identified = mapping._fit(constraints, tolerance)
        else:
            shift = constraints[0]["timeA"] - scale * constraints[0]["timeB"]
        inliers = [
            abs(m["timeA"] - (shift + scale * m["timeB"])) <= tolerance for m in matches
        ]
    errors = []
    for match, inlier in zip(matches, inliers):
        match["residual"] = match["timeA"] - (shift + scale * match["timeB"])
        match["inlier"] = inlier
        errors.append(abs(match["residual"]))
    counts_a = collections.Counter(keys_a)
    counts_b = collections.Counter(keys_b)
    unique = sum(
        1
        for m in matches
        if m.get("explicit") or counts_a[m["key"]] == counts_b[m["key"]] == 1
    )
    distinct = len({m["key"] for m in matches})
    repeated = len(matches) - unique
    repetition_gaps = any(
        counts_a[k] != counts_b[k] and max(counts_a[k], counts_b[k]) > 1
        for k in counts_a.keys() & counts_b.keys()
    )
    coverage_a = (
        (max(m["timeA"] for m in matches) - min(m["timeA"] for m in matches)) / duration
        if matches
        else 0.0
    )
    coverage_b = (
        (max(m["timeB"] for m in matches) - min(m["timeB"] for m in matches))
        / duration_b
        if matches
        else 0.0
    )
    p95 = mapping._percentile(errors, 0.95)
    median = mapping._percentile(errors, 0.5)
    evidence = min(1, len(matches) / 12) * (0.35 + 0.65 * min(1, distinct / 5))
    support = 0.3 + 0.7 * math.sqrt(max(0, min(1, coverage_a) * min(1, coverage_b)))
    fit = math.exp(
        -max(p95, max(errors, default=0) * 0.5) / max(duration * 0.02, tolerance)
    )
    ambiguity = (
        0.45
        if unique < 2 and repeated
        else 0.65 if ambiguities else 0.8 if unique < 4 and repeated else 1.0
    )
    correspondence = max(0, min(1, evidence * support * ambiguity))
    confidence = correspondence * fit
    if len(matches) < 3 or not scale_identified:
        confidence = min(confidence, 0.25)
    diagnostics = selection_diagnostics + diagnostics_a + diagnostics_b
    if not matches:
        diagnostics.append(
            dict(
                code="no_common_anchors",
                message="No ordered matching function or marker anchors were found.",
            )
        )
    if len(matches) < 3:
        diagnostics.append(
            dict(
                code="too_few_anchors",
                message="At least three separated semantic anchors are needed to corroborate offset and scale.",
            )
        )
    ambiguous = bool(ambiguities) or bool(repeated and unique < 2 and not constraints)
    if ambiguities:
        diagnostics.append(
            dict(
                code="repetition_ambiguity",
                message="Several repeated-phase correspondences remain possible. Ambiguous pairs are excluded from the fitted mapping; add recorded iteration identities or explicit anchors to resolve them.",
            )
        )
    elif ambiguous:
        diagnostics.append(
            dict(
                code="repetition_ambiguity",
                message="Repeated labels match by ordered occurrence only; independent iteration identities or explicit anchors are needed to corroborate that correspondence.",
            )
        )
    if constraints:
        diagnostics.append(
            dict(
                code="explicit_constraints",
                message="Explicit anchors partition the correspondence and are preserved exactly in the piecewise mapping.",
            )
        )
    if len(blocks) > 1:
        diagnostics.append(
            dict(
                code="insertions_or_deletions",
                message="The ordered match contains gaps; additional or omitted phases were not forced into one-to-one matches.",
            )
        )
    if p95 > tolerance:
        diagnostics.append(
            dict(
                code="non_affine_timing",
                message="Some matched phases do not follow one affine time map; inspect anchors or the piecewise preview.",
            )
        )
    if meta_a["subsampled"] or meta_b["subsampled"]:
        confidence *= 0.85
    points = mapping._piecewise(matches, max(tick_a, tick_b, tolerance * 0.15))
    automatic = sum(not m.get("explicit") for m in matches)
    quality = dict(
        confidence=confidence,
        affineConfidence=confidence,
        correspondenceConfidence=correspondence,
        level=(
            "high" if confidence >= 0.8 else "moderate" if confidence >= 0.5 else "low"
        ),
        status=(
            "ambiguous"
            if ambiguous
            else (
                "constrained"
                if constraints
                else "insufficient-evidence" if len(matches) < 3 else "matched"
            )
        ),
        matched=len(matches),
        distinctLabels=distinct,
        uniqueMatches=unique,
        repeatedMatches=repeated,
        repeatedOccurrenceMismatch=repetition_gaps,
        ambiguousRanks=ambiguity_count,
        explicitConstraints=len(constraints),
        inliers=sum(inliers),
        coverageA=coverage_a,
        coverageB=coverage_b,
        residualMedian=median,
        residualP95=p95,
        residualMaximum=max(errors, default=0),
        tolerance=tolerance,
        scaleIdentified=scale_identified,
        unmatchedA=max(0, len(aa) - automatic),
        unmatchedB=max(0, len(bb) - automatic),
    )
    for match in matches:
        match.pop("key", None)
    recommendation = (
        "piecewise"
        if len(points) >= 3
        and max(errors, default=0) > tolerance
        and correspondence >= 0.5
        else "affine" if confidence >= 0.5 else "inspect-anchors"
    )
    if constraints and len(points) >= 3 and max(errors, default=0) > tolerance:
        recommendation = "piecewise"
    return dict(
        method="semantic-context/mandatory-sequence/robust-affine",
        mapping="timeA = shift + scale * timeB",
        shift=shift,
        scale=scale,
        proposed=dict(shift=shift, scale=scale),
        quality=quality,
        matches=matches,
        ambiguities=ambiguities,
        ambiguitiesTruncated=ambiguity_count > len(ambiguities),
        blocks=blocks,
        piecewise=points,
        diagnostics=diagnostics,
        selection=selection,
        recommendedMode=recommendation,
        locationA=loc_a,
        locationB=loc_b,
        anchorsA=meta_a,
        anchorsB=meta_b,
        rangeA=dict(start=start, end=end),
        rangeB=dict(start=start_b, end=end_b),
        semantics=dict(
            sequence="Only pairs shared by every longest semantic correspondence affect the mapping. Context and recorded iteration parameters distinguish repeated names.",
            scale="Display-time dilation fitted to semantic events; not a measured hardware clock drift.",
            piecewise="Monotone interpolation preserves explicit anchors; extrapolation outside anchor coverage uses the affine slope and is not evidence of phase correspondence.",
            confidence="Heuristic evidence score, not a calibrated probability.",
        ),
    )


def align_many(traces, q):
    """Map each comparison run independently into one common baseline."""
    if not isinstance(traces, dict) or not 2 <= len(traces) <= 16:
        raise ValueError("Multi-run alignment requires 2 to 16 distinct traces")
    baseline = str(q.get("baseline", next(iter(traces))))
    if baseline not in traces:
        raise ValueError("Baseline trace not found")
    options = q.get("runs", {})
    if not isinstance(options, dict) or any(key not in traces for key in options):
        raise ValueError("Run options must reference selected trace IDs")
    trace = traces[baseline]
    common = {k: v for k, v in q.items() if k not in ("baseline", "runs", "ids")}
    start, end = _limits(trace, common)
    lo, hi = start, end
    results = []
    diagnostics = []
    for ident, other in traces.items():
        if ident == baseline:
            continue
        override = options.get(ident, {})
        if not isinstance(override, dict):
            raise ValueError("Run alignment options must be an object")
        pair = dict(common, **override)
        # Every run shares the same baseline selection even if its own range
        # or anchor constraints differ.
        pair["start"] = start
        pair["end"] = end
        result = align(trace, other, pair)
        results.append(dict(id=ident, name=other.meta["name"], alignment=result))
        mode = "piecewise" if result["recommendedMode"] == "piecewise" else "affine"
        lo = max(lo, mapping.map_time(result["rangeB"]["start"], result, mode))
        hi = min(hi, mapping.map_time(result["rangeB"]["end"], result, mode))
        if result["quality"]["status"] in ("ambiguous", "insufficient-evidence"):
            diagnostics.append(
                dict(
                    code="run_requires_inspection",
                    run=ident,
                    message="This run has unresolved or insufficient anchor evidence; inspect its independent mapping.",
                )
            )
    return dict(
        baseline=dict(
            id=baseline, name=trace.meta["name"], range=dict(start=start, end=end)
        ),
        runs=results,
        commonRange=dict(start=lo, end=hi) if hi > lo else None,
        diagnostics=diagnostics,
        semantics="Every comparison maps directly to the baseline. Mappings change display coordinates; durations and costs remain physical measurements in each run.",
    )
