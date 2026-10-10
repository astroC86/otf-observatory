"""Match ordered semantic anchors while preserving explicit constraints."""

from __future__ import annotations

import array
import bisect
import collections
import json
import math


def _semantic_keys(a, b):
    """Use common recorded identities first, common call contexts second."""
    names_a = collections.defaultdict(set)
    names_b = collections.defaultdict(set)
    for rows, names in ((a, names_a), (b, names_b)):
        for r in rows:
            names[r["key"]].update(r.get("parameters", {}))
    for rows in (a, b):
        for r in rows:
            r["parameters"] = {
                n: v
                for n, v in r.get("parameters", {}).items()
                if n in names_a[r["key"]] & names_b[r["key"]]
            }

    def signatures(rows, field):
        result = collections.defaultdict(set)
        for r in rows:
            value = (
                tuple(sorted(r.get(field, {}).items()))
                if field == "parameters"
                else tuple(r.get(field, ()))
            )
            if value:
                result[r["key"]].add(value)
        return result

    pa, pb = signatures(a, "parameters"), signatures(b, "parameters")
    ca, cb = signatures(a, "callPath"), signatures(b, "callPath")
    for rows in (a, b):
        occurrences = collections.Counter()
        for r in rows:
            key = r["key"]
            parameters = tuple(sorted(r.get("parameters", {}).items()))
            context = tuple(r.get("callPath", ()))
            if parameters and pa[key] & pb[key]:
                r["matchKey"] = (key, "parameters", parameters)
                r["identity"] = "recorded-parameters"
            elif context and len(ca[key] | cb[key]) > 1 and ca[key] & cb[key]:
                r["matchKey"] = (key, "callpath", context)
                r["identity"] = "recorded-call-path"
            else:
                r["matchKey"] = (key,)
                r["identity"] = "ordered-occurrence"
            occurrences[r["matchKey"]] += 1
            r["occurrence"] = occurrences[r["matchKey"]]


def _sequence_blocks(a, b):
    """Retain pairs shared by every longest ordered semantic correspondence.

    A greedy longest block picks an arbitrary repeated iteration. Forward and
    backward LCS lengths expose every eligible pair at each correspondence
    rank; only a rank with one candidate identifies a mandatory pair.
    """
    n, m = len(a), len(b)
    forward = [array.array("H", [0]) * (m + 1)]
    for x in a:
        previous = forward[-1]
        row = array.array("H", [0]) * (m + 1)
        for j, y in enumerate(b, 1):
            row[j] = previous[j - 1] + 1 if x == y else max(previous[j], row[j - 1])
        forward.append(row)
    length = forward[-1][-1]
    options = collections.defaultdict(list)
    counts = collections.Counter()
    following = array.array("H", [0]) * (m + 1)
    for i in range(n - 1, -1, -1):
        current = array.array("H", [0]) * (m + 1)
        for j in range(m - 1, -1, -1):
            equal = a[i] == b[j]
            current[j] = (
                following[j + 1] + 1 if equal else max(following[j], current[j + 1])
            )
            if equal and forward[i][j] + 1 + following[j + 1] == length:
                rank = forward[i][j]
                counts[rank] += 1
                if len(options[rank]) < 16:
                    options[rank].append((i, j))
        following = current
    matches = [options[rank][0] for rank in sorted(options) if counts[rank] == 1]
    ambiguities = [
        dict(rank=rank, candidateCount=counts[rank], candidates=options[rank])
        for rank in sorted(options)
        if counts[rank] > 1
    ]
    blocks = []
    for ai, bi in matches:
        if (
            blocks
            and ai == blocks[-1]["a"] + blocks[-1]["count"]
            and bi == blocks[-1]["b"] + blocks[-1]["count"]
        ):
            blocks[-1]["count"] += 1
        else:
            blocks.append(dict(a=ai, b=bi, count=1))
    return blocks, ambiguities


