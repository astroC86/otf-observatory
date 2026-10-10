"""Producer-qualified Score-P reduce-scatter byte profiles."""

from .collective_causes import PayloadPlan, ROOT_NONE, uint


def _scorep_reduce_scatter_plan(cohort, resolver, group, sizes, by_id, status, reject):
    """Positive local output under the exact audited Score-P byte contract.

    For local output bytes b_i and common input bytes B=sum(b_i), Score-P10
    records (S_i,R_i)=(B,N*b_i) or (B-b_i,(N-1)*b_i) in place. Retain all
    compatible profiles, without guessing which local in-place mode was used.
    A zero receive is never promoted to a known absent result/prerequisite.
    """
    archives = list(resolver.defs.get("ArchiveProperties", {}).values())
    if len(archives) != 1 or archives[0].get("creator") != "Score-P 10.0":
        return reject(
            "producer-contract-unverified",
            "Variable reduce-scatter local-output bytes require the audited exact Score-P 10.0 archive creator.",
        )
    if uint(group.get("paradigm"), 8) != 4:
        return reject(
            "producer-contract-unverified",
            "The producer contract requires an original MPI communicator-group paradigm.",
        )
    for participant in cohort["participants"]:
        routine = (
            "i" if participant["recordKind"] == "NonBlockingCollectiveComplete" else ""
        ) + "reduce_scatter"
        name = participant.get("initiationName")
        # The local Score-P10 recording wrappers call the regular count helper.
        # A large-count helper exists, but no *_c recording wrapper was verified.
        if (
            not participant.get("initiationRoutineComplete")
            or uint(participant.get("initiationParadigm"), 8) != 4
            or not isinstance(name, str)
            or name.casefold() != "mpi_" + routine
        ):
            return reject(
                "producer-contract-unverified",
                "The audited Score-P 10.0 regular-count recording wrapper needs a complete exact MPI_Reduce_scatter or MPI_Ireduce_scatter initiating region with the original MPI paradigm.",
            )
    count = len(by_id)
    if count < 2:
        return reject(
            "no-remote-participants",
            "A one-participant reduce-scatter has no remote prerequisites.",
        )
    # The audited regular-count helper multiplies the receive expression as
    # signed int before assigning to uint64_t. Stay within signed32 rather
    # than explaining large/negative-cast results by an overflow convention.
    if any(received > 2**31 - 1 for sent, received in sizes.values()):
        return reject(
            "producer-payload-overflow",
            "The regular-count receive byte expression exceeds the audited signed32 arithmetic range; overflow is not repaired or used as payload evidence.",
        )
    # Each row supplies at most two candidate common totals. At a fixed B,
    # both modes can coincide only when R_i=0, with the same zero byte term.
    # This keeps complete profile consistency O(N), not 2**N combinations.
    candidates = set()
    rows = []
    for sent, received in sizes.values():
        row = {}
        if received % count == 0:
            row[sent] = received // count
        if received % (count - 1) == 0:
            local = received // (count - 1)
            total = sent + local
            if total < 2**64 - 1:
                row[total] = local
        candidates = candidates & row.keys() if rows else set(row)
        rows.append(row)
        if not candidates:
            return reject(
                "producer-payload-inconsistent",
                "The original byte pairs cannot share a Score-P 10.0 reduce-scatter input total under either recorded formula.",
            )
    candidates = sorted(
        total for total in candidates if sum(row[total] for row in rows) == total
    )
    if not candidates:
        return reject(
            "producer-payload-inconsistent",
            "The original byte pairs do not satisfy a complete common Score-P 10.0 reduce-scatter output profile.",
        )
    sources = frozenset(by_id)
    targets = frozenset(p for p in by_id if sizes[p][1] > 0)
    if not targets:
        return reject(
            "payload-zero-or-unrecorded",
            "No positive producer-qualified local-output field establishes a nonempty result.",
        )
    latest = tuple(sorted(by_id.values(), key=lambda p: p["start"], reverse=True)[:2])
    invalid = frozenset(
        target
        for target in targets
        if next(p for p in latest if p["participant"] != target)["start"]
        > by_id[target]["end"]
    )
    unproven = sources - targets
    evidence = dict(
        status,
        status="directed-positive-payload",
        direction="all-contributors-to-positive-local-results",
        root=None,
        rootRank=ROOT_NONE,
        sourceCount=count,
        targetCount=len(targets),
        sourceBytes=None,
        targetBytes=None,
        clockInvalidTargets=sorted(invalid)[:16],
        clockInvalidTargetCount=len(invalid),
        producer="Score-P 10.0",
        producerContract="scorep-10.0-reduce-scatter-bytes",
        compatibleProfileCount=len(candidates),
        compatibleAggregateByteCounts=[str(total) for total in candidates],
        localOutputEvidence="Positive sizeReceived is N or N-1 times this participant’s result bytes in the audited producer formulas; element counts and in-place mode are not inferred.",
        arithmeticScope="Exact nonnegative integer profiles within signed32 receive expressions and finite uint64 totals; no overflow wrapping or missing-byte reconstruction.",
        unprovenTargetCount=len(unproven),
        unprovenTargetPreview=sorted(unproven)[:16],
        zeroInterpretation="Zero received bytes retain an unresolved local-output role; those participants remain input sources for positively evidenced results.",
        guard="Exact recorded Score-P 10.0 creator, complete regular-count initiating MPI API regions, complete typed intracommunicator cohort, and an integer-consistent producer byte profile.",
        sourceContract="Local Score-P 10.0 scorep_mpi_coll.inc.c:638-684 and MPI_Reduce_scatter/Ireduce_scatter recording wrappers; local Open MPI Reduce_scatter semantics.",
    )
    reason = "The producer-qualified positive local result requires the input contribution of every other communicator participant, including participants whose own output is not evidenced as nonempty."
    return (
        PayloadPlan(sources, targets, latest, invalid, count - 1, evidence, reason),
        evidence,
    )
