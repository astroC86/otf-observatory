"""Recorded thread lifetimes, fork/join nesting, and team graph relations."""

import collections

from ..trace.definitions import enum
from ..trace.event_spans import WorkBudget
from ..mpi.communicators import Communicators
from ..mpi.rma_lock_graph import RMA_LOCK_KINDS
from ..threads.lifecycle import native_thread_lifecycle
from ..threads.lock_dependencies import analyze_thread_locks
from ..threads.lock_waits import LOCK_KINDS
from .common import _members


def _thread_lifetimes(out, events):
    """Present only validated physical lifetimes; retain other endpoints."""
    endpoints = [
        event for event in events if event["kind"] in ("ThreadBegin", "ThreadEnd")
    ]
    if not endpoints:
        return
    lifecycle = None
    if not out.scan_truncated:
        try:
            lifecycle = native_thread_lifecycle(
                out.trace, include_operations=False, charge=WorkBudget(out.cap)
            )
        except OverflowError:
            out.scan_truncated = True
    if lifecycle is None:
        out.warn(
            "thread-lifetime-context-partial",
            "Incomplete lifecycle context prevents validated thread lifetime intervals; raw endpoints remain inspectable.",
        )
    else:
        for code, count in lifecycle["diagnostics"].items():
            out.warn(code, code.replace("_", " "), count)
    by_id = {event["id"]: event for event in endpoints}
    matched = set()
    if lifecycle is not None:
        for lifetime in lifecycle["lifetimesByEndEvent"].values():
            begin = by_id.get(lifetime["beginEvent"])
            end = by_id.get(lifetime["endEvent"])
            if begin is None or end is None:
                continue
            data = dict(lifetime, contingent=lifetime["endContingent"])
            out.interval(begin, end, "thread", "Thread lifetime", data)
            out.edge(begin, end, "thread-lifetime", "Thread begin → end", data=data)
            matched.update((begin["id"], end["id"]))
    for event in endpoints:
        if event["id"] in matched:
            continue
        observation = (
            lifecycle["observations"].get(event["id"])
            if lifecycle is not None
            else None
        )
        issues = (
            lifecycle["lifecycleIssuesByEndEvent"].get(event["id"], [])
            if lifecycle is not None
            else ["incomplete-context"]
        )
        if not issues:
            issues = [
                "unmatched-begin" if event["kind"] == "ThreadBegin" else "unmatched-end"
            ]
        out.interval(
            event,
            event,
            "thread",
            "Thread lifecycle observation",
            dict(observation=observation, lifecycleIssues=issues, complete=False),
            confidence="unresolved-lifetime",
            status="; ".join(issues),
        )