def _constraints(trace, other, q, ranges):
    requested = q.get("constraints", [])
    if isinstance(requested, str):
        try:
            requested = json.loads(requested)
        except json.JSONDecodeError as error:
            raise ValueError("Alignment constraints must be valid JSON") from error
    if not isinstance(requested, list) or len(requested) > 256:
        raise ValueError("Alignment accepts at most 256 explicit constraints")
    result = []
    for i, item in enumerate(requested):
        if not isinstance(item, dict):
            raise ValueError("An alignment constraint must be an object")
        match = dict(
            label=str(item.get("label") or "Explicit anchor " + str(i + 1)),
            kind="explicit",
            identity="explicit-constraint",
            explicit=True,
            key=("constraint", i),
        )
        for suffix, run, scope in [("A", trace, ranges[0]), ("B", other, ranges[1])]:
            if "span" + suffix in item:
                rows = run.rows(
                    "SELECT id,start,location,incomplete,sampled FROM spans WHERE id=?",
                    [int(item["span" + suffix])],
                )
                if not rows or rows[0]["incomplete"] or rows[0]["sampled"]:
                    raise ValueError(
                        "Constraint span must identify a complete recorded region"
                    )
                row = rows[0]
                time = row["start"]
                match["span" + suffix] = row["id"]
                match["location" + suffix] = row["location"]
            elif "marker" + suffix in item:
                rows = run.rows(
                    "SELECT id,time,location FROM markers WHERE id=?",
                    [int(item["marker" + suffix])],
                )
                if not rows:
                    raise ValueError("Constraint marker not found")
                row = rows[0]
                time = row["time"]
                match["marker" + suffix] = row["id"]
                match["location" + suffix] = row["location"]
            elif "time" + suffix in item:
                time = float(item["time" + suffix])
            else:
                raise ValueError(
                    "Constraint needs a timestamp, span or marker for each run"
                )
            if not math.isfinite(time) or not scope[0] <= time <= scope[1]:
                raise ValueError(
                    "Constraint timestamps must be finite and inside the selected ranges"
                )
            match["time" + suffix] = time
        result.append(match)
    result.sort(key=lambda r: r["timeA"])
    if any(
        b["timeA"] <= a["timeA"] or b["timeB"] <= a["timeB"]
        for a, b in zip(result, result[1:])
    ):
        raise ValueError("Explicit constraints must increase strictly in both runs")
    return result


def _correspondence(a, b, constraints):
    matches = []
    blocks = []
    ambiguities = []
    ambiguity_count = 0
    left_a = left_b = 0
    times_a = [r["time"] for r in a]
    times_b = [r["time"] for r in b]
    for boundary in constraints + [None]:
        right_a = bisect.bisect_left(times_a, boundary["timeA"]) if boundary else len(a)
        right_b = bisect.bisect_left(times_b, boundary["timeB"]) if boundary else len(b)
        local, uncertain = _sequence_blocks(
            [r["matchKey"] for r in a[left_a:right_a]],
            [r["matchKey"] for r in b[left_b:right_b]],
        )
        for block in local:
            block = dict(
                a=left_a + block["a"], b=left_b + block["b"], count=block["count"]
            )
            blocks.append(block)
            for offset in range(block["count"]):
                x, y = a[block["a"] + offset], b[block["b"] + offset]
                matches.append(
                    dict(
                        label=x["label"],
                        kind=x["kind"],
                        timeA=x["time"],
                        timeB=y["time"],
                        spanA=x.get("span"),
                        spanB=y.get("span"),
                        markerA=x.get("marker"),
                        markerB=y.get("marker"),
                        locationA=x.get("location"),
                        locationB=y.get("location"),
                        key=x["matchKey"],
                        identity=x["identity"],
                        occurrenceA=x["occurrence"],
                        occurrenceB=y["occurrence"],
                        contextA=dict(
                            callPath=x.get("callPath", []),
                            parameters=x.get("parameters", {}),
                        ),
                        contextB=dict(
                            callPath=y.get("callPath", []),
                            parameters=y.get("parameters", {}),
                        ),
                    )
                )
        for group in uncertain:
            ambiguity_count += 1
            group["candidates"] = [
                dict(
                    label=a[left_a + i]["label"],
                    timeA=a[left_a + i]["time"],
                    timeB=b[left_b + j]["time"],
                    spanA=a[left_a + i].get("span"),
                    spanB=b[left_b + j].get("span"),
                    markerA=a[left_a + i].get("marker"),
                    markerB=b[left_b + j].get("marker"),
                )
                for i, j in group["candidates"]
            ]
            if len(ambiguities) < 100:
                ambiguities.append(group)
        if boundary:
            matches.append(dict(boundary))
            left_a = bisect.bisect_right(times_a, boundary["timeA"])
            left_b = bisect.bisect_right(times_b, boundary["timeB"])
    return matches, blocks, ambiguities, ambiguity_count
