"""Required CUDA completion prerequisites from recorded producer contracts.

This constructs a bounded frontier of identified work, not a complete device
queue and not measured scheduler sleep. CUDA contracts come from the installed
public CUDA/CUPTI headers; no recovered causal-wait formula is claimed.
"""

from __future__ import annotations
import collections
import re

from ..causality.operations import Operation, prerequisite
from .invocations import GpuInvocations, GpuSubmissionOrder as _Order
from .api import api_result, cuda_event_action, cuda_synchronization_contract
from .fields import field_kind
from .links import stream_dependencies
from .records import collect_gpu_fields, stream_definitions
from .event_records import CuptiEventRecords


def _operation(item, event=None):
    data = item["data"]
    return Operation(
        item["location"],
        data.get("span"),
        event,
        data.get("region"),
        item["label"],
        item["start"],
        item["end"],
        {"rma": data["rma"]} if "rma" in data else None,
    )


class _Graph:
    def __init__(self, cap):
        self.cap = cap
        self.edges = []
        self.nodes = {}
        self.diagnostics = collections.Counter()
        self.messages = {}

    def warn(self, code, message, count=1):
        self.diagnostics[code] += count
        self.messages[code] = message


def gpu_waits(trace, records, *, cap=150000):
    """Return internal ``by_span``, ``fields``, diagnostics and partial status.

    ``records`` may contain synchronization_model.Record objects or span objects.
    Only successful, complete CUDA calls receive required causes. The returned
    fields model can be reused by a caller's conditional identifier fallback.
    """
    # Imports stay local to avoid a GPU-view/shared-collector import cycle.
    from ..dependencies.common import _owner, _string
    from ..trace.definitions import enum

    targets = {}
    for record in records.values() if isinstance(records, dict) else records:
        span = getattr(record, "span", record)
        if cuda_synchronization_contract(span.name) is not None:
            targets[span.id] = span
    out = _Graph(cap)
    result = dict(
        by_span={},
        fields=None,
        diagnostics=out.diagnostics,
        messages=out.messages,
        partial=False,
    )
    if not targets:
        return result
    kinds = {
        field_kind(_string(trace, d.get("name")))
        for kind in ("Attribute", "Parameter")
        for d in trace.defs.get(kind, {}).values()
    }
    # Real Score-P callsite-only archives need no global event replay here.
    if (
        "api-result" not in kinds
        or not kinds.intersection(("stream", "event", "context"))
        or "correlation" not in kinds
    ) and not CuptiEventRecords(trace.defs).scan_refs:
        out.warn(
            "gpu-wait-contract-fields-missing",
            "Required GPU waits need recorded success, synchronization scope and invocation-correlation fields.",
        )
        return result
    streams = {
        loc["id"]: loc
        for loc in trace.meta.get("locations", [])
        if loc.get("type") == "ACCELERATOR_STREAM"
    }
    items = {}
    rma_events = {}
    lookup = GpuInvocations(trace, out.warn)
    order = _Order(trace, lookup, out.warn)

    def add_span(row):
        ident = "span:" + str(row["id"])
        if ident in items:
            return items[ident]
        loc = str(row["location"])
        region = trace.regions.get(str(row["region"]), {})
        name = region.get("name", "")
        group = region.get("group", "").upper()
        if loc in streams:
            kind = "kernel" if region.get("role") == "KERNEL" else "accelerator-region"
        elif re.match(r"^(?:cuda|cu)[A-Z]", name) or group in (
            "CUDA",
            "HIP",
            "OPENCL",
            "OPENACC",
            "OPENMP_TARGET",
        ):
            kind = (
                "launch-api"
                if re.search("launch", name, re.I)
                else "copy-api" if re.search("memcpy", name, re.I) else "gpu-api"
            )
        else:
            return None
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
                process=_owner(trace, loc),
                paradigm=group,
            ),
        )
        items[ident] = item
        return item

    def resolve(event):
        if event["id"] in rma_events:
            return rma_events[event["id"]]
        if event["kind"].startswith("Rma"):
            with trace.connect() as db:
                has = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rma_evidence'"
                ).fetchone()
            if not has:
                return None
            rows = trace.rows(
                "SELECT rma.*,re.completion_event,re.completion_location,re.native_source,re.native_target FROM rma JOIN rma_evidence re ON re.begin_event=rma.event WHERE rma.event=?",
                [event["id"]],
            )
            if len(rows) != 1:
                return None
            row = rows[0]
            loc = (
                row["native_source"]
                if row["native_source"] in streams
                else row["native_target"] if row["native_target"] in streams else None
            )
            if loc is None or row["end"] is None:
                return None
            if str(row["location"]) != loc or str(row["completion_location"]) != loc:
                out.warn(
                    "gpu-wait-copy-completion-scope",
                    "A transfer completion recorded outside the accelerator stream is not a proved device-completion prerequisite.",
                )
                return None
            win = trace.defs.get("RmaWin", {}).get(str(row["win"]), {})
            comm = trace.defs.get("Comm", {}).get(str(win.get("comm")), {})
            group = trace.defs.get("Group", {}).get(str(comm.get("group")), {})
            paradigm = enum("OTF2_PARADIGM_", group.get("paradigm", 0))
            # Completion of an RMA transfer is a recorded copy interval. The
            # host/device correlation must still independently identify it.
            item = dict(
                id="rma:" + str(row["id"]),
                kind="memory-copy",
                label=row["operation"],
                location=loc,
                start=row["start"],
                end=row["end"],
                status="complete",
                confidence="recorded-rma",
                evidence=[
                    i for i in (row["event"], row["completion_event"]) if i is not None
                ],
                data=dict(
                    rma=row["id"],
                    process=_owner(trace, loc),
                    paradigm=paradigm,
                    completionSemantics="recorded local transfer completion on accelerator stream",
                ),
            )
            items[item["id"]] = item
            rma_events[event["id"]] = item
            return item
        row = lookup.at(event)
        return add_span(row) if row is not None else None

    model = collect_gpu_fields(
        trace,
        resolve,
        streams,
        _owner,
        _string,
        cap=cap,
        warn=out.warn,
        include_callsites=False,
        include_external=False,
    )
    result["fields"] = model
    if model.truncated or out.diagnostics.get("gpu-invocation-limit"):
        result["partial"] = True
        out.warn(
            "gpu-wait-scan-incomplete",
            "A bounded GPU field scan may omit duplicate identifiers or event generations; required wait attribution is suppressed.",
        )
        return result
    definitions, properties = stream_definitions(
        trace, streams, items.values(), _owner, _string
    )
    # Resolve stream handles before adding correlation edges, so this helper
    # does not build the GPU display's complete relationship graph.
    stream_dependencies(
        out, items, streams, definitions, properties=properties, before=order.before
    )
    from .frontiers import CompletionFrontiers

    frontiers = CompletionFrontiers(
        trace, model, items, streams, properties, out, order, cap=cap
    )
    for ident in targets:
        if not frontiers.charge():
            break
        item = items.get("span:" + str(ident))
        if item is None:
            continue
        contract = cuda_synchronization_contract(item["label"])
        if item["data"].get("paradigm") != "CUDA" or contract is None:
            continue
        if item["status"] != "complete" or item["confidence"] == "sampled":
            continue
        if item["data"].get("cuptiSynchronizationConflict"):
            out.warn(
                "gpu-wait-sync-contract-conflict",
                "The typed CUPTI synchronization record disagrees with the recorded API contract; required attribution is unresolved.",
            )
            continue
        if api_result(item) != 0:
            out.warn(
                "gpu-wait-success-unrecorded",
                "A required GPU completion prerequisite needs a recorded successful synchronization result.",
            )
            continue
        anchor = item
        generation = None
        event_evidence = []
        if contract == "event":
            edge = frontiers.event_edges.get(item["id"])
            if edge is None:
                out.warn(
                    "gpu-wait-event-generation-unresolved",
                    "The successful event synchronization has no uniquely ordered recorded event generation.",
                )
                continue
            anchor = items.get(edge["source"])
            generation = edge["data"]["generation"]
            event_evidence = edge["evidence"]
            if (
                anchor is None
                or cuda_event_action(anchor) not in ("record", "context-record")
                or api_result(anchor) != 0
                or not order.before(anchor, item)
            ):
                out.warn(
                    "gpu-wait-event-record-unproven",
                    "The captured event generation lacks a recorded successful and ordered EventRecord.",
                )
                continue
        if contract == "context":
            frontier = frontiers.capture_context(item, set())
        elif contract == "event":
            frontier = frontiers.capture_record(anchor, set())
        else:
            stream = anchor["data"].get("resolvedStream")
            if stream is None:
                out.warn(
                    "gpu-wait-stream-unresolved",
                    "The successful synchronization or event record has no unambiguous recorded stream location.",
                )
                continue
            frontier = frontiers.capture(anchor, stream, set())
        if frontiers.exhausted():
            break
        causes = []
        for entry in frontier.values():
            if not frontiers.mappings.continuous(entry["host"], item):
                continue
            device = entry["device"]
            if device["end"] > item["end"]:
                out.warn(
                    "gpu-wait-completion-clock-conflict",
                    "A successful synchronization returns before the identified device work completes; no required timing edge is assigned.",
                )
                continue
            edge = prerequisite(
                f"gpu-wait:{device['id']}:{item['id']}",
                "gpu_completion",
                _operation(device, entry["deviceEvent"]),
                _operation(item),
                device["end"],
                required=True,
                confidence="recorded-cuda-contract",
                reason="The recorded successful CUDA synchronization requires completion of this identified, previously submitted kernel or copy.",
            )
            if edge is None:
                continue
            edge["gpuContract"] = contract
            edge["submissionSpan"] = entry["host"]["data"].get("span")
            edge["evidence"] = list(
                dict.fromkeys(
                    entry["evidence"]
                    + event_evidence
                    + [
                        r["event"]
                        for r in item["data"].get("gpuFields", {}).get("api-result", [])
                    ]
                )
            )
            edge["submissionPath"] = entry["path"]
            edge["eventGeneration"] = (
                generation if generation is not None else entry.get("eventGeneration")
            )
            edge["defaultStream"] = entry.get("defaultStream", False)
            edge["coverage"] = (
                "known recorded completion frontier; additional unrecorded work may exist"
            )
            if entry.get("contextMappings"):
                edge["contextMappings"] = entry["contextMappings"]
            causes.append(edge)
        if causes:
            latest = max(causes, key=lambda edge: edge["readinessTime"])
            result["by_span"][ident] = dict(
                causes=causes,
                deadline=max(item["start"], latest["readinessTime"]),
                peer=latest.source.location,
                evidence=dict(
                    gpuContract=contract,
                    knownCompletionSources=len(causes),
                    completeWorkset=False,
                    apiResult=0,
                ),
                confidence="recorded-cuda-completion",
            )
        else:
            out.warn(
                "gpu-wait-identified-work-missing",
                "No complete, uniquely identified preceding kernel or copy establishes this synchronization prerequisite.",
            )
    result["partial"] = frontiers.exhausted()
    return result
