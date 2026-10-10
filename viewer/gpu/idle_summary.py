"""Native IdleSummary activity union and accelerator grouping.

The recovered query consumes StateStack/StateTree activity, not message or RMA
lifetimes. See docs/binary-idle-summary.md for producer contracts and limits.
"""

from __future__ import annotations

import collections
import math


def interval_union(intervals, start, end):
    """Clip, sort and merge touching intervals (native 0x1409170/0x1409720)."""
    merged = []
    for a, b in sorted((max(start, a), min(end, b)) for a, b in intervals):
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _summary(intervals, start, end):
    intervals = interval_union(intervals, start, end)
    duration = end - start
    active = sum(b - a for a, b in intervals)
    idle = max(0.0, duration - active)
    return dict(
        active=active,
        idle=idle,
        duration=duration,
        idlePercentage=100 * idle / duration if duration else None,
        intervals=[list(pair) for pair in intervals],
    )


def aggregate_idle(activity, topology, start, end):
    """Aggregate selected locations with proven (context, device, host) keys.

    Context/device identifiers are scoped to the recorded shared-memory node.
    Every physical-device result is an interval union, never a mean of streams.
    """
    if not math.isfinite(start) or not math.isfinite(end) or end < start:
        raise ValueError("Invalid idle-statistics time interval")
    locations = []
    context_members = collections.defaultdict(list)
    device_members = collections.defaultdict(list)
    for loc, key in topology.items():
        intervals = activity.get(loc, ())
        locations.append(
            dict(location=loc, key=[-1, -1, loc], **_summary(intervals, start, end))
        )
        context_members[tuple(key)].append(loc)
        device_members[tuple(key[1:])].append(loc)

    def grouped(members, device=False):
        return [
            dict(
                key=[-1, *key] if device else list(key),
                locations=locs,
                **_summary(
                    (pair for loc in locs for pair in activity.get(loc, ())), start, end
                ),
            )
            for key, locs in members.items()
        ]

    return dict(
        locations=locations,
        contexts=grouped(context_members),
        devices=grouped(device_members, True),
    )


def stack_activity(records, selected, start, end, diagnostics):
    """Selected explicit Enter/Leave activity, excluding the native dummy root."""
    stack = []
    intervals = []
    previous = 0.0
    for row in records:
        t = row["time"]
        if t < previous:
            diagnostics["nonmonotonic-stack-time"] += 1
        previous = max(previous, t)
        ref = str(row["data"].get("region"))
        if ref not in selected:
            continue
        if row["kind"] == "Enter":
            stack.append((ref, t))
        elif stack:
            region, a = stack.pop()
            if region != ref:
                diagnostics["mismatched-stack-leave"] += 1
            intervals.append((a, t))
        else:
            diagnostics["unmatched-stack-leave"] += 1
    # Native ea50a0 extends unfinished real frames to the request end.
    intervals.extend((a, end) for _, a in stack)
    return interval_union(intervals, start, end)


def tree_activity(
    records, definitions, selected, start, end, diagnostics, event_mode=0
):
    """Union selected post-record CallingContext stacks, including samples.

    EventMode 0 accepts all kinds, 1 excludes ordinary samples, 2 accepts samples
    and their undefined-context resets. A reset has native kind 0 and remains
    visible in mode 1 as well.
    A Leave removes its recorded leaf; unwindDistance is not this consumer's
    chain source. Local timestamps follow the native producer's monotone clamp.
    """
    if event_mode not in (0, 1, 2):
        raise ValueError("Invalid calling-context event mode")

    def normalized():
        chains = {}
        previous = 0.0
        for row in records:
            t = max(previous, row["time"])
            previous = t
            kind = row["kind"]
            ref = str(row["data"].get("callingContext"))
            native_kind = (
                (0 if ref == "4294967295" else 1)
                if kind == "CallingContextSample"
                else 3 if kind == "CallingContextLeave" else 2
            )
            if (
                event_mode == 1
                and native_kind == 1
                or event_mode == 2
                and native_kind >= 2
            ):
                continue
            if ref not in chains:
                current = ref
                seen = set()
                chain = []
                while current in definitions and current not in seen:
                    seen.add(current)
                    definition = definitions[current]
                    chain.append((current, str(definition.get("region"))))
                    current = str(definition.get("parent"))
                if current in seen:
                    diagnostics["cyclic-calling-context"] += 1
                if not chain and ref != "4294967295":
                    diagnostics["missing-calling-context"] += 1
                chains[ref] = tuple(reversed(chain))
            yield dict(native_time=t, kind=native_kind, chain=chains[ref])

    return finalized_tree_activity(normalized(), selected, start, end)


