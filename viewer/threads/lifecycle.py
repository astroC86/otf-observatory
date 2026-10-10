"""Recovered OTF2 create/wait participants, plus recorded thread lifetimes.

Native participants are collective-store records; their duration is an operation
interval, not a measurement of CPU blocked time. Lifetimes are independent
Begin/End observations: creation and waiting have different sequence families.
"""

import collections
import json

from ..mpi.communicators import Communicators

UINT64_MAX = (1 << 64) - 1
LIFECYCLE_KINDS = ("ThreadCreate", "ThreadBegin", "ThreadWait", "ThreadEnd")


def native_thread_lifecycle(
    trace,
    *,
    tick_domain=False,
    charge=lambda work: None,
    diagnostics=None,
    include_operations=True
):
    """Replay typed region boundaries and the four recorded lifecycle events.

    Operation times use seconds by default, original relative double ticks when
    requested. No event cap silently returns a partial operation stream. The
    caller can enforce a budget with ``charge``; its exception propagates.
    With ``include_operations=False``, replay only lifecycle records for the
    same scope and physical lifetime validation, without region scans or native
    participant emission. Native operation fields then remain empty.
    """
    if diagnostics is None:
        diagnostics = collections.Counter()
    result = dict(
        operations=[],
        by_event={},
        waitPairs={},
        lifetimesByEndEvent={},
        lifecycleIssuesByEndEvent={},
        observations={},
        diagnostics=diagnostics,
    )
    with trace.connect() as db:
        locations = [
            row[0]
            for row in db.execute(
                "SELECT DISTINCT location FROM events WHERE kind IN (?,?,?,?)",
                LIFECYCLE_KINDS,
            )
        ]
    if not locations:
        return result
    resolver = Communicators(trace.defs)
    classes = {7: 2, 14: 2, 15: 2, 16: 2}
    classes.update(
        {
            int(d["paradigm"]): d["paradigmClass"]
            for d in trace.defs.get("Paradigm", {}).values()
        }
    )
    classified = {
        str(ref): (d["regionRole"], d.get("paradigm"))
        for ref, d in trace.defs.get("Region", {}).items()
        if d.get("regionRole") in (32, 33) and classes.get(d.get("paradigm")) == 2
    }
    resolution = int(trace.meta.get("clock", {}).get("resolution", 1))
    if resolution <= 0:
        raise ValueError("Invalid recorded clock resolution")
    offset = int(trace.meta.get("clock", {}).get("offset", 0))
    clock_tick = 1 if tick_domain else 1 / resolution
    scope_cache = {}

    def scope(comm, location):
        key = (comm, location)
        if key in scope_cache:
            return scope_cache[key]
        definition = trace.defs.get("Comm", {}).get(comm)
        inter = trace.defs.get("InterComm", {}).get(comm)
        group = (
            resolver.group(definition.get("group"))
            if definition
            else (resolver.group(inter.get("groupA")) if inter else {})
        )
        paradigm = group.get("paradigm")
        world = resolver.world(paradigm)
        members = resolver.world_members(world)
        identity = (
            resolver.request_scope(location)
            if world.get("groupType") == 7
            else location
        )
        valid_groups = group.get("groupType") in (5, 6)
        if inter:
            other = resolver.group(inter.get("groupB"))
            valid_groups = (
                valid_groups
                and other.get("groupType") in (5, 6)
                and other.get("paradigm") == paradigm
            )
        valid = bool(valid_groups and world and identity in members)
        # The native callback checks its paradigm-world lookup. A separate
        # membership guard is required before exposing a causal correspondence.
        # MPI's representative() can map an executing worker to the one
        # recorded rank location in its process. A thread contingent needs its
        # actual recorded location (or explicitly recorded location group).
        # COMM_SELF cannot establish a cross-location Wait/End membership.
        contingent_members = (
            resolver.members(definition.get("group"))
            if definition
            else (
                resolver.members(inter.get("groupA"))
                + resolver.members(inter.get("groupB"))
                if inter
                else []
            )
        )
        member = valid and identity in contingent_members
        value = (paradigm, valid, member)
        scope_cache[key] = value
        return value

    def sequence(value):
        try:
            if isinstance(value, bool) or not isinstance(value, (str, int)):
                return None
            if isinstance(value, str) and (
                not value or not value.isascii() or not value.isdecimal()
            ):
                return None
            parsed = int(value)
            return parsed if 0 <= parsed < UINT64_MAX else None
        except (ValueError, TypeError, OverflowError):
            return None

    pending = None
    active_begin = None
    repeated_begin = False
    current_location = None
    kinds = (
        (
            *LIFECYCLE_KINDS,
            "Enter",
            "Leave",
            "CallingContextEnter",
            "CallingContextLeave",
        )
        if include_operations
        else LIFECYCLE_KINDS
    )
    query = (
        "SELECT id,location,time,tick,kind,data FROM events WHERE location IN ("
        + ",".join("?" for _ in locations)
        + ") AND kind IN ("
        + ",".join("?" for _ in kinds)
        + ") ORDER BY location,id"
    )
    with trace.connect() as db:
        for event, location, time, tick, kind, encoded in db.execute(
            query, (*locations, *kinds)
        ):
            charge(1)
            location = str(location)
            if tick_domain:
                try:
                    time = float((int(tick) - offset) & UINT64_MAX)
                except (ValueError, TypeError, OverflowError):
                    time *= resolution
                    diagnostics["missing-original-clock-ticks"] += 1
            if location != current_location:
                current_location = location
                pending = None
                active_begin = None
                repeated_begin = False
            data = json.loads(encoded)
            if kind not in LIFECYCLE_KINDS:
                region = data.get("region")
                if kind.startswith("CallingContext"):
                    context = trace.defs.get("CallingContext", {}).get(
                        str(data.get("callingContext"))
                    )
                    if context is None:
                        pending = None
                        diagnostics["native_thread_lifecycle_unknown_context"] += 1
                        continue
                    region = context.get("region")
                classification = classified.get(str(region))
                if classification is None:
                    continue
                entering = kind.endswith("Enter")
                if entering and pending is None:
                    pending = (classification, time, event)
                else:
                    if pending is not None:
                        issue = "pending_reused" if entering else "pending_unconsumed"
                        diagnostics["native_thread_lifecycle_" + issue] += 1
                    pending = None
                continue

            comm = str(data.get("threadContingent"))
            paradigm, valid, member = scope(comm, location)
            seq = sequence(data.get("sequenceCount"))
            family = (
                "THREAD_CREATE"
                if kind in ("ThreadCreate", "ThreadBegin")
                else "THREAD_WAIT"
            )
            obs = dict(
                event=event,
                kind=kind,
                location=location,
                time=time,
                comm=comm,
                paradigm=paradigm,
                nativeEmitted=False,
                scopeValid=valid,
                membershipValid=member,
                sequenceValid=seq is not None,
                sequenceCount=str(seq) if seq is not None else None,
                reasons=[],
            )
            result["observations"][event] = obs
            if not valid:
                obs["reasons"].append("unknown-contingent-or-paradigm-membership")
                diagnostics["native_thread_lifecycle_scope_invalid"] += 1
            elif not member:
                obs["reasons"].append("outside-contingent-membership")
            if seq is None:
                obs["reasons"].append("undefined-or-invalid-sequence")

            # A thread's creation sequence identifies its creator, while its
            # ending sequence identifies its waiter. Do not equate the two.
            if kind == "ThreadBegin":
                if active_begin is not None:
                    repeated_begin = True
                    diagnostics["native_thread_lifecycle_begin_repeated"] += 1
                active_begin = obs
            elif kind == "ThreadEnd":
                issue = (
                    "missing-begin"
                    if active_begin is None
                    else (
                        "repeated-begin"
                        if repeated_begin
                        else (
                            "unknown-lifecycle-scope"
                            if not active_begin["scopeValid"] or not valid
                            else (
                                "lifecycle-paradigm-conflict"
                                if active_begin["paradigm"] != paradigm
                                else (
                                    "lifecycle-clock-conflict"
                                    if active_begin["time"] > time
                                    else None
                                )
                            )
                        )
                    )
                )
                if issue is None:
                    result["lifetimesByEndEvent"][event] = dict(
                        location=location,
                        start=active_begin["time"],
                        end=time,
                        beginEvent=active_begin["event"],
                        endEvent=event,
                        beginContingent=active_begin["comm"],
                        endContingent=comm,
                        createSequenceCount=active_begin["sequenceCount"],
                        waitSequenceCount=obs["sequenceCount"],
                        complete=True,
                    )
                else:
                    result["lifecycleIssuesByEndEvent"][event] = [issue]
                active_begin = None
                repeated_begin = False

            if not include_operations or not valid:
                continue
            boundary, start = event, time
            if kind in ("ThreadCreate", "ThreadWait"):
                expected = (32 if kind == "ThreadCreate" else 33, paradigm)
                if (
                    pending is None
                    or pending[0] != expected
                    or pending[1] == -clock_tick
                ):
                    obs["reasons"].append("matching-typed-entry-missing")
                    diagnostics["native_thread_lifecycle_entry_missing"] += 1
                    continue
                _, start, boundary = pending
                pending = None  # Also consumed for the undefined sequence.
            if seq is None:
                continue
            encoded_seq = 4 * seq + (2 if family == "THREAD_CREATE" else 3)
            overflow = encoded_seq > UINT64_MAX
            if overflow:
                diagnostics["native_thread_lifecycle_sequence_overflow"] += 1
                obs["reasons"].append("native-sequence-overflow")
            operation = dict(
                operation=family,
                kind=kind,
                comm=comm,
                location=location,
                sequenceCount=str(seq),
                encodedSequence=str(encoded_seq & UINT64_MAX),
                start=start,
                end=time,
                event=event,
                boundaryEvent=boundary,
                paradigm=paradigm,
                root=location if kind == "ThreadCreate" else None,
                sequenceOverflow=overflow,
                membershipValid=member,
            )
            result["operations"].append(operation)
            result["by_event"][event] = operation
            obs["nativeEmitted"] = True

    groups = collections.defaultdict(list)
    for operation in result["operations"]:
        if operation["operation"] == "THREAD_WAIT":
            groups[
                (
                    operation["comm"],
                    operation["operation"],
                    operation["encodedSequence"],
                )
            ].append(operation)
    for records in groups.values():
        waits = [r for r in records if r["kind"] == "ThreadWait"]
        ends = [r for r in records if r["kind"] == "ThreadEnd"]
        if len(waits) != 1 or len(ends) != 1:
            if len(waits) > 1 or len(ends) > 1:
                diagnostics["native_thread_lifecycle_duplicate_identity"] += 1
            continue
        wait, end = waits[0], ends[0]
        if any(r["sequenceOverflow"] or not r["membershipValid"] for r in records):
            continue
        if (
            wait["location"] == end["location"]
            or wait["end"] < end["end"]
            or wait["start"] > wait["end"]
        ):
            diagnostics["native_thread_lifecycle_pair_order_invalid"] += 1
            continue
        result["waitPairs"][wait["event"]] = dict(
            waitEvent=wait["event"],
            endEvent=end["event"],
            comm=wait["comm"],
            sequenceCount=wait["sequenceCount"],
            encodedSequence=wait["encodedSequence"],
            wait=wait,
            end=end,
        )
    return result
