"""Explicit CUDA stream modes, submission scopes and creation epochs."""

from __future__ import annotations

import re

from .api import api_result, cuda_stream_lifecycle_action
from .fields import context_identity, cuda_stream_handles, stream_namespace


def cuda_stream_semantics(properties):
    """Decode only explicit context, mode and stream-flag contracts."""
    semantics = {}
    for loc, fields in properties.items():

        def one(kind):
            values = {str(row["value"]) for row in fields.get(kind, [])}
            return next(iter(values)) if len(values) == 1 else None

        contexts = {
            context_identity(row["name"], row["value"])
            for row in fields.get("context", [])
        }
        context = next(iter(contexts)) if len(contexts) == 1 else None
        mode = one("default-stream-mode")
        flags = one("stream-flags")
        handles = {
            str(row["value"])
            for row in fields.get("stream", [])
            if stream_namespace(row["name"]) == "api-stream-handle"
        }
        special = cuda_stream_handles(fields.get("stream", []))
        if mode is not None:
            mode = re.sub(r"[^a-z]", "", mode.lower())
        if mode in ("legacy", "cudastreamlegacy"):
            mode = "legacy"
        elif mode in ("perthread", "cudastreamperthread"):
            mode = "per-thread"
        elif special == {"1"}:
            mode = "legacy"
        elif special == {"2"}:
            mode = "per-thread"
        else:
            try:
                flag = int(flags, 0) if flags is not None else None
            except ValueError:
                flag = None
            mode = (
                "blocking"
                if flag == 0 and "0" not in handles
                else "nonblocking" if flag == 1 else "unknown"
            )
        semantics[loc] = dict(context=context, mode=mode)
    return semantics


def cuda_property_applies(row, item, before=None):
    """Definitions are atemporal; SDK creation records describe later uses."""
    creation = row.get("creation")
    return creation is None or (
        before(creation, item)
        if before is not None
        else creation["end"] < item["start"]
    )


def cuda_invocation_properties(item, stream, properties, before=None):
    """Recorded stream properties applicable to this invocation's lifetime."""
    return {
        kind: [row for row in rows if cuda_property_applies(row, item, before)]
        for kind, rows in properties.get(stream, {}).items()
    }


def cuda_invocation_stream_mode(item, stream, properties, *, before=None):
    """Recorded location defaults plus this invocation's explicit CUDA mode."""
    fields = cuda_invocation_properties(item, stream, properties, before)
    for kind in ("default-stream-mode", "stream-flags"):
        fields.setdefault(kind, []).extend(
            item["data"].get("gpuFields", {}).get(kind, [])
        )
    fields.setdefault("stream", []).extend(item["data"].get("streamIdentifierRows", []))
    mode = cuda_stream_semantics({stream: fields})[stream]["mode"]
    explicit = cuda_stream_handles(item["data"].get("streamIdentifierRows", []))
    if explicit == {"2"}:
        mode = "per-thread"
    elif explicit == {"1"}:
        mode = "legacy"
    elif explicit == {"0"} and re.search(r"_(?:ptsz|ptds)$", item["label"], re.I):
        mode = "per-thread"
    return mode


def cuda_zero_default(item, stream, properties):
    rows = item["data"].get("streamIdentifierRows", []) or properties.get(
        stream, {}
    ).get("stream", [])
    return any(
        str(row["value"]) == "0"
        and re.sub(r"[^a-z0-9]", "", row["name"].casefold())
        in ("cudastream", "cudastreamt", "custream", "custreamt")
        for row in rows
    )


def cuda_stream_submission_scope(item, stream, properties, *, before=None):
    if item["data"].get("paradigm") != "CUDA":
        return None
    mode = cuda_invocation_stream_mode(item, stream, properties, before=before)
    if mode == "per-thread":
        return (mode, item["location"])
    if mode == "unknown" and cuda_zero_default(item, stream, properties):
        return ("unknown-zero", item["location"])
    if mode == "legacy":
        return ("legacy", None)
    return None


def cuda_stream_epoch(anchor, changes, *, before, charge):
    """Select a proved live creation epoch from start-ordered lifecycle calls.

    Ordering every Create before the anchor is insufficient: two Creates can
    overlap each other. Retain the latest-returning transition as a barrier,
    and require a fresh ordered Create to resolve an uncertain generation.
    """
    usable = True
    created = None
    frontier = None
    for change in changes:
        if change["start"] > anchor["start"]:
            break
        if not charge():
            return False, None
        status = api_result(change)
        if isinstance(status, int) and status != 0:
            continue
        if (
            not before(change, anchor)
            or frontier is not None
            and not before(frontier, change)
        ):
            usable = False
            created = None
        else:
            usable = cuda_stream_lifecycle_action(change) == "create" and status == 0
            created = change if usable else None
        if frontier is None or change["end"] >= frontier["end"]:
            frontier = change
    return usable, created
