"""Align location scopes and reduce their descendant signals."""

import collections

from .pixels import merge_pixels, pixel_reduce, source_properties
from .series import Data, Series
from .values import reduce_values, reducer_valid


def group_key(ctx, loc, scope):
    if scope == "all":
        return "all", "All selected locations"
    group = str(ctx.trace.locations[loc].get("group", ""))
    if scope == "group":
        return "group:" + group, ctx.groups.get(group, {}).get("name", "Group " + group)
    if scope != "system":
        raise ValueError("Aggregation scope must be all, group or system")
    node = str(ctx.groups.get(group, {}).get("parent", ""))
    target_class = ctx.q.get("systemClass", "")
    seen = set()
    while node in ctx.nodes and node not in seen:
        seen.add(node)
        info = ctx.nodes[node]
        if not target_class or info.get("className") == target_class:
            return "system:" + node, info.get("name", node)
        node = str(info.get("parent", ""))
    return "group:" + group, ctx.groups.get(group, {}).get("name", "Group " + group)


def members_of(ctx, data, key):
    return data.members.get(key, ctx.members.get(key, frozenset()))


def scope_depth(ctx, key):
    if key in ctx.locations:
        return (3, 0)
    if key.startswith("group:"):
        return (2, 0)
    if key.startswith("system:"):
        node = key[7:]
        seen = set()
        while node in ctx.nodes and node not in seen:
            seen.add(node)
            node = str(ctx.nodes[node].get("parent", ""))
        return (1, len(seen))
    return (0, 0)


def target_keys(ctx, datasets):
    selected = [data for data in datasets if not data.literal] or datasets
    keys = list(dict.fromkeys(key for data in selected for key in data.series))
    members = {
        key: frozenset().union(
            *(members_of(ctx, data, key) for data in selected if key in data.series)
        )
        for key in keys
    }
    # Broadcast ancestor aggregates to descendant results when combining scopes.
    return [
        (key, members[key])
        for key in keys
        if not any(
            members[other] < members[key]
            or members[other] == members[key]
            and scope_depth(ctx, other) > scope_depth(ctx, key)
            for other in keys
            if other != key
        )
    ]


def corresponding(ctx, data, key, members):
    if data.literal and data.series:
        return next(iter(data.series.values()))
    if key in data.series:
        return data.series[key]
    candidates = [
        k for k in data.series if members and members <= members_of(ctx, data, k)
    ]
    return (
        data.series[min(candidates, key=lambda k: len(members_of(ctx, data, k)))]
        if candidates
        else Series([])
    )


def aggregate(ctx, data, reducer="sum", scope="all"):
    reducer = reducer_valid(reducer)
    groups = collections.defaultdict(list)
    for key, series in data.series.items():
        descendants = members_of(ctx, data, key)
        group_targets = {group_key(ctx, loc, scope) for loc in descendants}
        if len(group_targets) > 1:
            raise ValueError(
                "Cannot split an already-aggregated series; aggregate original location data instead"
            )
        for target, name in group_targets:
            groups[target].append((key, series))
            ctx.names[target] = name
    output = {}
    output_members = {}
    for target, inputs in groups.items():
        output_members[target] = frozenset().union(
            *(members_of(ctx, data, key) for key, _ in inputs)
        )
        if reducer in ("sum", "mean", "min", "max"):
            # b46550 promotes a one-pixel hierarchy child to 1000 pixels;
            # the enclosing/output request retains its original width.
            bins = 1000 if ctx.bins == 1 else ctx.bins
            ctx.charge(sum(len(series.points) + bins for _, series in inputs))
            pixels = merge_pixels(
                pixel_reduce(
                    series,
                    ctx.timeline_start,
                    ctx.timeline_end,
                    bins,
                    flags=series.flags,
                    source_id=ctx.output.pixel_source(key, members_of(ctx, data, key)),
                )
                for key, series in inputs
            )
            # The native hierarchy feeds these pixel-left timestamp/value
            # pairs back through SignalSourceCustom before outer operators.
            points = [(p.start, p.select_hierarchy(reducer)) for p in pixels]
            output[target] = Series(
                points, pixels=pixels, flags=0x200 | source_properties(points)
            )
            ctx.output.record_pixels(
                target, output_members[target], pixels, "hierarchy", reducer
            )
            continue
        times = sorted(
            {t for _, series in inputs for t, _ in series.points} | {ctx.start, ctx.end}
        )
        ctx.charge(len(times) * len(inputs))
        observed = set().union(*(series.observed for _, series in inputs))
        interpolation = (
            "linear"
            if all(
                series.interpolation in ("linear", "constant") for _, series in inputs
            )
            else "previous"
        )
        output[target] = Series(
            [
                (t, reduce_values([series.at(t) for _, series in inputs], reducer))
                for t in times
            ],
            interpolation,
            observed=observed,
        )
    unit = (
        "count"
        if reducer == "count"
        else data.unit + "²" if reducer == "variance" and data.unit else data.unit
    )
    return Data(output, unit, members=output_members)
