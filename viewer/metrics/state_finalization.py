"""Native full-read state-finalizer input range (worker 0xf20300).

This is the union of accepted counter, collective, I/O and transfer stores.
State events and ClockProperties.traceLength do not directly set this seed.
"""

import collections
import json
import math

from ..mpi.communicators import Communicators
from ..threads.barriers import native_barriers
from ..threads.lifecycle import native_thread_lifecycle


def native_state_end_seed(trace, charge=lambda work: None, limit=10_000_000):
    """Return the complete session's finalization seed in original clock ticks.

    ``endTicks`` is -1 when no accepted backend has a range. ``end`` is the
    corresponding seconds value, including that negative one-tick sentinel.
    SQL extrema avoid decoding full counter/message streams. Stateful thread
    and collective replay is bounded by ``limit`` and charged to the caller.
    """
    if limit < 1:
        raise ValueError("State finalization replay limit must be positive")
    clock = trace.meta.get("clock", {})
    resolution, offset = int(clock.get("resolution", 1)), int(clock.get("offset", 0))
    if resolution <= 0:
        raise ValueError("Invalid recorded clock resolution")
    diagnostics = collections.Counter()
    ranges = {
        name: dict(endTicks=None) for name in ("counter", "collective", "io", "message")
    }
    work = 0
    replay_threads = True

    def account(count=1):
        nonlocal work
        work += count
        if work > limit:
            raise ValueError("State finalization replay exceeds the event limit")
        charge(count)

    def tick(raw, fallback):
        try:
            return float((int(raw) - offset) & 0xFFFFFFFFFFFFFFFF)
        except (TypeError, ValueError, OverflowError):
            diagnostics["missing-original-clock-ticks"] += 1
            return float(fallback) * resolution

    def include(family, value):
        if value is None:
            return
        if not math.isfinite(value):
            diagnostics["nonfinite-source-range"] += 1
            return
        previous = ranges[family]["endTicks"]
        ranges[family]["endTicks"] = value if previous is None else max(previous, value)

    with trace.connect() as db:
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if trace.meta.get("format") == "OTF" and any(
            name in tables and db.execute(f"SELECT 1 FROM {name} LIMIT 1").fetchone()
            for name in ("messages", "collectives", "io")
        ):
            diagnostics["otf1-operation-seed-unverified"] += 1

        def maximum(
            family,
            source,
            where="1",
            args=(),
            *,
            raw="e.tick",
            seconds="e.time",
            extra=0,
        ):
            # Original uint64 ticks can exceed SQLite's signed INTEGER range.
            # Fixed-width decimal text preserves their integer ordering without
            # casting the absolute timestamp to a low-precision REAL.
            valid = f"({raw} IS NOT NULL AND {raw}<>'' AND {raw} NOT GLOB '*[^0-9]*')"
            row = db.execute(
                f"""SELECT MAX(CASE WHEN {valid} THEN printf('%020s',{raw}) END),
                 MAX(CASE WHEN NOT {valid} THEN {seconds} END)
                 FROM {source} WHERE {where}""",
                args,
            ).fetchone()
            account()
            values = []
            if row[0] is not None:
                values.append(tick(row[0].strip(), None) + extra)
            if row[1] is not None:
                diagnostics["missing-original-clock-ticks"] += 1
                values.append(row[1] * resolution + extra)
            value = max(values, default=None)
            if family is not None:
                include(family, value)
            return value

        # Counter definition order is irrelevant to the max timestamp, but a
        # class must resolve at least one recorded value to a known member.
        members = trace.defs.get("MetricMember", {})
        classes = {}
        for ref, definition in trace.defs.get("MetricClass", {}).items():
            first = next(
                (
                    i
                    for i, member in enumerate(definition.get("metricMembers", ()))
                    if str(member) in members
                ),
                None,
            )
            if first is not None:
                classes[str(ref)] = first
        for ref, definition in trace.defs.get("MetricInstance", {}).items():
            member_class = str(definition.get("metricClass"))
            if member_class in classes:
                classes[str(ref)] = classes[member_class]
        if classes:
            # Join values rather than emitting one OR clause per metric class.
            bindings = ",".join("(?,?)" for _ in classes)
            args = tuple(value for pair in classes.items() for value in pair)
            source = f"events e JOIN (SELECT column1 AS ref,column2 AS first FROM (VALUES {bindings})) c ON CAST(json_extract(e.data,'$.metric') AS TEXT)=c.ref"
            accepted = (
                "e.kind='Metric' AND json_array_length(e.data,'$.metricValues')>c.first"
            )
            # The kind/time index seeks the last accepted normalized time.
            # Inspect every original tick tied there: conversion to seconds
            # can collapse nearby integer timestamps but cannot reverse them.
            last = db.execute(
                f"SELECT e.time FROM {source} WHERE {accepted} ORDER BY e.time DESC LIMIT 1",
                args,
            ).fetchone()
            account()
            if last is not None:
                maximum("counter", source, accepted + " AND e.time=?", (*args, last[0]))
        if ranges["counter"]["endTicks"] is None and members and "metrics" in tables:
            marks = ",".join("?" for _ in members)
            fallback = db.execute(
                f"SELECT MAX(time) FROM metrics WHERE metric IN ({marks})",
                tuple(members),
            ).fetchone()[0]
            account()
            if fallback is not None:
                diagnostics["counter-range-without-original-events"] += 1
                include("counter", fallback * resolution)

        if "message_evidence" in tables:
            source = """messages m JOIN message_evidence p
                        ON p.send_event=m.send_event AND p.recv_event=m.recv_event
                        LEFT JOIN events e ON e.id=m.recv_event
                        LEFT JOIN events s ON s.id=m.send_event"""
            proven = "p.emitter IN ('send','receive') AND p.native_end IS NOT NULL AND m.source IS NOT NULL AND m.target IS NOT NULL"
            maximum("message", source, proven, seconds="p.native_end")
            # Only a send-side emitter moves the receive endpoint forward.
            # Relative double conversion and the +1 happen after SQL selection.
            inversion = "(length(s.tick)>length(e.tick) OR length(s.tick)=length(e.tick) AND s.tick>e.tick)"
            maximum(
                "message",
                source,
                proven + " AND p.emitter='send' AND " + inversion,
                raw="s.tick",
                seconds="m.start",
                extra=1,
            )
        if "rma_evidence" in tables:
            maximum(
                "message",
                """rma r JOIN rma_evidence p ON p.begin_event=r.event
                        LEFT JOIN events e ON e.id=p.completion_event""",
                "r.end IS NOT NULL AND p.completion_event IS NOT NULL AND p.native_source IS NOT NULL AND p.native_target IS NOT NULL",
                seconds="r.end",
            )

        if "io" in tables:
            proxy_handles = [
                ref
                for ref, d in trace.defs.get("IoHandle", {}).items()
                if d.get("ioHandleFlags", 0) & 2
            ]
            replay_io = False
            if proxy_handles:
                marks = ",".join("?" for _ in proxy_handles)
                replay_io = (
                    db.execute(
                        f"SELECT 1 FROM events WHERE kind='IoOperationCancelled' AND CAST(json_extract(data,'$.handle') AS TEXT) IN ({marks}) LIMIT 1",
                        proxy_handles,
                    ).fetchone()
                    is not None
                )
            if replay_io:
                _io_ends(trace, db, tick, include, diagnostics, account)
            else:
                maximum(
                    "io",
                    "io i JOIN events e ON e.id=i.event",
                    "i.status='complete' AND e.kind='IoOperationComplete'",
                    seconds="i.end",
                )
        _collective_ends(trace, db, tick, include, diagnostics, account)

        # A thread operation can only finish at one of these raw boundaries.
        # If every candidate precedes an already proven backend end, replay
        # cannot change the global seed. Avoid decoding millions of unrelated
        # Enter/Leave records merely to establish that dominance.
        classes = {3: 1}
        classes.update(
            {
                int(d["paradigm"]): d["paradigmClass"]
                for d in trace.defs.get("Paradigm", {}).values()
            }
        )
        regions = {
            ref
            for ref, d in trace.defs.get("Region", {}).items()
            if d.get("regionRole") in (15, 16) and classes.get(d.get("paradigm")) == 1
        }
        contexts = {
            ref
            for ref, d in trace.defs.get("CallingContext", {}).items()
            if str(d.get("region")) in regions
        }
        clauses = [
            "e.kind IN ('ThreadTeamBegin','ThreadTeamEnd','ThreadJoin','ThreadCreate','ThreadBegin','ThreadWait','ThreadEnd')"
        ]
        args = []
        for kind, field, refs in (
            ("Leave", "region", regions),
            ("CallingContextLeave", "callingContext", contexts),
        ):
            if refs:
                clauses.append(
                    f"(e.kind=? AND CAST(json_extract(e.data,'$.{field}') AS TEXT) IN ({','.join('?' for _ in refs)}))"
                )
                args.extend([kind, *refs])
        upper = maximum(None, "events e", " OR ".join(clauses), args)
        proven_ends = [
            row["endTicks"] for row in ranges.values() if row["endTicks"] is not None
        ]
        if upper is None or proven_ends and upper <= max(proven_ends):
            replay_threads = False
            ranges["collective"].update(
                threadUpperBoundTicks=upper,
                threadReplay="dominated" if upper is not None else "empty",
            )

    if replay_threads:
        thread_diagnostics = collections.Counter()
        for replay in (native_barriers, native_thread_lifecycle):
            result = replay(
                trace, diagnostics=thread_diagnostics, tick_domain=True, charge=account
            )
            for operation in result["operations"]:
                include("collective", operation["end"])
        # Both replayers share their diagnostic counter; merge after both.
        diagnostics.update(thread_diagnostics)
        ranges["collective"]["threadReplay"] = "complete"
    ends = [row["endTicks"] for row in ranges.values() if row["endTicks"] is not None]
    end = max(ends, default=-1.0)
    return dict(
        endTicks=end,
        end=end / resolution,
        tickSeconds=1 / resolution,
        ranges=ranges,
        diagnostics=[dict(code=k, count=v) for k, v in sorted(diagnostics.items())],
    )


