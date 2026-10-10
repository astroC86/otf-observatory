"""Recorded GPU event generations and completion-observation relationships."""

from __future__ import annotations

import re

from .api import API_RESULT_UNRESOLVED, api_result, cuda_event_action


def event_dependencies(out, records, *, before=None, producer_records=()):
    """Match event-record/wait API calls using recorded handles and generations.

    The edge describes submission dependency. A host record call's return does not
    prove device event completion, so no GPU completion timestamp is invented.
    """
    for identity, rows in records.items():
        # Span IDs are display strings ("span:10" sorts before "span:2").
        # At equal ticks the original event sequence establishes same-thread
        # order; a later re-record must never supply an earlier wait.
        rows = sorted(rows.values(), key=lambda r: (r[0]["start"], r[1]["id"]))
        latest = None
        pending_until = float("-inf")
        pending_item = None
        ambiguous_generation = False
        generation = 0
        not_ready = None
        completed_by = None
        bound_evidence = []
        for item, event, name, value in rows:
            label = re.sub(r"[^a-z]", "", item["label"].lower())
            action = cuda_event_action(item)
            if item["data"].get("paradigm") == "CUDA" and action is None:
                if any(
                    token in label
                    for token in (
                        "eventrecord",
                        "eventcreate",
                        "eventdestroy",
                        "eventquery",
                        "eventsynchronize",
                        "waitevent",
                    )
                ):
                    out.warn(
                        "gpu-event-api-contract-unrecognized",
                        "A region name containing an event operation is not a recognized CUDA event API; its handle remains raw evidence.",
                    )
                continue
            result = api_result(item)
            creating = "eventcreate" in label or "createevent" in label
            recording = "eventrecord" in label or "recordevent" in label
            destroying = "eventdestroy" in label or "destroyevent" in label
            if result is API_RESULT_UNRESOLVED or creating or recording or destroying:
                if result is API_RESULT_UNRESOLVED:
                    out.warn(
                        "gpu-api-result-unresolved",
                        "Conflicting or invalid recorded GPU return values do not establish a successful API operation.",
                    )
                    # These calls may have changed handle state. Retaining an old
                    # generation would guess that the conflicting failure won.
                    if not (creating or recording or destroying):
                        continue
                    if recording:
                        generation += 1
                    latest = None
                    ambiguous_generation = True
                elif result not in (None, 0):
                    if recording and not creating:
                        out.warn(
                            "gpu-api-failed",
                            "A recorded failed GPU API call does not establish a submission or completion dependency.",
                        )
                    continue
                elif creating:
                    # A successfully created event has an empty capture, even when
                    # an older destroyed handle's value is reused and its destroy
                    # was not recorded. Never retain that older generation.
                    latest = None
                    ambiguous_generation = result is None
                elif recording:
                    ambiguous_generation = item["start"] < pending_until or (
                        item["start"] == pending_until
                        and pending_item is not None
                        and (
                            not before(pending_item, item)
                            if before is not None
                            else item["location"] != pending_item["location"]
                        )
                    )
                    latest = (item, event, generation)
                    generation += 1
                else:
                    latest = None
                if item["end"] >= pending_until:
                    pending_until = item["end"]
                    pending_item = item
                not_ready = None
                completed_by = None
                bound_evidence = []
                continue
            query = "eventquery" in label
            if not query and not any(
                token in label
                for token in ("waitevent", "waitforevents", "eventsynchronize")
            ):
                continue
            if query and result is None:
                out.warn(
                    "gpu-event-query-result-missing",
                    "An event-query call without its recorded return value does not prove completion.",
                )
                continue
            if result not in (None, 0) and not (
                query and result == 600 and item["data"].get("paradigm") == "CUDA"
            ):
                out.warn(
                    "gpu-api-failed",
                    "A recorded failed GPU API call does not establish a submission or completion dependency.",
                )
                continue
            if latest is None or pending_until > item["start"]:
                out.warn(
                    "gpu-event-record-unresolved",
                    "An event wait has no uniquely ordered preceding event-record call for its recorded handle.",
                )
                continue
            source, source_event, occurrence = latest
            # Concurrent CPU record calls leave generation order ambiguous even
            # when both have returned before this wait.
            if ambiguous_generation:
                out.warn(
                    "gpu-event-generation-ambiguous",
                    "Overlapping event-record calls reuse a handle; the waited generation is ambiguous.",
                )
                continue
            if pending_until == item["start"] and (
                not before(source, item) if before is not None else True
            ):
                out.warn(
                    "gpu-event-generation-ambiguous",
                    "Same-tick event calls lack a proved Leave-before-Enter record-before-wait order.",
                )
                continue
            # Successful CUDA queries and synchronization provide an upper
            # bound at host return, never the exact device completion instant.
            # A NotReady query was incomplete at some instant within the call,
            # so its start is a conservative lower bound (not its return).
            observation = query or ("eventsynchronize" in label and result == 0)
            if query and result == 600:
                not_ready = max(
                    item["start"], not_ready if not_ready is not None else float("-inf")
                )
            fields = dict(
                identifier=name,
                value=str(value),
                process=identity[0],
                generation=occurrence,
                deviceCompletion=None,
                interpretation="Dependency between API submissions; device completion time is not recorded by these calls.",
            )
            if observation:
                if result == 0:
                    completed_by = (
                        min(completed_by, item["end"])
                        if completed_by is not None
                        else item["end"]
                    )
                bound_evidence.extend(
                    [event["id"]]
                    + [
                        r["event"]
                        for r in item["data"].get("gpuFields", {}).get("api-result", [])
                    ]
                )
                conflict = (
                    not_ready is not None
                    and completed_by is not None
                    and not_ready >= completed_by
                )
                if conflict:
                    out.warn(
                        "gpu-event-observation-conflict",
                        "Recorded event results contradict an earlier completion bound for the same generation; inspect clock and producer evidence.",
                    )
                fields.update(
                    apiResult=result,
                    completionLowerBound=not_ready,
                    completionLowerBoundExclusive=not_ready is not None,
                    completionUpperBound=completed_by,
                    completionConflict=conflict,
                    completionEvidence=list(dict.fromkeys(bound_evidence)),
                    completionStatus=(
                        "complete-by-return"
                        if result == 0
                        else "not-ready-during-query"
                    ),
                    interpretation="Recorded API result bounds completion; the exact device completion timestamp is not observed.",
                )
            out.edges.append(
                dict(
                    id=f'gpu-event:{source["id"]}:{item["id"]}',
                    source=source["id"],
                    target=item["id"],
                    kind="gpu-event-observation" if query else "gpu-event-dependency",
                    label=(
                        "Recorded event completion observation"
                        if query
                        else "Recorded event handle: record → wait"
                    ),
                    start=source["start"],
                    end=item["start"],
                    confidence="recorded-event-handle",
                    evidence=list(
                        dict.fromkeys(
                            [source_event["id"], event["id"]]
                            + [
                                r["event"]
                                for r in item["data"]
                                .get("gpuFields", {})
                                .get("api-result", [])
                            ]
                        )
                    ),
                    data=fields,
                )
            )
    if producer_records:
        from .event_records import event_generation_dependencies

        event_generation_dependencies(out, producer_records, before)
