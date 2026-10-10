"""Directed MPI payload prerequisites from recorded OTF2 evidence.

These are MPI semantic constraints, not recovered causal formulas. Byte
sizes are optional in OTF2: zero/missing fields do not establish a zero-count MPI
call. Only complete, consistent positive profiles enable stronger links.
"""

from __future__ import annotations

import dataclasses

OPERATIONS = {
    "BCAST": 1,
    "GATHER": 2,
    "GATHERV": 3,
    "SCATTER": 4,
    "SCATTERV": 5,
    "ALLGATHER": 6,
    "ALLGATHERV": 7,
    "ALLTOALL": 8,
    "ALLREDUCE": 11,
    "REDUCE": 12,
    "REDUCE_SCATTER": 13,
    "SCAN": 14,
    "EXSCAN": 15,
    "REDUCE_SCATTER_BLOCK": 16,
}
ROOTLESS = frozenset(
    (
        "ALLGATHER",
        "ALLGATHERV",
        "ALLTOALL",
        "ALLREDUCE",
        "REDUCE_SCATTER",
        "SCAN",
        "EXSCAN",
        "REDUCE_SCATTER_BLOCK",
    )
)
ROOT_NONE = 2**32 - 1


def uint(value, bits):
    # Original reader JSON records contain integers, not SQL-coerced numbers.
    return value if type(value) is int and 0 <= value < 2**bits else None


@dataclasses.dataclass(slots=True)
class PayloadPlan:
    sources: frozenset
    targets: frozenset
    latest: tuple
    clock_invalid: frozenset
    expected: int
    evidence: dict
    reason: str

    def latest_for(self, participant):
        return next((p for p in self.latest if p["participant"] != participant), None)


@dataclasses.dataclass(slots=True)
class PrefixPlan(PayloadPlan):
    prefix_ranks: dict
    prefix_latest: tuple

    def latest_for(self, participant):
        return self.prefix_latest[self.prefix_ranks[participant]]


def _prefix_plan(resolver, group, sizes, by_id, status, reject):
    """Validate communicator order, independent of event rank encoding flags."""
    if group["groupType"] == 6:
        ordered = list(by_id) if len(by_id) == 1 else []
    else:
        worlds = [
            world
            for world in resolver.defs.get("Group", {}).values()
            if world.get("groupType") in (4, 7)
            and world.get("paradigm") == group.get("paradigm")
        ]
        members = group.get("members", [])
        if len(worlds) != 1 or not isinstance(members, (list, tuple)):
            return reject(
                "prefix-rank-domain-unresolved",
                "A unique paradigm world and ordered communicator member list are required.",
            )
        world = worlds[0]
        world_members = world.get("members", [])
        if (
            not isinstance(world_members, (list, tuple))
            or any(uint(v, 64) is None for v in world_members)
            or len(set(world_members)) != len(world_members)
            or any(uint(v, 64) is None or v >= len(world_members) for v in members)
        ):
            return reject(
                "prefix-rank-domain-unresolved",
                "Communicator member indices and world identities must be valid unique unsigned integers.",
            )
        domain = resolver.world_members(world)
        ordered = [domain[i] for i in members]
    if (
        len(ordered) != len(by_id)
        or len(set(ordered)) != len(ordered)
        or set(ordered) != set(by_id)
    ):
        return reject(
            "prefix-rank-domain-unresolved",
            "The ordered communicator must name every participant exactly once.",
        )
    sources = frozenset(ordered[:-1])
    targets = frozenset(ordered[1:])
    if any(sizes[p][0] <= 0 for p in sources) or any(sizes[p][1] <= 0 for p in targets):
        return reject(
            "payload-zero-or-unrecorded",
            "Each nonterminal prefix contributor needs positive sent bytes and each noninitial receiver positive received bytes.",
        )
    # Score-P includes all logical peer contributions in these totals: they
    # vary with rank and in-place mode. Do not require uniform aggregate bytes
    # or invent a count/in-place mode by dividing them.
    ranks = {participant: rank for rank, participant in enumerate(ordered)}
    latest = [None]
    invalid = set()
    for participant in ordered:
        previous = latest[-1]
        record = by_id[participant]
        if previous is not None and previous["start"] > record["end"]:
            invalid.add(participant)
        latest.append(
            record
            if previous is None or record["start"] > previous["start"]
            else previous
        )
    name = status["operation"]
    evidence = dict(
        status,
        status="directed-positive-payload",
        direction="lower-ranks-to-prefix-receiver",
        root=None,
        rootRank=ROOT_NONE,
        sourceCount=len(sources),
        targetCount=len(targets),
        clockInvalidTargets=sorted(invalid)[:16],
        clockInvalidTargetCount=len(invalid),
        sourceBytes=None,
        targetBytes=None,
        rankOrder="COMM_GROUP.members sequence; GLOBAL_MEMBERS changes event rank encoding only.",
        prefixSemantics="Remote contributors have communicator rank strictly below the receiver; local input is not a remote prerequisite.",
        guard="Complete rootless prefix cohort; unique ordered communicator members and positive payloads for every nonempty send/receive role.",
        sourceContract="Local Open MPI Scan/Exscan documentation, OTF2 definitions and Score-P collective byte accounting.",
    )
    reason = f"{name} completion requires the recorded positive contributions of communicator ranks below the receiver; this does not establish measured blocked time."
    return (
        PrefixPlan(
            sources,
            targets,
            (),
            frozenset(invalid),
            max(0, len(ordered) - 1),
            evidence,
            reason,
            ranks,
            tuple(latest),
        ),
        evidence,
    )


