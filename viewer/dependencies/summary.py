"""Accelerator graph diagnostics, activity statistics, and response metadata."""

import collections

from ..trace.callsites import CALLSITE_LABEL
from ..gpu.clocks import clock_provenance
from .device import _occupancy


def finish_gpu(out, activity, fields, associations):
    trace = out.trace
    kernels = [i for i in activity.activity if i["kind"] == "kernel"]
    unmatched = sum(
        i["id"] not in associations.linked
        for i in kernels
        if out.visible(i["start"], i["end"], [i["location"]])
    )
    if unmatched:
        out.warn(
            "kernel-launch-unresolved",
            "Recorded kernel spans lack an unambiguous host correlation identifier; timing proximity is not treated as causality.",
            unmatched,
        )
    if associations.callsite_matches:
        out.warn(
            "callsite-not-unique-id",
            "Callsite parameters identify a source launch site, not necessarily a unique invocation. One-to-one candidates are labeled shared-callsite, not proven launch causality.",
            associations.callsite_matches,
        )
    if not kernels and activity.streams:
        out.warn(
            "no-kernel-records",
            "Accelerator streams exist, but no kernel spans are recorded in this selected interval. Copy activity does not imply kernel visibility.",
        )
    if not activity.streams:
        out.warn(
            "no-accelerator-streams", "This trace has no accelerator stream locations."
        )
    filtered_activity = [i for i in activity.activity if out.visible_interval(i)]
    device_rows = []
    for device in activity.devices.values():
        relevant = [
            i for i in filtered_activity if i["location"] in device["locations"]
        ]
        if (
            out.selected
            and not relevant
            and not any(loc in out.selected for loc in device["locations"])
        ):
            continue
        row = dict(
            device,
            **_occupancy(relevant, out.start, out.end),
            kernels=sum(i["kind"] == "kernel" for i in relevant),
            copies=sum(i["kind"] == "memory-copy" for i in relevant),
            bytes=sum(i["data"].get("bytes", 0) for i in relevant),
            partial=out.scan_truncated,
            coverage="recorded activity only",
        )
        device_rows.append(row)
    out.extra = dict(
        externalMappings=associations.external_rows[
            associations.external_offset : associations.external_offset
            + associations.external_limit
        ],
        externalMappingTotal=len(associations.external_rows),
        externalMappingMore=associations.external_offset + associations.external_limit
        < len(associations.external_rows),
        externalMappingOffset=associations.external_offset,
        externalMappingPartial=associations.external_partial,
        externalMappingInvalidRecords=fields.external_invalid,
        devices=device_rows,
        streams=[
            dict(
                s,
                device=activity.stream_devices[s["id"]],
                topology=activity.stream_topology[s["id"]],
            )
            for s in activity.streams.values()
        ],
        correlationIdentifiers=list(fields.identifiers.values())
        + list(fields.parameters.values())
        + ([CALLSITE_LABEL] if fields.source_callsites.scan_refs else []),
        correlationCandidates=associations.candidates,
        correlationCandidateTotal=associations.candidate_total,
        clockProvenance=clock_provenance(trace),
    )
    out.scanned += len(activity.activity)
    directions = collections.Counter()
    for i in filtered_activity:
        if i["kind"] == "memory-copy":
            directions[i["data"]["direction"]] += i["data"]["bytes"] or 0
    correlations = sum(
        e["kind"] in ("kernel-correlation", "memory-correlation")
        and out.visible_edge(e)
        for e in out.edges
    )
    return out.finish(
        dict(
            kernels=sum(i["kind"] == "kernel" for i in filtered_activity),
            copies=sum(i["kind"] == "memory-copy" for i in filtered_activity),
            hostApiIntervals=activity.host_count,
            correlations=correlations,
            unresolvedKernels=unmatched,
            bytes=sum(i["data"].get("bytes", 0) for i in filtered_activity),
            directionBytes=dict(directions),
            deviceStatistics="unions of recorded intervals; idle means no recorded accelerator activity",
        )
    )
