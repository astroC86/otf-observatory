"""Producer-scoped GPU correlation identities and invocation pairing."""

from __future__ import annotations

import bisect
import collections
import itertools
import re

from .fields import field_kind


def correlation_domain(name, item, split_cuda=False, device=False):
    """Keep CUPTI runtime and driver namespaces distinct when both are recorded.

    Older CUPTI kernel/memcpy records carry correlationId (driver) and a
    separate runtimeCorrelationId; a runtime API record's correlationId joins
    the latter. Newer records with a single correlationId retain the ordinary
    recorded-ID path. Unknown explicit producer prefixes do not alias CUPTI.
    """
    from .external import cupti_correlation_member

    member = cupti_correlation_member(name)
    key = re.sub(r"[^a-z0-9]", "", name.casefold())
    category = field_kind(name)
    if category != "correlation":
        return category
    if member == "runtimeCorrelationId" or key in (
        "runtimecorrelationid",
        "runtimecorrelationidentifier",
        "cuptiruntimecorrelationid",
    ):
        return "runtime-correlation"
    if key in (
        "drivercorrelationid",
        "drivercorrelationidentifier",
        "cuptidrivercorrelationid",
    ):
        return "driver-correlation"
    generic = key in ("correlation", "correlationid", "correlationidentifier")
    cuda = (key == "cupticorrelationid" or member == "correlationId") and item[
        "data"
    ].get("paradigm") == "CUDA"
    hip = (
        key in ("roctracercorrelationid", "rocprofilercorrelationid")
        and item["data"].get("paradigm") == "HIP"
    )
    if not (generic or cuda or hip):
        return "producer:" + key
    if split_cuda and item["data"].get("paradigm") == "CUDA":
        if device:
            return "driver-correlation"
        label = item["label"].lower()
        if label.startswith("cuda"):
            return "runtime-correlation"
        if label.startswith("cu"):
            return "driver-correlation"
    return category


def correlation_pairs(host, device, category, limit=2000):
    """Return unambiguous pairs and inspectable candidates for unresolved IDs.

    Repeated invocation identifiers are reusable only across disjoint lifetimes:
    the device operation must finish before the next host invocation of that ID.
    This rule never applies to source callsites, which are not invocation IDs.
    """
    if len(host) == len(device) == 1:
        return [(host[0], device[0], None)], []
    if category in ("callsite", "external-correlation") or not host or not device:
        return [], list(itertools.islice(itertools.product(host, device), limit))
    ordered = sorted(host, key=lambda r: (r[0]["start"], r[0]["id"]))
    starts = [h[0]["start"] for h in ordered]
    candidates = collections.defaultdict(list)
    for g in device:
        i = bisect.bisect_right(starts, g[0]["start"]) - 1
        if i < 0:
            continue
        h = ordered[i]
        next_start = starts[i + 1] if i + 1 < len(ordered) else float("inf")
        if i and ordered[i - 1][0]["end"] > h[0]["start"]:
            continue
        if g[0]["end"] <= next_start:
            candidates[h[0]["id"]].append((h, g, i))
    pairs = [values[0] for values in candidates.values() if len(values) == 1]
    # One device candidate must not be assigned to multiple host generations.
    use = collections.Counter(g[0]["id"] for _, g, _ in pairs)
    pairs = [p for p in pairs if use[p[1][0]["id"]] == 1]
    paired_hosts = {h[0]["id"] for h, _, _ in pairs}
    paired_devices = {g[0]["id"] for _, g, _ in pairs}
    remaining_hosts = [h for h in host if h[0]["id"] not in paired_hosts]
    remaining_devices = [g for g in device if g[0]["id"] not in paired_devices]
    unresolved = list(
        itertools.islice(itertools.product(remaining_hosts, remaining_devices), limit)
    )
    return pairs, unresolved
