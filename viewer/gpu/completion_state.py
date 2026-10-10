"""Collected submission indexes and shared state for completion frontiers."""

from __future__ import annotations

import collections

from .api import (
    api_result,
    cuda_event_action,
    cuda_api_name,
    cuda_stream_lifecycle_action,
)
from .fields import context_identity
from .event_links import event_dependencies
from .stream_semantics import (
    cuda_stream_semantics,
    cuda_invocation_stream_mode as _stream_mode,
    cuda_zero_default as _zero_default,
    cuda_property_applies,
    cuda_invocation_properties,
)
from .contexts import ContextLifetimes
from .context_mappings import ContextMappings


def _contexts(fields):
    return {
        context_identity(row["name"], row["value"]) for row in fields.get("context", [])
    }


def _context(fields):
    values = _contexts(fields)
    return next(iter(values)) if len(values) == 1 else None


class CompletionState:
    """Own the budget, context proofs and indexes shared by all captures."""

    def __init__(
        self,
        trace,
        model,
        items,
        streams,
        properties,
        out,
        order,
        *,
        cap,
        events_ready=False,
    ):
        from ..dependencies.common import _owner

        self._owner = _owner
        self.trace = trace
        self.items = items
        self.streams = streams
        self.properties = properties
        self.out = out
        self.order = order
        self._budget = max(1000, cap * 8)
        self._exhausted = False

        self.context_lifetimes = ContextLifetimes(
            self.items.values(),
            before=self.order.before,
            charge=self.charge,
            warn=self.out.warn,
            provenance=lambda change: list(
                dict.fromkeys(
                    change["evidence"]
                    + [
                        event
                        for kind in ("Enter", "Leave")
                        if (event := self.order.boundary(change, kind)) is not None
                    ]
                )
            ),
        )
        self.mappings = ContextMappings(
            self.trace,
            self.items,
            self.order,
            self.context_lifetimes,
            charge=self.charge,
            warn=self.out.warn,
            limit=cap,
        )
        if self.mappings.incomplete:
            self._budget = -1
            self.charge()
        self.semantics = cuda_stream_semantics(self.properties)

        self._collect_events(model, events_ready)
        self._collect_launches(model)
        self._index_launches()
        self._collect_waits()
        self._collect_lifecycle()

    def charge(self):
        self._budget -= 1
        if self._budget < 0:
            if not self._exhausted:
                self.out.warn(
                    "gpu-wait-work-limit",
                    "GPU wait prerequisite traversal reached its work bound; only completed analyses are retained.",
                )
            self._exhausted = True
            return False
        return True

    def exhausted(self):
        return self._exhausted

    def _unify_contexts(self, contexts, anchor):
        return (
            self.mappings.unify(contexts, anchor)
            if contexts
            else dict(context=None, evidence=[], relations=[])
        )

    def stream_context(self, stream, anchor):
        fields = cuda_invocation_properties(
            anchor, stream, self.properties, self.order.before
        )
        contexts = _contexts(fields)
        derived = self.mappings.stream_context(stream, anchor)
        if derived is not None:
            if derived.get("conflict"):
                return None
            if derived.get("noGreen") and any(
                (canonical := self.mappings.canonical(context, anchor)) is not None
                and canonical[0] == "cuda-green-context-handle"
                for context in contexts
            ):
                return None
            if derived["context"] is not None:
                contexts.add(derived["context"])
        unified = self._unify_contexts(contexts, anchor)
        if unified is not None and derived is not None:
            unified["evidence"] = list(
                dict.fromkeys(unified["evidence"] + derived["evidence"])
            )
            unified["relations"] = list(
                {
                    r["id"]: r for r in unified["relations"] + derived["relations"]
                }.values()
            )
        return unified

    def scope_evidence(self, item, *locations):
        evidence = list(item["evidence"])
        for bridge in item["data"].get("streamBridges", []):
            evidence.extend(bridge["evidence"])
        for location in locations:
            for rows in self.properties.get(location, {}).values():
                for row in rows:
                    if not cuda_property_applies(row, item, self.order.before):
                        continue
                    if row.get("event") is not None:
                        evidence.append(row["event"])
                    evidence.extend(row.get("evidence", []))
        return list(dict.fromkeys(evidence))

    def _collect_events(self, model, events_ready):
        if not events_ready:
            event_dependencies(
                self.out,
                model.event_handles,
                before=self.order.before,
                producer_records=model.event_records,
            )
        grouped_events = collections.defaultdict(list)
        for edge in self.out.edges:
            if edge["kind"] == "gpu-event-dependency" and not edge["data"].get(
                "completionConflict"
            ):
                grouped_events[edge["target"]].append(edge)
        self.event_edges = {
            target: rows[0] for target, rows in grouped_events.items() if len(rows) == 1
        }
        if any(len(rows) > 1 for rows in grouped_events.values()):
            self.out.warn(
                "gpu-wait-event-identity-conflict",
                "Several recorded event handles or generations describe one call; its required dependency is unresolved.",
            )

    def _collect_launches(self, model):
        self.launches = collections.defaultdict(list)
        for key, rows in model.correlations.items():
            if key[1] != "CUDA" or key[2] not in (
                "correlation",
                "runtime-correlation",
                "driver-correlation",
            ):
                continue
            hosts = [
                row for row in rows.values() if row[0]["location"] not in self.streams
            ]
            devices = [
                row for row in rows.values() if row[0]["location"] in self.streams
            ]
            # Reused IDs are inspectable in the GPU view. Without a producer's
            # lifetime schema they do not establish required wait prerequisites.
            if len(hosts) != 1 or len(devices) != 1:
                continue
            host, he, name, value = hosts[0]
            device, ge, _, _ = devices[0]
            if host["kind"] not in ("launch-api", "copy-api") or device["kind"] not in (
                "kernel",
                "memory-copy",
            ):
                continue
            if any(
                item["status"] != "complete" or item["confidence"] == "sampled"
                for item in (host, device)
            ):
                continue
            if api_result(host) not in (None, 0):
                continue
            if device["start"] < host["start"]:
                self.out.warn(
                    "gpu-wait-clock-conflict",
                    "Device work precedes its identified host submission; it is not a required timing prerequisite.",
                )
                continue
            stream = device["location"]
            explicit = host["data"].get("resolvedStream")
            if host["data"].get("streamIdentifiers") and explicit is None:
                self.out.warn(
                    "gpu-wait-stream-unresolved",
                    "The identified launch has ambiguous or unresolved recorded stream identifiers.",
                )
                continue
            if explicit is not None and explicit != stream:
                self.out.warn(
                    "gpu-wait-stream-conflict",
                    "A launch correlation disagrees with its recorded stream handle.",
                )
                continue
            prop_context = self.stream_context(stream, host)
            known = set().union(
                *(
                    _contexts(item["data"].get("gpuFields", {}))
                    for item in (host, device)
                )
            )
            if prop_context is not None and prop_context["context"] is not None:
                known.add(prop_context["context"])
            unified = self._unify_contexts(known, host)
            if prop_context is None or unified is None:
                self.out.warn(
                    "gpu-wait-context-conflict",
                    "The identified launch, device work and stream have conflicting recorded context namespaces.",
                )
                continue
            context = unified["context"]
            self.launches[stream].append(
                dict(
                    host=host,
                    device=device,
                    mode=_stream_mode(
                        host, stream, self.properties, before=self.order.before
                    ),
                    zeroDefault=_zero_default(host, stream, self.properties),
                    deviceEvent=ge["id"],
                    evidence=list(
                        dict.fromkeys(
                            [he["id"], ge["id"]]
                            + self.scope_evidence(host, stream)
                            + self.scope_evidence(device)
                            + unified["evidence"]
                            + prop_context["evidence"]
                        )
                    ),
                    context=context,
                    contextMappings=list(
                        {
                            r["id"]: r
                            for r in unified["relations"] + prop_context["relations"]
                        }.values()
                    ),
                    identifier=name,
                    value=str(value),
                )
            )

    def _index_launches(self):
        self.indices = {}
        index_rows = collections.defaultdict(list)
        for stream, rows in self.launches.items():
            for row in rows:
                thread = (
                    row["host"]["location"] if row["mode"] == "per-thread" else None
                )
                scopes = [thread, "all-host-threads"]
                if row["mode"] == "legacy":
                    scopes.append("known-legacy")
                if row["mode"] == "blocking":
                    scopes.append("known-blocking")
                if row["mode"] == "unknown" and row["zeroDefault"]:
                    scopes.append(("unknown-zero", row["host"]["location"]))
                for context in (
                    [None, row["context"]] if row["context"] is not None else [None]
                ):
                    for scope in scopes:
                        index_rows[(stream, context, scope)].append(row)
        for index_key, rows in index_rows.items():
            rows.sort(
                key=lambda row: (
                    row["host"]["end"],
                    row["host"]["start"],
                    row["host"]["id"],
                )
            )
            best = []
            latest = None
            for row in rows:
                if latest is None or row["device"]["end"] > latest["device"]["end"]:
                    latest = row
                best.append(latest)
            self.indices[index_key] = ([row["host"]["end"] for row in rows], rows, best)

    def _collect_waits(self):
        self.waits = collections.defaultdict(list)
        self.context_waits = []
        for item in self.items.values():
            if (
                cuda_api_name(item["label"])
                in ("cudastreamwaitevent", "custreamwaitevent")
                and api_result(item) == 0
                and item["data"].get("resolvedStream")
            ):
                self.waits[item["data"]["resolvedStream"]].append(item)
            if (
                cuda_event_action(item) == "context-wait"
                and api_result(item) == 0
                and item["status"] == "complete"
                and item["confidence"] != "sampled"
            ):
                self.context_waits.append(item)
        for rows in self.waits.values():
            rows.sort(key=lambda item: item["end"])
        self.context_waits.sort(key=lambda item: item["end"])

    def _collect_lifecycle(self):
        self.lifecycle = collections.defaultdict(list)
        for item in self.items.values():
            stream = item["data"].get("resolvedStream")
            if stream and cuda_stream_lifecycle_action(item):
                self.lifecycle[stream].append(item)
        for rows in self.lifecycle.values():
            rows.sort(
                key=lambda item: (item["start"], min(item["evidence"], default=0))
            )
