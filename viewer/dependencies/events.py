"""Bounded dependency event scans with surrounding identity context."""

import json


def _events(result, kinds):
    """Full identity context when bounded; otherwise a bounded window + context."""
    trace = result.trace
    count = sum(trace.meta.get("eventTypes", {}).get(k, 0) for k in kinds)
    marks = ",".join("?" for _ in kinds)
    if count <= result.cap:
        rows = trace.rows(
            f"SELECT id,location,time,kind,data FROM events WHERE kind IN ({marks}) ORDER BY time,id LIMIT ?",
            [*kinds, result.cap + 1],
        )
    else:
        prefix = result.cap // 8
        suffix = result.cap // 8
        middle = result.cap - prefix - suffix
        rows = trace.rows(
            f"SELECT id,location,time,kind,data FROM events WHERE kind IN ({marks}) AND time<? ORDER BY time DESC,id DESC LIMIT ?",
            [*kinds, result.start, prefix],
        )
        rows += trace.rows(
            f"SELECT id,location,time,kind,data FROM events WHERE kind IN ({marks}) AND time>=? AND time<=? ORDER BY time,id LIMIT ?",
            [*kinds, result.start, result.end, middle],
        )
        rows += trace.rows(
            f"SELECT id,location,time,kind,data FROM events WHERE kind IN ({marks}) AND time>? ORDER BY time,id LIMIT ?",
            [*kinds, result.end, suffix],
        )
        result.scan_truncated = True
        result.warn(
            "bounded-context",
            "Analysis scanned a bounded window with surrounding context. Long-lived operations may lack endpoints; narrow the time range for additional detail.",
        )
    if len(rows) > result.cap:
        rows = rows[: result.cap]
        result.scan_truncated = True
    rows.sort(key=lambda e: (e["time"], e["id"]))
    result.scanned += len(rows)
    for row in rows:
        try:
            row["data"] = json.loads(row["data"])
        except (ValueError, TypeError):
            row["data"] = {}
            result.warn("invalid-event-data", "An event contains invalid JSON data.")
    return rows
