"""Context-wide recorded CUDA event capture in the shared completion model."""

from __future__ import annotations
import collections

from .api import (
    api_result,
    cuda_event_action,
    cuda_context_event_action,
    cuda_context_event_scope,
)
from .frontiers import CompletionFrontiers
from .context_mappings import context_mapping_api


def context_event_dependencies(trace, model, items, streams, properties, out, order):
    if model.truncated or not any(
        cuda_context_event_action(item) or context_mapping_api(item)
        for item in items.values()
    ):
        return
    frontiers = CompletionFrontiers(
        trace,
        model,
        items,
        streams,
        properties,
        out,
        order,
        cap=out.cap,
        events_ready=True,
    )
    relations = collections.defaultdict(list)
    for edge in out.edges:
        if edge["kind"] in ("gpu-event-dependency", "gpu-event-observation"):
            relations[edge["target"]].append(edge)
    for rows in relations.values():
        if len(rows) != 1:
            continue
        edge = rows[0]
        record = items.get(edge["source"])
        wait = items.get(edge["target"])
        if (
            not record
            or not wait
            or not (
                cuda_context_event_action(record) or cuda_context_event_action(wait)
            )
        ):
            continue
        if edge["data"].get("completionConflict") or any(
            item["status"] != "complete" or item["confidence"] == "sampled"
            for item in (record, wait)
        ):
            continue
        if (
            api_result(wait) not in (0, 600)
            or api_result(wait) == 600
            and cuda_event_action(wait) != "query"
        ):
            continue
        if not order.before(record, wait):
            continue
        if not frontiers.mappings.continuous(record, wait):
            continue
        captured = frontiers.capture_record(record, set())
        if frontiers.exhausted():
            break
        edge["data"].update(
            captureScope=(
                "context" if cuda_event_action(record) == "context-record" else "stream"
            ),
            captureContext=cuda_context_event_scope(record),
            waitScope=(
                "context"
                if cuda_event_action(wait) == "context-wait"
                else "event-or-stream"
            ),
            waitContext=cuda_context_event_scope(wait),
            knownCompletionSources=len(captured),
            completeWorkset=False,
            hostBlocking=False if cuda_event_action(wait) == "context-wait" else None,
        )
        if not captured:
            continue
        latest = max(captured.values(), key=lambda row: row["device"]["end"])
        lower = latest["device"]["end"]
        upper = edge["data"].get("completionUpperBound")
        if upper is not None and lower > upper:
            out.warn(
                "gpu-event-device-clock-conflict",
                "A successful event observation precedes work captured by its recorded context; no context completion bound is assigned.",
            )
            continue
        old = edge["data"].get("completionLowerBound")
        edge["data"]["completionLowerBound"] = (
            max(old, lower) if old is not None else lower
        )
        if old is None or lower > old:
            edge["data"]["completionLowerBoundExclusive"] = False
        edge["data"]["predecessors"] = [
            entry["device"]["id"] for entry in captured.values()
        ]
        edge["evidence"] = list(
            dict.fromkeys(
                edge["evidence"]
                + [event for entry in captured.values() for event in entry["evidence"]]
            )
        )
        edge["data"]["contextMappings"] = list(
            {
                row["id"]: row
                for entry in captured.values()
                for row in entry.get("contextMappings", [])
            }.values()
        )
        targets = frontiers.following_targets(wait)
        if frontiers.exhausted():
            break
        for target_stream, target in targets.items():
            if target["device"]["start"] < lower:
                out.warn(
                    "gpu-event-device-clock-conflict",
                    "A context/stream event dependency contradicts the recorded device activity order; no device completion edge is assigned.",
                )
                continue
            for source_stream, source in captured.items():
                if not frontiers.charge():
                    break
                out.edges.append(
                    dict(
                        id=f'gpu-context-event:{edge["id"]}:{source["device"]["id"]}:{target["device"]["id"]}',
                        source=source["device"]["id"],
                        target=target["device"]["id"],
                        kind="gpu-event-activity-dependency",
                        label="Device work ordered by a recorded context event",
                        start=source["device"]["end"],
                        end=target["device"]["start"],
                        confidence="recorded-submission-and-correlation",
                        evidence=list(
                            dict.fromkeys(
                                edge["evidence"]
                                + source["evidence"]
                                + target["evidence"]
                                + frontiers.scope_evidence(wait)
                            )
                        ),
                        data=dict(
                            eventDependency=edge["id"],
                            sourceStream=source_stream,
                            targetStream=target_stream,
                            generation=edge["data"]["generation"],
                            captureScope=edge["data"]["captureScope"],
                            waitScope=edge["data"]["waitScope"],
                            contextMappings=list(
                                {
                                    row["id"]: row
                                    for entry in (source, target)
                                    for row in entry.get("contextMappings", [])
                                }.values()
                            ),
                            deviceCompletion=None,
                            completionLowerBound=source["device"]["end"],
                            completeWorkset=False,
                            hostBlocking=False,
                            interpretation="A recorded event capture orders this later identified submission; its host enqueue duration is not blocked time.",
                        ),
                    )
                )
    if frontiers.exhausted():
        out.scan_truncated = True
        out.warn(
            "gpu-context-event-analysis-limit",
            "Context event completion analysis reached its bounded work budget; displayed dependencies are partial.",
        )
    return frontiers
