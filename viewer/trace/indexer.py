"""Dispatch retained events to their derived interval and operation indexes."""

import time

from ..mpi.rma_matching import RmaMatcher, RMA_EVENTS
from .definitions import enum
from .encoding import record_dumps
from .interval_index import build_indexes
from .message_index import MessageIndex
from .schema import MPI_MESSAGE_EVENTS, STACK_EVENTS
from .spans import SpanIndex


class Indexer(SpanIndex, MessageIndex):
    def __init__(self, db, progress=lambda **kw: None):
        super().__init__(db, progress)
        self.collective = {}
        self.io = {}
        self.rma = RmaMatcher(self.defs, self.add_rma, self.warnings)
        self.metric_members = {}
        self.started = time.monotonic()

    def definition(self, kind, d):
        super().definition(kind, d)
        self.rma.comms.invalidate()

    def add_rma(self, row, evidence):
        self.add("rma", row)
        self.add("rma_evidence", evidence)

    def initialize(self):
        self.metric_members = {
            k: [str(member) for member in v.get("metricMembers", [])]
            for k, v in self.defs["MetricClass"].items()
        }
        for k, v in self.defs["MetricInstance"].items():
            self.metric_members[k] = self.metric_members.get(str(v["metricClass"]), [])

    def event(self, record):
        loc = str(record["location"])
        tick = record["time"]
        t = (tick - self.offset) / self.resolution
        k = record["kind"]
        d = record["data"]
        if t > self.max_time:
            self.max_time = t
        self.next_event += 1
        eid = self.next_event
        last = self.last_events.get(loc, t)
        self.last_events[loc] = last if last > t else t
        self.event_counts[k] += 1
        self.location_counts[loc] += 1
        raw = d
        if record.get("attributes"):
            raw = dict(d)
            raw["attributes"] = record["attributes"]
        self.add("events", (eid, loc, t, str(tick), k, record_dumps(raw)))
        if k in STACK_EVENTS:
            self.stack_event(loc, t, k, d)
        elif k == "Metric":
            for member, value in zip(
                self.metric_members.get(str(d["metric"]), []), d["metricValues"]
            ):
                if value is None:
                    continue
                md = self.defs["MetricMember"].get(member, {})
                scale = (2 if md.get("base", 1) == 0 else 10) ** md.get("exponent", 0)
                # SQLite INTEGER is signed 64-bit, while OTF2 also records full
                # uint64 counters. Preserve exact spelling in raw and use REAL
                # for the scaled display value, including recorded IEEE values.
                self.add(
                    "metrics", (None, loc, member, t, float(value) * scale, str(value))
                )
        elif k in MPI_MESSAGE_EVENTS:
            self.mpi_event(loc, t, k, d, eid)
        elif k in (
            "MpiCollectiveBegin",
            "RmaCollectiveBegin",
            "NonBlockingCollectiveRequest",
        ):
            scope = (
                self.communicators.request_scope(loc)
                if k == "NonBlockingCollectiveRequest"
                else loc
            )
            key = (
                scope,
                k.replace("Begin", "").replace("Request", ""),
                d.get("requestID", 0),
            )
            self.collective[key] = t
        elif k in (
            "MpiCollectiveEnd",
            "RmaCollectiveEnd",
            "NonBlockingCollectiveComplete",
        ):
            scope = (
                self.communicators.request_scope(loc)
                if k == "NonBlockingCollectiveComplete"
                else loc
            )
            key = (
                scope,
                k.replace("End", "").replace("Complete", ""),
                d.get("requestID", 0),
            )
            start = self.collective.pop(key, None)
            if start is None:
                self.warnings["Collective completion without begin"] += 1
                start = t
            self.add(
                "collectives",
                (
                    None,
                    loc,
                    start,
                    t,
                    enum("OTF2_COLLECTIVE_OP_", d["collectiveOp"]),
                    str(d.get("communicator", d.get("win", ""))),
                    str(d["root"]),
                    d.get("sizeSent", d.get("bytesSent", 0)),
                    d.get("sizeReceived", d.get("bytesReceived", 0)),
                    eid,
                ),
            )
        elif k == "OtfCollective":
            end = t + d["duration"] / self.resolution
            self.max_time = max(self.max_time, end)
            self.add(
                "collectives",
                (
                    None,
                    loc,
                    t,
                    end,
                    d["operation"],
                    str(d["communicator"]),
                    str(d["root"]),
                    d["sent"],
                    d["received"],
                    eid,
                ),
            )
        elif k == "IoOperationBegin":
            self.io[(loc, d["handle"], d["matchingId"])] = (t, d, eid)
        elif k in ("IoOperationComplete", "IoOperationCancelled"):
            pending = self.io.pop((loc, d["handle"], d["matchingId"]), None)
            if pending:
                start, begin, _ = pending
                h = self.defs["IoHandle"].get(str(d["handle"]), {})
                self.add(
                    "io",
                    (
                        None,
                        loc,
                        start,
                        t,
                        str(d["handle"]),
                        str(h.get("file", "")),
                        enum("OTF2_IO_OPERATION_MODE_", begin["mode"]),
                        d.get("bytesResult", 0),
                        "cancelled" if "Cancelled" in k else "complete",
                        eid,
                    ),
                )
            else:
                self.warnings["I/O completion without begin"] += 1
        elif k == "OtfFileOperation":
            end = t + d["duration"] / self.resolution
            self.max_time = max(self.max_time, end)
            self.add(
                "io",
                (
                    None,
                    loc,
                    t,
                    end,
                    str(d["handle"]),
                    str(d["file"]),
                    d["operation"],
                    d["bytes"],
                    "complete",
                    eid,
                ),
            )
        elif k == "Otf1Record":
            self.warnings["OTF record retained raw (no derived analysis)"] += 1
        elif k == "Unknown":
            self.warnings["Unknown OTF2 record: payload unavailable from reader"] += 1
        elif k in ("MpiProbe", "MpiMrecv", "MpiImrecvRequest", "MpiImrecv"):
            self.warnings[
                "Matched-probe record retained; native message attribution is unavailable"
            ] += 1
        elif k in RMA_EVENTS:
            self.rma.event(loc, t, k, d, eid)
        if self.next_event % 100000 == 0:
            self.progress(
                phase="Reading events",
                events=self.next_event,
                seconds=round(time.monotonic() - self.started, 1),
            )

    def finish(self, path):
        self.finish_stacks()
        self.finish_messages()
        for (loc, handle, match), (t, d, eid) in self.io.items():
            h = self.defs["IoHandle"].get(str(handle), {})
            self.add(
                "io",
                (
                    None,
                    loc,
                    t,
                    None,
                    str(handle),
                    str(h.get("file", "")),
                    enum("OTF2_IO_OPERATION_MODE_", d["mode"]),
                    0,
                    "incomplete",
                    eid,
                ),
            )
        self.warnings["Unfinished collective operations"] += len(self.collective)
        self.rma.finish()
        self.flush()
        self.db.commit()
        self.progress(phase="Building interval indexes", events=self.next_event)
        build_indexes(self.db)
        return self.metadata(path)
