"""Graph presentation of shared OTF2 RMA lock availability analysis."""

from __future__ import annotations

from .rma_lock_replay import LOCK_EVENTS
from .rma_lock_waits import rma_lock_analysis

RMA_LOCK_KINDS = LOCK_EVENTS


def analyze_rma_locks(out, events, members=None):
    # ``members`` remains accepted for callers of the former graph-only helper.
    # The shared core resolves ranks without collapsing group identities or
    # shifting rank indices when a malformed group member is encountered.
    model = rma_lock_analysis(
        out.trace, events, cap=out.cap, complete=not out.scan_truncated
    )
    for code, count in model["diagnostics"].items():
        out.warn(code, model["messages"][code], count)
    if model["partial"]:
        out.scan_truncated = True
    by_id = {event["id"]: event for event in events}

    def details(row):
        return {
            key: value
            for key, value in row.items()
            if key
            not in (
                "request",
                "grant",
                "acquire",
                "release",
                "event",
                "causes",
                "status",
                "id",
            )
        }

    for row in model["tests"]:
        out.interval(
            row["event"],
            row["event"],
            "rma-lock-test",
            "Unsuccessful RMA lock attempt",
            details(row),
            status="unsuccessful",
        )
    for row in model["ownership"]:
        acquire, release = row["acquire"], row["release"]
        data = details(row)
        out.interval(
            acquire,
            release,
            "rma-lock",
            "RMA lock ownership",
            data,
            status=row["status"],
        )
        if release is not None:
            out.edge(
                acquire,
                release,
                "rma-lock-ownership",
                "RMA lock acquired → released",
                data=data,
            )
    for row in model["attempts"]:
        request, grant = row["request"], row["grant"]
        data = details(row)
        data["causes"] = [
            cause.as_dict(cause.start, cause.end) for cause in row["causes"]
        ]
        out.interval(
            request,
            grant,
            "rma-lock-request",
            "RMA lock request → grant" if grant else "RMA lock request without grant",
            data,
            status=row["status"],
        )
        if grant is not None:
            out.edge(
                request,
                grant,
                "rma-lock-grant",
                "RMA lock requested → acquired",
                data=details(row),
            )
        for cause in row["causes"]:
            release = by_id[cause.source.event]
            fields = cause.as_dict(cause.start, cause.end)
            fields.update(
                overlapStart=cause.start,
                overlapEnd=cause.end,
                overlapSeconds=cause.end - cause.start,
                blockedLowerBound=0.0,
                blockedUpperBound=grant["time"] - request["time"],
                interpretation="Recorded incompatible ownership must end before this grant; resource availability is distinct from CPU blocked time.",
            )
            out.edge(
                release,
                grant,
                "rma-lock-contention",
                "Required conflicting owner release → grant",
                confidence=cause.confidence,
                data=fields,
            )
    return model
