"""Dependencies proved by recorded legacy/blocking CUDA stream contracts."""

from __future__ import annotations

import bisect
import collections

from .stream_semantics import (
    cuda_invocation_stream_mode,
    cuda_property_applies,
    cuda_stream_semantics,
)


def cuda_default_stream_dependencies(
    out, items, properties, *, before=None, frontiers=None
):
    """Order observed submissions using explicitly recorded CUDA stream modes.

    The legacy stream synchronizes with blocking streams in its context.
    Per-thread and nonblocking streams do not enter this relation. A numeric
    zero alone cannot distinguish legacy from per-thread compilation mode.
    Unknown contexts/flags therefore do not manufacture a default-stream edge.
    """
    if frontiers is not None and frontiers.exhausted():
        out.scan_truncated = True
        return
    semantics = cuda_stream_semantics(properties)
    identified = (
        {
            (entry["host"]["id"], entry["device"]["id"]): entry
            for rows in frontiers.launches.values()
            for entry in rows
        }
        if frontiers is not None
        else {}
    )
    launches = collections.defaultdict(list)
    for edge in out.edges:
        if (
            edge["kind"] not in ("kernel-correlation", "memory-correlation")
            or edge["confidence"] != "recorded-identifier"
            or not edge["data"].get("causal")
        ):
            continue
        host = items.get(edge["source"])
        device = items.get(edge["target"])
        if not host or not device or host["data"].get("paradigm") != "CUDA":
            continue
        if (
            host["status"] != "complete"
            or device["status"] != "complete"
            or "sampled" in (host["confidence"], device["confidence"])
        ):
            continue
        stream = host["data"].get("resolvedStream")
        if stream is None or stream != device["location"]:
            continue
        sem = dict(
            semantics.get(stream, {}),
            mode=cuda_invocation_stream_mode(host, stream, properties, before=before),
        )
        proof_entry = identified.get((host["id"], device["id"]))
        if frontiers is not None:
            if proof_entry is None:
                continue
            sem["context"] = frontiers.mappings.canonical(proof_entry["context"], host)
        host["data"]["streamSemantics"] = sem
        if sem.get("context") is None or sem.get("mode") not in ("legacy", "blocking"):
            continue
        launches[(host["data"]["process"], sem["context"])].append(
            (host, device, edge, sem["mode"], proof_entry)
        )
    seen = set()
    budget = max(1000, out.cap * 8)
    for (_, context), rows in launches.items():
        indexes = {}
        by_stream = collections.defaultdict(list)
        for row in rows:
            by_stream[row[1]["location"]].append(row)
        for stream, entries in by_stream.items():
            ordered = sorted(
                entries, key=lambda row: (row[0]["end"], row[0]["start"], row[0]["id"])
            )
            indexes[stream] = ([row[0]["end"] for row in ordered], ordered)
        for host, target, correlation, mode, target_entry in rows:
            for stream, (ends, ordered) in indexes.items():
                budget -= 1
                if budget < 0:
                    out.warn(
                        "gpu-default-stream-analysis-limit",
                        "Recorded default-stream dependency analysis reached its work bound; narrow the selection.",
                    )
                    return
                if stream == target["location"]:
                    continue
                i = bisect.bisect_right(ends, host["start"]) - 1
                while i >= 0 and ordered[i][0]["end"] == host["start"]:
                    budget -= 1
                    if budget < 0:
                        out.warn(
                            "gpu-default-stream-analysis-limit",
                            "Recorded default-stream dependency analysis reached its work bound; narrow the selection.",
                        )
                        return
                    if before is not None and before(ordered[i][0], host):
                        break
                    i -= 1
                if i < 0:
                    continue
                previous, source, source_correlation, source_mode, source_entry = (
                    ordered[i]
                )
                if (mode, source_mode) not in (
                    ("legacy", "blocking"),
                    ("blocking", "legacy"),
                ):
                    continue
                context_proof = dict(evidence=[], relations=[])
                if frontiers is not None:
                    context_proof = frontiers.mappings.proof(
                        target_entry["context"], source_entry["context"], host, previous
                    )
                    if frontiers.exhausted():
                        out.scan_truncated = True
                        return
                    if context_proof is None:
                        continue
                key = (source["id"], target["id"])
                if key in seen:
                    continue
                seen.add(key)
                if target["start"] < source["end"]:
                    out.warn(
                        "gpu-default-stream-clock-conflict",
                        "Recorded legacy-stream synchronization contradicts device timestamps; no completion edge is assigned.",
                    )
                    continue
                evidence = list(
                    dict.fromkeys(
                        source_correlation["evidence"]
                        + correlation["evidence"]
                        + context_proof["evidence"]
                        + (
                            (source_entry["evidence"] + target_entry["evidence"])
                            if frontiers is not None
                            else []
                        )
                        + [
                            event
                            for loc, submission in (
                                (stream, previous),
                                (target["location"], host),
                            )
                            for values in properties[loc].values()
                            for r in values
                            if cuda_property_applies(r, submission, before)
                            for event in (
                                [r["event"]] if r.get("event") is not None else []
                            )
                            + r.get("evidence", [])
                        ]
                    )
                )
                out.edges.append(
                    dict(
                        id=f'gpu-default-stream:{source["id"]}:{target["id"]}',
                        source=source["id"],
                        target=target["id"],
                        kind="gpu-default-stream-dependency",
                        label="Recorded legacy/blocking CUDA stream synchronization",
                        start=source["end"],
                        end=target["start"],
                        confidence="recorded-stream-contract",
                        evidence=evidence,
                        data=dict(
                            context=context[1],
                            contextNamespace=context[0],
                            sourceStream=stream,
                            targetStream=target["location"],
                            sourceMode=source_mode,
                            targetMode=mode,
                            contextMappings=list(
                                {
                                    row["id"]: row
                                    for row in context_proof["relations"]
                                    + (
                                        (
                                            source_entry.get("contextMappings", [])
                                            + target_entry.get("contextMappings", [])
                                        )
                                        if frontiers is not None
                                        else []
                                    )
                                }.values()
                            ),
                            causal=True,
                            contract="CUDA legacy default stream",
                            interpretation="Orders identified device operations whose host submissions are ordered. This is not an exhaustive set of unrecorded stream work.",
                        ),
                    )
                )
