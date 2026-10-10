"""Synchronization routine records, boundary lookup, and thread-team identity."""

from __future__ import annotations

import bisect
import collections
import dataclasses
import re

from ..causality.lazy_causes import CauseCollection
from ..causality.operations import BoundaryOrder


@dataclasses.dataclass(slots=True)
class Span:
    id: int
    location: str
    region: str
    start: float
    end: float
    depth: int
    incomplete: int
    sampled: int
    name: str
    category: str


@dataclasses.dataclass(slots=True)
class Record:
    """Mutable attribution state with an explicit observed upper endpoint."""

    span: Span
    start: float
    end: float
    category: str
    deadline: float
    upper_end: float
    confidence: str = "observed-routine"
    peer: str | None = None
    evidence: dict = dataclasses.field(default_factory=dict)
    causes: CauseCollection = dataclasses.field(default_factory=CauseCollection)
    inferred_intervals: list | None = None


def routine_category(region, taskgroup=False):
    if taskgroup:
        return "task_group"
    group = region.get("group", "").upper()
    name = region.get("name", "")
    low = name.casefold()
    role = region.get("role", "")
    if group == "MPI" or re.search(r"\bp?mpi_", low):
        return None
    if group in ("CUDA", "HIP", "OPENCL", "OPENACC", "OPENMP_TARGET"):
        from ..gpu.api import cuda_context_event_action

        context_event = cuda_context_event_action(
            dict(label=name, data=dict(paradigm=group))
        )
        if (
            "streamwaitevent" in low
            or context_event
            and context_event[0] == "context-wait"
            or "acc_wait" in low
            and "async" in low
        ):
            return "gpu_dependency_enqueue"
        if re.search(r"synchron|waitevent|waitforevents|\bclfinish\b|\bacc_wait", low):
            return "gpu_synchronization"
        return None
    if role in ("BARRIER", "IMPLICIT_BARRIER") or re.search(
        r"(?:omp|gomp|kmp|pthread).*barrier", low
    ):
        return (
            "openmp_barrier" if group == "OPENMP" or "omp" in low else "thread_barrier"
        )
    if role == "TASK_WAIT" or re.search(
        r"taskwait|task_wait|taskgroup.*(?:end|wait)", low
    ):
        return "task_wait"
    if role == "THREAD_WAIT" or re.search(
        r"pthread_join|thrd_join|std::.*thread::join", low
    ):
        return "thread_join"
    if re.search(r"(?:test|try).*lock|lock.*(?:try|test)", low):
        return "lock_test"
    if re.search(
        r"omp_set_(?:nest_)?lock|pthread_mutex_lock|pthread_rwlock_(?:rd|wr)lock|\bmtx_lock\b|std::.*mutex.*::lock",
        low,
    ):
        return "lock_acquire"
    if role in ("CRITICAL", "ORDERED"):
        return "critical_acquire"
    if re.search(
        r"pthread_cond_(?:timed)?wait|cnd_(?:timed)?wait|sem_(?:timed)?wait", low
    ):
        return "condition_wait"
    if group == "OPENMP" and ("join" in low or "parallel_end" in low):
        return "thread_join"
    return None


class Lookup:
    def __init__(self, spans, trace):
        self.order = BoundaryOrder(trace)
        self.by_location = collections.defaultdict(list)
        for s in spans:
            self.by_location[s.location].append(s)
        self.starts = {}
        self.ends = {}
        for loc, rows in self.by_location.items():
            rows.sort(key=lambda s: (s.start, s.id))
            self.starts[loc] = [s.start for s in rows]
            high = -1.0
            ends = []
            for s in rows:
                high = max(high, s.end)
                ends.append(high)
            self.ends[loc] = ends

    def at(self, loc, t, categories=None, event=None):
        rows = self.by_location.get(loc, ())
        i = bisect.bisect_right(self.starts.get(loc, ()), t) - 1
        found = []
        while i >= 0 and self.ends[loc][i] >= t:
            s = rows[i]
            if s.end >= t and (categories is None or s.category in categories):
                found.append(s)
            i -= 1
        found = self.order.filter(found, loc, t, event)
        return max(found, key=lambda s: (s.depth, s.start, -s.id), default=None)


def team_members(trace, comm):
    """Resolve a causal thread team without dropping malformed members.

    Recorded fork/join operations name executing locations, not process-group
    representatives. A malformed/ambiguous rank domain cannot prove a complete
    barrier or team join even when the retained operations happen to match.
    """

    def uint(value, bits):
        return type(value) is int and 0 <= value < 2**bits - 1

    if str(comm) in trace.defs.get("InterComm", {}):
        return None
    definition = trace.defs.get("Comm", {}).get(str(comm), {})
    if not uint(definition.get("group"), 32):
        return None
    group = trace.defs.get("Group", {}).get(str(definition["group"]), {})
    if group.get("groupType") != 5:
        return None
    flags = group.get("groupFlags", 0)
    if type(flags) is not int or flags not in (0, 1):
        return None
    worlds = [
        world
        for world in trace.defs.get("Group", {}).values()
        if world.get("groupType") in (4, 7)
        and world.get("paradigm") == group.get("paradigm")
    ]
    if len(worlds) != 1 or worlds[0].get("groupType") != 4:
        return None
    world = worlds[0].get("members")
    members = group.get("members")
    if not isinstance(world, (list, tuple)) or not isinstance(members, (list, tuple)):
        return None
    if any(not uint(value, 64) for value in world) or len(set(world)) != len(world):
        return None
    if any(not uint(rank, 64) or rank >= len(world) for rank in members) or len(
        set(members)
    ) != len(members):
        return None
    locations = [str(world[rank]) for rank in members]
    if any(location not in trace.defs.get("Location", {}) for location in locations):
        return None
    # GLOBAL_MEMBERS alters recorded rank encoding, not the team's membership.
    return locations
