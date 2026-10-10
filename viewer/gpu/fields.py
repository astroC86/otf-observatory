"""Recorded GPU field namespaces and exact identifier normalization."""

from __future__ import annotations

import re


def cuda_context_handle_value(value):
    """Opaque pointer bits require an exact unsigned integer representation."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in ("null", "nullptr", "(nil)"):
            return 0
        if not re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)", text):
            return None
        try:
            value = int(text, 16 if text.startswith("0x") else 10)
        except ValueError:
            return None
    return value if 0 <= value < (1 << 64) else None


def field_kind(name):
    key = re.sub(r"[^a-z0-9]", "", name.casefold())
    if name.startswith(("CUpti_ActivityExternalCorrelation.", "CUpti_ActivityOpenAcc")):
        return None
    # These are recorded API fields, never values guessed from a region name.
    if key in (
        "returnvalue",
        "apireturnvalue",
        "cuptireturnvalue",
        "cuptiactivityapireturnvalue",
        "cudaerror",
        "cudaerrort",
        "curesult",
        "hiperror",
        "hiperrort",
    ):
        return "api-result"
    if key in (
        "contextid",
        "cudacontext",
        "cudacontextid",
        "cucontext",
        "cugreenctx",
        "cudaexecutioncontextt",
        "cupticontextid",
        "hipcontext",
        "hipcontextid",
    ):
        return "context"
    if key in ("streamflags", "cudastreamflags", "custreamflags", "hipstreamflags"):
        return "stream-flags"
    if key in ("defaultstreammode", "cudadefaultstreammode"):
        return "default-stream-mode"
    if "callsite" in key:
        return "callsite"
    if "external" in key and "correlation" in key:
        return "external-correlation"
    if "correlation" in key:
        return "correlation"
    for prefix in ("kernel", "launch", "activity"):
        if key.endswith((prefix + "id", prefix + "identifier")):
            return prefix + "-id"
    if key in (
        "stream",
        "streamid",
        "streamhandle",
        "streamlocation",
        "cudastream",
        "cudastreamid",
        "cudastreamt",
        "custream",
        "custreamt",
        "hipstream",
        "hipstreamid",
        "hipstreamt",
        "clcommandqueue",
        "commandqueue",
        "queueid",
        "cuptistreamid",
    ):
        return "stream"
    if key in (
        "event",
        "eventid",
        "eventhandle",
        "cudaevent",
        "cudaeventid",
        "cudaeventt",
        "hipevent",
        "hipeventid",
        "hipeventt",
        "clevent",
        "cuevent",
        "cuptieventid",
        "cupticudaeventid",
    ):
        return "event"
    return None


def stream_namespace(name):
    # CUPTI's numeric streamId is not the CUDA API's opaque cudaStream_t.
    return (
        "cupti-stream-id"
        if re.sub(r"[^a-z0-9]", "", name.casefold()) == "cuptistreamid"
        else "api-stream-handle"
    )


def event_namespace(name):
    key = re.sub(r"[^a-z0-9]", "", name.casefold())
    return (
        "cupti-event-id"
        if key in ("cuptieventid", "cupticudaeventid")
        else "api-event-handle"
    )


def context_namespace(name):
    key = re.sub(r"[^a-z0-9]", "", name.casefold())
    if key == "cudaexecutioncontextt":
        return "cuda-execution-context-handle"
    if key == "cugreenctx":
        return "cuda-green-context-handle"
    if key == "hipcontext":
        return "hip-context-handle"
    if key in ("cucontext", "cudacontext"):
        return "api-context-handle"
    if key in ("cupticontextid", "contextid", "cudacontextid"):
        return "cupti-context-id"
    return key


def context_identity(name, value):
    """CUPTI context IDs are process-unique uint32 IDs with an invalid sentinel."""
    namespace = context_namespace(name)
    if namespace in (
        "api-context-handle",
        "cuda-execution-context-handle",
        "cuda-green-context-handle",
        "hip-context-handle",
    ):
        number = cuda_context_handle_value(value)
        return (namespace, str(number)) if number not in (None, 0) else None
    if namespace == "cupti-context-id":
        from .external import unsigned_integer

        number = unsigned_integer(value, 32)
        if number is None or number == 0xFFFFFFFF:
            return None
        return namespace, str(number)
    return namespace, str(value)


def stream_identifiers(data):
    """Retain recorded identifier rows, including repeated producer spellings."""
    if "streamIdentifierRows" in data:
        return [
            (row["name"], str(row["value"])) for row in data["streamIdentifierRows"]
        ]
    return data.get("streamIdentifiers", {}).items()


def cuda_stream_handles(rows):
    """Opaque CUDA stream handles, excluding CUPTI's numeric stream IDs."""
    return {
        str(row["value"])
        for row in rows
        if re.sub(r"[^a-z0-9]", "", row["name"].casefold())
        in ("cudastream", "cudastreamt", "custream", "custreamt")
    }
