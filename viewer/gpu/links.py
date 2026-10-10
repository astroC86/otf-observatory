"""Recorded stream order and device dependencies from GPU event captures.

Identity binding, event generations and CUDA stream contracts live in their
own modules; this module connects the resulting recorded device activity.
"""

from __future__ import annotations

import bisect
import collections
import re

from .api import api_result, cuda_stream_lifecycle_action
from .stream_bindings import resolve_streams
from .stream_semantics import cuda_stream_epoch, cuda_stream_submission_scope


def _recorded_order(item):
    """Sort key: time, then record id within one record table ("span:9" before "span:10")."""
    table, _, number = item["id"].rpartition(":")
    return (item["start"], -item["end"], table, int(number) if number.isdigit() else -1)


def stream_order(out, activity):
    """Recorded execution ordering, without equating idle gaps with queue waits."""
    streams = collections.defaultdict(list)
    for item in activity:
        if item["status"] == "complete" and item["confidence"] != "sampled":
            streams[item["location"]].append(item)
    for loc, items in streams.items():
        previous = None
        for item in sorted(items, key=_recorded_order):
            if previous and item["start"] < previous["end"]:
                # Nested annotations and overlapping activities do not establish
                # a serial completion edge; retain them as separate intervals.
                if item["end"] <= previous["end"]:
                    continue
                out.warn(
                    "stream-overlapping-activity",
                    "Overlapping activities on one stream prevent a serial completion relationship.",
                )
            elif (
                previous
                and item["start"] == previous["start"]
                and item["id"].rpartition(":")[0] != previous["id"].rpartition(":")[0]
            ):
                # Ids from different record tables (e.g. a kernel span and a copy) do not
                # order same-tick items, so no execution order is claimed between them.
                out.warn(
                    "stream-order-ambiguous",
                    "Different activity types share a timestamp on one stream; their execution order is unrecorded.",
                )
            elif previous:
                for row in (previous, item):
                    out.nodes.setdefault(
                        row["id"],
                        dict(
                            id=row["id"],
                            kind=row["kind"],
                            label=row["label"],
                            location=loc,
                            time=row["start"],
                            event=None,
                            data=row["data"],
                        ),
                    )
                out.edges.append(
                    dict(
                        id=f'stream-order:{previous["id"]}:{item["id"]}',
                        source=previous["id"],
                        target=item["id"],
                        kind="stream-order",
                        label="Recorded execution order on stream",
                        start=previous["end"],
                        end=item["start"],
                        confidence="recorded-stream-order",
                        evidence=previous["evidence"] + item["evidence"],
                        data=dict(
                            stream=loc,
                            idleGap=max(0.0, item["start"] - previous["end"]),
                            interpretation="Execution order; the gap does not measure queue or dependency wait.",
                        ),
                    )
                )
            previous = item


