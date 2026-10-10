"""Collective brackets, communicator cohorts, and arrival observations."""

import collections
import json
import math

from .communicators import Communicators
from .wait_models import Record, Span


def _group_members(resolver, reference, location):
    group = resolver.group(reference)
    if group.get("groupType") == 6:
        world = resolver.world(group.get("paradigm"))
        local = (
            resolver.representative(location, resolver.world_members(world))
            if world
            else location
        )
        return {local} if local is not None else set()
    members = resolver.members(reference)
    return set(members) if None not in members else set()


def _comm_members(resolver, comm, location):
    if comm in resolver.defs.get("InterComm", {}):
        from .intercomm import domain as intercomm_domain

        scope = intercomm_domain(resolver, comm)
        return (set(scope.members) if scope else set()), False, True
    definition = resolver.defs.get("Comm", {}).get(comm)
    if definition:
        group = resolver.defs.get("Group", {}).get(str(definition.get("group")), {})
        return (
            _group_members(resolver, definition.get("group"), location),
            group.get("groupType") == 6,
            False,
        )
    return set(), False, False


def _valid_interval(p):
    return (
        p["end"] is not None
        and math.isfinite(p["start"])
        and math.isfinite(p["end"])
        and p["end"] >= p["start"]
    )


def _collective_brackets(trace, diagnostics):
    """Retain missing/replaced initiation evidence hidden by old index repair."""
    pending = {}
    result = {}
    resolver = Communicators(trace.defs)
    with trace.connect() as db:
        rows = db.execute(
            "SELECT id,location,time,kind,data FROM events WHERE kind IN ('MpiCollectiveBegin','MpiCollectiveEnd','NonBlockingCollectiveRequest','NonBlockingCollectiveComplete') ORDER BY time,id"
        )
        for event, location, time, kind, data in rows:
            nonblocking = kind.startswith("NonBlocking")
            # Only nonblocking records carry the request identity in their payload.
            key = (
                (
                    resolver.request_scope(location),
                    nonblocking,
                    str(json.loads(data).get("requestID", 0)),
                )
                if nonblocking
                else (location, nonblocking, "")
            )
            if kind in ("MpiCollectiveBegin", "NonBlockingCollectiveRequest"):
                pending[key] = (event, time, key not in pending, location)
            else:
                begin = pending.pop(key, None)
                valid = begin is not None and begin[2] and begin[1] <= time
                result[event] = dict(
                    valid=valid,
                    event=begin[0] if begin else None,
                    location=begin[3] if begin else None,
                )
                if not valid:
                    diagnostics["collective_initiation_missing_or_reused"] += 1
    return result


