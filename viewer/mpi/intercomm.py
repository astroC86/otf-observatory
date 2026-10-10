"""OTF2 intercommunicator collective prerequisites, never same-group barriers.

The two original ordered MPI groups determine separate peer domains. Root
sentinels determine inactive/local-root roles; aggregate payload never invents
per-destination counts. See docs/mpi-intercomm-causality.md for local sources.
"""

from __future__ import annotations

import dataclasses
import math

from ..causality.lazy_causes import BarrierCohort
from .communicators import GROUP_PREFIX
from .collective_causes import OPERATIONS as INTRA_OPERATIONS, ROOT_NONE, uint

ROOT_SELF = ROOT_NONE - 1
ROOT_THIS_GROUP = ROOT_NONE - 2
OPERATIONS = {
    name: value
    for name, value in INTRA_OPERATIONS.items()
    if name not in ("SCAN", "EXSCAN", "REDUCE_SCATTER")
}
OPERATIONS["BARRIER"] = 0
ROOTED = frozenset(("BCAST", "SCATTER", "SCATTERV", "GATHER", "GATHERV", "REDUCE"))


@dataclasses.dataclass(slots=True)
class Domain:
    groups: tuple
    flags: tuple
    world: tuple
    owners: dict
    by_process: dict

    @property
    def members(self):
        return frozenset(self.owners)

    def participant(self, definitions, location):
        row = definitions.get("Location", {}).get(str(location), {})
        owner = uint(row.get("locationGroup"), 64)
        if owner is None:
            return None
        return self.by_process.get(owner)


def domain(resolver, communicator):
    """Resolve exact, disjoint MPI process groups without coercing definitions."""
    definitions = resolver.defs
    if communicator in definitions.get("Comm", {}):
        return None
    inter = definitions.get("InterComm", {}).get(communicator, {})
    if not inter or uint(inter.get("flags", 0), 32) not in (0, 1):
        return None
    worlds = [
        row
        for row in definitions.get("Group", {}).values()
        if type(row.get("groupType")) is int
        and row["groupType"] in (4, 7)
        and uint(row.get("paradigm"), 8) == 4
    ]
    if len(worlds) != 1:
        return None
    world = worlds[0]
    raw_world = world.get("members")
    if (
        not isinstance(raw_world, (list, tuple))
        or not raw_world
        or any(uint(member, 64) is None or member == 2**64 - 1 for member in raw_world)
        or len(set(raw_world)) != len(raw_world)
        or uint(world.get("groupFlags", 0), 32) != 0
    ):
        return None
    prefix = GROUP_PREFIX if world["groupType"] == 7 else ""
    world_ids = tuple(prefix + str(member) for member in raw_world)
    groups = []
    flags = []
    for field in ("groupA", "groupB"):
        ref = uint(inter.get(field), 32)
        if ref is None or ref == 2**32 - 1:
            return None
        group = definitions.get("Group", {}).get(str(ref), {})
        # COMM_SELF does not encode which side's one process it represents.
        if uint(group.get("groupType"), 8) != 5 or uint(group.get("paradigm"), 8) != 4:
            return None
        flag = uint(group.get("groupFlags", 0), 32)
        members = group.get("members")
        if (
            flag not in (0, 1)
            or not isinstance(members, (list, tuple))
            or not members
            or any(uint(rank, 64) is None or rank >= len(world_ids) for rank in members)
            or len(set(members)) != len(members)
        ):
            return None
        groups.append(tuple(world_ids[rank] for rank in members))
        flags.append(flag)
    if set(groups[0]) & set(groups[1]):
        return None
    owners = {}
    for member in (*groups[0], *groups[1]):
        if prefix:
            owner = int(member[len(prefix) :])
        else:
            row = definitions.get("Location", {}).get(member, {})
            owner = uint(row.get("locationGroup"), 64)
        if owner is None or owner == 2**64 - 1:
            return None
        group = definitions.get("LocationGroup", {}).get(str(owner), {})
        if uint(group.get("locationGroupType"), 8) != 1:
            return None
        owners[member] = owner
    if len(set(owners.values())) != len(owners):
        return None
    return Domain(
        tuple(groups),
        tuple(flags),
        world_ids,
        owners,
        {owner: member for member, owner in owners.items()},
    )


@dataclasses.dataclass(slots=True)
class Channel:
    sources: frozenset
    targets: frozenset
    latest: dict
    evidence: dict


