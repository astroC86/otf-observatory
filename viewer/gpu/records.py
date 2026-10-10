"""Bounded, shared decoding of recorded GPU invocation fields.

The caller owns interval selection. Identity fields retain their producer
namespace; API results remain separate from missing observations.
"""

from __future__ import annotations
import collections
import dataclasses
import json
import re

from .correlations import correlation_domain
from .fields import field_kind, event_namespace, context_identity
from ..trace.callsites import SourceCallsites, CALLSITE_LABEL
from .external import (
    ExternalRecords,
    cupti_correlation_member,
    cupti_activity_correlation_scope,
    unsigned_integer,
)
from .event_records import CuptiEventRecords, bind_event_records
from .stream_records import CuptiStreamRecords, bind_stream_records

GPU_PARADIGMS = {"CUDA", "HIP", "OPENCL", "OPENACC", "OPENMP_TARGET"}


@dataclasses.dataclass
class GPUFields:
    correlations: dict = dataclasses.field(
        default_factory=lambda: collections.defaultdict(dict)
    )
    event_handles: dict = dataclasses.field(
        default_factory=lambda: collections.defaultdict(dict)
    )
    items: dict = dataclasses.field(default_factory=dict)
    identifiers: dict = dataclasses.field(default_factory=dict)
    parameters: dict = dataclasses.field(default_factory=dict)
    source_callsites: SourceCallsites = dataclasses.field(
        default_factory=lambda: SourceCallsites({})
    )
    scanned: int = 0
    truncated: bool = False
    external_mappings: list = dataclasses.field(default_factory=list)
    external_records: list = dataclasses.field(default_factory=list)
    external_invalid: int = 0
    event_records: list = dataclasses.field(default_factory=list)
    stream_records: list = dataclasses.field(default_factory=list)


