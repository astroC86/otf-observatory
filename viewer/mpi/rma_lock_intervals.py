"""Union and overlap queries for recorded lock ownership intervals."""

import math


def _union(pairs):
    end = -math.inf
    total = 0.0
    for a, b in sorted(pairs):
        if b > max(end, a):
            total += b - max(end, a)
        end = max(end, b)
    return total


def _index(rows):
    rows = sorted(rows, key=lambda row: row["acquire"]["time"])

    def build(lo, hi):
        if lo >= hi:
            return None
        mid = (lo + hi) // 2
        left, right = build(lo, mid), build(mid + 1, hi)
        return (
            rows[mid],
            left,
            right,
            max(
                rows[mid]["release"]["time"],
                left[3] if left else -math.inf,
                right[3] if right else -math.inf,
            ),
            rows[lo]["acquire"]["time"],
        )

    return build(0, len(rows))


def _overlap(node, start, end):
    if node is None or node[3] <= start or node[4] >= end:
        return
    row, left, right, _, _ = node
    if row["acquire"]["time"] < end and row["release"]["time"] > start:
        yield row
    yield from _overlap(left, start, end)
    yield from _overlap(right, start, end)
