"""Attribute incompatible ownership intervals to recorded RMA lock requests."""

import collections

from ..causality.operations import Operation, prerequisite
from .rma_lock_intervals import _index, _overlap, _union
from .rma_lock_replay import LOCK_EVENTS, replay


def build_rma_lock_model(definitions, events, *, complete=True, charge=None):
    """Pure full-context replay; raw records and exact integer IDs are retained.

    ``complete=False`` suppresses all required causes: a bounded scan could
    omit a duplicate identity or a window lifetime boundary.
    """
    diagnostics = collections.Counter()
    messages = {}

    def warn(code, message):
        diagnostics[code] += 1
        messages[code] = message

    def step():
        if charge is not None:
            charge()

    events = sorted(events, key=lambda event: event["id"])
    if complete and not any(event["kind"] in LOCK_EVENTS for event in events):
        return dict(
            attempts=[],
            ownership=[],
            tests=[],
            diagnostics=diagnostics,
            messages=messages,
            partial=False,
        )
    attempts, ownership, tests, reused_windows = replay(definitions, events, warn, step)

    owners = collections.defaultdict(list)
    for row in ownership:
        if row["status"] == "complete" and row["resourceValid"]:
            owners[(row["window"], row["lock"])].append(row)
    indices = {identity: _index(rows) for identity, rows in owners.items()}
    # A mutually exclusive ownership history must itself be possible. Merely
    # releasing both owners before a later grant does not repair overlapping
    # exclusive (or exclusive/shared) ownership of the same resource.
    inconsistent_owners = set()
    if complete:
        for identity, rows in owners.items():
            exclusive = _index([row for row in rows if row["lockType"] == "exclusive"])
            for owner in rows:
                step()
                peers = (
                    exclusive if owner["lockType"] == "shared" else indices[identity]
                )
                for peer in _overlap(
                    peers, owner["acquire"]["time"], owner["release"]["time"]
                ):
                    step()
                    if peer["acquire"]["id"] <= owner["acquire"]["id"]:
                        continue
                    if not (
                        owner["allTargets"]
                        or peer["allTargets"]
                        or owner["targetIdentity"] == peer["targetIdentity"]
                    ):
                        continue
                    inconsistent_owners.update(
                        (owner["acquire"]["id"], peer["acquire"]["id"])
                    )
                    owner["ownershipConflict"] = peer["ownershipConflict"] = True
                    warn(
                        "rma-lock-owner-overlap",
                        "Incompatible owners overlap on the same window, target and lock; required attribution using either ownership interval is suppressed.",
                    )
    if not complete:
        warn(
            "rma-lock-context-incomplete",
            "A bounded RMA scan may omit ownership, duplicate IDs or lifecycle boundaries; required attribution is suppressed.",
        )
    for attempt in attempts:
        step()
        if (
            not complete
            or attempt["status"] != "complete"
            or not attempt["resourceValid"]
            or attempt["window"] in reused_windows
        ):
            attempt["unresolvedReasons"] = (
                ([attempt["status"]] if attempt["status"] != "complete" else [])
                + (["incomplete-scan"] if not complete else [])
                + (
                    ["resource-or-lifetime-unresolved"]
                    if not attempt["resourceValid"]
                    else []
                )
                + (
                    ["window-generation-unresolved"]
                    if attempt["window"] in reused_windows
                    else []
                )
            )
            continue
        request, grant = attempt["request"], attempt["grant"]
        conflicts = []
        clock_conflict = False
        ownership_conflict = False
        for owner in _overlap(
            indices.get((attempt["window"], attempt["lock"])),
            request["time"],
            grant["time"],
        ):
            step()
            if owner["scope"] == attempt["scope"]:
                continue
            if not (
                owner["allTargets"]
                or attempt["allTargets"]
                or owner["targetIdentity"] == attempt["targetIdentity"]
            ):
                continue
            if owner["lockType"] == attempt["lockType"] == "shared":
                continue
            acquire, release = owner["acquire"], owner["release"]
            if acquire["id"] in inconsistent_owners:
                ownership_conflict = True
            if release["time"] > grant["time"]:
                warn(
                    "rma-lock-conflicting-ownership",
                    "Incompatible ownership extends beyond the recorded grant; its timing cannot establish a release prerequisite.",
                )
                clock_conflict = True
                continue
            source = Operation(
                str(release["location"]),
                None,
                release["id"],
                None,
                "RMA lock ownership",
                acquire["time"],
                release["time"],
                dict(
                    acquireEvent=acquire["id"],
                    acquireLocation=str(acquire["location"]),
                    window=owner["window"],
                    lock=owner["lock"],
                ),
            )
            target = Operation(
                str(request["location"]),
                None,
                grant["id"],
                None,
                "RMA lock request → grant",
                request["time"],
                grant["time"],
                dict(requestEvent=request["id"], grantLocation=str(grant["location"])),
            )
            cause = prerequisite(
                f"rma-lock:{release['id']}:{grant['id']}",
                "rma_lock_release",
                source,
                target,
                release["time"],
                target_start=max(request["time"], acquire["time"]),
                confidence="recorded-rma-lock-availability",
                communicator=attempt["communicator"],
                reason="An incompatible owner of the same window, target and lock must release before this recorded grant; the interval is resource unavailability, not measured CPU blocking.",
            )
            if cause is None:
                continue
            cause.extra = dict(
                window=attempt["window"],
                lock=attempt["lock"],
                remoteRank=attempt["remoteRank"],
                ownerRemoteRank=owner["remoteRank"],
                targetIdentity=attempt["targetIdentity"],
                requestEvent=request["id"],
                grantEvent=grant["id"],
                ownerAcquireEvent=acquire["id"],
                ownerReleaseEvent=release["id"],
                ownerAcquireTime=acquire["time"],
                requestTime=request["time"],
                grantTime=grant["time"],
                ownerScope=owner["scope"],
                requestScope=attempt["scope"],
                ownerLockType=owner["lockType"],
                requestLockType=attempt["lockType"],
                evidence=[acquire["id"], release["id"], request["id"], grant["id"]],
                blockedTime=None,
            )
            conflicts.append(cause)
        if clock_conflict:
            conflicts = []
            attempt["unresolvedReasons"].append("incompatible-ownership-past-grant")
        if ownership_conflict:
            conflicts = []
            attempt["unresolvedReasons"].append("incompatible-owner-overlap")
        attempt["causes"] = conflicts
        attempt["conflictingOwners"] = len(conflicts)
        attempt["unavailableSeconds"] = _union(
            (cause.start, cause.end) for cause in conflicts
        )
    return dict(
        attempts=attempts,
        ownership=ownership,
        tests=tests,
        diagnostics=diagnostics,
        messages=messages,
        partial=not complete,
    )
