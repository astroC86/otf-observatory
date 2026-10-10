"""RMA records in the recovered native, sender-owned MsgCom source stream.

The graph retains group identities; this adapter separately reproduces the
native source's first non-metric location representative for numeric placement.
"""

import collections
import json

from ..mpi.communicators import GROUP_PREFIX


def group_representatives(definitions):
    """Global Location definition order is the native registration order."""
    result = {}
    for reference, location in definitions.get("Location", {}).items():
        if location.get("locationType") == 3:
            continue
        group = location.get("locationGroup")
        if group is not None:
            result.setdefault(GROUP_PREFIX + str(group), str(reference))
    return result


def normalize_rma_transfer(row, begin, representatives):
    """Return (native operation, omission reason) without mutating raw input."""
    if row.get("end") is None:
        return None, "missing-endpoint"
    if row.get("completion_event") is None or row.get("completion_location") is None:
        return None, "missing-completion-evidence"
    operation = row.get("operation")
    if operation == "RmaPut":
        native_type, category, size = -3, 2, begin.get("bytes")
    elif operation == "RmaGet":
        native_type, category, size = -4, 3, begin.get("bytes")
    elif operation == "RmaAtomic":
        native_type = begin.get("type")
        if not isinstance(native_type, int) or not 0 <= native_type <= 255:
            return None, "invalid-atomic-type"
        sent, received = begin.get("bytesSent"), begin.get("bytesReceived")
        if not all(
            isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 2**64
            for v in (sent, received)
        ):
            return None, "invalid-byte-count"
        # 0xf8d190 defines the eight known OTF2 atomic types as category 4.
        # Their MsgCom amount is the low (sent) half of the saturated payload.
        category = 4 if native_type < 8 else None
        sent, received = min(sent, 0xFFFFFFFF), min(received, 0xFFFFFFFF)
        size = sent if category == 4 else sent | (received << 32)
    else:
        return None, "unknown-operation"
    if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size < 2**64:
        return None, "invalid-byte-count"
    source_identity, target_identity = row.get("native_source"), row.get(
        "native_target"
    )

    def endpoint(identity):
        if identity is None:
            return None
        identity = str(identity)
        return (
            representatives.get(identity)
            if identity.startswith(GROUP_PREFIX)
            else identity
        )

    source, target = endpoint(source_identity), endpoint(target_identity)
    if source is None or target is None:
        return None, "unresolved-native-endpoint"
    provenance = dict(
        beginEvent=row.get("event"),
        completionEvent=row["completion_event"],
        beginLocation=row.get("location"),
        completionLocation=row["completion_location"],
        sourceIdentity=source_identity,
        targetIdentity=target_identity,
        sourceRepresentative=source,
        targetRepresentative=target,
        completionKind=row.get("status"),
        nativeCategory=category,
        byteConvention=(
            "atomic-sent-u32"
            if category == 4
            else (
                "unknown-atomic-packed-u64"
                if operation == "RmaAtomic"
                else "recorded-u64"
            )
        ),
    )
    return (
        dict(
            start=row.get("start"),
            end=row["end"],
            sender=source,
            receiver=target,
            bytes=size,
            nativeType=native_type,
            tag=-1,
            win=str(row.get("win")),
            sequence=(row["completion_event"], row["id"]),
            provenance=provenance,
        ),
        None,
    )


def rma_transfer_rows(trace, *, locations=None, limit=1_000_000, charge=None):
    """Read full-prefix RMA transfers for the message source, with omission counts.

    Location filtering applies to native source/destination after representative
    resolution. Numeric/communication/type filters remain the caller's job.
    """
    if limit < 1:
        raise ValueError("RMA metric source limit must be positive")
    selected = None if locations is None else set(map(str, locations))
    if selected is not None and not selected:
        return dict(rows=[], skipped={})
    representatives = group_representatives(trace.defs)
    rows, skipped = [], collections.Counter()
    with trace.connect() as db:
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rma_evidence'"
        ).fetchone()
        if not exists:
            count = db.execute("SELECT count(*) FROM rma").fetchone()[0]
            return dict(
                rows=[], skipped={"missing-completion-evidence": count} if count else {}
            )
        sql = """SELECT r.*, e.completion_event,e.completion_location,e.native_source,e.native_target,
                 b.data AS begin_data FROM rma r
                 LEFT JOIN rma_evidence e ON e.begin_event=r.event
                 LEFT JOIN events b ON b.id=r.event ORDER BY r.id LIMIT ?"""
        pending = 0
        for count, raw in enumerate(db.execute(sql, (limit + 1,)), 1):
            if count > limit:
                raise ValueError("RMA metric source exceeds the operation limit")
            pending += 1
            if charge and pending == 512:
                charge(pending)
                pending = 0
            row = dict(raw)
            try:
                begin = json.loads(row.pop("begin_data"))
            except (ValueError, TypeError):
                begin = None
            if not isinstance(begin, dict):
                skipped["invalid-begin-record"] += 1
                continue
            operation, reason = normalize_rma_transfer(row, begin, representatives)
            if reason:
                skipped[reason] += 1
                continue
            if selected is not None and not selected.intersection(
                (operation["sender"], operation["receiver"])
            ):
                continue
            window = trace.defs.get("RmaWin", {}).get(operation["win"], {})
            operation["comm"] = (
                str(window.get("comm")) if window.get("comm") is not None else None
            )
            operation["status"] = row["status"]
            rows.append(operation)
        if charge and pending:
            charge(pending)
    return dict(rows=rows, skipped=dict(skipped))