def stream_dependencies(
    out, items, streams, definitions, *, before=None, properties=None
):
    """Resolve explicit stream handles and event-ordered recorded operations.

    Definitions contain (process, paradigm, handle, location). A reused handle
    naming different stream locations remains unresolved without lifecycle data.
    Event completion is a lower bound from known preceding activity, never an
    exact device timestamp inferred from a host API call.
    """
    properties = {} if properties is None else properties

    resolve_streams(out, items, streams, definitions, properties, before)

    # Host/device correlation establishes which recorded submission created an
    # operation. Shared callsites and inferred identifier generations are not
    # enough to establish device completion for an event generation.
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
        if (
            not host
            or not device
            or host["status"] != "complete"
            or device["status"] != "complete"
        ):
            continue
        if host["confidence"] == "sampled" or device["confidence"] == "sampled":
            continue
        explicit = host["data"].get("resolvedStream")
        if explicit is not None and explicit != device["location"]:
            out.warn(
                "gpu-correlation-stream-conflict",
                "A correlation identifier and an explicit stream handle disagree about the execution stream.",
            )
            continue
        scope = cuda_stream_submission_scope(
            host, device["location"], properties, before=before
        )
        launches[(device["location"], scope)].append((host, device, edge))
    preceding_index = {}
    following_index = {}
    for stream, entries in launches.items():
        entries.sort(key=lambda entry: (entry[0]["end"], entry[0]["start"]))
        best = []
        latest = None
        for entry in entries:
            if latest is None or entry[1]["end"] > latest[1]["end"]:
                latest = entry
            best.append(latest)
        preceding_index[stream] = (
            [entry[0]["end"] for entry in entries],
            best,
            entries,
        )
        ordered = sorted(
            entries, key=lambda entry: (entry[0]["start"], entry[0]["end"])
        )
        following_index[stream] = ([entry[0]["start"] for entry in ordered], ordered)
    # Resolve each recorded record→wait pair separately, retaining its handle
    # generation. Destroy/re-record ambiguity was already checked above.
    budget = max(1000, out.cap * 8)
    lifecycle = collections.defaultdict(list)
    for item in items.values():
        stream = item["data"].get("resolvedStream")
        if stream is not None and cuda_stream_lifecycle_action(item):
            lifecycle[stream].append(item)
    for rows in lifecycle.values():
        rows.sort(key=lambda item: (item["start"], min(item["evidence"], default=0)))

    def ordered(a, b):
        return before(a, b) if before is not None else a["end"] < b["start"]

    def charge():
        nonlocal budget
        budget -= 1
        if budget < 0:
            out.warn(
                "gpu-stream-event-analysis-limit",
                "Recorded stream-event ordering reached its work bound; narrow the selection.",
            )
            return False
        return True

    epochs = {}

    def epoch(anchor, stream):
        key = (anchor["id"], stream)
        if key in epochs:
            return epochs[key]
        usable, created = cuda_stream_epoch(
            anchor, lifecycle.get(stream, []), before=ordered, charge=charge
        )
        if not usable:
            out.warn(
                "gpu-event-stream-generation-unresolved",
                "A stream handle was destroyed or changed without a proved live generation; no device capture bound is assigned.",
            )
        epochs[key] = (usable, created)
        return usable, created

    for dependency in list(out.edges):
        if dependency["kind"] not in ("gpu-event-dependency", "gpu-event-observation"):
            continue
        if dependency["data"].get("completionConflict"):
            continue
        record = items.get(dependency["source"])
        wait = items.get(dependency["target"])
        if (
            not record
            or not wait
            or record["status"] != "complete"
            or wait["status"] != "complete"
            or record["confidence"] == "sampled"
            or wait["confidence"] == "sampled"
        ):
            continue
        source_stream = record["data"].get("resolvedStream")
        target_stream = wait["data"].get("resolvedStream")
        if source_stream is None:
            continue
        if record["data"].get("paradigm") == "CUDA" and api_result(record) != 0:
            continue
        valid, created = epoch(record, source_stream)
        if budget < 0:
            return
        if not valid:
            continue
        scope = cuda_stream_submission_scope(
            record, source_stream, properties, before=before
        )
        times, preceding, entries = preceding_index.get(
            (source_stream, scope), ([], [], [])
        )
        first = bisect.bisect_left(times, record["start"])
        after = bisect.bisect_right(times, record["start"])
        predecessor = preceding[first - 1] if first and created is None else None
        if created is not None:
            for index in range(bisect.bisect_left(times, created["end"]), first):
                if not charge():
                    return
                entry = entries[index]
                if ordered(created, entry[0]) and (
                    predecessor is None or entry[1]["end"] > predecessor[1]["end"]
                ):
                    predecessor = entry
        # Rounded clock equality is not submission order. Keep a proven older
        # predecessor if a later equal-tick launch has no original brackets.
        for index in range(first, after):
            if not charge():
                return
            entry = entries[index]
            if (
                ordered(entry[0], record)
                and (created is None or ordered(created, entry[0]))
                and (predecessor is None or entry[1]["end"] > predecessor[1]["end"])
            ):
                predecessor = entry
        if predecessor is None:
            continue
        host, source, correlation = predecessor
        upper = dependency["data"].get("completionUpperBound")
        if upper is not None and source["end"] > upper:
            out.warn(
                "gpu-event-device-clock-conflict",
                "A recorded successful event observation precedes known device work completion; the incompatible device bound is not assigned.",
            )
            continue
        lower = dependency["data"].get("completionLowerBound")
        dependency["data"].update(
            sourceStream=source_stream,
            targetStream=target_stream,
            completionLowerBound=(
                max(source["end"], lower) if lower is not None else source["end"]
            ),
            predecessor=source["id"],
        )
        if lower is None or source["end"] > lower:
            dependency["data"]["completionLowerBoundExclusive"] = False
        if target_stream is None or not any(
            token in re.sub(r"[^a-z]", "", wait["label"].lower())
            for token in ("waitevent", "waitforevents")
        ):
            continue
        if wait["data"].get("paradigm") == "CUDA" and api_result(wait) != 0:
            continue
        valid, wait_created = epoch(wait, target_stream)
        if budget < 0:
            return
        if not valid:
            continue
        scope = cuda_stream_submission_scope(
            wait, target_stream, properties, before=before
        )
        times, following = following_index.get((target_stream, scope), ([], []))
        index = bisect.bisect_left(times, wait["end"])
        while index < len(following) and following[index][0]["start"] == wait["end"]:
            if not charge():
                return
            if ordered(wait, following[index][0]):
                break
            index += 1
        if index >= len(following):
            continue
        target_host, target, target_correlation = following[index]
        valid, target_created = epoch(target_host, target_stream)
        if budget < 0:
            return
        if not valid or (wait_created and wait_created["id"]) != (
            target_created and target_created["id"]
        ):
            continue
        if target["start"] < source["end"]:
            out.warn(
                "gpu-event-device-clock-conflict",
                "A recorded stream-wait dependency contradicts the device activity timestamps; no completion edge is assigned.",
            )
            continue
        out.edges.append(
            dict(
                id=f'gpu-event-activity:{dependency["id"]}:{source["id"]}:{target["id"]}',
                source=source["id"],
                target=target["id"],
                kind="gpu-event-activity-dependency",
                label="Device work ordered by a recorded stream event",
                start=source["end"],
                end=target["start"],
                confidence="recorded-submission-and-correlation",
                evidence=sorted(
                    set(
                        dependency["evidence"]
                        + correlation["evidence"]
                        + target_correlation["evidence"]
                    )
                ),
                data=dict(
                    eventDependency=dependency["id"],
                    sourceStream=source_stream,
                    targetStream=target_stream,
                    generation=dependency["data"]["generation"],
                    deviceCompletion=None,
                    completionLowerBound=source["end"],
                    interpretation="Known predecessor completion orders the subsequent operation. Unrecorded stream work can delay the event further.",
                ),
            )
        )
