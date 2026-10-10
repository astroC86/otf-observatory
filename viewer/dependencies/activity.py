"""Collect accelerator spans, host API calls, and recorded memory transfers.

The collector owns span identity and topology once, so graph links and summary
statistics share the same activity objects without rebuilding lookup state.
"""

import re

from ..trace.definitions import enum
from ..gpu.invocations import GpuInvocations
from .common import GPU_PARADIGMS, _owner, _string
from .device import _device


class GpuActivity:
    def __init__(self, out):
        self.out = out
        self.trace = out.trace
        self.streams = {
            loc["id"]: loc
            for loc in self.trace.meta.get("locations", [])
            if loc.get("type") == "ACCELERATOR_STREAM"
        }
        self.devices = {}
        self.stream_devices = {}
        self.stream_topology = {}
        for loc in self.streams:
            device = _device(self.trace, loc)
            self.stream_devices[loc] = device["id"]
            self.stream_topology[loc] = device.get("topology")
            self.devices.setdefault(device["id"], dict(device, locations=[]))[
                "locations"
            ].append(loc)
        self.api_regions = {
            ref
            for ref, r in self.trace.regions.items()
            if (
                r.get("group", "").upper() in GPU_PARADIGMS
                or re.match(
                    r"^(?:cuda[A-Z]|cu[A-Z]|hip[A-Z]|clEnqueue|clWaitForEvents|clFinish)",
                    r.get("name", ""),
                )
            )
            and r.get("role") != "KERNEL"
        }
        self.span_items = {}
        self.activity = []
        self.host_count = 0

        with self.trace.connect() as db:
            self._activity_spans(db)
            self._copies(db)
            self._host_spans(db)
        if self.out.scan_truncated:
            self.out.warn(
                "activity-limit",
                "Accelerator activity exceeded the scan limit. Device busy/idle statistics cover only scanned activity; narrow the time range.",
            )

        self.event_items = {
            event: item for item in self.activity for event in item["evidence"]
        }
        self.invocation_lookup = GpuInvocations(self.trace, self.out.warn)

    def add_span(self, row):
        ident = "span:" + str(row["id"])
        if ident in self.span_items:
            return self.span_items[ident]
        loc = str(row["location"])
        region = self.trace.regions.get(str(row["region"]), {})
        name = region.get("name", "Region " + str(row["region"]))
        is_stream = loc in self.streams
        if is_stream:
            kind = "kernel" if region.get("role") == "KERNEL" else "accelerator-region"
        elif re.search("launch|enqueue.*kernel", name, re.I):
            kind = "launch-api"
        elif re.search("memcpy|memcopy|enqueue.*(read|write|copy)", name, re.I):
            kind = "copy-api"
        elif re.search("synchron|waitevent|waitforevents|finish", name, re.I):
            kind = "synchronization-api"
        elif region.get("role") == "ALLOCATE":
            kind = "allocation-api"
        elif region.get("role") == "DEALLOCATE":
            kind = "deallocation-api"
        else:
            kind = "gpu-api"
        item = dict(
            id=ident,
            kind=kind,
            label=name,
            location=loc,
            start=row["start"],
            end=row["end"],
            status="incomplete" if row.get("incomplete") else "complete",
            confidence="sampled" if row.get("sampled") else "recorded",
            evidence=[],
            data=dict(
                span=row["id"],
                region=str(row["region"]),
                device=self.stream_devices.get(loc),
                process=_owner(self.trace, loc),
                paradigm=region.get("group", "").upper(),
            ),
        )
        self.out.intervals.append(item)
        self.span_items[ident] = item
        self.out.nodes[ident] = dict(
            id=ident,
            kind=kind,
            label=name,
            location=loc,
            time=row["start"],
            event=None,
            data=item["data"],
        )
        if is_stream:
            self.activity.append(item)
        else:
            self.host_count += 1
        return item

    def _spans(self, db, column, references, selected, cap):
        # Exact range filtering precedes every LIMIT, including long kernels
        # that begin before the selected range.
        marks = ",".join("?" for _ in references)
        selected_sql = (
            " AND s.location IN (" + ",".join("?" for _ in selected) + ")"
            if self.out.selected
            else ""
        )
        if self.out.selected and not selected:
            selected_sql = " AND 0"
        return db.execute(
            f"SELECT s.* FROM spans s JOIN span_time ix ON ix.id=s.id WHERE ix.start<=? AND ix.end>=? AND s.start<? AND s.end>=? AND s.{column} IN ({marks})"
            + selected_sql
            + " ORDER BY s.start,s.id LIMIT ?",
            [
                self.out.end,
                self.out.start,
                self.out.end,
                self.out.start,
                *references,
                *(selected if self.out.selected else []),
                cap + 1,
            ],
        ).fetchall()

    def _activity_spans(self, db):
        if not self.streams:
            return
        selected = [
            loc
            for loc in self.streams
            if not self.out.selected or loc in self.out.selected
        ]
        rows = self._spans(db, "location", self.streams, selected, self.out.cap)
        if len(rows) > self.out.cap:
            self.out.scan_truncated = True
            rows = rows[: self.out.cap]
        for row in rows:
            self.add_span(dict(row))

    def _copies(self, db):
        remaining = max(0, self.out.cap - len(self.activity))
        gpu_windows = []
        for win, wd in self.trace.defs.get("RmaWin", {}).items():
            cd = self.trace.defs.get("Comm", {}).get(str(wd.get("comm")), {})
            gd = self.trace.defs.get("Group", {}).get(str(cd.get("group")), {})
            if enum(
                "OTF2_PARADIGM_", gd.get("paradigm", 0)
            ) in GPU_PARADIGMS or re.search(
                "CUDA|HIP|OPENCL|OPENACC", _string(self.trace, wd.get("name")), re.I
            ):
                gpu_windows.append(win)
        has_evidence = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rma_evidence'"
        ).fetchone()
        selectors = []
        params = [self.out.end, self.out.start]
        if self.streams:
            marks = ",".join("?" for _ in self.streams)
            selectors.extend([f"location IN ({marks})", f"target IN ({marks})"])
            params.extend(self.streams)
            params.extend(self.streams)
            if has_evidence:
                selectors.extend(
                    [f"re.native_source IN ({marks})", f"re.native_target IN ({marks})"]
                )
                params.extend(self.streams)
                params.extend(self.streams)
        if gpu_windows:
            selectors.append("win IN (" + ",".join("?" for _ in gpu_windows) + ")")
            params.extend(gpu_windows)
        if selectors:
            selected_sql = ""
            if self.out.selected:
                marks = ",".join("?" for _ in self.out.selected)
                selection = [f"location IN ({marks})", f"target IN ({marks})"]
                params.extend(self.out.selected)
                params.extend(self.out.selected)
                if has_evidence:
                    selection.extend(
                        [
                            f"re.native_source IN ({marks})",
                            f"re.native_target IN ({marks})",
                        ]
                    )
                    params.extend(self.out.selected)
                    params.extend(self.out.selected)
                selected_sql = " AND (" + " OR ".join(selection) + ")"
            source_sql = (
                "SELECT rma.*, re.completion_event,re.completion_location,re.scope AS completion_scope,re.native_source,re.native_target FROM rma LEFT JOIN rma_evidence re ON re.begin_event=rma.event"
                if has_evidence
                else "SELECT * FROM rma"
            )
            rows = db.execute(
                source_sql
                + " WHERE start<? AND coalesce(end,start)>=? AND ("
                + " OR ".join(selectors)
                + ")"
                + selected_sql
                + " ORDER BY start,id LIMIT ?",
                params + [remaining + 1],
            ).fetchall()
            if len(rows) > remaining:
                self.out.scan_truncated = True
                rows = rows[:remaining]
            for row in rows:
                r = dict(row)
                origin = str(r["location"])
                remote = str(r["target"]) if r["target"] is not None else None
                source, target = (
                    (remote, origin) if r["operation"] == "RmaGet" else (origin, remote)
                )
                if r.get("completion_location") is not None:
                    source, target = r["native_source"], r["native_target"]
                source_gpu = source in self.streams
                target_gpu = target in self.streams
                direction = (
                    "D2D"
                    if source_gpu and target_gpu
                    else "H2D" if target_gpu else "D2H" if source_gpu else "unresolved"
                )
                loc = (
                    source
                    if source in self.streams
                    else target if target in self.streams else origin
                )
                wd = self.trace.defs.get("RmaWin", {}).get(str(r["win"]), {})
                cd = self.trace.defs.get("Comm", {}).get(str(wd.get("comm")), {})
                gd = self.trace.defs.get("Group", {}).get(str(cd.get("group")), {})
                data = dict(
                    rma=r["id"],
                    operation=r["operation"],
                    win=r["win"],
                    source=source,
                    target=target,
                    direction=direction,
                    bytes=r["bytes"],
                    device=self.stream_devices.get(loc),
                    completion=r["status"],
                    process=_owner(self.trace, loc),
                    paradigm=enum("OTF2_PARADIGM_", gd.get("paradigm", 0)),
                    beginLocation=origin,
                    completionLocation=r.get("completion_location"),
                    completionEvent=r.get("completion_event"),
                    completionScope=r.get("completion_scope"),
                )
                ident = "rma:" + str(r["id"])
                end = (
                    r["end"] if r["end"] is not None else max(r["start"], self.out.end)
                )
                evidence = list(
                    dict.fromkeys(
                        e
                        for e in (r["event"], r.get("completion_event"))
                        if e is not None
                    )
                )
                item = dict(
                    id=ident,
                    kind="memory-copy",
                    label=f'{direction} · {r["bytes"]:,} bytes',
                    location=loc,
                    start=r["start"],
                    end=end,
                    status="complete" if r["end"] is not None else "missing completion",
                    confidence="recorded-rma",
                    evidence=evidence,
                    data=data,
                )
                self.out.nodes[ident] = dict(
                    id=ident,
                    kind="memory-copy",
                    label=item["label"],
                    location=loc,
                    time=r["start"],
                    event=r["event"],
                    data=data,
                )
                self.activity.append(item)
                self.out.intervals.append(item)
                # RMA supplies the source/destination location relationship, but
                # completion may be local. This arrow is data movement, not a
                # claim that the remote process has consumed the memory.
                a = ident + ":source"
                b = ident + ":target"
                self.out.nodes[a] = dict(
                    id=a,
                    kind="copy-source",
                    label=direction + " source",
                    location=source,
                    time=r["start"],
                    event=r["event"],
                    data=data,
                )
                self.out.nodes[b] = dict(
                    id=b,
                    kind="copy-target",
                    label=direction + " destination",
                    location=target,
                    time=end,
                    event=None,
                    data=data,
                )
                if source is not None and target is not None:
                    self.out.edges.append(
                        dict(
                            id=ident + ":transfer",
                            source=a,
                            target=b,
                            kind="memory-transfer",
                            label=item["label"],
                            start=r["start"],
                            end=end,
                            confidence="recorded-rma",
                            evidence=item["evidence"],
                            data=data,
                        )
                    )
                else:
                    self.out.warn(
                        "copy-endpoint-unresolved",
                        "Some accelerator RMA records have no resolved remote location.",
                    )

    def _host_spans(self, db):
        # Host API detail never contributes blocking-call time to device work.
        if not self.api_regions:
            return
        cap = min(10000, self.out.cap)
        rows = self._spans(db, "region", self.api_regions, self.out.selected, cap)
        if len(rows) > cap:
            self.out.warn(
                "host-api-limit",
                "Host API detail is bounded; accelerator activity statistics are calculated independently.",
            )
            rows = rows[:cap]
        for row in rows:
            self.add_span(dict(row))

    def containing(self, e):
        # Correlation parameters can be on a host launch just outside the
        # selected range. Resolve the actual enclosing span using the index.
        if e["id"] in self.event_items:
            return self.event_items[e["id"]]
        row = self.invocation_lookup.at(e)
        if row is None:
            return None
        if (
            str(row["location"]) not in self.streams
            and str(row["region"]) not in self.api_regions
        ):
            return None
        return self.add_span(row)
