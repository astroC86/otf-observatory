"""MPI routine classification and compact wait-analysis records."""

from __future__ import annotations

import bisect
import collections
import dataclasses
import itertools
import math
import operator
import re

from ..causality.operations import BoundaryOrder, tied
from ..causality.lazy_causes import CauseCollection

SEND = {"send", "ssend", "bsend", "rsend"}
RECEIVE = {"recv", "mrecv"}
SENDRECV = {"sendrecv", "sendrecv_replace"}
WAIT = {"wait", "waitall", "waitany", "waitsome"}
TEST = {
    "test",
    "testall",
    "testany",
    "testsome",
    "request_get_status",
    "iprobe",
    "improbe",
    "win_test",
}
COLLECTIVE = {
    "barrier",
    "bcast",
    "reduce",
    "allreduce",
    "gather",
    "gatherv",
    "allgather",
    "allgatherv",
    "scatter",
    "scatterv",
    "alltoall",
    "alltoallv",
    "alltoallw",
    "reduce_scatter",
    "reduce_scatter_block",
    "scan",
    "exscan",
    "neighbor_allgather",
    "neighbor_allgatherv",
    "neighbor_alltoall",
    "neighbor_alltoallv",
    "neighbor_alltoallw",
}
SYNCHRONIZATION = {
    "init",
    "init_thread",
    "finalize",
    "comm_dup",
    "comm_split",
    "comm_split_type",
    "comm_create",
    "comm_create_group",
    "comm_free",
    "comm_disconnect",
    "comm_spawn",
    "comm_spawn_multiple",
    "intercomm_create",
    "intercomm_merge",
}
RMA_SYNCHRONIZATION = {
    "win_fence",
    "win_wait",
    "win_lock",
    "win_lock_all",
    "win_unlock",
    "win_unlock_all",
    "win_flush",
    "win_flush_all",
    "win_flush_local",
    "win_flush_local_all",
    "win_complete",
    "win_sync",
    "win_free",
}

CATEGORY_BY_ROUTINE = {
    routine: category
    for routines, category in (
        (SEND, "blocking_send"),
        (RECEIVE, "blocking_receive"),
        (SENDRECV, "mpi_sendrecv"),
        (WAIT, "mpi_wait"),
        (TEST, "mpi_test"),
        (COLLECTIVE, "collective_routine"),
        ({"probe", "mprobe"}, "mpi_probe"),
        (SYNCHRONIZATION, "mpi_synchronization"),
        (RMA_SYNCHRONIZATION, "mpi_rma_synchronization"),
    )
    for routine in routines
}


def _routine(name):
    match = re.search(r"(?i)(?:^|\b)p?mpi_([a-z0-9_]+)", name)
    return match[1].lower().rstrip("_") if match else ""


@dataclasses.dataclass(slots=True)
class Span:
    id: int
    location: str
    region: str
    start: float
    end: float
    depth: int
    incomplete: bool
    sampled: bool
    name: str
    routine: str

    @property
    def complete(self):
        return not self.sampled and not self.incomplete


def _innermost(span):
    return (span.depth, -(span.end - span.start), span.start, -span.id)


class SpanLookup:
    def __init__(self, trace):
        self.order = BoundaryOrder(trace)
        self._prefetched = {}
        self._recent = {}
        self.by_location = collections.defaultdict(list)
        regions = {
            r["id"]: (r["name"], routine)
            for r in trace.meta["regions"]
            if (routine := _routine(r["name"]))
        }
        with trace.connect() as db:
            cursor = db.cursor()
            cursor.row_factory = None
            for row in cursor.execute(
                "SELECT id,location,region,start,end,depth,incomplete,sampled FROM spans WHERE region IN ("
                + ",".join("?" for _ in regions)
                + ")",
                list(regions),
            ):
                self.by_location[row[1]].append(Span(*row, *regions[row[2]]))
        self.starts = {}
        self.maximum = {}
        for location, spans in self.by_location.items():
            spans.sort(key=operator.attrgetter("start", "id"))
            self.starts[location] = [s.start for s in spans]
            # Running maximum end, seeded like max(-inf, first end).
            ends = itertools.accumulate((s.end for s in spans), max, initial=-math.inf)
            next(ends)
            self.maximum[location] = list(ends)

    def _candidates(self, location, time, routines):
        cached = self._prefetched.get((location, time)) if self._prefetched else None
        if cached is None:
            recent = self._recent.get(location)
            if recent is not None and recent[0] <= time < recent[1]:
                cached = recent[2]
            else:
                starts = self.starts.get(location)
                if starts is None:
                    return []
                spans = self.by_location[location]
                maximum = self.maximum[location]
                stop = bisect.bisect_right(starts, time)
                right = starts[stop] if stop < len(starts) else math.inf
                index = stop - 1
                cached = []
                while index >= 0 and maximum[index] >= time:
                    span = spans[index]
                    if span.end >= time:
                        cached.append(span)
                        if span.end < right:
                            right = span.end
                    index -= 1
                # Forward lookups share candidates only until the next start/end.
                # Backward queries and arrivals at that next boundary rescan.
                self._recent[location] = (time, right, cached)
        if routines is None or not cached:
            return cached
        if len(cached) == 1:
            return cached if cached[0].routine in routines else []
        return [span for span in cached if span.routine in routines]

    def at(self, location, time, routines=None, event=None):
        candidates = self._candidates(location, time, routines)
        if event is not None and candidates:
            candidates = self.order.filter(candidates, location, time, event)
        span = (
            max(candidates, key=_innermost)
            if len(candidates) > 1
            else (candidates[0] if candidates else None)
        )
        return span

    def prefetched(self, rows, lookups, size=1024):
        """Reuse unfiltered span candidates within one bounded boundary batch.

        Routine filters and event-order checks still run for each association,
        preserving both same-tick resolution and logical diagnostic counts.
        """
        rows = iter(rows)
        previous = self._prefetched
        try:
            while chunk := list(itertools.islice(rows, size)):
                self._prefetched = {}
                upcoming = {}
                boundaries = []
                for row in chunk:
                    for location, time, routines, event in lookups(row):
                        key = (location, time)
                        candidates = upcoming.get(key)
                        if candidates is None:
                            candidates = self._candidates(location, time, None)
                            upcoming[key] = candidates
                        if event is not None and tied(candidates, time):
                            if routines is None or any(
                                span.routine in routines
                                and (span.start == time or span.end == time)
                                for span in candidates
                            ):
                                boundaries.append(key)
                self.order.prefetch(boundaries)
                self._prefetched = upcoming
                yield from chunk
        finally:
            self._prefetched = previous


@dataclasses.dataclass(slots=True)
class Record:
    span: Span
    category: str
    inferred_end: float
    peer: str | None = None
    confidence: str = "unavailable"
    evidence: dict = dataclasses.field(default_factory=dict)
    causes: list | CauseCollection = dataclasses.field(default_factory=list)
    inferred_intervals: list = dataclasses.field(default_factory=list)
