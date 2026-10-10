"""Identifier-backed accelerator associations and inspectable alternatives."""

from ..trace.callsites import CALLSITE_LABEL
from ..gpu.links import api_result
from ..gpu.correlations import correlation_pairs
from ..gpu.api import API_RESULT_UNRESOLVED
from ..gpu.external import mapping_associations


class GpuAssociations:
    def __init__(self, out, streams, fields, q):
        self.out = out
        self.streams = streams
        self.fields = fields
        self._correlations()
        self._external(q)

    def _correlations(self):
        self.linked = set()
        self.callsite_matches = 0
        self.candidates = []
        self.candidate_total = 0
        for key, records in self.fields.correlations.items():
            host = [r for r in records.values() if r[0]["location"] not in self.streams]
            device = [r for r in records.values() if r[0]["location"] in self.streams]
            pairs, _ = correlation_pairs(host, device, key[2], 0)
            used_host = {h[0]["id"] for h, _, _ in pairs}
            used_device = {g[0]["id"] for _, g, _ in pairs}
            if len(used_host) != len(host) or len(used_device) != len(device):
                self.out.warn(
                    (
                        "ambiguous-correlation"
                        if host and device
                        else "unmatched-correlation"
                    ),
                    "Identifiers need a unique pair or disjoint recorded lifetimes. Repeated callsites retain inspectable alternatives.",
                )
            remaining_hosts = [h for h in host if h[0]["id"] not in used_host]
            selected_hosts = [
                h for h in remaining_hosts if h[0]["location"] in self.out.selected
            ]
            for g in device:
                if g[0]["id"] in used_device or not self.out.visible(
                    g[0]["start"],
                    g[0]["end"],
                    [g[0]["location"], *(self.out.selected if selected_hosts else [])],
                ):
                    continue
                possible = (
                    remaining_hosts
                    if not self.out.selected or g[0]["location"] in self.out.selected
                    else selected_hosts
                )
                self.candidate_total += len(possible)
                for h in possible[: max(0, self.out.limit - len(self.candidates))]:
                    self.candidates.append(
                        dict(
                            identifier=h[2],
                            value=str(h[3]),
                            host=h[0]["id"],
                            device=g[0]["id"],
                            hostLocation=h[0]["location"],
                            deviceLocation=g[0]["location"],
                            confidence="ambiguous-identifier",
                            evidence=[h[1]["id"], g[1]["id"]],
                            causal=False,
                            reason="Multiple recorded invocations share this identifier.",
                        )
                    )
            for host_record, device_record, generation in pairs:
                h, he, name, value = host_record
                g, ge, _, _ = device_record
                is_callsite = key[2] == "callsite"
                is_external = key[2] == "external-correlation"
                label = (
                    "Shared callsite (unique candidate)"
                    if is_callsite
                    else (
                        "Shared external ID (unique candidate)"
                        if is_external
                        else "Recorded correlation identifier"
                    )
                )
                confidence = (
                    "shared-callsite"
                    if is_callsite
                    else (
                        "shared-external-correlation"
                        if is_external
                        else (
                            "identifier-generation"
                            if generation is not None
                            else "recorded-identifier"
                        )
                    )
                )
                causal = (
                    not self.fields.truncated
                    and not (is_callsite or is_external)
                    and h["kind"] in ("launch-api", "copy-api")
                    and api_result(h) in (None, 0)
                )
                if api_result(h) is API_RESULT_UNRESOLVED:
                    self.out.warn(
                        "gpu-api-result-unresolved",
                        "Conflicting or invalid recorded GPU return values leave the identifier association noncausal.",
                    )
                if is_external:
                    self.out.warn(
                        "external-correlation-mapping-missing",
                        "A shared external ID is an association; a recorded external-kind/external-ID to internal-correlation mapping is needed to establish launch causality.",
                    )
                if g["start"] < h["start"]:
                    causal = False
                    self.out.warn(
                        "gpu-launch-clock-conflict",
                        "A recorded device activity starts before its matching host invocation; the identifier association is retained without causal timing.",
                    )
                data = dict(
                    identifier=name,
                    value=str(value),
                    identifierDomain=key[2],
                    hostSpan=h["data"].get("span"),
                    deviceSpan=g["data"].get("span"),
                    deviceRma=g["data"].get("rma"),
                    generation=generation,
                    launchToStartSeconds=g["start"] - h["start"],
                    hostReturnToStartSeconds=g["start"] - h["end"],
                    causal=causal,
                )
                if name == CALLSITE_LABEL and "sourceCallsite" in he:
                    data["sourceCallsite"] = he["sourceCallsite"]
                context = self.out.visible(
                    g["start"], g["end"], [g["location"], h["location"]]
                )
                self.out.edges.append(
                    dict(
                        id=f'correlation:{h["id"]}:{g["id"]}',
                        source=h["id"],
                        target=g["id"],
                        kind=(
                            "memory-correlation"
                            if g["kind"] == "memory-copy"
                            else "kernel-correlation"
                        ),
                        label=label,
                        start=h["start"],
                        end=g["start"],
                        confidence=confidence,
                        evidence=[he["id"], ge["id"]],
                        data=data,
                        context=context,
                    )
                )
                self.linked.add(g["id"])
                self.callsite_matches += int(is_callsite)

    def _external(self, q):
        self.external_rows, external_links, self.external_partial = (
            mapping_associations(
                self.fields,
                self.streams,
                limit=self.out.limit,
                warn=self.out.warn,
                visible=lambda row: self.out.visible(
                    row.get("start", row.get("time")),
                    row.get("end", row.get("time")),
                    [row["location"]],
                ),
            )
        )
        self.external_offset = max(0, int(q.get("externalMappingOffset", 0)))
        self.external_limit = max(1, min(1000, int(q.get("externalMappingLimit", 500))))
        for link in external_links:
            mapping = link["mapping"]
            source = link["source"]
            target = link["target"]
            if source["id"] not in self.out.nodes:
                self.out.nodes[source["id"]] = dict(
                    id=source["id"],
                    kind="external-correlation",
                    label=source.get(
                        "label", source.get("recordType", "External correlation")
                    ),
                    location=source["location"],
                    time=source.get("start", source.get("time", mapping["time"])),
                    event=source["event"],
                    data=dict(
                        externalKind=mapping["externalKind"],
                        externalId=mapping["externalId"],
                        recordType=source.get("recordType"),
                        causal=False,
                    ),
                )
            evidence = list(
                dict.fromkeys([mapping["event"], source["event"], target["event"]])
            )
            a = self.out.nodes[source["id"]]["time"]
            b = target["start"]
            self.out.edges.append(
                dict(
                    id=f"external-mapping:{mapping['event']}:{source['id']}:{target['id']}",
                    source=source["id"],
                    target=target["id"],
                    kind="external-correlation",
                    label="Recorded CUPTI external-to-internal association",
                    start=min(a, b),
                    end=max(a, b),
                    confidence="recorded-external-mapping",
                    evidence=evidence,
                    data=dict(
                        producer="CUPTI",
                        externalKind=mapping["externalKind"],
                        externalId=mapping["externalId"],
                        correlationId=mapping["correlationId"],
                        identifierDomain=target["domain"],
                        mappingEvent=mapping["event"],
                        causal=False,
                        interpretation="CUPTI associates the external range with this CUDA record; the range is not a unique launch or synchronization prerequisite.",
                    ),
                )
            )