def _io_ends(trace, db, tick, include, diagnostics, account):
    """Replay cancellation acceptance when an ALL_PROXY handle can cancel peers.

    0xffed60 erases a known (handle, matchingId) operation. Its flag2 branch
    calls 0x1001890, which erases remaining pending operations on the same
    execution location and I/O paradigm. Unknown cancellations do not cascade.
    Raw observations and the importer's general I/O table remain untouched.
    """
    handles = trace.defs.get("IoHandle", {})
    pending = collections.defaultdict(dict)
    kinds = ("IoOperationBegin", "IoOperationComplete", "IoOperationCancelled")
    for row in db.execute(
        "SELECT location,time,tick,kind,data FROM events WHERE kind IN (?,?,?) ORDER BY id",
        kinds,
    ):
        account()
        location, seconds, raw, kind, encoded = tuple(row)
        data = json.loads(encoded)
        handle = str(data.get("handle"))
        key = (handle, str(data.get("matchingId")))
        local = pending[location]
        if kind == "IoOperationBegin":
            local[key] = handles.get(handle, {})
            continue
        definition = local.pop(key, None)
        if definition is None:
            continue
        if kind == "IoOperationComplete":
            include("io", tick(raw, seconds))
        elif definition.get("ioHandleFlags", 0) & 2:
            # The native definition stores its uint8 paradigm as an int, with
            # 0xff promoted to the -1 sentinel, in exactly the compared field.
            paradigm = definition.get("ioParadigm")
            if paradigm is None:
                diagnostics["io-handle-paradigm-unresolved"] += 1
                continue
            for sibling in [
                k for k, d in local.items() if d.get("ioParadigm") == paradigm
            ]:
                del local[sibling]


