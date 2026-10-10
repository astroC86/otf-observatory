"""Recovered MessageSummary transfer statistics, separate from raw events.

The native query selects transfer starts in a closed time window and summarizes
the complete transfer duration. See docs/binary-query-contracts.md.
"""

from __future__ import annotations

import math

import numpy as np

from .statistics import (
    GROUPS,
    _seconds_record,
    merge_columns,
    statistics_columns,
    statistics_record,
)
from .transfers import native_transfer_records

# Transfers field of each native group key.
_KEYS = dict(
    size="bytes", tag="tag", type="nativeType", communicator="comm", callsite="callsite"
)


def _location_ranks(transfers, location_order):
    """Sender location rank of each transfer: recorded order, then by name."""
    codes, names = transfers.recode("sender", str)
    order = {str(loc): index for index, loc in enumerate(location_order)}
    ranked = sorted(
        range(len(names)),
        key=lambda code: (order.get(names[code], len(order)), names[code]),
    )
    ranks = np.empty(len(names), np.intp)
    ranks[ranked] = np.arange(len(names))
    return ranks[codes]


def bin_summaries(transfers, rows, bins, count, location_order=(), groups=GROUPS):
    """summarize_transfers of count bins at once, where rows[i] lies in bins[i].

    Records merge per (bin, sender location, key) in (start, sequence) order,
    then per (bin, key) in location order, like the native accumulation. Group
    rows keep the order in which their keys first occur.
    """
    results = [
        dict(groups={name: [] for name in GROUPS}, totals=dict(count=0))
        for _ in range(count)
    ]
    if not len(rows):
        return results
    location = _location_ranks(transfers, location_order)[rows]
    order = np.lexsort((transfers.rank[rows], location, bins))
    rows, bins, location = rows[order], bins[order], location[order]
    columns = statistics_columns(
        transfers.start[rows], transfers.end[rows], transfers.size[rows]
    )
    local = bins.astype(np.int64) * (int(location.max()) + 1) + location
    for name in ("totals", *groups):
        if name == "totals":
            codes = np.zeros(len(rows), np.intp)
        else:
            codes = transfers.codes[_KEYS[name]][rows]
        width = int(codes.max()) + 1
        first, partial = merge_columns(columns, local * width + codes)
        # Partial results ascend by (bin, location, key), so each (bin, key)
        # merges its locations in order.
        second, merged = merge_columns(
            partial, bins[first].astype(np.int64) * width + codes[first]
        )
        first = first[second]
        order = np.argsort(first)
        first = first[order]
        records = zip(
            bins[first].tolist(), codes[first].tolist(), merged.T[order].tolist()
        )
        if name == "totals":
            for index, _, values in records:
                results[index]["totals"] = statistics_record(values)
        else:
            keys = transfers.values[_KEYS[name]]
            for index, code, values in records:
                results[index]["groups"][name].append(
                    statistics_record(values, key=keys[code])
                )
    return results


def summarize_transfers(transfers, start, end, location_order=()):
    """Port the native sender-location accumulation then worker group merge."""
    if not all(math.isfinite(value) for value in (start, end)) or end < start:
        raise ValueError("Invalid message-summary window or clock resolution")
    if start == end:
        return dict(groups={name: [] for name in GROUPS}, totals=dict(count=0))
    rows = np.flatnonzero((start <= transfers.start) & (transfers.start <= end))
    return bin_summaries(
        transfers, rows, np.zeros(len(rows), np.intp), 1, location_order
    )[0]


def native_message_summary(trace, q):
    """Native summary contract over proven MPI/RMA emissions."""
    source = native_transfer_records(trace, q)
    resolution = source["resolution"]
    result = summarize_transfers(
        source["transfers"], source["startTick"], source["endTick"], trace.locations
    )
    # Convert only after native tick-domain construction and reduction.
    for rows in result["groups"].values():
        for row in rows:
            _seconds_record(row, resolution)
    _seconds_record(result["totals"], resolution)
    result.update(
        start=source["start"],
        end=source["end"],
        clockResolution=str(resolution),
        callsites=source["callsites"],
        diagnostics=source["diagnostics"],
        semantics=dict(
            selection="Transfer starts in the closed selected interval; an empty window returns no records.",
            durations="Full transfer lifetimes, with negative or unordered duration clamped to zero.",
            ownership="Sender location; receiverLocations applies a separate peer filter.",
            rate="Bytes per second. A zero-duration transfer uses one recorded clock tick.",
            provenance="Proven native MPI bounds and completed RMA transfers; original raw records remain unchanged.",
            totals="Viewer total across the same selected records; native replies expose the five grouped summaries.",
        ),
    )
    return result