def analyze_threads(out, events):
    """Append thread relations in their recorded traversal order."""
    trace = out.trace
    threads = collections.defaultdict(lambda: collections.defaultdict(list))
    forks = collections.defaultdict(list)
    parallel = {}
    teams = collections.defaultdict(list)
    team_instances = collections.defaultdict(int)
    memberships = []
    team_forks = {}

    for e in events:
        k = e["kind"]
        d = e["data"]
        loc = str(e["location"])
        out.node(e)
        if k in RMA_LOCK_KINDS or k in LOCK_KINDS:
            continue
        elif k in ("ThreadCreate", "ThreadBegin", "ThreadWait", "ThreadEnd"):
            comm, sequence = d.get("threadContingent"), d.get("sequenceCount")
            if (
                type(comm) is not int
                or not 0 <= comm < 2**32 - 1
                or type(sequence) is not int
                or not 0 <= sequence < 2**64
            ):
                out.warn(
                    "thread-identity-invalid",
                    "A thread contingent or sequence has an invalid unsigned identity and cannot establish a create/wait correspondence.",
                )
                continue
            key = (str(d.get("threadContingent")), str(d.get("sequenceCount")))
            if sequence != 2**64 - 1:
                if threads[key][k]:
                    out.warn(
                        "duplicate-thread-identity",
                        "Repeated thread contingent/sequence identifiers are ambiguous.",
                    )
                threads[key][k].append(e)
        elif k in ("ThreadFork", "OmpFork"):
            forks[loc].append(e)
        elif k in ("ThreadJoin", "OmpJoin"):
            if forks[loc]:
                first = forks[loc].pop()
                parallel[first["id"]] = e
                out.edge(
                    first,
                    e,
                    "fork-join",
                    "Fork → join",
                    data={"model": d.get("model", 3)},
                )
                out.interval(
                    first,
                    e,
                    "parallel",
                    "Parallel team",
                    dict(
                        requestedThreads=first["data"].get(
                            "numberOfRequestedThreads",
                            first["data"].get("numberOfThreads"),
                        ),
                        model=enum("OTF2_PARADIGM_", d.get("model", 3)),
                    ),
                )
            else:
                out.warn(
                    "fork-missing",
                    "Join has no matching local fork in the scanned context.",
                )
        elif k == "ThreadTeamBegin":
            comm = str(d.get("threadTeam"))
            tk = (comm, loc)
            occurrence = team_instances[tk]
            team_instances[tk] += 1
            teams[tk].append((e, occurrence))
            members = _members(trace, comm)
            if members and loc == members[0] and forks[loc]:
                team_forks[(comm, occurrence)] = forks[loc][-1]
        elif k == "ThreadTeamEnd":
            comm = str(d.get("threadTeam"))
            tk = (comm, loc)
            if teams[tk]:
                first, occurrence = teams[tk].pop()
                out.interval(
                    first,
                    e,
                    "team",
                    "Team " + comm,
                    dict(team=comm, occurrence=occurrence),
                )
                memberships.append((comm, occurrence, first, e))
            else:
                out.warn(
                    "team-begin-missing",
                    "Team end has no matching begin in the scanned context.",
                )
    _thread_lifetimes(out, events)
    analyze_thread_locks(out, events)
    resolver = Communicators(trace.defs)
    for key, pair in threads.items():
        if out.scan_truncated:
            # A bounded scan can omit another endpoint with this identity.
            # Observed uniqueness is insufficient for a peer correspondence.
            continue
        comm = trace.defs.get("Comm", {}).get(key[0])
        inter = trace.defs.get("InterComm", {}).get(key[0])
        references = (
            [comm.get("group")]
            if comm
            else ([inter.get("groupA"), inter.get("groupB")] if inter else [])
        )
        groups = [resolver.group(ref) for ref in references]
        valid = bool(groups) and all(
            group.get("groupType") in (5, 6) for group in groups
        )
        valid = valid and all(
            group.get("paradigm") == groups[0].get("paradigm") for group in groups
        )
        members = (
            [member for ref in references for member in resolver.members(ref)]
            if valid
            else []
        )
        for a, b, kind, label in [
            ("ThreadCreate", "ThreadBegin", "thread-create", "Thread created → begins"),
            ("ThreadEnd", "ThreadWait", "thread-wait", "Thread end → wait/join record"),
        ]:
            if len(pair[a]) == len(pair[b]) == 1:
                if not all(
                    str(event["location"]) in members
                    or resolver.request_scope(event["location"]) in members
                    for event in (pair[a][0], pair[b][0])
                ):
                    out.warn(
                        "thread-peer-membership-unresolved",
                        "Thread counterpart locations are not both members of their recorded contingent.",
                    )
                    continue
                if pair[a][0]["location"] == pair[b][0]["location"]:
                    out.warn(
                        "thread-peer-same-location",
                        "A thread creation/join counterpart is recorded on the same execution location.",
                    )
                    continue
                out.edge(
                    pair[a][0],
                    pair[b][0],
                    kind,
                    label,
                    data={"contingent": key[0], "sequence": key[1]},
                )
            elif not pair[a] or not pair[b]:
                out.warn(
                    "thread-peer-missing",
                    "A thread lifecycle identifier has only one recorded endpoint.",
                )
    for comm, occurrence, first, last in memberships:
        fork = team_forks.get((comm, occurrence))
        if fork:
            out.edge(
                fork,
                first,
                "team-start",
                "Fork → team member begins",
                "recorded-context",
                {"team": comm, "occurrence": occurrence},
            )
            if fork["id"] in parallel:
                out.edge(
                    last,
                    parallel[fork["id"]],
                    "team-finish",
                    "Team member ends → join",
                    "recorded-context",
                    {"team": comm, "occurrence": occurrence},
                )
        else:
            out.warn(
                "team-fork-unresolved",
                "Team membership is recorded but its parent fork cannot be established from master-thread nesting.",
            )
    for loc, values in forks.items():
        for first in values:
            out.interval(
                first, None, "parallel", "Parallel team", status="missing join"
            )
    for key, values in teams.items():
        for first, occurrence in values:
            out.interval(
                first,
                None,
                "team",
                "Team " + key[0],
                dict(team=key[0], occurrence=occurrence),
                status="missing end",
            )
