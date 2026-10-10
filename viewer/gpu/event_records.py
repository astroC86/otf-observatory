"""Exact CUPTI event and synchronization records in typed OTF2 attributes.

The layouts are CUpti_ActivityCudaEvent2 and CUpti_ActivitySynchronization2
from the locally installed CUDA 13.2/13.4 headers. Buffer timestamps are never
converted into the OTF2 time domain. An API correlation ID supplies the anchor.
"""

from __future__ import annotations
import collections

from .external import unsigned_integer, cupti_correlation_member, CuptiRecords

RECORD = "CUpti_ActivityCudaEvent2"
SYNC = "CUpti_ActivitySynchronization2"
MEMBERS = {
    RECORD: dict(
        kind=3,
        correlationId=3,
        contextId=3,
        streamId=3,
        eventId=3,
        deviceId=3,
        deviceTimestamp=4,
        cudaEventSyncId=4,
    ),
    SYNC: dict(
        kind=3,
        type=3,
        start=4,
        end=4,
        correlationId=3,
        contextId=3,
        streamId=3,
        cudaEventId=3,
        cudaEventSyncId=4,
        returnValue=3,
    ),
}
REQUIRED = {
    RECORD: (
        "kind",
        "correlationId",
        "contextId",
        "streamId",
        "eventId",
        "cudaEventSyncId",
    ),
    SYNC: (
        "kind",
        "type",
        "correlationId",
        "contextId",
        "streamId",
        "cudaEventId",
        "cudaEventSyncId",
        "returnValue",
    ),
}
SYNC_SCOPE_REQUIRED = ("kind", "type", "correlationId", "contextId", "returnValue")


class CuptiEventRecords(CuptiRecords):
    members = MEMBERS

    def required_members(self, struct, fields):
        scope_type = (
            next(iter(fields["type"]))
            if struct == SYNC and len(fields.get("type", ())) == 1
            else None
        )
        return (
            SYNC_SCOPE_REQUIRED + ("streamId",)
            if scope_type == 3
            else SYNC_SCOPE_REQUIRED if scope_type == 4 else REQUIRED[struct]
        )

    def extract(self, event, process, warn):
        records = []
        for struct, values in self.records(event):
            if values is None:
                warn(
                    "gpu-cupti-event-record-invalid",
                    "A qualified CUPTI event or synchronization record lacks complete consistently typed applicable members on one event.",
                )
                continue
            scope_type = values.get("type") if struct == SYNC else None
            kind = 36 if struct == RECORD else 38
            if values["kind"] != kind:
                warn(
                    "gpu-cupti-event-record-invalid",
                    "The CUPTI activity kind does not match its recorded layout.",
                )
                continue
            if struct == SYNC and values["type"] not in (1, 2, 3, 4):
                warn(
                    "gpu-cupti-event-type-unavailable",
                    "This CUPTI synchronization type has no supported synchronization contract.",
                )
                continue
            scope_sync = scope_type in (3, 4)
            if (
                values["contextId"] == 0xFFFFFFFF
                or not scope_sync
                and values["cudaEventSyncId"] == 0xFFFFFFFF
            ):
                warn(
                    "gpu-cupti-event-record-invalid",
                    "The CUPTI generation/context identity uses the invalid sentinel.",
                )
                continue
            if values["correlationId"] == 0:
                warn(
                    "gpu-cupti-event-api-unresolved",
                    "CUPTI_CORRELATION_ID_UNKNOWN is not an API invocation identity.",
                )
                continue
            inapplicable = ("cudaEventId", "cudaEventSyncId") + (
                ("streamId",) if scope_type == 4 else ()
            )
            if scope_sync and any(
                values.get(key, 0xFFFFFFFF) != 0xFFFFFFFF for key in inapplicable
            ):
                warn(
                    "gpu-cupti-event-record-invalid",
                    "A stream/context synchronization record assigns an identity to an inapplicable SDK member.",
                )
                continue
            event_id = (
                None
                if scope_sync
                else values["eventId"] if struct == RECORD else values["cudaEventId"]
            )
            if (
                event_id == 0xFFFFFFFF
                or (struct == RECORD or values["type"] in (2, 3))
                and values["streamId"] == 0xFFFFFFFF
            ):
                warn(
                    "gpu-cupti-event-record-invalid",
                    "A CUPTI event or applicable stream ID uses the invalid sentinel.",
                )
                continue
            records.append(
                dict(
                    recordType=struct,
                    process=process,
                    event=event["id"],
                    location=str(event["location"]),
                    time=event["time"],
                    correlationId=str(values["correlationId"]),
                    contextId=str(values["contextId"]),
                    eventId=None if scope_sync else str(event_id),
                    cudaEventSyncId=(
                        None if scope_sync else str(values["cudaEventSyncId"])
                    ),
                    fields={
                        name: str(value) if MEMBERS[struct][name] == 4 else value
                        for name, value in values.items()
                    },
                    evidence=[event["id"]],
                )
            )
        return records


