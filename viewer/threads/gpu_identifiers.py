"""Producer-conditional GPU completion attribution from scoped identifiers."""

from ..causality.operations import operation as cause_operation, prerequisite
from ..dependencies.common import _owner, _string
from ..gpu.links import api_result
from ..gpu.api import API_RESULT_UNRESOLVED
from ..gpu.fields import field_kind
from ..gpu.invocations import GpuInvocations
from ..gpu.records import collect_gpu_fields
from .synchronization_model import Span


def attribute_gpu_identifiers(trace, records, diagnostics, fields, *, cap):
    """Generic, scoped ID associations remain conditional on producer semantics."""
    targets = {
        ident: r
        for ident, r in records.items()
        if r.category == "gpu_synchronization" and not r.causes
    }
    if not targets:
        return
    streams = {
        loc["id"]: loc
        for loc in trace.meta.get("locations", [])
        if loc.get("type") == "ACCELERATOR_STREAM"
    }
    if fields is None:
        accepted = {
            "correlation",
            "kernel-id",
            "activity-id",
            "launch-id",
            "external-correlation",
        }
        if not any(
            field_kind(_string(trace, d.get("name"))) in accepted
            for kind in ("Attribute", "Parameter")
            for d in trace.defs.get(kind, {}).values()
        ):
            return
        invocation_lookup = GpuInvocations(
            trace, lambda code, message, count=1: diagnostics.update({code: count})
        )
        items = {}

        def resolve(event):
            row = invocation_lookup.at(event)
            if row is None:
                return None
            ident = row["id"]
            loc = row["location"]
            region = trace.regions.get(row["region"], {})
            kernel = loc in streams and region.get("role") == "KERNEL"
            if ident not in targets and not kernel:
                return None
            key = "span:" + str(ident)
            if key not in items:
                items[key] = dict(
                    id=key,
                    kind="kernel" if kernel else "gpu-api",
                    label=region.get("name", ""),
                    location=loc,
                    start=row["start"],
                    end=row["end"],
                    status="incomplete" if row["incomplete"] else "complete",
                    confidence="sampled" if row["sampled"] else "recorded",
                    evidence=[],
                    data=dict(
                        span=ident,
                        region=row["region"],
                        paradigm=region.get("group", "").upper(),
                    ),
                )
            return items[key]

        fields = collect_gpu_fields(
            trace,
            resolve,
            streams,
            _owner,
            _string,
            cap=cap,
            warn=lambda code, message, count=1: diagnostics.update({code: count}),
            include_callsites=False,
        )
    if fields.truncated or diagnostics.get("gpu-invocation-limit"):
        diagnostics["gpu_identifier_limit"] += 1
        return
    resolved = set()
    edges = {}

    def span(item, category):
        data = item["data"]
        return Span(
            data["span"],
            item["location"],
            data["region"],
            item["start"],
            item["end"],
            0,
            int(item["status"] != "complete"),
            int(item["confidence"] == "sampled"),
            item["label"],
            category,
        )

    for (_, paradigm, domain, value, namespace), matched in fields.correlations.items():
        host = [p for p in matched.values() if p[0]["data"].get("span") in targets]
        if domain in ("callsite", "external-correlation"):
            diagnostics["gpu_sync_nonunique_identifier"] += len(host)
            continue
        if domain not in (
            "correlation",
            "runtime-correlation",
            "driver-correlation",
            "kernel-id",
            "activity-id",
            "launch-id",
        ):
            continue
        device = [p for p in matched.values() if p[0]["kind"] == "kernel"]
        if not host or not device:
            continue
        if len(host) != 1 or len(device) != 1:
            diagnostics["gpu_sync_identifier_ambiguous"] += 1
            continue
        item, event, name, _ = host[0]
        kernel_item, kevent, kname, _ = device[0]
        s = span(item, "gpu_synchronization")
        kernel = span(kernel_item, "kernel")
        record = targets[s.id]
        result = api_result(item)
        if result is API_RESULT_UNRESOLVED:
            diagnostics["gpu_sync_api_result_unresolved"] += 1
            continue
        if result not in (None, 0):
            diagnostics["gpu_sync_failed_api"] += 1
            continue
        if kernel.end > s.end or any(
            (s.sampled, s.incomplete, kernel.sampled, kernel.incomplete)
        ):
            diagnostics["gpu_sync_identifier_conflict"] += 1
            continue
        latest = kernel.end >= record.deadline or not record.causes
        record.deadline = max(record.deadline, s.start, kernel.end)
        record.confidence = "conditional-gpu-completion"
        if latest:
            record.peer = kernel.location
            record.evidence.update(
                identifier=name,
                value=value,
                identifierEvents=[event["id"], kevent["id"]],
                kernelSpan=kernel.id,
                kernelEnd=kernel.end,
            )
        evidence = dict(
            identifier=name,
            deviceIdentifier=kname,
            domain=domain,
            paradigm=paradigm,
            value=value,
            events=[event["id"], kevent["id"]],
            kernelSpan=kernel.id,
        )
        record.evidence.setdefault("gpuCorrelations", []).append(evidence)
        pair = (s.id, kernel.id)
        if pair in edges:
            edges[pair].extra["identifiers"].append(evidence)
            continue
        edge = prerequisite(
            f"gpu:{domain}:{value}:span:{s.id}",
            "gpu_completion",
            cause_operation(kernel, event=kevent["id"]),
            cause_operation(s, event=event["id"]),
            kernel.end,
            required=False,
            reason="A unique recorded identifier links the kernel and synchronization call; its producer-specific synchronization contract remains conditional.",
        )
        if edge:
            edge["identifiers"] = [evidence]
            record.causes.append(edge)
            edges[pair] = edge
            resolved.add(s.id)
    diagnostics["gpu_sync_dependency_unrecorded"] -= len(resolved)
