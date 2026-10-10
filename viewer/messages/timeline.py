"""Recovered MessageSummaryTimeline's repeated closed-bin transfer summaries."""

from __future__ import annotations

import math

import numpy as np

from .statistics import GROUPS, _seconds_record, merge_statistics
from .summary import bin_summaries
from .transfers import native_transfer_records

MAX_BINS = 1000
MAX_GROUP_CELLS = 200000
METRICS = ("count", "bytes.sum", "duration.sum", "rate")


def timeline_value(row, metric):
    """bb36a0/bb34e0: ratio of sums, with a one-tick zero-sum denominator."""
    if not row.get("count"):
        return 0.0
    if metric == "count":
        return float(row["count"])
    if metric == "bytes.sum":
        return row["bytes"]["sum"]
    if metric == "duration.sum":
        return row["duration"]["sum"]
    if metric == "rate":
        return row["bytes"]["sum"] / (row["duration"]["sum"] or 1.0)
    raise ValueError("Invalid native transfer timeline metric")


def reduce_timeline_keys(series, metric="count", max_keys=100):
    """Global key selection before per-bin scalar conversion (bb8f20).

    The native limit is a trigger, not a strict output cap: its scan retains
    max_keys+1 leading entries and all ties, subject to maximum/1000. The
    discarded keys are merged into Other independently in every bin.
    """
    if metric not in METRICS:
        raise ValueError("Invalid native transfer timeline metric")
    max_keys = _count(max_keys, "maxKeys", 10000)
    totals = {}
    for rows in series:
        for row in rows:
            totals[row["key"]] = merge_statistics(totals.get(row["key"]), row)
    ranked = sorted(totals, key=lambda key: -timeline_value(totals[key], metric))
    discarded = []
    triggered = len(ranked) > max_keys
    if triggered and ranked:
        threshold = max(0.0, timeline_value(totals[ranked[0]], metric)) / 1000.0
        previous = None
        for index, key in enumerate(ranked):
            score = timeline_value(totals[key], metric)
            if previous is not None and score == previous:
                continue
            if score < threshold or index >= max_keys + 1:
                discarded = ranked[index:]
                break
            previous = score
    removed = set(discarded)
    output = []
    for rows in series:
        kept = [
            dict(row, value=timeline_value(row, metric))
            for row in rows
            if row["key"] not in removed
        ]
        if triggered:
            indexed = {row["key"]: row for row in rows}
            other = None
            # Descending score follows the native remaining multimap. Equal
            # score ordering depends on native hash traversal; membership does
            # not. The port preserves first occurrence for those ties.
            for key in discarded:
                if key in indexed:
                    other = merge_statistics(other, indexed[key])
            other = other or dict(count=0)
            kept.append(
                dict(other, key=-100, other=True, value=timeline_value(other, metric))
            )
        output.append(kept)
    return output, dict(
        metric=metric,
        maxKeys=max_keys,
        originalKeyCount=len(ranked),
        retainedKeyCount=len(ranked) - len(discarded),
        otherKey=-100,
        discardedKeys=discarded,
        triggered=triggered,
        thresholdFraction=0.001,
    )