def cupti_api_anchors(model, streams, warn=lambda *args: None):
    """Known CUPTI API correlation IDs, without timestamp-based disambiguation."""
    apis = collections.defaultdict(dict)
    domains = collections.defaultdict(dict)
    for key, rows in model.correlations.items():
        process, paradigm, domain, value, _ = key
        if paradigm != "CUDA" or domain not in (
            "correlation",
            "runtime-correlation",
            "driver-correlation",
        ):
            continue
        number = unsigned_integer(value, 32)
        if number in (None, 0):
            continue
        for item, event, name, _ in rows.values():
            if item["location"] in streams or cupti_correlation_member(name) is None:
                continue
            domains[(process, item["id"], domain)][str(number)] = item
    blocked = set()
    for (process, _, _), values in domains.items():
        if len(values) != 1:
            blocked.update((process, value) for value in values)
            warn(
                "gpu-cupti-api-identity-conflict",
                "One API invocation records conflicting CUPTI correlation IDs in the same domain; none can anchor a typed activity record.",
            )
    for (process, _, _), values in domains.items():
        for value, item in values.items():
            if (process, value) not in blocked:
                apis[(process, value)][item["id"]] = item
    return apis


def bind_event_records(model, streams, warn):
    """Attach SDK metadata only through a unique actual CUPTI API ID."""
    from .api import cuda_event_action, cuda_synchronization_contract
    from .fields import context_identity, context_namespace

    if not model.event_records or model.truncated:
        return
    apis = cupti_api_anchors(model, streams, warn)
    for record in model.event_records:
        candidates = apis.get((record["process"], record["correlationId"]), {})
        if len(candidates) != 1:
            warn(
                "gpu-cupti-event-api-unresolved",
                "A CUPTI event or synchronization record needs one unique recorded API correlation ID; reuse and missing anchors remain unresolved.",
            )
            continue
        item = next(iter(candidates.values()))
        sync_type = (
            record["fields"].get("type") if record["recordType"] == SYNC else None
        )
        scope_sync = sync_type in (3, 4)
        expected = (
            "record"
            if record["recordType"] == RECORD
            else {
                1: "synchronize",
                2: "wait",
                3: "stream-synchronize",
                4: "context-synchronize",
            }[sync_type]
        )
        action = (
            {"stream": "stream-synchronize", "context": "context-synchronize"}.get(
                cuda_synchronization_contract(item["label"])
            )
            if scope_sync and item["data"].get("paradigm") == "CUDA"
            else cuda_event_action(item)
        )
        if action != expected:
            if scope_sync:
                item["data"]["cuptiSynchronizationConflict"] = True
            warn(
                "gpu-cupti-event-api-conflict",
                "The CUPTI record type disagrees with its uniquely identified CUDA API.",
            )
            continue
        record["item"] = item
        item["data"].setdefault(
            "cuptiSynchronizationRecords" if scope_sync else "cuptiEventRecords", []
        ).append({key: value for key, value in record.items() if key != "item"})
        if scope_sync and record["event"] not in item["evidence"]:
            item["evidence"].append(record["event"])
        fields = item["data"].setdefault("gpuFields", {})
        # A StreamWaitEvent can target a stream in another context. Its SDK
        # event context identifies the recording, not the destination queue.
        if expected != "wait":
            fields.setdefault("context", []).append(
                dict(
                    name="cupti.contextId",
                    value=record["contextId"],
                    event=record["event"],
                    producerMember=record["recordType"] + ".contextId",
                )
            )
        if expected in ("record", "stream-synchronize"):
            row = dict(
                name="cupti.streamId",
                value=str(record["fields"]["streamId"]),
                event=record["event"],
                producerMember=record["recordType"] + ".streamId",
            )
            item["data"].setdefault("streamIdentifierRows", []).append(row)
            item["data"].setdefault("streamIdentifiers", {})[row["name"]] = row["value"]
        if record["recordType"] == SYNC:
            fields.setdefault("api-result", []).append(
                dict(
                    name=SYNC + ".returnValue",
                    value=record["fields"]["returnValue"],
                    event=record["event"],
                )
            )
        record["contextConflict"] = expected != "wait" and any(
            context_identity(row["name"], row["value"])
            != ("cupti-context-id", record["contextId"])
            for row in fields.get("context", [])
            if context_namespace(row["name"]) == "cupti-context-id"
        )


