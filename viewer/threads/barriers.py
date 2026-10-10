"""Replay the statically recovered OTF2 thread-barrier operation boundaries.

This is the reader's operation stream, not an inferred blocking-time model.
See docs/binary-thread-barriers.md for the inspected paths and limitations.
"""

import collections
import json

from ..mpi.communicators import Communicators


def native_barriers(
    trace,
    spans=None,
    diagnostics=None,
    *,
    tick_domain=False,
    charge=lambda work: None,
    include_regions=True
):
    """Replay all thread operations when spans is None, or associate given spans.

    The full replay is also a source for the native state-finalization boundary.
    Its clock-tick option converts original relative timestamps before replay.
    ``include_regions=False`` replays only team control events, for producer
    transitions such as a non-primary TeamEnd. It omits operation ordinals and
    counts because skipped barrier records could change those values.
    """
    if not include_regions and spans is not None:
        raise ValueError("Control-only team replay cannot associate region spans")
    if diagnostics is None:
        diagnostics = collections.Counter()
    candidates = [
        s for s in (spans or ()) if s.category in ("openmp_barrier", "thread_barrier")
    ]
    joins = [s for s in (spans or ()) if s.category == "thread_join"]
    if spans is not None and not candidates and not joins:
        return dict(by_span={}, operations=[], counts={})
    definitions = trace.defs
    classes = {3: 1}  # OPENMP's predefined fork/join paradigm class.
    classes.update(
        {
            int(d["paradigm"]): d["paradigmClass"]
            for d in definitions.get("Paradigm", {}).values()
        }
    )
    barrier_regions = {
        ref: d.get("paradigm")
        for ref, d in definitions.get("Region", {}).items()
        if d.get("regionRole") in (15, 16) and classes.get(d.get("paradigm")) == 1
    }
    if spans is None or joins:
        with trace.connect() as db:
            locations = [
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT location FROM events WHERE kind='ThreadTeamBegin'"
                )
            ]
    else:
        locations = sorted(
            {s.location for s in candidates if s.region in barrier_regions}
        )
    if not locations:
        return dict(by_span={}, operations=[], counts={})
    span_keys = collections.defaultdict(collections.deque)
    for s in sorted(candidates, key=lambda s: (s.start, s.depth, s.id)):
        span_keys[(s.location, s.start, s.region)].append(s)
    resolver = Communicators(definitions)
    sequences = collections.Counter()
    epochs = collections.Counter()
    operations = []
    by_span = {}
    current_location = None
    # The reader uses one location field (+0x150) for a pending fork or join.
    teams = []
    frames = []
    lifecycle_time = None
    lifecycle_event = None

    def valid_paradigm(location, paradigm):
        world = resolver.world(paradigm)
        members = resolver.world_members(world)
        identity = (
            resolver.request_scope(location)
            if world.get("groupType") == 7
            else location
        )
        if identity not in members:
            diagnostics["native_thread_paradigm_membership_invalid"] += 1
            return False
        return True

    def emit(operation, team, location, start, end, event, span=None, boundary=None):
        key = (location, team["comm"])
        sequence = sequences[key]
        sequences[key] += 1
        item = dict(
            operation=operation,
            comm=team["comm"],
            location=location,
            sequence=sequence if include_regions else None,
            teamInvocation=team["epoch"],
            start=start,
            end=end,
            event=event,
            teamBeginEvent=team["event"],
            teamBeginTime=team["time"],
            primary=team["primary"],
            paradigm=team["paradigm"],
        )
        if span is not None:
            item.update(
                span=span.id,
                boundaryEvent=boundary,
                routineStart=span.start,
                routineEnd=span.end,
                sampled=bool(span.sampled),
                incomplete=bool(span.incomplete),
            )
            by_span[span.id] = item
        operations.append(item)

    def enter(location, time, region, event):
        region = str(region)
        queue = span_keys.get((location, time, region))
        frame = dict(
            region=region, span=queue.popleft() if queue else None, event=event
        )
        frames.append(frame)
        if not teams:
            return
        team = teams[-1]
        if region in barrier_regions and barrier_regions[region] != team["paradigm"]:
            team["pending"] = None
            diagnostics["native_barrier_paradigm_mismatch"] += 1
        elif region in barrier_regions or team["pending"] is not None:
            team["pending"] = (time, event)

    def leave(location, time, region, event):
        if not frames:
            diagnostics["native_barrier_region_nesting_invalid"] += 1
            return
        frame = frames.pop()
        region = frame["region"] if region is None else str(region)
        if frame["region"] != region:
            diagnostics["native_barrier_region_nesting_invalid"] += 1
            if teams:
                teams[-1]["pending"] = None
            return
        if not teams:
            return
        team = teams[-1]
        if region in barrier_regions:
            if barrier_regions[region] != team["paradigm"]:
                diagnostics["native_barrier_paradigm_mismatch"] += 1
            elif team["pending"] is None:
                diagnostics["native_barrier_entry_missing"] += 1
            else:
                start, boundary = team["pending"]
                emit(
                    "BARRIER",
                    team,
                    location,
                    start,
                    time,
                    event,
                    frame["span"],
                    boundary,
                )
                operations[-1]["entryEvent"] = frame["event"]
                team["pending"] = None
        elif team["pending"] is not None:
            team["pending"] = (time, event)

    kinds = ("ThreadFork", "ThreadJoin", "ThreadTeamBegin", "ThreadTeamEnd")
    if include_regions:
        kinds = (
            "Enter",
            "Leave",
            "CallingContextEnter",
            "CallingContextLeave",
            "CallingContextSample",
            *kinds,
        )
    marks = ",".join("?" for _ in locations)
    kind_marks = ",".join("?" for _ in kinds)
    # Stream every relevant event. A cap would silently change operation ordinals.
    with trace.connect() as db:
        sql = (
            "SELECT id,location,time,kind,CASE WHEN kind IN ('Enter','Leave') THEN json_extract(data,'$.region') ELSE data END payload,tick FROM events WHERE location IN ("
            + marks
            + ") AND kind IN ("
            + kind_marks
            + ") ORDER BY location,"
            + ("id" if tick_domain else "time,id")
        )
        for row in db.execute(sql, locations + list(kinds)):
            charge(1)
            event, location, time, kind, payload, tick = tuple(row)
            if tick_domain:
                try:
                    time = float(
                        (int(tick) - int(trace.meta["clock"]["offset"]))
                        & 0xFFFFFFFFFFFFFFFF
                    )
                except (ValueError, TypeError, KeyError):
                    time *= int(trace.meta.get("clock", {}).get("resolution", 1))
                    diagnostics["missing-original-clock-ticks"] += 1
            if location != current_location:
                current_location = location
                teams = []
                frames = []
                lifecycle_time = None
                lifecycle_event = None
            if kind == "Enter":
                enter(location, time, payload, event)
                continue
            if kind == "Leave":
                leave(location, time, payload, event)
                continue
            data = json.loads(payload)
            if kind == "ThreadFork":
                if not valid_paradigm(location, data.get("model")):
                    continue
                if lifecycle_time is not None:
                    diagnostics["native_thread_fork_reused"] += 1
                else:
                    lifecycle_time = time
                    lifecycle_event = event
            elif kind == "ThreadTeamBegin":
                comm = str(data["threadTeam"])
                definition = definitions.get("Comm", {}).get(comm, {})
                group = resolver.group(definition.get("group"))
                members = resolver.members(definition.get("group"))
                if not valid_paradigm(location, group.get("paradigm")):
                    continue
                if not members or location not in members:
                    diagnostics["native_thread_team_membership_invalid"] += 1
                    continue
                primary = members[0]
                if location == primary and lifecycle_time is None:
                    diagnostics["native_thread_fork_missing"] += 1
                    continue
                epoch = epochs[(location, comm)]
                epochs[(location, comm)] += 1
                team = dict(
                    comm=comm,
                    paradigm=group.get("paradigm"),
                    primary=primary,
                    epoch=epoch,
                    event=event,
                    time=time,
                    pending=None,
                )
                teams.append(team)
                emit(
                    "FORK",
                    team,
                    location,
                    lifecycle_time if location == primary else time,
                    time,
                    event,
                )
                if location == primary:
                    lifecycle_time = None
                    lifecycle_event = None
            elif kind == "ThreadTeamEnd":
                if not teams or teams[-1]["comm"] != str(data["threadTeam"]):
                    diagnostics["native_thread_team_end_invalid"] += 1
                    continue
                team = teams[-1]
                if location == team["primary"]:
                    if lifecycle_time is not None:
                        diagnostics["native_thread_team_end_reused"] += 1
                    else:
                        lifecycle_time = time
                        lifecycle_event = event
                else:
                    emit("JOIN", teams.pop(), location, time, time, event)
            elif kind == "ThreadJoin":
                if not valid_paradigm(location, data.get("model")):
                    continue
                if not teams:
                    diagnostics["native_thread_join_missing_team_end"] += 1
                    continue
                team = teams.pop()
                if lifecycle_time is None:
                    diagnostics["native_thread_join_missing_team_end"] += 1
                    continue
                emit("JOIN", team, location, lifecycle_time, time, event)
                operations[-1]["boundaryEvent"] = lifecycle_event
                lifecycle_time = None
                lifecycle_event = None
            elif kind != "CallingContextSample":
                # The native adapter forwards unwindDistance, but the region
                # body ignores it: only explicit leaf Enter/Leave changes this
                # stack. Samples update a separate StateTree record stream.
                context = definitions.get("CallingContext", {}).get(
                    str(data.get("callingContext"))
                )
                if context is None:
                    diagnostics["native_barrier_context_unknown"] += 1
                    continue
                if kind == "CallingContextEnter":
                    enter(location, time, context["region"], event)
                else:
                    leave(location, time, context["region"], event)
    return dict(
        by_span=by_span,
        operations=operations,
        counts=dict(sequences) if include_regions else {},
    )
