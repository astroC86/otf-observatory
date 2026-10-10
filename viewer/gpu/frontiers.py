"""Shared recorded CUDA completion frontiers for graph and required wait views."""

from __future__ import annotations

from .completion_state import _context, _contexts
from .completion_streams import StreamCapture
from .api import (
    api_result,
    cuda_event_action,
    cuda_api_name,
    cuda_sync_context_fields,
    cuda_context_event_action,
    cuda_context_event_scope,
)
from .fields import context_namespace
from .stream_semantics import (
    cuda_stream_epoch,
    cuda_stream_submission_scope,
    cuda_invocation_properties,
)


class CompletionFrontiers(StreamCapture):
    """Query context captures and future submissions against one shared state."""

    def capture_context(self, anchor, path, context=None):
        if cuda_context_event_action(anchor) is not None:
            context = cuda_context_event_scope(anchor)
        elif context is None:
            fields = cuda_sync_context_fields(anchor)
            allowed = (
                {"cuda-execution-context-handle", "cupti-context-id"}
                if cuda_api_name(anchor["label"]) == "cudaexecutionctxsynchronize"
                else {"api-context-handle", "cupti-context-id"}
            )
            context = (
                _context(fields)
                if all(
                    context_namespace(row["name"]) in allowed
                    for row in fields.get("context", [])
                )
                else None
            )
        if context is None:
            self.out.warn(
                "gpu-wait-context-unresolved",
                "Context capture needs the API-specific recorded context identity; other context namespaces or NULL do not supply its scope.",
            )
            return {}
        frontier = {}
        for stream in self.streams:
            if self._owner(self.trace, stream) != anchor["data"]["process"]:
                continue
            candidates = {
                row["context"]
                for row in self.launches.get(stream, [])
                if self.mappings.proof(
                    context, row["context"], anchor, row["host"], containment=True
                )
                is not None
            }
            sem = self.stream_context(stream, anchor)
            if (
                sem is not None
                and self.mappings.proof(
                    context, sem["context"], anchor, anchor, containment=True
                )
                is not None
            ):
                candidates.add(sem["context"])
            for candidate in candidates:
                for loc, entry in self.capture(
                    anchor, stream, path, required_context=candidate, all_threads=True
                ).items():
                    if (
                        loc not in frontier
                        or entry["device"]["end"] > frontier[loc]["device"]["end"]
                    ):
                        frontier[loc] = entry
        return frontier

    def capture_record(self, record, path):
        if (
            record["status"] != "complete"
            or record["confidence"] == "sampled"
            or api_result(record) != 0
        ):
            return {}
        action = cuda_event_action(record)
        if action == "context-record":
            return self.capture_context(record, path)
        if action != "record":
            return {}
        stream = record["data"].get("resolvedStream")
        return self.capture(record, stream, path) if stream is not None else {}

    def _context_generation_evidence(self, anchor, target, context):
        """Return lifetime evidence, or None when the shared generation is unproved."""
        valid, epoch, evidence = self.context_lifetimes.at(anchor, context)
        other_valid, other_epoch, other_evidence = self.context_lifetimes.at(
            target, context
        )
        if (
            not valid
            or not other_valid
            or (epoch and epoch["id"]) != (other_epoch and other_epoch["id"])
        ):
            return None
        return evidence + other_evidence

    def _context_wait_target(self, wait, entry):
        """Attach a proved context wait scope to its following submission."""
        scope = cuda_context_event_scope(wait)
        if scope is None or wait["data"]["process"] != entry["host"]["data"]["process"]:
            return None
        if not self.order.before(wait, entry["host"]):
            return None
        proof = self.mappings.proof(
            scope, entry["context"], wait, entry["host"], containment=True
        )
        if proof is None:
            return None
        evidence = self._context_generation_evidence(wait, entry["host"], scope)
        if evidence is None:
            return None
        return dict(
            entry,
            evidence=list(
                dict.fromkeys(entry["evidence"] + evidence + proof["evidence"])
            ),
            contextMappings=list(
                {
                    r["id"]: r
                    for r in entry.get("contextMappings", []) + proof["relations"]
                }.values()
            ),
        )

    def following_targets(self, wait):
        """One proved first future submission per affected recorded stream."""
        result = {}
        action = cuda_event_action(wait)
        if action not in ("wait", "context-wait") or api_result(wait) != 0:
            return result
        for stream, entries in self.launches.items():
            if action == "wait" and wait["data"].get("resolvedStream") != stream:
                continue
            for entry in sorted(
                entries,
                key=lambda row: (
                    row["host"]["start"],
                    row["host"]["end"],
                    row["host"]["id"],
                ),
            ):
                if not self.charge():
                    return {}
                if not self.order.before(wait, entry["host"]):
                    continue
                if action == "context-wait":
                    entry = self._context_wait_target(wait, entry)
                    if entry is None:
                        continue
                else:
                    if cuda_stream_submission_scope(
                        wait, stream, self.properties, before=self.order.before
                    ) != cuda_stream_submission_scope(
                        entry["host"], stream, self.properties, before=self.order.before
                    ):
                        continue
                    valid, epoch = cuda_stream_epoch(
                        wait,
                        self.lifecycle.get(stream, ()),
                        before=self.order.before,
                        charge=self.charge,
                    )
                    other_valid, other_epoch = cuda_stream_epoch(
                        entry["host"],
                        self.lifecycle.get(stream, ()),
                        before=self.order.before,
                        charge=self.charge,
                    )
                    if (
                        not valid
                        or not other_valid
                        or (epoch and epoch["id"])
                        != (other_epoch and other_epoch["id"])
                    ):
                        continue
                    # Context destruction can invalidate/detach a live stream
                    # without a StreamDestroy call. Its previously queued wait
                    # must not constrain work in a reused context generation.
                    fields = wait["data"].get("gpuFields", {})
                    prop_fields = cuda_invocation_properties(
                        wait, stream, self.properties, self.order.before
                    )
                    contexts = _contexts(fields) | _contexts(prop_fields)
                    derived = self.stream_context(stream, wait)
                    if derived is None:
                        continue
                    if derived["context"] is not None:
                        contexts.add(derived["context"])
                    unified = self.mappings.unify(contexts, wait)
                    if unified is None:
                        continue
                    context = unified["context"]
                    proof = self.mappings.proof(
                        context, entry["context"], wait, entry["host"]
                    )
                    if proof is None:
                        continue
                    evidence = self._context_generation_evidence(
                        wait, entry["host"], context
                    )
                    if evidence is None:
                        continue
                    entry = dict(
                        entry,
                        evidence=list(
                            dict.fromkeys(
                                entry["evidence"]
                                + evidence
                                + proof["evidence"]
                                + unified["evidence"]
                                + derived["evidence"]
                            )
                        ),
                        contextMappings=list(
                            {
                                r["id"]: r
                                for r in entry.get("contextMappings", [])
                                + proof["relations"]
                                + unified["relations"]
                                + derived["relations"]
                            }.values()
                        ),
                    )
                result[stream] = entry
                break
        return result