def event_generation_dependencies(out, records, before):
    """Join exact producer generations; recorded clock conflicts remain explicit."""
    from .api import api_result

    sources = collections.defaultdict(dict)
    targets = collections.defaultdict(list)
    source_identities = collections.defaultdict(set)
    for record in records:
        item = record.get("item")
        if item is None:
            continue
        if record["recordType"] == SYNC and record["fields"]["type"] not in (1, 2):
            continue
        if record["recordType"] == RECORD:
            key = (
                record["process"],
                record["contextId"],
                record["eventId"],
                record["cudaEventSyncId"],
            )
            sources[key].setdefault(item["id"], []).append(record)
            source_identities[item["id"]].add((key, record["fields"]["streamId"]))
        else:
            targets[item["id"]].append(record)
    # A complete typed target record establishes that an exact generation is
    # available. Do not replace an unresolved exact join with a guessed epoch.
    out.edges[:] = [
        edge
        for edge in out.edges
        if edge["kind"] not in ("gpu-event-dependency", "gpu-event-observation")
        or edge["target"] not in targets
    ]
    for target_id, rows in targets.items():
        identities = {
            (r["process"], r["contextId"], r["eventId"], r["cudaEventSyncId"])
            for r in rows
        }
        if len(identities) != 1 or any(r.get("contextConflict") for r in rows):
            out.warn(
                "gpu-cupti-event-generation-conflict",
                "One synchronization API carries conflicting recorded CUPTI event generations or contexts.",
            )
            continue
        key = next(iter(identities))
        matched = sources.get(key, {})
        if len(matched) != 1:
            out.warn(
                "gpu-cupti-event-generation-unresolved",
                "The synchronization generation has no unique recorded EventRecord API in the same process and CUPTI context.",
            )
            continue
        source_rows = next(iter(matched.values()))
        source = source_rows[0]["item"]
        target = rows[0]["item"]
        if (
            any(r.get("contextConflict") for r in source_rows)
            or len(source_identities[source["id"]]) != 1
        ):
            out.warn(
                "gpu-cupti-event-generation-conflict",
                "One EventRecord API carries conflicting recorded CUPTI generation or stream identities.",
            )
            continue
        if (
            source["status"] != "complete"
            or target["status"] != "complete"
            or "sampled" in (source["confidence"], target["confidence"])
        ):
            continue
        if api_result(source) not in (None, 0) or api_result(target) != 0:
            out.warn(
                "gpu-api-failed",
                "The recorded CUPTI/API result does not establish a successful event dependency.",
            )
            continue
        ordered = (
            before(source, target)
            if before is not None
            else source["end"] < target["start"]
        )
        if not ordered:
            out.warn(
                "gpu-cupti-event-submission-order-conflict",
                "The exact CUPTI generation identifies a recording whose API is not proved complete before the synchronization call; no causal completion edge is assigned.",
            )
            continue
        evidence = list(
            dict.fromkeys(
                [r["event"] for r in source_rows + rows]
                + source["evidence"]
                + target["evidence"]
            )
        )
        data = dict(
            identifier="CUpti cudaEventSyncId",
            value=key[3],
            process=key[0],
            generation=key[3],
            generationKind="cupti-cudaEventSyncId",
            contextId=key[1],
            eventId=key[2],
            deviceCompletion=None,
            producer="CUPTI",
            interpretation="The recorded producer generation identifies the exact EventRecord API; its device timestamp remains in the separate recorded clock domain.",
        )
        if rows[0]["fields"]["type"] == 1:
            data.update(
                apiResult=0,
                completionUpperBound=target["end"],
                completionLowerBound=None,
                completionConflict=False,
                completionStatus="complete-by-return",
            )
        out.edges.append(
            dict(
                id=f'gpu-cupti-event:{source["id"]}:{target_id}:{key[3]}',
                source=source["id"],
                target=target_id,
                kind="gpu-event-dependency",
                label="Exact recorded CUPTI event generation",
                start=source["start"],
                end=target["start"],
                confidence="recorded-cupti-event-generation",
                evidence=evidence,
                data=data,
            )
        )
