"""Recorded accelerator topology and activity-union statistics."""

import collections
import re

from .common import _string


def _device(trace, loc):
    definition = trace.locations.get(str(loc), {})
    group = str(definition.get("group", "?"))
    gd = trace.defs.get("LocationGroup", {}).get(group, {})
    node = str(gd.get("systemTreeParent", "?"))
    nodes = trace.defs.get("SystemTreeNode", {})
    domains = collections.defaultdict(set)
    for record in trace.defs.get("SystemTreeNodeDomain", {}).values():
        domains[str(record.get("systemTreeNode"))].add(record.get("systemTreeDomain"))
    ancestors = []
    seen = set()
    current = node
    device_node = None
    shared_node = None
    while current in nodes and current not in seen:
        seen.add(current)
        current_domains = domains[current]
        ancestors.append(dict(id=current, domains=sorted(current_domains)))
        # Native 0x10e2e10 updates the accelerator ancestor while walking
        # towards the first shared-memory domain, including nested devices.
        if 7 in current_domains:
            device_node = current
        if 1 in current_domains:
            shared_node = current
            break
        current = str(nodes[current].get("parent", "?"))
    archive = next(iter(trace.defs.get("ArchiveProperties", {}).values()), {})
    major = archive.get("major")
    topology = dict(
        contextNode=node,
        deviceNode=device_node,
        sharedMemoryNode=shared_node,
        ancestors=ancestors,
        creatingLocationGroup=gd.get("creatingLocationGroup"),
        archiveVersion=archive or None,
    )
    if (
        major is not None
        and major >= 3
        or major is None
        and gd.get("locationGroupType") == 2
    ):
        if device_node is not None and shared_node is not None:
            nd = nodes[device_node]
            return dict(
                id=f"shared:{shared_node}:node:{device_node}",
                name=(
                    _string(trace, nd.get("className"))
                    + " "
                    + _string(trace, nd.get("name"))
                ).strip()
                or "Device " + device_node,
                confidence="recorded-system-tree-domains",
                topology=topology,
            )
        nd = nodes.get(node, {})
        return dict(
            id="node:" + node,
            name=(
                _string(trace, nd.get("className"))
                + " "
                + _string(trace, nd.get("name"))
            ).strip()
            or "Device " + node,
            confidence="recorded-system-tree",
            topology=topology,
        )
    # Native legacy CUDA identifies a device by its producer ordinal and
    # shared-memory domain. Without that domain, preserve process-local scope.
    cuda = re.search(r"CUDA\[(\d+):(\d+)\]", definition.get("name", ""))
    if cuda and shared_node is not None:
        ordinal = int(cuda[1])
        topology.update(legacyDeviceOrdinal=ordinal, legacyContextId=int(cuda[2]))
        return dict(
            id=f"shared:{shared_node}:CUDA:{ordinal}",
            name=f"CUDA device {ordinal} · shared-memory node {shared_node}",
            confidence="producer-name-and-recorded-domain",
            topology=topology,
        )
    match = re.search(r"(CUDA|HIP|OpenCL)\[(\d+):", definition.get("name", ""), re.I)
    if match:
        ordinal = match[2]
        paradigm = match[1].upper()
        return dict(
            id=f"process:{group}:{paradigm}:{ordinal}",
            name=f"{paradigm} device {ordinal} · process {group}",
            confidence="producer-stream-name",
            topology=topology,
        )
    return dict(
        id="group:" + group,
        name="Accelerator group " + group,
        confidence="recorded-location-group",
        topology=topology,
    )


def _occupancy(intervals, start, end):
    points = []
    totals = collections.Counter()
    for item in intervals:
        a = max(start, item["start"])
        b = min(end, item["end"])
        if b <= a:
            continue
        kind = (
            "kernel"
            if item["kind"] == "kernel"
            else "copy" if item["kind"] == "memory-copy" else "other"
        )
        points.extend([(a, 1, item["location"], kind), (b, -1, item["location"], kind)])
    active = collections.Counter()
    kinds = collections.Counter()
    last = start
    for t, delta, loc, kind in sorted(points):
        elapsed = t - last
        n = sum(v > 0 for v in active.values())
        if n:
            totals["busy"] += elapsed
        if n > 1:
            totals["overlap"] += elapsed
        if kinds["kernel"]:
            totals["kernel"] += elapsed
        if kinds["copy"]:
            totals["copy"] += elapsed
        if kinds["kernel"] and kinds["copy"]:
            totals["kernelCopyOverlap"] += elapsed
        active[loc] += delta
        kinds[kind] += delta
        last = t
    return dict(
        busy=totals["busy"],
        idle=max(0, end - start - totals["busy"]),
        kernel=totals["kernel"],
        copy=totals["copy"],
        overlap=totals["overlap"],
        kernelCopyOverlap=totals["kernelCopyOverlap"],
        utilization=totals["busy"] / max(end - start, 1e-30),
    )