def plan(cohort, resolver):
    """Return (shared plan or None, public status); never invent missing sizes."""
    name = cohort["operation"].upper().removeprefix("MPI_")
    status = dict(
        operation=name,
        status="unresolved",
        interpretation="Recorded payload prerequisites are completion constraints, not measured blocked time.",
    )

    def reject(code, message):
        return None, dict(status, code=code, message=message)

    if name not in OPERATIONS:
        return reject(
            "unsupported-operation",
            "No directed positive-payload contract is applied to this operation.",
        )
    if (
        cohort["confidence"] != "conditional"
        or not cohort["complete"]
        or not cohort["sequenceReliable"]
        or cohort["evidence"].get("intercommunicator")
    ):
        return reject(
            "cohort-unresolved",
            "Complete, consistently ordered intracommunicator participation is required.",
        )
    participants = cohort["participants"]
    comm = resolver.defs.get("Comm", {}).get(cohort["comm"], {})
    group = resolver.group(comm.get("group"))
    if group.get("groupType") not in (5, 6):
        return reject(
            "root-domain-unresolved",
            "The communicator must reference a COMM_GROUP or COMM_SELF definition.",
        )
    flags = uint(group.get("groupFlags", 0), 32)
    if flags is None or flags & ~1:
        return reject(
            "root-domain-unresolved",
            "Communicator rank-domain flags are malformed or unsupported.",
        )
    if any(
        p.get("recordKind") not in ("MpiCollectiveEnd", "NonBlockingCollectiveComplete")
        or uint(p.get("recordedOp"), 8) != OPERATIONS[name]
        or str(p.get("recordedComm")) != cohort["comm"]
        for p in participants
    ):
        return reject(
            "record-contract-unresolved",
            "Original OTF2 collective operation and communicator fields must match the indexed cohort.",
        )
    if name in ("ALLGATHER", "ALLGATHERV", "ALLTOALL"):
        # Score-P uses these SAME OTF2 operation enums for the neighborhood
        # APIs. Positive totals alone therefore cannot prove an all-peer
        # exchange. Require the complete original initiating API invocation,
        # not a completion Wait or the indexed collective label.
        for participant in participants:
            routine = (
                "i"
                if participant["recordKind"] == "NonBlockingCollectiveComplete"
                else ""
            ) + name.lower()
            api_names = {
                prefix + api
                for prefix in ("mpi_", "pmpi_")
                for api in (routine, routine + "_c")
            }
            recorded_name = participant.get("initiationName")
            # Broad routine classification intentionally recognizes wrappers
            # for display. An embedded token is not proof of the initiating
            # API family. Group labels are customizable; use the original
            # typed Region paradigm instead, not its displayed function group.
            if (
                not participant.get("initiationRoutineComplete")
                or uint(participant.get("initiationParadigm"), 8) != 4
                or not isinstance(recorded_name, str)
                or recorded_name.casefold() not in api_names
            ):
                return reject(
                    "api-family-unresolved",
                    "This operation code is also used for neighborhood collectives; every participant needs a complete exact all-peer initiating MPI API label with the original MPI Region paradigm.",
                )
    roots = [uint(p.get("root"), 32) for p in participants]
    if None in roots or len(set(roots)) != 1:
        return reject(
            "root-inconsistent",
            "Every participant must record the same valid root rank or rootless sentinel.",
        )
    root_rank = roots[0]
    by_id = {p["participant"]: p for p in participants}
    root = None
    if name in ROOTLESS:
        if root_rank != ROOT_NONE:
            return reject(
                "root-inconsistent",
                "A rootless collective must record OTF2_COLLECTIVE_ROOT_NONE.",
            )
    else:
        if root_rank >= ROOT_NONE - 2:
            return reject(
                "root-domain-unresolved",
                "Intercommunicator root sentinels do not identify an intracommunicator root.",
            )
        root = resolver.peer(cohort["comm"], root_rank, participants[0]["location"])
        if root not in by_id:
            return reject(
                "root-domain-unresolved",
                "The recorded root rank does not map to a participant in this communicator.",
            )
    sizes = {}
    for p in participants:
        sent = uint(p.get("sizeSent"), 64)
        received = uint(p.get("sizeReceived"), 64)
        if (
            sent is None
            or received is None
            or sent == 2**64 - 1
            or received == 2**64 - 1
        ):
            return reject(
                "payload-unavailable",
                "Original finite uint64 payload sizes are missing, malformed, or undefined.",
            )
        sizes[p["participant"]] = (sent, received)
    if name in ("SCAN", "EXSCAN"):
        return _prefix_plan(resolver, group, sizes, by_id, status, reject)
    if name == "REDUCE_SCATTER":
        from .scorep_collective import _scorep_reduce_scatter_plan

        return _scorep_reduce_scatter_plan(
            cohort, resolver, group, sizes, by_id, status, reject
        )
    ids = frozenset(by_id)
    if name in ("BCAST", "SCATTER", "SCATTERV"):
        sources = frozenset((root,))
        targets = ids - {root}
        direction = "root-to-receivers"
    elif name in ("GATHER", "GATHERV", "REDUCE"):
        sources = ids - {root}
        targets = frozenset((root,))
        direction = "contributors-to-root"
    else:
        sources = ids
        targets = ids
        direction = "all-contributors-to-all-receivers"
    sends = {sizes[i][0] for i in sources}
    receives = {sizes[i][1] for i in targets}
    if 0 in sends or 0 in receives:
        return reject(
            "payload-zero-or-unrecorded",
            "Optional zero payload fields do not prove positive-count data movement.",
        )
    # Fixed-count roles have equal type signatures. Do not infer an aggregate
    # byte multiplier (some producers include local contributions); require
    # consistency within each sender/receiver role, not sent == received.
    # Allgatherv replicates each possibly different contribution to EVERY
    # receiver. Gatherv/Scatterv have only one root destination/source. Those
    # directions need no inferred destination-count vector, unlike Alltoallv/w.
    # Require positive fields for EVERY relevant role: optional zero bytes
    # cannot establish a known absent contributor or a complete peer set.
    variable_payload = name in ("GATHERV", "SCATTERV", "ALLGATHERV")
    if not variable_payload and (len(sends) > 1 or len(receives) > 1):
        return reject(
            "payload-inconsistent",
            "Recorded payload sizes differ within a fixed-count sender or receiver role.",
        )
    if (
        name in ("BCAST", "SCATTER", "SCATTERV")
        and sends
        and receives
        and next(iter(sends)) < max(receives)
    ):
        return reject(
            "payload-inconsistent",
            "The recorded root send size is smaller than an individual receive size.",
        )
    if (
        name in ("GATHER", "GATHERV", "REDUCE")
        and sends
        and receives
        and next(iter(receives)) < max(sends)
    ):
        return reject(
            "payload-inconsistent",
            "The recorded root receive size is smaller than an individual contribution.",
        )
    latest = tuple(
        sorted((by_id[i] for i in sources), key=lambda p: p["start"], reverse=True)[:2]
    )
    invalid = set()
    for target in targets:
        peer = next((p for p in latest if p["participant"] != target), None)
        if peer is not None and peer["start"] > by_id[target]["end"]:
            invalid.add(target)
    evidence = dict(
        status,
        status="directed-positive-payload",
        direction=direction,
        root=root,
        rootRank=root_rank,
        sourceCount=len(sources),
        targetCount=len(targets),
        clockInvalidTargets=sorted(invalid)[:16],
        clockInvalidTargetCount=len(invalid),
        sourceBytes=next(iter(sends), None) if len(sends) <= 1 else None,
        targetBytes=next(iter(receives), None) if len(receives) <= 1 else None,
        guard=(
            "Complete variable-count cohort; consistent root domain and positive recorded payload for every directed source/receiver role; operation semantics identify the destination without inferring count vectors."
            if variable_payload
            else "Complete fixed-count cohort; consistent root and positive uniform recorded payload roles."
        ),
        sourceContract="Local Open MPI collective documentation and OTF2 event/communicator definitions.",
    )
    if variable_payload:
        evidence["payloadProfile"] = {
            "ALLGATHERV": "variable-contributions-replicated-to-every-receiver",
            "GATHERV": "variable-contributions-to-root",
            "SCATTERV": "variable-root-blocks-to-receivers",
        }[name]
        evidence["sourceByteRange"] = [min(sends), max(sends)] if sends else None
        evidence["targetByteRange"] = (
            [min(receives), max(receives)] if receives else None
        )
    if name in ("ALLGATHER", "ALLGATHERV", "ALLTOALL"):
        evidence["apiFamily"] = (
            "matching all-peer initiating MPI API, verified on every participant"
        )
    reason = (
        f"{name} completion at a receiver requires the recorded positive payload from the root."
        if name in ("BCAST", "SCATTER", "SCATTERV")
        else (
            f"{name} completion at the root requires every recorded positive contributor."
            if name in ("GATHER", "GATHERV", "REDUCE")
            else (
                "ALLTOALL completion requires the positive per-destination block from every other communicator participant."
                if name == "ALLTOALL"
                else (
                    "REDUCE_SCATTER_BLOCK completion requires every communicator participant’s positive input contribution to the receiver’s fixed-size result block."
                    if name == "REDUCE_SCATTER_BLOCK"
                    else (
                        "ALLGATHERV completion requires every communicator participant’s recorded positive contribution, although contribution sizes may differ."
                        if name == "ALLGATHERV"
                        else f"{name} completion requires the recorded positive contribution of every communicator participant."
                    )
                )
            )
        )
    )
    return (
        PayloadPlan(
            sources,
            targets,
            latest,
            frozenset(invalid),
            len(sources) - (1 if sources == targets else 0),
            evidence,
            reason,
        ),
        evidence,
    )
