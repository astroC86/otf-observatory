"""Replay RMA lock identities and window lifetimes in recorded order."""

import collections

from .communicators import Communicators, GROUP_PREFIX

LOCK_EVENTS = ("RmaRequestLock", "RmaAcquireLock", "RmaReleaseLock", "RmaTryLock")
ALL_TARGETS = 2**32 - 1


def _uint(value, bits):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        number = int(value)
    except ValueError:
        return None
    return number if 0 <= number < 2**bits else None


def replay(definitions, events, warn, step):
    comms = Communicators(definitions)
    attempts, ownership, tests = [], [], []
    requests = collections.defaultdict(list)
    acquired = collections.defaultdict(list)
    lifetimes = {}
    reused_windows = set()

    # OTF2 defers a Destroy inside a destroying collective until its End.
    brackets, deferred, closes = {}, {}, collections.defaultdict(list)
    for event in events:
        step()
        loc, kind, data = str(event["location"]), event["kind"], event["data"]
        if kind == "RmaCollectiveBegin":
            if loc in brackets:
                warn(
                    "rma-lock-collective-lifetime-ambiguous",
                    "Nested or replaced RMA collective beginnings cannot establish a window destruction boundary.",
                )
            brackets[loc] = (event, [], loc not in brackets)
        elif kind == "RmaWinDestroy" and loc in brackets:
            brackets[loc][1].append(event)
            deferred[event["id"]] = None
        elif kind == "RmaCollectiveEnd":
            bracket = brackets.pop(loc, None)
            if not bracket:
                continue
            begin, destroys, valid = bracket
            for destroyed in destroys:
                if (
                    valid
                    and data.get("collectiveOp") in (18, 22)
                    and str(data.get("win")) == str(destroyed["data"].get("win"))
                    and begin["time"] <= destroyed["time"] <= event["time"]
                ):
                    deferred[destroyed["id"]] = event
                    closes[event["id"]].append(destroyed)

    def identity(event):
        data = event["data"]
        window = _uint(data.get("win"), 32)
        remote = _uint(data.get("remote"), 32)
        lock = _uint(data.get("lockId"), 64)
        if window is None or remote is None or lock is None:
            warn(
                "rma-lock-identity-missing",
                "An RMA lock record lacks valid window, remote rank or unsigned lock identity.",
            )
            return None
        win = definitions.get("RmaWin", {}).get(str(window), {})
        local = comms.local(win.get("comm"), event["location"])
        # A COMM_LOCATION_GROUPS rank owns process-scoped state; a location
        # rank retains its location scope, including unknown definitions.
        scope = (
            local
            if local and local.startswith(GROUP_PREFIX)
            else str(event["location"])
        )
        comm = definitions.get("Comm", {}).get(str(win.get("comm")), {})
        members = comms.members(comm.get("group"))
        target = (
            comms.peer(win.get("comm"), remote, event["location"])
            if remote != ALL_TARGETS
            else None
        )
        valid = (
            bool(win)
            and local is not None
            and (
                target is not None
                or remote == ALL_TARGETS
                and bool(members)
                and None not in members
            )
        )
        if not valid:
            warn(
                "rma-lock-resource-unresolved",
                "The window, origin rank or remote target cannot be resolved; raw lock records remain visible without required attribution.",
            )
        life = lifetimes.get((scope, str(window)))
        if win.get("flags", 0) & 1:
            if not life or not life["active"] or life["ambiguous"]:
                valid = False
                warn(
                    "rma-lock-window-lifetime-unresolved",
                    "A lock record is outside a uniquely recorded live window lifetime.",
                )
        epoch = life["generation"] if life else 0
        return dict(
            window=str(window),
            remoteRank=str(remote),
            lock=str(lock),
            target=target,
            targetIdentity=target,
            allTargets=remote == ALL_TARGETS,
            scope=scope,
            communicator=str(win.get("comm")) if win else None,
            lifetime=epoch,
            windowCreateEvent=(
                life["create"]["id"] if life and life.get("create") else None
            ),
            resourceValid=valid,
            blockedTime=None,
            interpretation="Recorded request latency and incompatible lock availability; CPU blocked time is not recorded.",
        )

    def retire(event, destroyed=None):
        data = (destroyed or event)["data"]
        window = str(data.get("win"))
        win = definitions.get("RmaWin", {}).get(window, {})
        local = comms.local(win.get("comm"), event["location"])
        scope = (
            local
            if local and local.startswith(GROUP_PREFIX)
            else str(event["location"])
        )
        life = lifetimes.get((scope, window))
        if not life or not life["active"]:
            warn(
                "rma-lock-window-destroy-unmatched",
                "Window destruction has no unique active creation in this origin scope.",
            )
            return
        life["active"] = False
        life["destroy"] = event
        for keys, table, status in (
            (list(requests), requests, "missing grant at window destruction"),
            (list(acquired), acquired, "missing release at window destruction"),
        ):
            for ident in keys:
                if ident[:2] != (scope, window):
                    continue
                for row in table.pop(ident):
                    row["status"] = status
                    row["resourceValid"] = False
                    row["windowDestroyEvent"] = event["id"]

    for event in events:
        step()
        kind, data = event["kind"], event["data"]
        location = str(event["location"])
        if kind in ("RmaWinCreate", "RmaWinDestroy"):
            window = str(data.get("win"))
            win = definitions.get("RmaWin", {}).get(window, {})
            if not win or not win.get("flags", 0) & 1:
                warn(
                    "rma-lock-window-lifecycle-without-flag",
                    "Window lifecycle records require a defined CREATE_DESTROY_EVENTS window flag.",
                )
                continue
            local = comms.local(win.get("comm"), location)
            scope = local if local and local.startswith(GROUP_PREFIX) else location
            ident = scope, window
            old = lifetimes.get(ident)
            if kind == "RmaWinCreate":
                if old and old["active"]:
                    old["ambiguous"] = True
                    warn(
                        "rma-lock-window-create-ambiguous",
                        "Duplicate live window creation makes its lock lifetime ambiguous.",
                    )
                    for row in attempts + ownership:
                        if (
                            row["scope"] == scope
                            and row["window"] == window
                            and row["lifetime"] == old["generation"]
                        ):
                            row["resourceValid"] = False
                    continue
                generation = old["generation"] + 1 if old else 1
                if old:
                    reused_windows.add(window)
                    warn(
                        "rma-lock-window-generation-unresolved",
                        "Repeated local window lifetimes have no recorded cross-rank generation identity; required cross-rank attribution is suppressed.",
                    )
                lifetimes[ident] = dict(
                    generation=generation, create=event, active=True, ambiguous=False
                )
            elif event["id"] in deferred:
                if deferred[event["id"]] is None:
                    if old:
                        old["ambiguous"] = True
                    warn(
                        "rma-lock-window-destruction-incomplete",
                        "A window destruction inside a collective lacks a matching destroying collective end.",
                    )
            else:
                retire(event)
            continue
        if kind == "RmaCollectiveEnd":
            for destroyed in closes.get(event["id"], ()):
                retire(event, destroyed)
            continue
        if kind not in LOCK_EVENTS:
            continue
        info = identity(event)
        if info is None:
            continue
        if kind != "RmaReleaseLock" and data.get("lockType") not in (0, 1):
            warn(
                "rma-lock-type-missing",
                "A lock request, grant or test lacks a valid shared/exclusive type.",
            )
            continue
        ident = (
            info["scope"],
            info["window"],
            info["lifetime"],
            info["remoteRank"],
            info["lock"],
        )
        if kind == "RmaRequestLock":
            row = dict(
                info,
                id="rma-lock-request:" + str(event["id"]),
                request=event,
                grant=None,
                status="missing grant",
                causes=[],
                lockType="shared" if data["lockType"] == 1 else "exclusive",
                unavailableSeconds=0.0,
                conflictingOwners=0,
                completeOwnerSet=False,
                unresolvedReasons=[],
            )
            requests[ident].append(row)
            attempts.append(row)
        elif kind == "RmaTryLock":
            tests.append(
                dict(
                    info,
                    event=event,
                    status="unsuccessful",
                    lockType="shared" if data["lockType"] == 1 else "exclusive",
                )
            )
        elif kind == "RmaAcquireLock":
            pending = requests.pop(ident, [])
            if len(pending) == 1:
                row = pending[0]
                if row["request"]["data"]["lockType"] != data["lockType"]:
                    row["status"] = "request/grant type mismatch"
                    warn(
                        "rma-lock-type-mismatch",
                        "An RMA grant and its request have different lock types.",
                    )
                elif row["request"]["time"] > event["time"]:
                    row["status"] = "clock inversion"
                    warn(
                        "rma-lock-clock-conflict",
                        "An RMA lock grant precedes its recorded request.",
                    )
                else:
                    row.update(
                        grant=event,
                        status="complete",
                        resourceValid=row["resourceValid"] and info["resourceValid"],
                    )
            elif len(pending) > 1:
                for row in pending:
                    row["status"] = "ambiguous repeated request"
                warn(
                    "rma-lock-request-ambiguous",
                    "Several outstanding requests share an origin, window, target and lock identity.",
                )
            row = dict(
                info,
                acquire=event,
                release=None,
                status="missing release",
                lockType="shared" if data["lockType"] == 1 else "exclusive",
            )
            acquired[ident].append(row)
            ownership.append(row)
        else:
            owners = acquired.pop(ident, [])
            if len(owners) == 1:
                row = owners[0]
                if row["acquire"]["time"] > event["time"]:
                    row["status"] = "clock inversion"
                    warn(
                        "rma-lock-clock-conflict",
                        "An RMA lock release precedes its recorded acquisition.",
                    )
                else:
                    row.update(
                        release=event,
                        status="complete",
                        resourceValid=row["resourceValid"] and info["resourceValid"],
                    )
            else:
                for row in owners:
                    row["status"] = "ambiguous repeated acquisition"
                warn(
                    "rma-lock-owner-unresolved",
                    "An RMA release has missing or duplicate ownership grants.",
                )
    return attempts, ownership, tests, reused_windows
