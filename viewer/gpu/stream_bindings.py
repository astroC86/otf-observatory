"""Bind explicit GPU stream identities and proven CUPTI creation bridges."""

from __future__ import annotations

import collections

from .api import api_result, cuda_stream_lifecycle_action
from .fields import (
    context_identity,
    context_namespace,
    cuda_stream_handles,
    stream_identifiers,
    stream_namespace,
)


def resolve_streams(out, items, streams, definitions, properties, before):
    """Resolve recorded handles without guessing their execution locations."""

    def key(process, paradigm, namespace, handle, contexts):
        if namespace == "cupti-stream-id":
            from .external import unsigned_integer

            number = unsigned_integer(handle, 32)
            if number is None or number == 0xFFFFFFFF:
                out.warn(
                    "gpu-cupti-stream-id-invalid",
                    "The recorded CUPTI stream ID is invalid or outside its unsigned 32-bit domain.",
                )
                return None
            identities = {
                context_identity(row["name"], row["value"])
                for row in contexts
                if context_namespace(row["name"]) == "cupti-context-id"
            }
            if len(identities) != 1 or None in identities:
                out.warn(
                    "gpu-cupti-stream-context-unresolved",
                    "CUPTI stream IDs are context-unique; a unique recorded CUPTI context ID is required on both sides of the mapping.",
                )
                return None
            namespace = (namespace, next(iter(identities)))
            handle = str(number)
        return process, paradigm, namespace, str(handle)

    handles = collections.defaultdict(set)
    for definition in definitions:
        process, paradigm, handle, location = definition[:4]
        namespace = (
            stream_namespace(definition[4])
            if len(definition) > 4
            else "api-stream-handle"
        )
        identity = key(
            process,
            paradigm,
            namespace,
            handle,
            properties.get(str(location), {}).get("context", []),
        )
        if identity is not None:
            handles[identity].add(str(location))
    for item in items.values():
        if item["location"] not in streams:
            continue
        data = item["data"]
        for name, handle in stream_identifiers(data):
            contexts = data.get("gpuFields", {}).get("context", []) + properties.get(
                item["location"], {}
            ).get("context", [])
            identity = key(
                data["process"],
                data["paradigm"],
                stream_namespace(name),
                handle,
                contexts,
            )
            if identity is not None:
                handles[identity].add(item["location"])
    # A preserved SDK stream record ties its numeric ID to one successful
    # creation call. Only that call's explicitly typed opaque output handle
    # supplies a bridge, and only after the creating invocation has returned.
    creators = collections.defaultdict(set)
    bridges = collections.defaultdict(list)
    creation_aliases = {}
    for item in items.values():
        if cuda_stream_lifecycle_action(item) != "create":
            continue
        status = api_result(item)
        if isinstance(status, int) and status != 0:
            continue
        data = item["data"]
        opaque = cuda_stream_handles(data.get("streamIdentifierRows", []))
        for handle in opaque:
            creators[
                (data["process"], data["paradigm"], "api-stream-handle", handle)
            ].add(item["id"])
        record = data.get("cuptiStreamCreation")
        if record is None:
            continue
        identity = key(
            data["process"],
            "CUDA",
            "cupti-stream-id",
            record["streamId"],
            [dict(name="cupti.contextId", value=record["contextId"])],
        )
        locations = handles.get(identity, set())
        if len(locations) != 1:
            out.warn(
                "gpu-cupti-stream-location-unresolved",
                "The recorded CUPTI stream identity does not identify one execution location; no opaque-handle bridge is inferred.",
            )
            continue
        location = next(iter(locations))
        prop = properties.setdefault(location, {})
        record_evidence = list(dict.fromkeys(record["evidence"] + item["evidence"]))
        creation = {key: item[key] for key in ("id", "location", "start", "end")}
        creation["data"] = {key: item["data"].get(key) for key in ("region", "span")}
        for kind, member in (("context", "contextId"), ("stream", "streamId")):
            prop.setdefault(kind, []).append(
                dict(
                    name="cupti." + member,
                    value=record[member],
                    event=record["event"],
                    evidence=record_evidence,
                    creation=creation,
                    producerMember="CUpti_ActivityStream." + member,
                )
            )
        if record["flag"] in (1, 2):
            prop.setdefault("stream-flags", []).append(
                dict(
                    name="cudaStreamFlags",
                    value=record["flag"] - 1,
                    event=record["event"],
                    evidence=record_evidence,
                    creation=creation,
                    producerMember="CUpti_ActivityStream.flag",
                )
            )
        if len(opaque) != 1:
            if opaque:
                out.warn(
                    "gpu-cupti-stream-bridge-conflict",
                    "The creating API records several opaque output handles; its CUPTI stream bridge is ambiguous.",
                )
            continue
        handle = next(iter(opaque))
        identity = (data["process"], "CUDA", "api-stream-handle", handle)
        bridges[identity].append((item, location, record))
        creation_aliases[(item["id"], identity)] = (item, location, record)
    aliases = {}
    for identity, rows in bridges.items():
        if (
            len(creators[identity]) != 1
            or len(
                {
                    (item["id"], location, record["contextId"], record["streamId"])
                    for item, location, record in rows
                }
            )
            != 1
        ):
            out.warn(
                "gpu-cupti-stream-bridge-generation-unresolved",
                "The same opaque stream handle has multiple recorded creations; their numeric stream generations cannot be collapsed into one bridge.",
            )
            continue
        aliases[identity] = rows[0]
    for item in items.values():
        data = item["data"]
        locations = set()
        ambiguous = False
        unresolved = False
        for name, handle in stream_identifiers(data):
            contexts = data.get("gpuFields", {}).get("context", []) + (
                properties.get(item["location"], {}).get("context", [])
                if item["location"] in streams
                else []
            )
            identity = key(
                data["process"],
                data["paradigm"],
                stream_namespace(name),
                handle,
                contexts,
            )
            candidates = handles.get(identity, set()) if identity is not None else set()
            bridge = creation_aliases.get((item["id"], identity)) or aliases.get(
                identity
            )
            if bridge is not None:
                creator, location, record = bridge
                ordered = item["id"] == creator["id"] or (
                    before(creator, item)
                    if before is not None
                    else creator["end"] < item["start"]
                )
                if ordered:
                    candidates = candidates | {location}
                    data.setdefault("streamBridges", []).append(
                        dict(
                            producer="CUPTI",
                            creationSpan=creator["data"].get("span"),
                            creationEvent=record["event"],
                            contextId=record["contextId"],
                            streamId=record["streamId"],
                            opaqueHandle=handle,
                            location=location,
                            evidence=list(
                                dict.fromkeys(record["evidence"] + creator["evidence"])
                            ),
                        )
                    )
                elif not candidates:
                    out.warn(
                        "gpu-cupti-stream-lifetime-unresolved",
                        "The opaque handle has no proved creation-before-use order for its recorded CUPTI bridge.",
                    )
            if not candidates:
                unresolved = True
            if len(candidates) == 1:
                locations.update(candidates)
            elif len(candidates) > 1:
                ambiguous = True
                out.warn(
                    "gpu-stream-handle-ambiguous",
                    "A recorded stream handle names several locations; lifecycle evidence is needed to select its generation.",
                )
        if len(locations) == 1 and not ambiguous and not unresolved:
            data["resolvedStream"] = next(iter(locations))
            data["streamResolution"] = "resolved"
        elif len(locations) > 1:
            data["streamResolution"] = "conflicting"
            out.warn(
                "gpu-stream-identifiers-conflict",
                "Stream identifiers on one API invocation resolve to different recorded streams.",
            )
        elif data.get("streamIdentifiers"):
            data["streamResolution"] = "ambiguous" if ambiguous else "unresolved"