def _collectives(trace, lookup, diagnostics, continuity, brackets):
    counts = collections.Counter()
    episodes = {}
    records = []
    resolver = Communicators(trace.defs)
    membership_cache = {}

    def lookups(row):
        # The span and bracketed-initiation at() calls made for each row below;
        # default brackets carry no event and need no boundary records.
        if row["event_kind"] == "RmaCollectiveEnd":
            return
        if row["end"] is not None:
            yield row["location"], row["end"], None, row["event"]
        bracket = brackets.get(row["event"])
        if bracket and bracket.get("valid"):
            location = bracket.get("location", row["location"])
            yield location, row["start"], None, bracket["event"]

    with trace.connect() as db:
        sql = """SELECT c.*,e.kind event_kind,e.data event_data FROM collectives c LEFT JOIN events e ON e.id=c.event
                 ORDER BY c.start,c.id"""
        for row in lookup.prefetched(db.execute(sql), lookups):
            c = dict(row)
            location = c["location"]
            comm = c["comm"]
            # RMA collectives share the index table but have a different matching domain.
            if c["event_kind"] == "RmaCollectiveEnd":
                continue
            definition = trace.defs.get("Comm", {}).get(comm, {})
            is_self = resolver.group(definition.get("group")).get("groupType") == 6
            membership_key = (comm, location if is_self else None)
            if membership_key not in membership_cache:
                membership_cache[membership_key] = _comm_members(
                    resolver, comm, location
                )
            members, self_comm, intercomm = membership_cache[membership_key]
            # For valid groups this is the same representative lookup over a
            # reused set, avoiding an N-member list rebuild at every rank.
            participant = (
                resolver.representative(location, members)
                if members
                else None if intercomm else resolver.local(comm, location)
            ) or location
            domain = (comm, participant if self_comm else "")
            sequence = counts[(domain, participant)]
            counts[(domain, participant)] += 1
            key = (domain, sequence)
            episode = episodes.setdefault(
                key,
                dict(
                    comm=comm,
                    sequence=sequence,
                    expected=members,
                    intercomm=intercomm,
                    participants=[],
                    domain=domain,
                ),
            )
            nonblocking = c["event_kind"] == "NonBlockingCollectiveComplete"
            span = (
                lookup.at(location, c["end"], event=c["event"])
                if c["end"] is not None
                else None
            )
            bracket = brackets.get(
                c["event"], dict(valid=c["event_kind"] == "OtfCollective", event=None)
            )
            initiation_span = (
                lookup.at(
                    bracket.get("location", location),
                    c["start"],
                    event=bracket["event"],
                )
                if bracket.get("valid")
                else None
            )
            initiation_definition = (
                trace.defs.get("Region", {}).get(initiation_span.region, {})
                if initiation_span
                else {}
            )
            raw = json.loads(c["event_data"]) if c["event_data"] else {}
            episode["participants"].append(
                dict(
                    location=location,
                    participant=participant,
                    start=c["start"],
                    end=c["end"],
                    operation=c["operation"],
                    event=c["event"],
                    nonblocking=nonblocking,
                    span=span,
                    bracketComplete=bracket["valid"],
                    initiationEvent=bracket["event"],
                    initiationLocation=bracket.get("location", location),
                    initiationRoutine=(
                        initiation_span.routine if initiation_span else None
                    ),
                    initiationName=initiation_span.name if initiation_span else None,
                    initiationParadigm=initiation_definition.get("paradigm"),
                    initiationSpan=initiation_span.id if initiation_span else None,
                    initiationRoutineComplete=bool(
                        initiation_span and initiation_span.complete
                    ),
                    recordKind=c["event_kind"],
                    recordedOp=raw.get("collectiveOp"),
                    recordedComm=raw.get("communicator"),
                    root=raw.get("root"),
                    sizeSent=raw.get("sizeSent"),
                    sizeReceived=raw.get("sizeReceived"),
                )
            )
    output = []
    for episode in episodes.values():
        participants = episode["participants"]
        expected = episode["expected"]
        observed = {p["participant"] for p in participants}
        operations = {p["operation"] for p in participants}
        first = min(p["start"] for p in participants)
        last = max(p["start"] for p in participants)
        initiation_classes = {
            "nonblocking" if p["nonblocking"] else "blocking" for p in participants
        }
        missing = expected - observed
        complete = (
            bool(expected)
            and observed == expected
            and len(operations) == 1
            and len(initiation_classes) == 1
            and all(p["end"] is not None and p["bracketComplete"] for p in participants)
        )
        valid_intervals = all(map(_valid_interval, participants))
        totals = [counts[(episode["domain"], m)] for m in expected]
        reliable = bool(totals) and len(set(totals)) == 1
        locations = [p["location"] for p in participants] + [
            p["initiationLocation"]
            for p in participants
            if p["initiationLocation"] is not None
        ]
        recording_issue = continuity.issue(
            locations,
            max(
                (p["end"] if p["end"] is not None else p["start"]) for p in participants
            ),
            comm=episode["comm"],
            start=first,
        )
        if recording_issue:
            reliable = False
            diagnostics["collective_recording_gap"] += 1
        if missing:
            diagnostics["collective_missing_participants"] += 1
        if not expected:
            diagnostics["collective_unknown_membership"] += 1
        if len(operations) != 1:
            diagnostics["collective_operation_mismatch"] += 1
        if len(initiation_classes) != 1:
            diagnostics["collective_initiation_class_mismatch"] += 1
        if not reliable:
            diagnostics["collective_sequence_uncertain"] += 1
        if not valid_intervals:
            diagnostics["collective_invalid_interval"] += 1
        if episode["intercomm"]:
            diagnostics["intercommunicator_collective"] += 1
        operation = (
            next(iter(operations))
            if len(operations) == 1
            else " / ".join(sorted(operations))
        )
        barrier_inversion = (
            not episode["intercomm"]
            and operation.upper() in ("BARRIER", "MPI_BARRIER")
            and any(p["end"] is not None and p["end"] < last for p in participants)
        )
        if barrier_inversion:
            diagnostics["collective_barrier_clock_inversion"] += 1
        eid = (
            "collective:"
            + str(episode["comm"])
            + ":"
            + str(episode["sequence"])
            + (":" + episode["domain"][1] if episode["domain"][1] else "")
        )
        ends = [p["end"] for p in participants if p["end"] is not None]
        item = dict(
            id=eid,
            comm=episode["comm"],
            sequence=episode["sequence"],
            operation=operation,
            start=first,
            end=max(ends, default=last),
            arrivalSkew=last - first,
            participants=[],
            expectedParticipants=len(expected) if expected else None,
            missingParticipants=sorted(missing),
            complete=complete,
            sequenceReliable=reliable,
            confidence=(
                "conditional"
                if complete
                and reliable
                and valid_intervals
                and not episode["intercomm"]
                and not barrier_inversion
                else "low"
            ),
            evidence=dict(
                matching="communicator, per-rank initiation ordinal and blocking/nonblocking class",
                operations=sorted(operations),
                initiationClasses=sorted(initiation_classes),
                intercommunicator=episode["intercomm"],
                barrierClockInversion=barrier_inversion,
                validIntervals=valid_intervals,
            ),
        )
        recording_proof = recording_issue or continuity.proof(
            locations, item["end"], episode["comm"]
        )
        item["evidence"]["recordingContinuity"] = recording_proof
        # The reference 10.8.1 collective-detail worker retains min/max start and
        # stop times; its UI computes positive intersection / overall span.
        # See docs/binary-waits.md for the statically recovered instructions.
        # This is interval overlap, not inferred blocked time. Suppress it
        # when cohort membership or the ordinal matching is incomplete.
        overall_duration = item["end"] - first if valid_intervals else None
        overlap_known = complete and reliable and valid_intervals
        overlap = max(0.0, min(ends) - last) if overlap_known else None
        item.update(
            overallDuration=overall_duration,
            participantOverlap=overlap,
            participantOverlapPercent=(
                (100.0 * overlap / overall_duration if overall_duration > 0 else 0.0)
                if overlap_known
                else None
            ),
        )
        item["evidence"][
            "overlapDefinition"
        ] = "Intersection of all participant intervals divided by their overall span; not blocked time."
        item["evidence"][
            "intervalSemantics"
        ] = "Nonblocking participants use request initiation-to-completion lifetimes; blocking participants use collective begin-to-end intervals."
        for p in participants:
            item["participants"].append(
                {k: v for k, v in p.items() if k != "span"}
                | dict(
                    span=p["span"].id if p["span"] else None,
                    arrivalDelay=last - p["start"],
                )
            )
            if p["nonblocking"] or not _valid_interval(p):
                continue
            span = p["span"]
            # Use the locally measured collective interval, not a surrounding
            # Waitall or a nonblocking request's entire lifetime.
            measured = Span(
                -(p["event"] or 0),
                p["location"],
                span.region if span else "",
                p["start"],
                p["end"],
                0,
                False,
                False,
                span.name if span else operation,
                "collective",
            )
            returned_early = p["end"] < last
            known = (
                complete
                and reliable
                and valid_intervals
                and not episode["intercomm"]
                and not barrier_inversion
                and not returned_early
                and not (span and span.incomplete)
            )
            deadline = min(p["end"], last) if known else p["start"]
            evidence = dict(
                collective=eid,
                event=p["event"],
                span=span.id if span else None,
                communicator=episode["comm"],
                sequence=episode["sequence"],
                lastArrival=last,
                returnedBeforeLastArrival=returned_early,
                completeParticipants=complete,
                sequenceReliable=reliable,
                recordingContinuity=recording_proof,
                interpretation="Arrival skew can overlap MPI progress; an early return does not wait for the final arrival.",
            )
            records.append(
                Record(
                    measured,
                    "collective_arrival_skew",
                    max(p["start"], deadline),
                    confidence="conditional" if known else "low",
                    evidence=evidence,
                )
            )
        output.append(item)
    return records, output
