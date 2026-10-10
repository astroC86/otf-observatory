"""Typed CUpti_ActivityStream creation records and their API anchors.

The SDK's stream flag enum is not CUDA's stream-creation bit mask. A null
stream record alone does not establish legacy versus per-thread semantics.
"""

from __future__ import annotations
import collections
from .external import unsigned_integer, CuptiRecords
from .event_records import cupti_api_anchors

STRUCT = "CUpti_ActivityStream"
MEMBERS = ("kind", "contextId", "streamId", "flag", "correlationId", "priority")
REQUIRED = MEMBERS[:-1]


class CuptiStreamRecords(CuptiRecords):
    members = {STRUCT: dict.fromkeys(MEMBERS, 3)}

    def required_members(self, struct, fields):
        return REQUIRED

    def extract(self, event, process, warn):
        for _, values in self.records(event):
            if values is None:
                warn(
                    "gpu-cupti-stream-record-invalid",
                    "A qualified CUPTI stream record needs complete consistently typed UINT32 members on one event.",
                )
                return []
            if (
                values["kind"] != 37
                or values["contextId"] == 0xFFFFFFFF
                or values["streamId"] == 0xFFFFFFFF
                or values["flag"] not in (0, 1, 2, 3)
            ):
                warn(
                    "gpu-cupti-stream-record-invalid",
                    "The CUPTI stream activity kind, identity or stream-flag enum is invalid.",
                )
                return []
            return [
                dict(
                    recordType=STRUCT,
                    event=event["id"],
                    location=str(event["location"]),
                    time=event["time"],
                    process=process,
                    correlationId=str(values["correlationId"]),
                    contextId=str(values["contextId"]),
                    streamId=str(values["streamId"]),
                    flag=values["flag"],
                    fields=values,
                )
            ]
        return []


def bind_stream_records(model, streams, warn):
    from .api import api_result, cuda_stream_lifecycle_action
    from .fields import context_identity, context_namespace, stream_namespace

    if not model.stream_records or model.truncated:
        return
    apis = cupti_api_anchors(model, streams, warn)
    grouped = collections.defaultdict(list)
    for record in model.stream_records:
        candidates = apis.get((record["process"], record["correlationId"]), {})
        if record["correlationId"] == "0" or len(candidates) != 1:
            warn(
                "gpu-cupti-stream-api-unresolved",
                "A stream record needs one known CUPTI creation API ID; zero, reuse and absent anchors cannot establish a bridge.",
            )
            continue
        item = next(iter(candidates.values()))
        if cuda_stream_lifecycle_action(item) != "create":
            warn(
                "gpu-cupti-stream-api-conflict",
                "The CUPTI stream record does not identify an exact CUDA stream-creation API.",
            )
            continue
        item["data"].setdefault("cuptiStreamRecords", []).append(dict(record))
        grouped[item["id"]].append((item, record))
    for entries in grouped.values():
        item = entries[0][0]
        records = [entry[1] for entry in entries]
        identities = {(r["contextId"], r["streamId"], r["flag"]) for r in records}
        if len(identities) != 1:
            warn(
                "gpu-cupti-stream-record-conflict",
                "One stream-creation API carries conflicting CUPTI stream records.",
            )
            continue
        if (
            item["status"] != "complete"
            or item["confidence"] == "sampled"
            or api_result(item) != 0
        ):
            warn(
                "gpu-cupti-stream-create-unproven",
                "A CUPTI stream bridge requires a complete successful recorded creation API.",
            )
            continue
        record = records[0]
        fields = item["data"].setdefault("gpuFields", {})
        contexts = {
            context_identity(row["name"], row["value"])
            for row in fields.get("context", [])
            if context_namespace(row["name"]) == "cupti-context-id"
        }
        if contexts and contexts != {("cupti-context-id", record["contextId"])}:
            warn(
                "gpu-cupti-stream-record-conflict",
                "The creating API and stream record carry different CUPTI contexts.",
            )
            continue
        stream_ids = {
            unsigned_integer(row["value"], 32)
            for row in item["data"].get("streamIdentifierRows", [])
            if stream_namespace(row["name"]) == "cupti-stream-id"
        }
        if stream_ids and stream_ids != {int(record["streamId"])}:
            warn(
                "gpu-cupti-stream-record-conflict",
                "The creating API and stream record carry different CUPTI stream IDs.",
            )
            continue
        flags = {
            unsigned_integer(row["value"], 32) for row in fields.get("stream-flags", [])
        }
        if record["flag"] in (1, 2) and flags and flags != {record["flag"] - 1}:
            warn(
                "gpu-cupti-stream-record-conflict",
                "The creating API flags disagree with the CUPTI stream mode; no creation bridge or derived mode is assigned.",
            )
            continue
        item["data"]["cuptiStreamCreation"] = dict(
            record, evidence=list(dict.fromkeys(r["event"] for r in records))
        )
        fields.setdefault("context", []).append(
            dict(
                name="cupti.contextId",
                value=record["contextId"],
                event=record["event"],
                producerMember=STRUCT + ".contextId",
            )
        )
        row = dict(
            name="cupti.streamId",
            value=record["streamId"],
            event=record["event"],
            producerMember=STRUCT + ".streamId",
        )
        item["data"].setdefault("streamIdentifierRows", []).append(row)
        item["data"].setdefault("streamIdentifiers", {})[row["name"]] = row["value"]
