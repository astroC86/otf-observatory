"""Collect recorded CUDA context mappings and their invalidation history.

Only actual UINT64 handle values on the original API Leave supply outputs;
addresses of output parameters are never dereferenced or treated as handles.
"""

from __future__ import annotations
import collections
import json
import math

from .api import api_result, cuda_api_name, cuda_stream_lifecycle_action
from .fields import (
    context_identity,
    context_namespace,
    cuda_context_handle_value,
    stream_namespace,
)

DRIVER = "api-context-handle"
GREEN = "cuda-green-context-handle"
_GETTERS = {"custreamgetctx", "custreamgetctx_v2", "custreamgetgreenctx"}
_INVALIDATORS = {
    "cudeviceprimaryctxreset",
    "cudeviceprimaryctxreset_v2",
    "cudeviceprimaryctxrelease",
    "cudeviceprimaryctxrelease_v2",
    "cudadevicereset",
}


class MappingRecords:
    """Own collected observations and history, before any lifetime proof."""

    def __init__(self, trace, items, order, lifetimes, *, charge, warn, limit=150000):
        self.trace = trace
        self.order = order
        self.lifetimes = lifetimes
        self.charge = charge
        self.warn = warn
        self.relations = []
        self.regular = []
        self.stream_rows = collections.defaultdict(list)
        self.lifecycle = collections.defaultdict(list)
        self.observed = collections.defaultdict(list)
        self.primary_invalidators = collections.defaultdict(list)
        self.invalidators = collections.defaultdict(list)
        self.incomplete = False
        self.measurement = collections.defaultdict(
            lambda: collections.defaultdict(list)
        )
        self._collect_items(items)
        self._index_relations(limit)
        self._collect_history(items, limit)

    def _collect_items(self, items):
        for item in items.values():
            if item["data"].get("paradigm") != "CUDA":
                continue
            name = cuda_api_name(item["label"])
            stream = item["data"].get("resolvedStream")
            if stream is not None and cuda_stream_lifecycle_action(item):
                self.lifecycle[stream].append(item)
            if (
                name in _INVALIDATORS
                and api_result(item) != 0
                and isinstance(api_result(item), int)
            ):
                continue
            if name in _INVALIDATORS:
                self.invalidators[item["data"]["process"]].append(item)
            if name not in _GETTERS | {"cuctxfromgreenctx"}:
                continue
            definition = self.trace.defs.get("Region", {}).get(
                str(item["data"].get("region")), {}
            )
            if (
                type(definition.get("paradigm")) is not int
                or definition["paradigm"] != 5
            ):
                self.warn(
                    "gpu-context-mapping-api-unproven",
                    "A context mapping requires an original exactly typed CUDA Region paradigm, not an API-name inference.",
                )
                continue
            if (
                item["status"] != "complete"
                or item["confidence"] == "sampled"
                or api_result(item) != 0
            ):
                continue
            leave = self.order.boundary(item, "Leave")
            if leave is None:
                continue
            rows = self.trace.rows("SELECT data FROM events WHERE id=?", [leave])
            if not rows:
                continue
            outputs = collections.defaultdict(list)
            for attr in json.loads(rows[0]["data"]).get("attributes", []):
                definition = self.trace.defs.get("Attribute", {}).get(
                    str(attr.get("ref")), {}
                )
                label = (
                    self.trace.defs.get("String", {})
                    .get(str(definition.get("name")), {})
                    .get("string", "")
                )
                namespace = context_namespace(label)
                if namespace not in (DRIVER, GREEN):
                    continue
                value = attr.get("value")
                if type(value) is not int or not 0 <= value < 2**64:
                    value = None
                if (
                    type(definition.get("type")) is not int
                    or definition["type"] != 4
                    or type(attr.get("type", 4)) is not int
                    or attr.get("type", 4) != 4
                ):
                    value = None
                outputs[namespace].append(value)

            def output(namespace, nullable=False):
                values = set(outputs.get(namespace, []))
                if len(values) != 1 or None in values:
                    return None
                value = next(iter(values))
                return (namespace, str(value)) if value or nullable else None

            evidence = list(
                dict.fromkeys(
                    item["evidence"]
                    + [leave]
                    + [
                        boundary
                        for kind in ("Enter",)
                        if (boundary := self.order.boundary(item, kind)) is not None
                    ]
                )
            )
            if name == "cuctxfromgreenctx":
                values = {
                    context_identity(row["name"], row["value"])
                    for row in item["data"].get("gpuFields", {}).get("context", [])
                    if context_namespace(row["name"]) == GREEN
                }
                green = (
                    next(iter(values))
                    if len(values) == 1 and None not in values
                    else None
                )
                converted = output(DRIVER)
                if converted is None or green is None:
                    self.warn(
                        "gpu-context-mapping-output-unresolved",
                        "A green conversion needs one typed recorded green input and one UINT64 CUcontext output on its original Leave.",
                    )
                    continue
                self._relation("converted-green", converted, green, item, evidence)
                for context in (converted, green):
                    self.observed[(item["data"]["process"], context)].append(item)
                continue
            driver = output(DRIVER)
            green = output(GREEN, nullable=True)
            if name == "custreamgetctx_v2":
                if driver is None or green is None:
                    self.warn(
                        "gpu-context-mapping-output-unresolved",
                        "cuStreamGetCtx_v2 needs both typed returned context handles on its original Leave; NULL green is distinct from an absent output.",
                    )
                    continue
                if green[1] != "0":
                    self._relation(
                        "primary-contains-green", driver, green, item, evidence
                    )
                else:
                    self.regular.append(dict(context=driver, item=item))
                scope = green if green[1] != "0" else driver
            elif name == "custreamgetctx":
                scope = driver
            else:
                scope = green if green is not None and green[1] != "0" else None
            handles = {
                cuda_context_handle_value(row["value"])
                for row in item["data"].get("streamIdentifierRows", [])
                if stream_namespace(row["name"]) == "api-stream-handle"
            }
            # Special streams query this CPU thread's current context, which
            # cannot become a permanent accelerator-location property.
            absent = green is not None and green[1] == "0"
            for context in (driver, green):
                if context is not None and context[1] != "0":
                    self.observed[(item["data"]["process"], context)].append(item)
            if (
                (scope is None and not absent)
                or stream is None
                or len(handles) != 1
                or None in handles
                or next(iter(handles)) <= 2
            ):
                continue
            row = dict(
                scope=scope, item=item, evidence=evidence, api=name, noGreen=absent
            )
            self.stream_rows[stream].append(row)
            item["data"].setdefault("contextMappings", []).append(
                dict(
                    relation="stream-context",
                    stream=stream,
                    context=scope,
                    evidence=evidence,
                )
            )

    def _index_relations(self, limit):
        for changes in self.lifecycle.values():
            changes.sort(
                key=lambda item: (item["start"], min(item["evidence"], default=0))
            )
        for stream, rows in self.stream_rows.items():
            legacy = [
                row
                for row in rows
                if row["api"] == "custreamgetctx" and row["scope"] is not None
            ]
            green = [
                row
                for row in rows
                if row["scope"] is not None and row["scope"][0] == GREEN
            ]
            for a in legacy:
                for b in green:
                    if not self.charge():
                        self.incomplete = True
                        break
                    if len(self.relations) >= limit:
                        self.incomplete = True
                        self.warn(
                            "gpu-context-mapping-scan-limit",
                            "The recorded getter-pair bound was reached; context mapping proofs are suppressed.",
                        )
                        break
                    relation = dict(
                        id=f'context-mapping:{a["item"]["id"]}:{b["item"]["id"]}:converted-green',
                        relation="converted-green",
                        source=a["scope"],
                        target=b["scope"],
                        api=[a["item"]["label"], b["item"]["label"]],
                        spans=[
                            a["item"]["data"].get("span"),
                            b["item"]["data"].get("span"),
                        ],
                        stream=stream,
                        status="candidate-requires-lifetime-proof",
                        evidence=list(dict.fromkeys(a["evidence"] + b["evidence"])),
                    )
                    a["item"]["data"].setdefault("contextMappings", []).append(relation)
                    self.relations.append(
                        dict(relation, item=a["item"], witnesses=[a["item"], b["item"]])
                    )
                if self.incomplete:
                    break
            if self.incomplete:
                break
        self.converted = collections.defaultdict(list)
        self.requires_history = bool(self.relations or self.stream_rows or self.regular)
        for row in self.relations:
            if row["relation"] == "converted-green":
                self.converted[(row["item"]["data"]["process"], row["source"])].append(
                    row
                )
            elif row["relation"] == "primary-contains-green":
                process = row["item"]["data"]["process"]
                for change, identity, action, _ in self.lifetimes.rows.get(
                    (process, GREEN), []
                ):
                    result = api_result(change)
                    if (
                        action == "destroy"
                        and identity in (None, row["target"])
                        and not (isinstance(result, int) and result != 0)
                    ):
                        self.primary_invalidators[(process, row["source"])].append(
                            change
                        )

    def _collect_history(self, items, limit):
        from ..dependencies.common import _owner

        markers = self.trace.rows(
            "SELECT id,location,time,data FROM events WHERE kind='MeasurementOnOff' ORDER BY id LIMIT ?",
            [limit + 1],
        )
        if len(markers) > limit:
            self.incomplete = True
            self.warn(
                "gpu-context-mapping-scan-limit",
                "The process recording-state scan is incomplete; context mapping proofs are suppressed.",
            )
        for marker in markers[:limit]:
            mode = json.loads(marker["data"]).get("measurementMode")
            loc = str(marker["location"])
            if type(marker["time"]) not in (int, float) or not math.isfinite(
                marker["time"]
            ):
                self.incomplete = True
                self.warn(
                    "gpu-context-mapping-scan-limit",
                    "A measurement-state timestamp is invalid; context continuity cannot be proved.",
                )
                continue
            self.measurement[_owner(self.trace, loc)][loc].append(
                (marker["time"], marker["id"], type(mode) is int and mode == 1)
            )
        for locations in self.measurement.values():
            for rows in locations.values():
                rows.sort()
        # Reset/release can have no recorded scalar fields at all. Their raw
        # spans still invalidate an older mapping when success is unknown.
        refs = [
            ref
            for ref, region in self.trace.regions.items()
            if cuda_api_name(region.get("name", "")) in _INVALIDATORS
        ]
        if refs:
            spans = self.trace.rows(
                "SELECT * FROM spans WHERE region IN ("
                + ",".join("?" for _ in refs)
                + ") ORDER BY id LIMIT ?",
                refs + [limit + 1],
            )
            if len(spans) > limit:
                self.incomplete = True
                self.warn(
                    "gpu-context-mapping-scan-limit",
                    "The context reset/release scan is incomplete; mappings cannot establish required prerequisites.",
                )
            for span in spans[:limit]:
                ident = "span:" + str(span["id"])
                if ident in items:
                    continue
                loc = str(span["location"])
                region = str(span["region"])
                item = dict(
                    id=ident,
                    label=self.trace.regions[region]["name"],
                    location=loc,
                    start=span["start"],
                    end=span["end"],
                    evidence=[],
                    status="incomplete" if span["incomplete"] else "complete",
                    confidence="sampled" if span["sampled"] else "recorded",
                    data=dict(
                        span=span["id"],
                        region=region,
                        process=_owner(self.trace, loc),
                        paradigm="CUDA",
                    ),
                )
                self.invalidators[item["data"]["process"]].append(item)

    def _relation(self, kind, source, target, item, evidence):
        relation = dict(
            id=f'context-mapping:{item["id"]}:{kind}',
            relation=kind,
            source=source,
            target=target,
            api=item["label"],
            span=item["data"].get("span"),
            evidence=evidence,
        )
        item["data"].setdefault("contextMappings", []).append(relation)
        self.relations.append(dict(relation, item=item))
