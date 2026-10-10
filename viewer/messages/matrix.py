"""Recovered CommunicationMatrix worker over normalized native transfers.

The native reducer selects transfer starts, aggregates actual location pairs,
then maps every pair to all matching requested groups. LocationSummary ranges
describe the actual pairs before that mapping. See binary-query-contracts.md.
"""

from __future__ import annotations

import collections
import json
import math

import numpy as np

from .statistics import (
    _seconds_record,
    merge_columns,
    merge_statistics,
    statistics_columns,
    statistics_record,
)
from .transfers import native_transfer_records

METRICS = (
    "count",
    "duration.sum",
    "duration.minimum",
    "duration.maximum",
    "duration.mean",
    "bytes.sum",
    "bytes.minimum",
    "bytes.maximum",
    "bytes.mean",
    "rate.minimum",
    "rate.maximum",
    "rate.aggregate",
)


def _groups(raw, locations):
    """Expand viewer group members; native membership uses closed index ranges."""
    if raw is None:
        return [dict(id=str(loc), locations=[str(loc)]) for loc in locations]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise ValueError("Matrix groups must be a JSON list") from error
    if not isinstance(raw, (list, tuple)):
        raise ValueError("Matrix groups must be a list")
    result, seen = [], set()
    for group in raw:
        if (
            not isinstance(group, dict)
            or not isinstance(group.get("id"), (str, int))
            or isinstance(group["id"], bool)
            or str(group["id"]) == ""
        ):
            raise ValueError("Each matrix group needs a string or integer id")
        ident = str(group["id"])
        if ident in seen:
            raise ValueError("Matrix group ids must be unique on each axis")
        seen.add(ident)
        members = group.get("locations")
        if not isinstance(members, (list, tuple)) or any(
            not isinstance(loc, (str, int)) or isinstance(loc, bool) for loc in members
        ):
            raise ValueError("Matrix group locations must be a list of references")
        entry = dict(
            id=ident, locations=list(dict.fromkeys(str(loc) for loc in members))
        )
        if "name" in group:
            entry["name"] = str(group["name"])
        result.append(entry)
    return result


def _memberships(groups):
    result = collections.defaultdict(list)
    for group in groups:
        for loc in group["locations"]:
            result[loc].append(group["id"])
    return result