def collect_gpu_fields(
    trace,
    resolve_event,
    streams,
    owner,
    string,
    *,
    cap=150000,
    warn=lambda *args: None,
    include_callsites=True,
    include_external=True,
):
    model = GPUFields(source_callsites=SourceCallsites(trace.defs))
    external = ExternalRecords(trace.defs)
    event_records = CuptiEventRecords(trace.defs)
    stream_records = CuptiStreamRecords(trace.defs)
    for ref, d in trace.defs.get("Attribute", {}).items():
        name = string(trace, d.get("name"))
        if (
            field_kind(name)
            and (include_callsites or field_kind(name) != "callsite")
            and ref not in model.source_callsites.reserved_refs
            and ref not in external.reserved_refs
            and ref not in event_records.reserved_refs
            and ref not in stream_records.reserved_refs
        ):
            model.identifiers[ref] = name
    for ref, d in trace.defs.get("Parameter", {}).items():
        name = string(trace, d.get("name"))
        if field_kind(name) and (include_callsites or field_kind(name) != "callsite"):
            model.parameters[ref] = name
    prepared = []
    split_cuda = set()

    def bind(e, name, value):
        if cupti_correlation_member(name) is not None and unsigned_integer(
            value, 32
        ) in (None, 0):
            warn(
                "gpu-cupti-field-invalid",
                "A recorded CUPTI correlation ID is unknown (zero) or does not fit its unsigned 32-bit member.",
            )
            return
        item = resolve_event(e)
        if item is None:
            warn(
                "identifier-span-missing",
                "A correlation identifier has no enclosing GPU activity/API span.",
            )
            return
        model.items[item["id"]] = item
        if e["id"] not in item["evidence"]:
            item["evidence"].append(e["id"])
        resolved = name == CALLSITE_LABEL and "sourceCallsite" in e
        if resolved:
            item["data"].setdefault("sourceCallsites", []).append(
                dict(e["sourceCallsite"], event=e["id"])
            )
        category = field_kind(name)
        paradigm = item["data"].get("paradigm", "")
        if paradigm not in GPU_PARADIGMS:
            match = re.match(r"^(cuda|cu|hip|cl)", item["label"], re.I)
            paradigm = (
                {"cu": "CUDA", "cuda": "CUDA", "hip": "HIP", "cl": "OPENCL"}.get(
                    match[1].lower(), "UNKNOWN"
                )
                if match
                else "UNKNOWN"
            )
        item["data"]["paradigm"] = paradigm
        if category in ("api-result", "context", "stream-flags", "default-stream-mode"):
            item["data"].setdefault("gpuFields", {}).setdefault(category, []).append(
                dict(name=name, value=value, event=e["id"])
            )
            return
        if paradigm == "CUDA" and (
            correlation_domain(name, item) == "runtime-correlation"
            or cupti_activity_correlation_scope(name) is not None
        ):
            split_cuda.add(owner(trace, e["location"]))
        prepared.append((item, e, name, value, category, resolved))

    if model.parameters:
        marks = ",".join("?" for _ in model.parameters)
        rows = trace.rows(
            f"SELECT id,location,time,kind,data FROM events WHERE kind IN ('ParameterInt','ParameterUnsignedInt','ParameterString') AND CAST(json_extract(data,'$.parameter') AS TEXT) IN ({marks}) ORDER BY time,id LIMIT ?",
            [*model.parameters, cap + 1],
        )
        if len(rows) > cap:
            model.truncated = True
            rows = rows[:cap]
        model.scanned += len(rows)
        for e in rows:
            e["data"] = json.loads(e["data"])
            ref = str(e["data"].get("parameter"))
            value = (
                string(trace, e["data"].get("string"))
                if e["kind"] == "ParameterString"
                else e["data"].get("value")
            )
            if value is not None:
                bind(e, model.parameters[ref], value)
    refs = sorted(
        set(model.identifiers)
        | (model.source_callsites.scan_refs if include_callsites else set())
        | (external.scan_refs if include_external else set())
        | event_records.scan_refs
        | stream_records.scan_refs
    )
    if refs:
        marks = ",".join("?" for _ in refs)
        rows = trace.rows(
            f"SELECT id,location,time,kind,data FROM events WHERE EXISTS (SELECT 1 FROM json_each(events.data,'$.attributes') a WHERE CAST(json_extract(a.value,'$.ref') AS TEXT) IN ({marks})) ORDER BY time,id LIMIT ?",
            [*refs, cap + 1],
        )
        if len(rows) > cap:
            model.truncated = True
            rows = rows[:cap]
        model.scanned += len(rows)
        for e in rows:
            e["data"] = json.loads(e["data"])
            callsite = (
                model.source_callsites.extract(e["data"].get("attributes", []))
                if include_callsites
                else None
            )
            model.event_records.extend(
                event_records.extract(e, owner(trace, e["location"]), warn)
            )
            model.stream_records.extend(
                stream_records.extract(e, owner(trace, e["location"]), warn)
            )
            if include_external:
                mappings, identities, invalid = external.extract(
                    e, owner(trace, e["location"]), warn
                )
                model.external_mappings.extend(mappings)
                model.external_invalid += invalid
                for identity in identities:
                    item = (
                        resolve_event(e)
                        if e["kind"]
                        in (
                            "Enter",
                            "Leave",
                            "CallingContextEnter",
                            "CallingContextLeave",
                        )
                        else None
                    )
                    if item is not None and item["data"].get("paradigm") == "OPENACC":
                        identity.update(
                            id=item["id"],
                            span=item["data"].get("span"),
                            label=item["label"],
                            start=item["start"],
                            end=item["end"],
                        )
                        model.items[item["id"]] = item
                    model.external_records.append(identity)
            if e["kind"] not in (
                "Enter",
                "Leave",
                "CallingContextEnter",
                "CallingContextLeave",
                "RmaPut",
                "RmaGet",
                "RmaAtomic",
            ):
                continue
            if callsite is not None:
                e["sourceCallsite"] = callsite
                bind(e, CALLSITE_LABEL, callsite["key"])
            for attr in e["data"].get("attributes", []):
                ref = str(attr.get("ref"))
                if ref not in model.identifiers or attr.get("value") is None:
                    continue
                name = model.identifiers[ref]
                declared = trace.defs["Attribute"][ref].get("type")
                if (
                    name.startswith("CUpti_Activity")
                    and cupti_correlation_member(name) is not None
                    and (declared != 3 or attr.get("type", declared) != 3)
                ):
                    warn(
                        "gpu-cupti-field-invalid",
                        "An explicitly qualified CUPTI correlation member has the wrong recorded unsigned width.",
                    )
                    continue
                value = (
                    string(trace, attr["value"])
                    if attr.get("type", declared) == 11
                    else attr["value"]
                )
                bind(e, name, value)
    api_domains = collections.defaultdict(set)
    for item, e, name, value, category, resolved in prepared:
        if (
            item["location"] in streams
            or item["data"]["paradigm"] != "CUDA"
            or cupti_correlation_member(name) is None
        ):
            continue
        domain = correlation_domain(
            name, item, owner(trace, e["location"]) in split_cuda, False
        )
        api_domains[(owner(trace, e["location"]), str(value))].add((item["id"], domain))
    for item, e, name, value, category, resolved in prepared:
        category = correlation_domain(
            name,
            item,
            owner(trace, e["location"]) in split_cuda,
            item["location"] in streams,
        )
        if item["data"]["paradigm"] == "CUDA" and item["location"] in streams:
            scope = cupti_activity_correlation_scope(name)
            if scope == "either-api":
                candidates = api_domains.get(
                    (owner(trace, e["location"]), str(value)), set()
                )
                if len(candidates) == 1:
                    category = next(iter(candidates))[1]
                else:
                    category = "cupti-api-unresolved"
                    warn(
                        "gpu-cupti-activity-api-unresolved",
                        "The qualified CUPTI activity allows a runtime or driver API, but its ID does not identify one unique recorded API across those domains.",
                    )
            elif scope is not None:
                category = scope
        namespace = "source-position" if resolved else "recorded-value"
        if category == "event":
            namespace = event_namespace(name)
            # CUPTI's numeric event IDs require their recorded context; an
            # opaque API handle is already process scoped.
            if namespace == "cupti-event-id":
                contexts = {
                    context_identity(r["name"], r["value"])
                    for r in item["data"].get("gpuFields", {}).get("context", [])
                }
                namespace = (
                    namespace,
                    (
                        next(iter(contexts))
                        if len(contexts) == 1 and None not in contexts
                        else ("unresolved", item["id"])
                    ),
                )
        key = (
            owner(trace, e["location"]),
            item["data"]["paradigm"],
            category,
            str(value),
            namespace,
        )
        if category == "event":
            model.event_handles[key].setdefault(item["id"], (item, e, name, value))
        elif category == "stream":
            item["data"].setdefault("streamIdentifierRows", []).append(
                dict(name=name, value=str(value), event=e["id"])
            )
            item["data"].setdefault("streamIdentifiers", {})[name] = str(value)
        else:
            model.correlations[key].setdefault(item["id"], (item, e, name, value))
    bind_event_records(model, streams, warn)
    bind_stream_records(model, streams, warn)
    if model.truncated:
        warn(
            "correlation-limit",
            "GPU field collection reached its bound; omitted identifiers may change matching and generation history.",
        )
    return model


