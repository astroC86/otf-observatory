"""Recorded opaque CUDA context lifetimes, distinct from CUPTI numeric IDs."""

from __future__ import annotations
import collections

from .api import api_result, cuda_api_name
from .fields import context_identity, context_namespace

_CONTRACTS = {
    "cudagreenctxcreate": ("cuda-execution-context-handle", "create"),
    "cudaexecutionctxdestroy": ("cuda-execution-context-handle", "destroy"),
    "cugreenctxcreate": ("cuda-green-context-handle", "create"),
    "cugreenctxdestroy": ("cuda-green-context-handle", "destroy"),
    "cuctxcreate": ("api-context-handle", "create"),
    "cuctxcreate_v2": ("api-context-handle", "create"),
    "cuctxcreate_v3": ("api-context-handle", "create"),
    "cuctxcreate_v4": ("api-context-handle", "create"),
    "cuctxdestroy": ("api-context-handle", "destroy"),
    "cuctxdestroy_v2": ("api-context-handle", "destroy"),
}


class ContextLifetimes:
    def __init__(
        self, items, *, before, charge, warn, provenance=lambda item: item["evidence"]
    ):
        self.rows = collections.defaultdict(list)
        self.before = before
        self.charge = charge
        self.warn = warn
        self.cache = {}
        self.provenance = provenance
        for item in items:
            if item["data"].get("paradigm") != "CUDA":
                continue
            contract = _CONTRACTS.get(cuda_api_name(item["label"]))
            if contract is None:
                continue
            namespace, action = contract
            fields = item["data"].get("gpuFields", {}).get("context", [])
            identities = {
                context_identity(row["name"], row["value"])
                for row in fields
                if context_namespace(row["name"]) == namespace
            }
            valid = len(identities) == 1 and None not in identities
            # Missing/conflicting handles cannot select an unaffected lifetime
            # or establish a fresh generation. A wildcard keeps this ambiguity.
            identity = next(iter(identities)) if valid else None
            self.rows[(item["data"]["process"], namespace)].append(
                (item, identity, action, valid)
            )
        for rows in self.rows.values():
            rows.sort(
                key=lambda row: (row[0]["start"], min(row[0]["evidence"], default=0))
            )

    def at(self, anchor, context):
        if context is None or context[0] not in (
            "api-context-handle",
            "cuda-execution-context-handle",
            "cuda-green-context-handle",
        ):
            return True, None, []
        key = (anchor["id"], context)
        if key in self.cache:
            return self.cache[key]
        usable = True
        created = None
        frontier = None
        evidence = []
        for change, identity, action, valid in self.rows.get(
            (anchor["data"]["process"], context[0]), []
        ):
            if change["start"] > anchor["end"]:
                break
            if identity is not None and identity != context:
                continue
            if not self.charge():
                usable = False
                created = None
                break
            result = api_result(change)
            if self.before(anchor, change):
                continue
            evidence.extend(self.provenance(change))
            if isinstance(result, int) and result != 0:
                continue
            complete = (
                change["status"] == "complete" and change["confidence"] != "sampled"
            )
            if (
                not self.before(change, anchor)
                or frontier is not None
                and not self.before(frontier, change)
            ):
                usable = False
                created = None
            else:
                usable = valid and complete and action == "create" and result == 0
                created = change if usable else None
            if frontier is None or change["end"] >= frontier["end"]:
                frontier = change
        if not usable:
            self.warn(
                "gpu-wait-context-generation-unresolved",
                "A recorded context destruction, reuse or ambiguous lifecycle prevents assigning work to a live opaque context generation.",
            )
        self.cache[key] = (usable, created, list(dict.fromkeys(evidence)))
        return self.cache[key]
