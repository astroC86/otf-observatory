"""Exact CUDA API contracts and recorded return-value decoding."""

from __future__ import annotations

import re

from .fields import context_identity, context_namespace, cuda_context_handle_value

API_RESULT_UNRESOLVED = object()

# Exact aliases declared by cuda.h/cuda_runtime_api.h. Event synchronization,
# context synchronization and create/destroy calls have no PTSZ/PTDS variants.
_CUDA_PTSZ_APIS = {
    prefix + name
    for prefix in ("cuda", "cu")
    for name in (
        "eventrecord",
        "eventrecordwithflags",
        "streamwaitevent",
        "streamquery",
        "streamsynchronize",
    )
}
_CUDA_PTSZ_APIS.update(("custreamgetctx", "custreamgetctx_v2"))
_CUDA_SYNC_CONTRACTS = {
    "cudastreamsynchronize": "stream",
    "custreamsynchronize": "stream",
    "cudaeventsynchronize": "event",
    "cueventsynchronize": "event",
    "cudadevicesynchronize": "context",
    "cudathreadsynchronize": "context",
    "cuctxsynchronize": "context",
    "cuctxsynchronize_v2": "context",
    "cudaexecutionctxsynchronize": "context",
}


def cuda_api_name(label):
    """Normalize documented CUDA symbol variants without erasing punctuation."""
    name = label.strip().casefold().removesuffix("()")
    if name.endswith("_ptsz") and name[:-5] in _CUDA_PTSZ_APIS:
        name = name[:-5]
    if name in ("cueventdestroy_v2", "custreamdestroy_v2"):
        name = name.removesuffix("_v2")
    return name


def cuda_synchronization_contract(label):
    """An exact SDK API contract; unknown suffixes never manufacture one."""
    return _CUDA_SYNC_CONTRACTS.get(cuda_api_name(label))


def cuda_context_event_action(item):
    """Exact context-wide event APIs; each explicit handle type stays distinct."""
    if item["data"].get("paradigm") != "CUDA":
        return None
    name = cuda_api_name(item["label"])
    for prefix, namespace in (
        ("cuctx", "api-context-handle"),
        ("cugreenctx", "cuda-green-context-handle"),
        ("cudaexecutionctx", "cuda-execution-context-handle"),
    ):
        if name == prefix + "recordevent":
            return "context-record", namespace
        if name == prefix + "waitevent":
            return "context-wait", namespace
    return None


def cuda_context_event_scope(item):
    contract = cuda_context_event_action(item)
    if contract is None:
        return None
    rows = item["data"].get("gpuFields", {}).get("context", [])
    if not rows or any(context_namespace(row["name"]) != contract[1] for row in rows):
        return None
    values = {context_identity(row["name"], row["value"]) for row in rows}
    return next(iter(values)) if len(values) == 1 else None


def cuda_sync_context_fields(item):
    """Keep the v2 NULL-current sentinel separate from a context identity.

    A typed activity context can establish the actual scope of a NULL argument.
    Conflicting explicit argument values cannot be repaired by that record.
    Runtime execution-context handles have no implicit/current-context case.
    """
    fields = item["data"].get("gpuFields", {})
    if cuda_api_name(item["label"]) != "cuctxsynchronize_v2":
        return fields
    rows = fields.get("context", [])
    handles = [
        row for row in rows if context_namespace(row["name"]) == "api-context-handle"
    ]
    if handles and all(cuda_context_handle_value(row["value"]) == 0 for row in handles):
        return dict(fields, context=[row for row in rows if row not in handles])
    return fields


def cuda_event_action(item):
    """Classify only CUDA event APIs declared in the installed public headers.

    A CUDA-group user wrapper containing "EventRecord" is not the SDK call.
    PTSZ aliases and the driver's documented cuEventDestroy_v2 symbol retain
    their actual API contract; other suffixes do not create one.
    """
    if item["data"].get("paradigm") != "CUDA":
        return None
    context_action = cuda_context_event_action(item)
    if context_action is not None:
        return context_action[0]
    name = cuda_api_name(item["label"])
    return {
        "cudaeventcreate": "create",
        "cudaeventcreatewithflags": "create",
        "cueventcreate": "create",
        "cudaeventrecord": "record",
        "cudaeventrecordwithflags": "record",
        "cueventrecord": "record",
        "cueventrecordwithflags": "record",
        "cudaeventdestroy": "destroy",
        "cueventdestroy": "destroy",
        "cudaeventquery": "query",
        "cueventquery": "query",
        "cudaeventsynchronize": "synchronize",
        "cueventsynchronize": "synchronize",
        "cudastreamwaitevent": "wait",
        "custreamwaitevent": "wait",
    }.get(name)


def api_result(item):
    """Decode return values, keeping missing separate from conflicting/invalid."""
    values = item["data"].get("gpuFields", {}).get("api-result", [])
    results = set()
    for row in values:
        value = str(row["value"]).strip()
        key = re.sub(r"[^a-z0-9]", "", value.casefold())
        if key in ("cudasuccess", "hipsuccess", "success"):
            results.add(0)
        elif key in ("cudaerrornotready", "cudaerrornotready600"):
            results.add(600)
        else:
            try:
                results.add(
                    int(value, 0) if value.startswith(("0x", "-0x")) else int(value)
                )
            except ValueError:
                return API_RESULT_UNRESOLVED
    return (
        next(iter(results))
        if len(results) == 1
        else API_RESULT_UNRESOLVED if results else None
    )


def cuda_stream_lifecycle_action(item):
    if item["data"].get("paradigm") != "CUDA":
        return None
    name = cuda_api_name(item["label"])
    if name in (
        "cudastreamcreate",
        "cudastreamcreatewithflags",
        "cudastreamcreatewithpriority",
        "custreamcreate",
        "custreamcreatewithpriority",
        "cugreenctxstreamcreate",
        "cudaexecutionctxstreamcreate",
    ):
        return "create"
    if name in ("cudastreamdestroy", "custreamdestroy"):
        return "destroy"
    return None