def _collective_ends(trace, db, tick, include, diagnostics, account):
    """Complete MPI collective intervals and type-3 request release ordering."""
    resolver = Communicators(trace.defs)
    pending = set()
    rma_pending = set()
    ignored_groups = {
        ref
        for ref, d in trace.defs.get("Group", {}).items()
        if d.get("groupType") == 6 and d.get("paradigm") == 4
    }
    ignored_comms = {
        ref
        for ref, d in trace.defs.get("Comm", {}).items()
        if str(d.get("group")) in ignored_groups
    }
    # Each request owns the ordered ends held behind it, without a separate
    # per-request state wrapper. Cancelled requests contribute no end of their own.
    requests = collections.defaultdict(dict)
    kinds = (
        "MpiCollectiveBegin",
        "MpiCollectiveEnd",
        "NonBlockingCollectiveRequest",
        "NonBlockingCollectiveComplete",
        "MpiRequestCancelled",
        "RmaCollectiveBegin",
        "RmaCollectiveEnd",
    )
    marks = ",".join("?" for _ in kinds)

    def release(owner, ident, values):
        queue = requests[owner]
        before = None
        for key in queue:
            if key == ident:
                break
            before = key
        values.extend(queue.pop(ident))
        if before is not None:
            queue[before].extend(values)
        else:
            for value in values:
                include("collective", value)

    for row in db.execute(
        f"SELECT location,time,tick,kind,data FROM events WHERE kind IN ({marks}) ORDER BY id",
        kinds,
    ):
        account()
        location, time, raw, kind, encoded = tuple(row)
        data = json.loads(encoded)
        t = tick(raw, time)
        if kind == "MpiCollectiveBegin":
            if location in pending:
                diagnostics["duplicate-collective-begin-retained"] += 1
            else:
                pending.add(location)
        elif kind == "MpiCollectiveEnd":
            if location not in pending:
                diagnostics["collective-end-without-begin"] += 1
                continue
            pending.remove(location)
            owner = resolver.request_scope(location)
            queue = requests[owner]
            if queue:
                # 0x1052d70 appends blocking collectives to the last pending
                # type-3 request as well, preserving its actual end timestamp.
                queue[next(reversed(queue))].append(t)
            else:
                include("collective", t)
        elif kind == "RmaCollectiveBegin":
            if location in rma_pending:
                diagnostics["duplicate-rma-collective-begin-retained"] += 1
            else:
                rma_pending.add(location)
        elif kind == "RmaCollectiveEnd":
            if location not in rma_pending:
                diagnostics["rma-collective-end-without-begin"] += 1
                continue
            rma_pending.remove(location)
            window = trace.defs.get("RmaWin", {}).get(str(data.get("win")))
            if window is None or str(window.get("comm")) not in trace.defs.get(
                "Comm", {}
            ):
                diagnostics["unresolved-rma-collective-window"] += 1
                continue
            # Group6/MPI is the native ignored-group map; Comm and RmaWin
            # definitions propagate it, and 0x104f920 skips that window.
            if str(window["comm"]) not in ignored_comms:
                include("collective", t)
        else:
            owner = resolver.request_scope(location)
            ident = str(data.get("requestID"))
            queue = requests[owner]
            if kind == "NonBlockingCollectiveRequest":
                if ident in queue:
                    diagnostics["reused-collective-request"] += 1
                    continue
                queue[ident] = []
            elif kind == "NonBlockingCollectiveComplete":
                if ident not in queue:
                    diagnostics["collective-completion-without-request"] += 1
                    continue
                release(owner, ident, [t])
            elif ident in queue:
                release(owner, ident, [])
    held = sum(len(values) for queue in requests.values() for values in queue.values())
    if held:
        diagnostics["collective-completion-held-at-eof"] += held
