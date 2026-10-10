"""Partition source-location activity by deepest recorded region."""

import collections
import heapq


def _partition(trace, location, start, end, budget):
    if end <= start:
        return [], 0, False
    _, _, sql, args = trace.interval(
        "spans", dict(start=start, end=end, locations=location)
    )
    rows = trace.rows(
        f"SELECT s.id,s.location,s.region,s.start,s.end,s.depth,s.incomplete,s.sampled FROM {sql} ORDER BY s.start,s.id LIMIT ?",
        [*args, budget + 1],
    )
    if len(rows) > budget:
        return (
            [
                dict(
                    start=start,
                    end=end,
                    duration=end - start,
                    status="scan-limit",
                    operations=[],
                )
            ],
            budget,
            True,
        )
    boundaries = collections.defaultdict(lambda: [[], []])
    boundaries[start]
    boundaries[end]
    for row in rows:
        a, b = max(start, row["start"]), min(end, row["end"])
        if b <= a:
            continue
        boundaries[a][1].append(row)
        boundaries[b][0].append(row)
    active = {}
    depths = []
    segments = []
    previous = start
    for time, (leaves, enters) in sorted(boundaries.items()):
        while depths and depths[0][1] not in active:
            heapq.heappop(depths)
        if time > previous:
            deepest = -depths[0][0] if depths else None
            chosen = sorted(
                (r for r in active.values() if r["depth"] == deepest),
                key=lambda r: r["id"],
            )
            status = (
                "unrecorded"
                if not chosen
                else (
                    "ambiguous-regions"
                    if len(chosen) > 1
                    else (
                        "incomplete-region"
                        if chosen[0]["incomplete"]
                        else (
                            "sampled-region"
                            if chosen[0]["sampled"]
                            else "recorded-region"
                        )
                    )
                )
            )
            operations = [
                dict(
                    location=r["location"],
                    span=r["id"],
                    region=r["region"],
                    routine=trace.regions.get(r["region"], {}).get("name", r["region"]),
                    start=r["start"],
                    end=r["end"],
                    sampled=bool(r["sampled"]),
                    incomplete=bool(r["incomplete"]),
                )
                for r in chosen[:8]
            ]
            if (
                segments
                and segments[-1]["status"] == status
                and segments[-1]["operations"] == operations
                and segments[-1]["operationCount"] == len(chosen)
            ):
                segments[-1]["end"] = time
                segments[-1]["duration"] = time - segments[-1]["start"]
            else:
                segments.append(
                    dict(
                        start=previous,
                        end=time,
                        duration=time - previous,
                        status=status,
                        operations=operations,
                        operationCount=len(chosen),
                    )
                )
        for row in leaves:
            active.pop(row["id"], None)
        for row in enters:
            active[row["id"]] = row
            heapq.heappush(depths, (-row["depth"], row["id"]))
        previous = time
    return segments, len(rows), False
