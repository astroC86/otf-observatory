"""Score-P cancellation evidence scoped to native OpenMP team epochs."""

import collections
import heapq
import json

from .contracts import scorep_ompt_cancellation_contracts


def barrier_cancellation(trace, native, *, cap=150000):
    """Positive Score-P cancellation records scoped to the active team epoch."""
    result = dict(byTeam={}, partial=False)
    regions = scorep_ompt_cancellation_contracts(trace)
    if not regions:
        return result
    rows = trace.rows(
        "SELECT id,location,time,data FROM events WHERE kind='Enter' AND CAST(json_extract(data,'$.region') AS TEXT) IN ("
        + ",".join("?" for _ in regions)
        + ") ORDER BY id LIMIT ?",
        [*regions, cap + 1],
    )
    if not rows:
        return result
    if len(rows) > cap or len(native.get("operations", ())) > max(1000, cap * 4):
        result["partial"] = True
        return result
    boundaries = collections.defaultdict(list)
    ends = {}
    for op in native.get("operations", ()):
        if op["operation"] == "JOIN":
            ends[op["teamBeginEvent"]] = op.get("boundaryEvent", op["event"])
    for op in native.get("operations", ()):
        if op["operation"] == "FORK":
            key = (op["comm"], op["teamInvocation"])
            boundaries[op["location"]].extend(
                ((op["event"], 0, key), (ends.get(op["event"], float("inf")), 1, key))
            )
    # Sweep boundaries and markers in original event order. Nested teams use
    # the most recently begun still-active scope, not every enclosing team.
    by_location = collections.defaultdict(list)
    for row in rows:
        by_location[str(row["location"])].append(row)
    for loc, markers in by_location.items():
        changes = sorted(boundaries[loc])
        position = 0
        active = set()
        latest = []
        for row in markers:
            while position < len(changes) and changes[position][0] < row["id"]:
                ident, end, key = changes[position]
                position += 1
                if end:
                    active.discard(key)
                else:
                    active.add(key)
                    heapq.heappush(latest, (-ident, key))
            while latest and latest[0][1] not in active:
                heapq.heappop(latest)
            if not active:
                continue
            key = latest[0][1]
            data = json.loads(row["data"])
            ref = str(data["region"])
            proof = result["byTeam"].setdefault(
                key,
                dict(
                    firstEvent=row["id"],
                    count=0,
                    eventsPreview=[],
                    previewTruncated=False,
                ),
            )
            proof["firstEvent"] = min(proof["firstEvent"], row["id"])
            proof["count"] += 1
            if len(proof["eventsPreview"]) < 20:
                proof["eventsPreview"].append(
                    dict(
                        event=row["id"],
                        location=loc,
                        time=row["time"],
                        region=ref,
                        semantics=regions[ref]["semantics"],
                    )
                )
            else:
                proof["previewTruncated"] = True
    return result