@dataclasses.dataclass(slots=True)
class IntercommPlan:
    channels: tuple
    sources: frozenset
    targets: frozenset
    clock_invalid: frozenset
    evidence: dict
    reason: str
    by_target: dict

    def latest_for(self, participant):
        channel = self.by_target.get(participant)
        return channel.latest if channel else None

    def shared_views(self, ident, communicator, peers):
        """At most two shared lists and one target reference per participant."""
        by_source = {str(peer[0]): peer for peer in peers}
        views = {}
        weight = 0
        for number, channel in enumerate(self.channels):
            shared = BarrierCohort(
                ident + ":intercomm:" + str(number),
                communicator,
                (by_source[source] for source in channel.sources),
                kind=(
                    "barrier_arrival"
                    if self.evidence["operation"] == "BARRIER"
                    else "collective_payload"
                ),
                reason=self.reason,
                expected_prerequisites=len(channel.sources),
                extra=dict(payload=dict(self.evidence, **channel.evidence)),
            )
            weight += shared.storage_weight
            views.update((target, shared) for target in channel.targets)
        return views, weight


def plan(cohort, resolver):
    name = cohort["operation"].upper().removeprefix("MPI_")
    status = dict(
        operation=name,
        status="unresolved",
        intercommunicator=True,
        interpretation="Remote-group completion prerequisites; these are not measured blocked time.",
    )

    def reject(code, message):
        return None, dict(status, code=code, message=message)

    if name not in OPERATIONS:
        return reject(
            "intercomm-operation-unresolved",
            "This intercommunicator operation has no implemented complete directed prerequisite contract.",
        )
    if (
        not cohort["complete"]
        or not cohort["sequenceReliable"]
        or not cohort["evidence"].get("validIntervals")
        or cohort["evidence"].get("recordingContinuity", {}).get("complete") is False
    ):
        return reject(
            "cohort-unresolved",
            "Complete, continuously recorded, consistently ordered participation in both groups is required.",
        )
    scope = domain(resolver, cohort["comm"])
    if scope is None:
        return reject(
            "intercomm-domain-unresolved",
            "Two nonempty disjoint typed MPI COMM_GROUPs, one unique MPI world and unique declared process scopes are required.",
        )
    participants = cohort["participants"]
    by_id = {p["participant"]: p for p in participants}
    if len(by_id) != len(participants) or set(by_id) != scope.members:
        return reject(
            "intercomm-domain-unresolved",
            "Each declared process must have exactly one participant in the cohort.",
        )
    sizes = {}
    roots = {}
    for p in participants:
        if (
            p.get("recordKind")
            not in ("MpiCollectiveEnd", "NonBlockingCollectiveComplete")
            or uint(p.get("recordedOp"), 8) != OPERATIONS[name]
            or uint(p.get("recordedComm"), 32) is None
            or str(p["recordedComm"]) != cohort["comm"]
        ):
            return reject(
                "record-contract-unresolved",
                "Original typed OTF2 collective operation and communicator must match the cohort.",
            )
        if (
            scope.participant(resolver.defs, p["location"]) != p["participant"]
            or scope.participant(resolver.defs, p.get("initiationLocation"))
            != p["participant"]
        ):
            return reject(
                "intercomm-domain-unresolved",
                "Initiation and completion must belong to the same uniquely declared MPI process.",
            )
        routine = (
            "i" if p["recordKind"] == "NonBlockingCollectiveComplete" else ""
        ) + name.lower()
        apis = {
            prefix + routine + suffix
            for prefix in ("mpi_", "pmpi_")
            for suffix in (("",) if name == "BARRIER" else ("", "_c"))
        }
        if (
            not p.get("initiationRoutineComplete")
            or uint(p.get("initiationParadigm"), 8) != 4
            or not isinstance(p.get("initiationName"), str)
            or p["initiationName"].casefold() not in apis
        ):
            return reject(
                "api-family-unresolved",
                "Every participant needs the exact complete initiating MPI API and the original typed MPI paradigm.",
            )
        if (
            not all(
                isinstance(p.get(key), (int, float)) and math.isfinite(p[key])
                for key in ("start", "end")
            )
            or p["end"] < p["start"]
        ):
            return reject(
                "cohort-unresolved",
                "Every participant needs a finite noninverted original collective bracket.",
            )
        root = uint(p.get("root"), 32)
        if root is None:
            return reject(
                "root-inconsistent",
                "Every participant requires an original typed collective root value.",
            )
        roots[p["participant"]] = root
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
                "Original finite uint64 payload sizes are required; missing or malformed sizes are not reconstructed.",
            )
        sizes[p["participant"]] = (sent, received)
    groups = tuple(frozenset(group) for group in scope.groups)
    root = None
    inactive = frozenset()
    if name in ROOTED:
        root_ids = [
            participant for participant, value in roots.items() if value == ROOT_SELF
        ]
        if len(root_ids) != 1:
            return reject(
                "root-inconsistent",
                "A rooted intercommunicator collective must record exactly one ROOT_SELF participant.",
            )
        root = root_ids[0]
        side = 0 if root in groups[0] else 1
        local = groups[side]
        remote = groups[1 - side]
        inactive = local - {root}
        if any(roots[participant] != ROOT_THIS_GROUP for participant in inactive):
            return reject(
                "root-inconsistent",
                "Other members of the root group must record ROOT_THIS_GROUP.",
            )
        for participant in remote:
            rank = roots[participant]
            rank_domain = scope.world if scope.flags[side] & 1 else scope.groups[side]
            if rank >= len(rank_domain) or rank_domain[rank] != root:
                return reject(
                    "root-inconsistent",
                    "Every remote root rank must identify the same ROOT_SELF process in the proper rank domain.",
                )
        if any(sizes[participant] != (0, 0) for participant in inactive):
            return reject(
                "payload-inconsistent",
                "Inactive ROOT_THIS_GROUP participants cannot record positive payload roles.",
            )
        if name in ("BCAST", "SCATTER", "SCATTERV"):
            directions = [(frozenset((root,)), remote, "root-to-remote-group")]
        else:
            directions = [(remote, frozenset((root,)), "remote-group-to-root")]
    else:
        if any(root != ROOT_NONE for root in roots.values()):
            return reject(
                "root-inconsistent",
                "This rootless intercommunicator collective must record ROOT_NONE on both groups.",
            )
        directions = [
            (groups[0], groups[1], "group-a-to-group-b"),
            (groups[1], groups[0], "group-b-to-group-a"),
        ]
    channels = []
    unproven = []
    invalid = set()
    for sources, targets, direction in directions:
        sends = {sizes[source][0] for source in sources}
        receives = {sizes[target][1] for target in targets}
        if name != "BARRIER":
            if 0 in sends or 0 in receives:
                unproven.append(
                    dict(direction=direction, code="payload-zero-or-unrecorded")
                )
                continue
            if name not in ("GATHERV", "SCATTERV", "ALLGATHERV") and (
                len(sends) > 1 or len(receives) > 1
            ):
                unproven.append(dict(direction=direction, code="payload-inconsistent"))
                continue
            if root is not None and (
                (
                    name in ("BCAST", "SCATTER", "SCATTERV")
                    and max(sends) < max(receives)
                )
                or (
                    name in ("GATHER", "GATHERV", "REDUCE")
                    and max(receives) < max(sends)
                )
            ):
                unproven.append(dict(direction=direction, code="payload-inconsistent"))
                continue
        latest = max((by_id[source] for source in sources), key=lambda p: p["start"])
        invalid.update(
            target for target in targets if latest["start"] > by_id[target]["end"]
        )
        channels.append(
            Channel(
                sources,
                targets,
                latest,
                dict(
                    direction=direction,
                    sourceCount=len(sources),
                    targetCount=len(targets),
                    expectedPrerequisites=len(sources),
                ),
            )
        )
    if not channels:
        code = unproven[0]["code"] if unproven else "intercomm-operation-unresolved"
        return reject(
            code,
            "No direction has a complete positively evidenced source and receiver payload role.",
        )
    evidence = dict(
        status,
        status="directed-remote-group-prerequisites",
        root=root,
        groupSizes=[len(group) for group in groups],
        groupReferences=[
            resolver.defs["InterComm"][cohort["comm"]][field]
            for field in ("groupA", "groupB")
        ],
        inactiveParticipantCount=len(inactive),
        inactiveParticipants=sorted(inactive)[:16],
        unprovenDirections=unproven,
        clockInvalidTargets=sorted(invalid)[:16],
        clockInvalidTargetCount=len(invalid),
        directions=[channel.evidence for channel in channels],
        apiFamily="complete exact initiating MPI API with original typed MPI Region paradigm",
        sourceContract="Local OTF2 InterComm/root definitions, Open MPI collective semantics and Score-P byte accounting.",
        guard="Complete continuously recorded cohort; exact disjoint MPI process groups; original typed API/event/root fields; positive payload for every directed role, except Barrier.",
        zeroInterpretation="Zero optional payload leaves that direction unresolved; no missing count or known absent communication is inferred.",
        sameGroupPrerequisites=False,
    )
    reason = (
        "An intercommunicator barrier cannot complete before every process in the remote group enters; local-group entries are not prerequisites."
        if name == "BARRIER"
        else name
        + " completion requires the positively evidenced inputs from its declared remote-group sources; local-group participants are not remote prerequisites."
    )
    targets = frozenset(target for channel in channels for target in channel.targets)
    sources = frozenset(source for channel in channels for source in channel.sources)
    return (
        IntercommPlan(
            tuple(channels),
            sources,
            targets,
            frozenset(invalid),
            evidence,
            reason,
            {target: channel for channel in channels for target in channel.targets},
        ),
        evidence,
    )
