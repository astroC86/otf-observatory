"""Bounded recursive traversal of captured stream submissions."""

from __future__ import annotations

import bisect

from .completion_state import CompletionState, _context, _contexts
from .api import (
    api_result,
    cuda_event_action,
    cuda_sync_context_fields,
    cuda_context_event_scope,
)
from .stream_semantics import (
    cuda_stream_semantics,
    cuda_invocation_stream_mode as _stream_mode,
    cuda_zero_default as _zero_default,
    cuda_stream_epoch,
    cuda_invocation_properties,
)


class StreamCapture(CompletionState):
    """Traverse stream work using the owning frontier's context/record queries."""

    def capture(self, anchor, stream, path, required_context=None, all_threads=False):
        """Known completion frontier for one captured stream submission."""
        if not self.charge():
            return {}
        if len(path) >= 128:
            self._exhausted = True
            self.out.warn(
                "gpu-wait-work-limit",
                "GPU event dependency depth exceeded the bounded traversal; the affected wait remains unresolved.",
            )
            return {}
        key = (anchor["id"], stream, required_context)
        if key in path:
            self.out.warn(
                "gpu-wait-dependency-cycle",
                "Recorded event waits form an inconsistent dependency cycle.",
            )
            return {}
        path = path | {key}
        frontier = {}
        anchor_values = _contexts(cuda_sync_context_fields(anchor))
        anchor_scope = self._unify_contexts(anchor_values, anchor)
        sem_scope = self.stream_context(stream, anchor)
        if anchor_scope is None or sem_scope is None:
            self.out.warn(
                "gpu-wait-context-conflict",
                "Conflicting recorded contexts cannot establish a synchronization scope.",
            )
            return {}
        anchor_context = anchor_scope["context"]
        sem = dict(self.semantics.get(stream, {}), context=sem_scope["context"])
        context_usable, context_epoch, context_evidence = self.context_lifetimes.at(
            anchor, required_context or anchor_context or sem.get("context")
        )
        if not context_usable:
            return {}
        mode = _stream_mode(anchor, stream, self.properties, before=self.order.before)
        unknown_zero = mode == "unknown" and _zero_default(
            anchor, stream, self.properties
        )
        if (
            anchor_context is not None
            and sem.get("context") is not None
            and self.mappings.proof(
                anchor_context, sem["context"], anchor, anchor, containment=all_threads
            )
            is None
        ):
            self.out.warn(
                "gpu-wait-context-conflict",
                "The synchronization call and resolved stream have different recorded context namespaces.",
            )
            return {}
        selected = [stream]
        # Only the legacy default stream itself captures blocking-stream work.
        # A synchronize on an ordinary stream is not an extra legacy barrier.
        if mode == "legacy" and sem.get("context") is not None:
            for loc in self.semantics:
                other_scope = self.stream_context(loc, anchor)
                if (
                    loc == stream
                    or other_scope is None
                    or self.mappings.proof(
                        sem["context"], other_scope["context"], anchor, anchor
                    )
                    is None
                    or self._owner(self.trace, loc) != anchor["data"]["process"]
                ):
                    continue
                fields = cuda_invocation_properties(
                    anchor, loc, self.properties, self.order.before
                )
                if cuda_stream_semantics({loc: fields})[loc]["mode"] == "blocking":
                    selected.append(loc)
        for source_stream in selected:
            if not self.charge():
                return {}
            thread = (
                "all-host-threads"
                if all_threads
                else (
                    anchor["location"]
                    if source_stream == stream and mode == "per-thread"
                    else (
                        ("unknown-zero", anchor["location"])
                        if source_stream == stream and unknown_zero
                        else (
                            "known-legacy"
                            if source_stream == stream and mode == "legacy"
                            else None
                        )
                    )
                )
            )
            if source_stream != stream:
                thread = "known-blocking"
            usable, epoch = cuda_stream_epoch(
                anchor,
                () if all_threads else self.lifecycle.get(source_stream, []),
                before=self.order.before,
                charge=self.charge,
            )
            if not usable:
                self.out.warn(
                    "gpu-wait-stream-generation-unresolved",
                    "A destroyed, recreated or concurrently changed stream handle has no proved live generation for this capture.",
                )
                continue
            epochs = [change for change in (epoch, context_epoch) if change is not None]
            ends, rows, best = self.indices.get(
                (source_stream, required_context, thread), ([], [], [])
            )
            i = bisect.bisect_left(ends, anchor["start"])
            candidates = []
            if i and not epochs and not self.mappings.requires_history:
                candidates.append(best[i - 1])
            elif i:
                first = (
                    bisect.bisect_left(ends, max(change["end"] for change in epochs))
                    if epochs
                    else 0
                )
                for entry in rows[first:i]:
                    if not self.charge():
                        return {}
                    if all(
                        self.order.before(change, entry["host"]) for change in epochs
                    ):
                        candidates.append(entry)
            j = i
            while j < len(rows) and ends[j] == anchor["start"]:
                if not self.charge():
                    return {}
                if self.order.before(rows[j]["host"], anchor) and all(
                    self.order.before(change, rows[j]["host"]) for change in epochs
                ):
                    candidates.append(rows[j])
                j += 1
            if candidates:
                usable_candidates = []
                for candidate in candidates:
                    scope = anchor_context or sem.get("context")
                    proof = (
                        self.mappings.proof(
                            scope,
                            candidate["context"],
                            anchor,
                            candidate["host"],
                            containment=all_threads,
                        )
                        if scope is not None and candidate["context"] is not None
                        else dict(evidence=[], relations=[])
                    )
                    if proof is not None:
                        usable_candidates.append((candidate, proof))
                if usable_candidates:
                    entry, proof = max(
                        usable_candidates, key=lambda row: row[0]["device"]["end"]
                    )
                    frontier[source_stream] = dict(
                        entry,
                        path=[anchor["id"]],
                        defaultStream=source_stream != stream,
                        evidence=list(
                            dict.fromkeys(
                                entry["evidence"]
                                + self.scope_evidence(anchor, stream, source_stream)
                                + context_evidence
                                + sem_scope["evidence"]
                                + anchor_scope["evidence"]
                                + proof["evidence"]
                            )
                        ),
                        contextMappings=list(
                            {
                                r["id"]: r
                                for r in entry.get("contextMappings", [])
                                + proof["relations"]
                                + sem_scope["relations"]
                                + anchor_scope["relations"]
                            }.values()
                        ),
                    )
                else:
                    self.out.warn(
                        "gpu-wait-context-conflict",
                        "A synchronization call and its identified stream work have different contexts.",
                    )
            for wait in self.waits.get(source_stream, []):
                if wait["end"] > anchor["start"]:
                    break
                if not self.charge():
                    return {}
                if not self.order.before(wait, anchor) or any(
                    not self.order.before(change, wait) for change in epochs
                ):
                    continue
                wait_mode = _stream_mode(
                    wait, source_stream, self.properties, before=self.order.before
                )
                if source_stream != stream and wait_mode != "blocking":
                    continue
                if all_threads:
                    pass
                elif unknown_zero and source_stream == stream:
                    if (
                        wait_mode != "unknown"
                        or not _zero_default(wait, source_stream, self.properties)
                        or wait["location"] != anchor["location"]
                    ):
                        continue
                elif mode == "legacy" and source_stream == stream:
                    if wait_mode != "legacy":
                        continue
                elif mode == "per-thread" and source_stream == stream:
                    if (
                        wait_mode != "per-thread"
                        or wait["location"] != anchor["location"]
                    ):
                        continue
                elif wait_mode == "per-thread":
                    continue
                if required_context is not None:
                    wait_sem = self.stream_context(source_stream, wait)
                    wait_context = _context(wait["data"].get("gpuFields", {})) or (
                        wait_sem["context"] if wait_sem is not None else None
                    )
                    if (
                        self.mappings.proof(
                            required_context, wait_context, anchor, wait
                        )
                        is None
                    ):
                        continue
                edge = self.event_edges.get(wait["id"])
                if edge is None:
                    continue
                record = self.items.get(edge["source"])
                if (
                    record is None
                    or cuda_event_action(record) not in ("record", "context-record")
                    or api_result(record) != 0
                    or not self.order.before(record, wait)
                ):
                    continue
                for loc, entry in self.capture_record(record, path).items():
                    entry = dict(
                        entry,
                        path=entry["path"] + [wait["id"], anchor["id"]],
                        eventGeneration=edge["data"]["generation"],
                        evidence=list(
                            dict.fromkeys(
                                entry["evidence"]
                                + edge["evidence"]
                                + self.scope_evidence(wait, source_stream)
                                + self.scope_evidence(anchor, stream)
                                + context_evidence
                            )
                        ),
                    )
                    if (
                        loc not in frontier
                        or entry["device"]["end"] > frontier[loc]["device"]["end"]
                    ):
                        frontier[loc] = entry
            # A context wait constrains FUTURE work. The wait call alone is
            # not a stream command or a measured host wait. Require an actual
            # later correlated submission before the capturing operation.
            for wait in self.context_waits:
                if wait["end"] > anchor["start"]:
                    break
                if not self.charge():
                    return {}
                if wait["data"]["process"] != anchor["data"]["process"]:
                    continue
                scope = cuda_context_event_scope(wait)
                if scope is None:
                    continue
                following = None
                for entry in rows[bisect.bisect_left(ends, wait["end"]) : j]:
                    if not self.charge():
                        return {}
                    if not self.order.before(
                        wait, entry["host"]
                    ) or not self.order.before(entry["host"], anchor):
                        continue
                    if any(
                        not self.order.before(change, entry["host"])
                        for change in epochs
                    ):
                        continue
                    following = self._context_wait_target(wait, entry)
                    if following is not None:
                        break
                if following is None:
                    continue
                edge = self.event_edges.get(wait["id"])
                if edge is None:
                    continue
                record = self.items.get(edge["source"])
                if (
                    record is None
                    or api_result(record) != 0
                    or not self.order.before(record, wait)
                ):
                    continue
                captured = self.capture_record(record, path)
                if any(
                    entry["device"]["end"] > following["device"]["start"]
                    for entry in captured.values()
                ):
                    self.out.warn(
                        "gpu-event-device-clock-conflict",
                        "A recorded context wait contradicts its later device submission; no required context-event timing is assigned.",
                    )
                    continue
                for loc, entry in captured.items():
                    entry = dict(
                        entry,
                        path=entry["path"]
                        + [wait["id"], following["host"]["id"], anchor["id"]],
                        eventGeneration=edge["data"]["generation"],
                        evidence=list(
                            dict.fromkeys(
                                entry["evidence"]
                                + edge["evidence"]
                                + following["evidence"]
                                + self.scope_evidence(wait)
                                + context_evidence
                            )
                        ),
                        contextMappings=list(
                            {
                                r["id"]: r
                                for r in entry.get("contextMappings", [])
                                + following.get("contextMappings", [])
                            }.values()
                        ),
                    )
                    if (
                        loc not in frontier
                        or entry["device"]["end"] > frontier[loc]["device"]["end"]
                    ):
                        frontier[loc] = entry
        return frontier