def _count(value, name, maximum):
    """value as an exact integer from 0 to maximum."""
    message = f"Timeline {name} must be an integer from 0 to {maximum}"
    try:
        count = int(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(message) from error
    if isinstance(value, bool) or str(value) != str(count) or not 0 <= count <= maximum:
        raise ValueError(message)
    return count


def timeline_bounds(start, end, bins):
    """Preserve f37056–f37064's multiply, divide, then add operation order."""
    bins = _count(bins, "bins", MAX_BINS)
    if not all(math.isfinite(value) for value in (start, end)) or end < start:
        raise ValueError("Invalid native transfer timeline window")
    bounds = (
        [
            start + (float(index) * (end - start)) / float(bins)
            for index in range(bins + 1)
        ]
        if bins
        else []
    )
    if not all(math.isfinite(value) for value in bounds):
        raise ValueError("Native transfer timeline bounds overflow")
    return bounds


def timeline_transfers(
    transfers,
    start,
    end,
    bins=100,
    *,
    location_order=(),
    group_cell_limit=MAX_GROUP_CELLS,
):
    """Five native scalar maps per bin, with closed internal boundaries.

    A transfer on an internal boundary belongs to both adjacent nonempty bins.
    A zero-width bin returns no records, as its f352e0 invocation does. All bins
    reduce together instead of repeatedly scanning the records for every bin.
    """
    bounds = timeline_bounds(start, end, bins)
    bins = _count(bins, "bins", MAX_BINS)
    groups = {name: [] for name in GROUPS}
    result = dict(
        bins=bins,
        binBounds=bounds,
        groups=groups,
        binTotals=[],
        totals=dict(count=0),
        binRecordCount=0,
        boundaryDuplicateCount=0,
    )
    if not bins:
        return result
    edges = np.array(bounds)
    rows = np.flatnonzero(
        (edges[0] <= transfers.start) & (transfers.start <= edges[-1])
    )
    starts = transfers.start[rows]
    # The nonempty bin starting at or before each start, and the nonempty bin
    # ending exactly at it; both are the same bin away from boundaries.
    after = np.searchsorted(edges, starts, "right") - 1
    before = np.searchsorted(edges, starts, "left") - 1
    first, second = after < bins, (before >= 0) & (before != after)
    summaries = bin_summaries(
        transfers,
        np.concatenate((rows[first], rows[second])),
        np.concatenate((after[first], before[second])),
        bins,
        location_order=location_order,
    )
    cells = 0
    for summary in summaries:
        result["binTotals"].append(summary["totals"])
        result["binRecordCount"] += summary["totals"]["count"]
        for name in GROUPS:
            bin_rows = summary["groups"][name]
            cells += len(bin_rows)
            if cells > group_cell_limit:
                raise ValueError(
                    "Native transfer timeline group-cell limit exceeded; reduce bins or narrow the selection"
                )
            groups[name].append(bin_rows)
    if bounds[-1] > bounds[0]:
        # This viewer total counts unique transfers. Native replies contain
        # the five vectors, whose closed bins can repeat boundary records.
        result["totals"] = bin_summaries(
            transfers,
            rows,
            np.zeros(len(rows), np.intp),
            1,
            location_order=location_order,
            groups=(),
        )[0]["totals"]
    result["boundaryDuplicateCount"] = (
        result["binRecordCount"] - result["totals"]["count"]
    )
    return result


def native_message_timeline(trace, q):
    """Browser-facing worker contract over proven native MPI/RMA emissions.

    q shares MessageSummary filters plus bins, metric and maxKeys. The original
    worker maps are retained alongside the native client's reduced maps.
    """
    bins = _count(q.get("bins", 100), "bins", MAX_BINS)
    start, end, _, _ = trace.scope(q, regions=False)
    resolution = int(trace.meta.get("clock", {}).get("resolution", 1))
    if resolution <= 0:
        raise ValueError("Invalid recorded clock resolution")
    first, last = start * resolution, end * resolution
    bounds = timeline_bounds(first, last, bins)
    # The computed final endpoint may differ from the nominal end by an ULP.
    # Load its exact native tick interval, not a seconds round-trip.
    source = native_transfer_records(
        trace, q, tick_window=(bounds[0], bounds[-1]) if bounds else (first, first)
    )
    result = timeline_transfers(
        source["transfers"], first, last, bins, location_order=trace.locations
    )
    metric = q.get("metric", "count")
    result["displayGroups"], result["keyReduction"] = {}, {}
    for name, series in result["groups"].items():
        display, info = reduce_timeline_keys(series, metric, q.get("maxKeys", 100))
        result["displayGroups"][name], result["keyReduction"][name] = display, info
        for rows in display:
            for row in rows:
                # clone nested scalars before modifying shared raw worker maps
                for key, value in list(row.items()):
                    if isinstance(value, dict):
                        row[key] = dict(value)
                _seconds_record(row, resolution)
                if metric == "duration.sum":
                    row["value"] /= resolution
                elif metric == "rate":
                    row["value"] *= resolution
    for series in result["groups"].values():
        for rows in series:
            for row in rows:
                _seconds_record(row, resolution)
    for row in [result["totals"], *result["binTotals"]]:
        _seconds_record(row, resolution)
    result["binBounds"] = [value / resolution for value in result["binBounds"]]
    result.update(
        start=start,
        end=end,
        clockResolution=str(resolution),
        callsites=source["callsites"],
        diagnostics=source["diagnostics"],
        semantics=dict(
            selection="Each nonempty bin independently selects transfer starts in its closed interval.",
            boundaries="An exact internal-boundary start contributes to both adjacent bins. Zero-width bins are empty.",
            durations="Full native transfer lifetimes are retained, even beyond the bin or selected window.",
            grouping="Independent maps by payload size, tag, transfer type, communicator and source position.",
            totals="Viewer totals count unique selected transfers. Bin totals can repeat boundary starts and must not be added as unique traffic.",
            units="Seconds, bytes and bytes per second. Zero-duration rates use one recorded clock tick.",
            provenance="Proven native MPI emissions and completed RMA transfers; raw records remain unchanged.",
            keys="Raw groups retain complete worker maps. Display groups use native global ranking, cutoff ties and per-bin Other aggregation.",
            ordering="Native bin arithmetic and original double ticks; serial location reduction order.",
        ),
    )
    return result