def stream_definitions(trace, streams, items, owner, string):
    definitions = []
    properties = collections.defaultdict(lambda: collections.defaultdict(list))
    paradigms = collections.defaultdict(set)
    for item in items:
        if (
            item["location"] in streams
            and item["data"].get("paradigm") in GPU_PARADIGMS
        ):
            paradigms[item["location"]].add(item["data"]["paradigm"])
    for definition in trace.defs.get("LocationProperty", {}).values():
        loc = str(definition.get("location"))
        name = string(trace, definition.get("name"))
        category = field_kind(name)
        if loc not in streams or category not in (
            "stream",
            "context",
            "stream-flags",
            "default-stream-mode",
        ):
            continue
        value = definition.get("value")
        if definition.get("type") == 11:
            value = string(trace, value)
        if value is None:
            continue
        properties[loc][category].append(
            dict(name=name, value=value, definition="LocationProperty")
        )
        if category != "stream":
            continue
        prefix = re.match(r"^(cuda|cu|hip|cl)", name, re.I)
        known = paradigms[loc]
        paradigm = (
            {"cu": "CUDA", "cuda": "CUDA", "hip": "HIP", "cl": "OPENCL"}[
                prefix[1].lower()
            ]
            if prefix
            else next(iter(known)) if len(known) == 1 else None
        )
        if paradigm:
            definitions.append((owner(trace, loc), paradigm, value, loc, name))
    return definitions, properties