def _axis_groups(trace, q, axis):
    raw = q.get(axis + "Groups")
    if raw is not None:
        return _groups(raw, trace.locations), dict(mode="explicit")
    selected = q.get("locations" if axis == "sender" else "receiverLocations")
    selected = set(selected.split(",")) if selected else None
    locations = [loc for loc in trace.locations if selected is None or loc in selected]
    size, maximum = 1, None
    for key in ("groupSize", "maxGroups"):
        if q.get(key) not in (None, ""):
            try:
                value = int(q[key])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    "Matrix group sizes must be positive integers"
                ) from error
            if isinstance(q[key], bool) or str(value) != str(q[key]) or value < 1:
                raise ValueError("Matrix group sizes must be positive integers")
            if key == "groupSize":
                size = value
            else:
                maximum = value
    if maximum:
        size = max(size, (len(locations) + maximum - 1) // maximum)
    names = {str(row["id"]): row["name"] for row in trace.meta.get("groups", [])}

    def label(loc):
        info = trace.locations[loc]
        group = names.get(str(info.get("group")), "")
        return (
            f"{group} · {info['name']} [{loc}]"
            if group
            else f"{info.get('name', 'Location')} [{loc}]"
        )

    groups = []
    for start in range(0, len(locations), size):
        members = locations[start : start + size]
        name = (
            label(members[0])
            if len(members) == 1
            else f"{label(members[0])} … {label(members[-1])} ({len(members)} locations)"
        )
        groups.append(
            dict(
                id=members[0] if size == 1 else f"group:{start // size}",
                locations=members,
                name=name,
            )
        )
    return groups, dict(
        mode="singletons" if size == 1 else "contiguous-recorded-order",
        groupSize=size,
        maxGroups=maximum,
        locations=len(locations),
        groups=len(groups),
    )


def _values(stats):
    duration, amount, count = stats["duration"], stats["bytes"], stats["count"]
    return (
        float(count),
        duration["sum"],
        duration["minimum"],
        duration["maximum"],
        duration["sum"] / count if count else 0,
        amount["sum"],
        amount["minimum"],
        amount["maximum"],
        amount["sum"] / count if count else 0,
        stats["rate"]["minimum"],
        stats["rate"]["maximum"],
        amount["sum"] / duration["sum"] if duration["sum"] else amount["sum"],
    )


def _seconds_value(metric, value, resolution):
    """The 1-based METRICS value in seconds: durations divide, rates multiply."""
    if 2 <= metric <= 5:
        return value / resolution
    return value * resolution if 10 <= metric <= 12 else value


def matrix_transfers(
    transfers,
    start,
    end,
    *,
    sender_groups=None,
    receiver_groups=None,
    location_order=(),
):
    """Port f33300/13cc0d0 in native double ticks and bytes per tick.

    This pure reducer does not clip lifetimes. The serial ordering follows
    location_order and retained emission sequence for tied transfer starts;
    native distributed/hash-map merge order is not claimed bitwise equivalent.
    """
    if not all(math.isfinite(value) for value in (start, end)) or end < start:
        raise ValueError("Invalid native matrix window")
    locations = list(
        dict.fromkeys([str(loc) for loc in location_order] + transfers.endpoints())
    )
    senders, receivers = _groups(sender_groups, locations), _groups(
        receiver_groups, locations
    )
    source_groups, target_groups = _memberships(senders), _memberships(receivers)
    order = {loc: index for index, loc in enumerate(locations)}
    sources, source_names = transfers.recode("sender", str)
    targets, target_names = transfers.recode("receiver", str)
    # Recorded order of each grouped sender; -1 excludes ungrouped senders.
    source_order = np.array(
        [order[name] if name in source_groups else -1 for name in source_names],
        np.intp,
    )[sources]
    grouped = np.array([name in target_groups for name in target_names], bool)
    rows = np.flatnonzero(
        (source_order >= 0)
        & grouped[targets]
        & (start <= transfers.start)
        & (transfers.start <= end)
    )
    rows = rows[np.lexsort((transfers.rank[rows], source_order[rows]))]
    first, merged = merge_columns(
        statistics_columns(
            transfers.start[rows], transfers.end[rows], transfers.size[rows]
        ),
        source_order[rows].astype(np.int64) * len(target_names) + targets[rows],
    )
    # Each source's pairs in the order their targets first occur.
    ordered = np.argsort(first)
    pairs = rows[first[ordered]]
    cells, ranges, totals = {}, {}, None
    for source, target, values in zip(
        sources[pairs].tolist(), targets[pairs].tolist(), merged.T[ordered].tolist()
    ):
        stats = statistics_record(values)
        totals = merge_statistics(totals, stats)
        for metric, value in enumerate(_values(stats), 1):
            if metric not in ranges:
                ranges[metric] = dict(
                    metric=metric,
                    name=METRICS[metric - 1],
                    minimum=value,
                    maximum=value,
                )
            bound = ranges[metric]
            # Match the ordered native comparisons, including NaN.
            if not bound["minimum"] <= value:
                bound["minimum"] = value
            if not value <= bound["maximum"]:
                bound["maximum"] = value
        for sender in source_groups[source_names[source]]:
            for receiver in target_groups[target_names[target]]:
                key = (sender, receiver)
                cells[key] = merge_statistics(cells.get(key), stats)
    return dict(
        cells=[
            dict(source=source, target=target, **stats)
            for (source, target), stats in cells.items()
        ],
        senderGroups=senders,
        receiverGroups=receivers,
        locationSummary=list(ranges.values()),
        totals=totals or dict(count=0),
        locationPairs=len(pairs),
    )


def native_communication_matrix(trace, q):
    """API-neutral native matrix; existing raw MPI matrix remains independent.

    Accepts native transfer-summary filters and optional senderGroups /
    receiverGroups lists (or JSON strings), each {id, locations, name?}.
    Group membership and location filters intersect. Omitted axes use recorded
    singleton locations; overlapping groups intentionally duplicate cells.
    """
    senders, sender_grouping = _axis_groups(trace, q, "sender")
    receivers, receiver_grouping = _axis_groups(trace, q, "receiver")
    source = native_transfer_records(trace, q, point_window=True)
    result = matrix_transfers(
        source["transfers"],
        source["startTick"],
        source["endTick"],
        sender_groups=senders,
        receiver_groups=receivers,
        location_order=trace.locations,
    )
    resolution = source["resolution"]
    for cell in result["cells"]:
        # Compute displayed means/aggregate rate from the grouped scalar
        # record in ticks; never average location-pair means.
        cell["values"] = {
            name: _seconds_value(metric, value, resolution)
            for metric, (name, value) in enumerate(zip(METRICS, _values(cell)), 1)
        }
        _seconds_record(cell, resolution)
    _seconds_record(result["totals"], resolution)
    for row in result["locationSummary"]:
        for field in ("minimum", "maximum"):
            row[field] = _seconds_value(row["metric"], row[field], resolution)
    result.update(
        start=source["start"],
        end=source["end"],
        clockResolution=str(resolution),
        grouping=dict(sender=sender_grouping, receiver=receiver_grouping),
        diagnostics=source["diagnostics"],
        semantics=dict(
            selection="Transfer starts in the closed selected interval, including an exact-time window.",
            durations="Full transfer lifetimes; negative or unordered duration is clamped to zero.",
            units="Seconds, bytes, and bytes per second. Zero-duration rates use one recorded clock tick.",
            groups="Each location pair contributes to every matching sender/receiver group combination.",
            locationSummary="Ranges over actual location-pair statistics before group aggregation.",
            totals="Viewer reduction of unique selected transfers; overlapping cells must not be summed.",
            provenance="Proven native MPI emissions and completed RMA transfers; raw records remain unchanged.",
            ordering="Serial recorded-location order; native distributed reduction order is not reproduced.",
        ),
    )
    return result