def finalized_tree_activity(records, selected, start, end, event_mode=0):
    """Consume shared normalized Tree records, including native closing leaves.

    The interval union remains in native clock ticks until after all device
    grouping, retaining one-tick tails even at large relative timestamps.
    """
    intervals = []
    active_since = None
    for row in records:
        kind = row["kind"]
        if event_mode == 1 and kind == 1 or event_mode == 2 and kind >= 2:
            continue
        t = row["native_time"]
        chain = row["chain"][:-1] if kind == 3 else row["chain"]
        active = any(str(region) in selected for _, region in chain)
        if active_since is not None and not active:
            intervals.append((active_since, t))
            active_since = None
        elif active and active_since is None:
            active_since = t
    if active_since is not None:
        intervals.append((active_since, end))
    return interval_union(intervals, start, end)


def idle_summary(trace, q):
    """Recorded accelerator state activity using the native IdleSummary math.

    Query keys follow the viewer's start/end, locations, region/exclude/group
    filters. eventMode optionally selects all(0), explicit(1), or samples(2).
    A CallingContext definition selects StateTree for the entire session,
    including locations whose Tree contains only the native dummy root.
    """
    from ..dependencies.device import _device

    start, end, _, _ = trace.scope(q, regions=False)
    event_mode = int(q.get("eventMode", 0))
    if event_mode not in (0, 1, 2):
        raise ValueError("Invalid calling-context event mode")
    requested = set(q["locations"].split(",")) if q.get("locations") else set()
    include = q.get("region", "").casefold()
    exclude = q.get("exclude", "").casefold()
    group = q.get("group", "")
    selected = {
        ref
        for ref, r in trace.regions.items()
        if (not include or include in r.get("name", "").casefold())
        and (not exclude or exclude not in r.get("name", "").casefold())
        and (not group or group == r.get("group"))
    }
    topology = {}
    devices = {}
    diagnostics = collections.Counter()
    producers = {}
    activity = {}
    session_tree = bool(trace.defs.get("CallingContext"))
    for loc, definition in trace.locations.items():
        if (
            definition.get("type") != "ACCELERATOR_STREAM"
            or requested
            and loc not in requested
        ):
            continue
        device = _device(trace, loc)
        topo = device["topology"]
        if device["confidence"] == "recorded-system-tree-domains":
            key = (topo["contextNode"], topo["deviceNode"], topo["sharedMemoryNode"])
        elif device["confidence"] == "producer-name-and-recorded-domain":
            key = (
                topo["legacyContextId"],
                topo["legacyDeviceOrdinal"],
                topo["sharedMemoryNode"],
            )
        else:
            diagnostics["unverified-device-topology"] += 1
            continue
        topology[loc] = key
        devices[key[1:]] = device
    from ..metrics.state_records import StateRecordStore

    store = StateRecordStore(trace)
    native_start, native_end = start * store.resolution, end * store.resolution
    for loc in topology:
        producers[loc] = "StateTree" if session_tree else "StateStack"
        if session_tree:
            activity[loc] = finalized_tree_activity(
                store.tree(loc), selected, native_start, native_end, event_mode
            )
        else:
            rows, issues = store.stack(loc)
            diagnostics.update(issues)
            stack_rows = [
                dict(
                    time=row["native_time"],
                    kind=row["kind"],
                    data=dict(region=row["region"]),
                )
                for row in rows
            ]
            activity[loc] = stack_activity(
                stack_rows, selected, native_start, native_end, collections.Counter()
            )
    diagnostics.update(store.diagnostics)
    result = aggregate_idle(activity, topology, native_start, native_end)
    for rows in (result["locations"], result["contexts"], result["devices"]):
        for row in rows:
            for field in ("duration", "active", "idle"):
                row[field] /= store.resolution
            row["intervals"] = [
                [a / store.resolution, b / store.resolution]
                for a, b in row["intervals"]
            ]
    for row in result["devices"]:
        device = devices[tuple(row["key"][1:])]
        row.update(id=device["id"], name=device["name"])
    result.update(
        start=start,
        end=end,
        eventMode=event_mode,
        producers=producers,
        sessionProducer="StateTree" if session_tree else "StateStack",
        source="native-state-activity-union",
        diagnostics=[dict(code=k, count=v) for k, v in sorted(diagnostics.items())],
        interpretation="Selected recorded function activity; idle is its complement in the selected window. RMA and message lifetimes are not inputs.",
    )
    return result
