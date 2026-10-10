"""Turn function intervals and event impulses into metric signals."""

import collections
import heapq
import math

from .series import Series
from .values import MISSING_ATTRIBUTE, number


def impulses(events, start, end):
    counts = collections.Counter()
    for t, value in events:
        counts[t] += value
    points = [(start, 0), (end, 0)]
    for t, value in counts.items():
        points.append((t, value))
        reset = math.nextafter(t, math.inf)
        if reset < end and reset not in counts:
            points.append((reset, 0))
    return Series(points)


def attribute_sweep(intervals, start, end, reducer, predicate, charge):
    """SignalSourceStackXAttr value semantics, including absent vs NaN entries."""
    changes = collections.defaultdict(list)
    for ident, (a, b, value, depth) in enumerate(intervals):
        a = max(start, a)
        b = min(end, b)
        if b <= a:
            continue
        changes[a].append((ident, value, depth))
        changes[b].append((ident, MISSING_ATTRIBUTE, None))
    active = {}
    points = []
    for t in sorted(set(changes) | {start, end}):
        for ident, value, depth in changes[t]:
            if depth is None:
                active.pop(ident, None)
            else:
                active[ident] = (value, depth)
        charge(len(active) + 1)
        ordered = sorted(
            active.items(), key=lambda pair: (pair[1][1], pair[0]), reverse=True
        )
        value = reduce_attribute_entries(
            [entry[0] for _, entry in ordered], reducer, predicate
        )
        if not points or points[-1][1] != value or t == end:
            points.append((t, value))
    return Series(points, flags=0x200)


def reduce_attribute_entries(entries, reducer, predicate):
    """Leaf-to-root StackXAttr reduction; absent and NaN are distinct."""
    if reducer == "top":
        value = entries[0] if entries else None
        return (0 if predicate else None) if value is MISSING_ATTRIBUTE else value
    entries = [entry for entry in entries if entry is not MISSING_ATTRIBUTE]
    value = entries[0] if entries else None
    for incoming in entries[1:]:
        if reducer == "bottom":
            value = incoming
        elif reducer in ("sum", "mean"):
            value = (
                None if value is None or incoming is None else number(value + incoming)
            )
        elif reducer == "min":
            value = (
                value
                if value is not None and incoming is not None and value <= incoming
                else incoming
            )
        elif reducer == "max":
            value = (
                value
                if value is not None and incoming is not None and incoming <= value
                else incoming
            )
    return (
        number(value / len(entries))
        if reducer == "mean" and value is not None
        else value
    )


def sweep(intervals, start, end, baseline, method):
    """Select invocation duration by depth, or binary function activity."""
    changes = collections.defaultdict(list)
    for ident, (a, b, value, depth) in enumerate(intervals):
        a = max(start, a)
        b = min(end, b)
        if b <= a:
            continue
        changes[a].append((1, ident, value, depth))
        changes[b].append((-1, ident, value, depth))
    active = {}
    points = []
    deep = []
    for t in sorted(set(changes) | {start, end}):
        for change, ident, value, depth in changes[t]:
            if change < 0:
                active.pop(ident, None)
            else:
                active[ident] = (value, depth)
                if method in ("deepest", "shallowest"):
                    heapq.heappush(
                        deep, (-depth if method == "deepest" else depth, -ident, ident)
                    )
        if not active:
            value = baseline
        elif method in ("deepest", "shallowest"):
            while deep and deep[0][2] not in active:
                heapq.heappop(deep)
            value = active[deep[0][2]][0]
        else:
            value = 1  # max is used for the binary function-active predicate
        if not points or points[-1][1] != value or t == end:
            points.append((t, value))
    return Series(points)
