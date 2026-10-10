"""Statically recovered FileIO/MsgCom signal states, in trace seconds.

Input operations contain start, end, bytes, attribute and optional sequence.
The caller supplies the full filtered stream, not just the visible time range.
Duplicate timestamps are significant cursor states. See docs/binary-gpu.md and
docs/binary-operation-signals.md for the evidence and malformed-input limits.

Message completions coalesce by timestamp; I/O completions retain per-operation
identity. I/O first/last reductions share an ordering heap, independent of the
completion heap and the native extrema tree.
"""

from dataclasses import dataclass, field
import collections
import heapq
import math
import sys


@dataclass
class OperationSignal:
    points: list
    flags: int
    skipped: dict = field(default_factory=dict)


def _double(value):
    if value is None:
        return math.nan
    try:
        return float(value)
    except OverflowError:
        return math.copysign(math.inf, -1 if value < 0 else 1)


def _public(value):
    return None if math.isnan(value) else value


class _Node:
    __slots__ = ("value", "parent", "left", "right", "red")

    def __init__(self, value=None):
        self.value = value
        self.parent = None
        self.left = None
        self.right = None
        self.red = True


class _ValueTree:
    """Red-black multiset with native less-than ordering and iterator erasure.

    NaN is intentionally inserted using ordinary IEEE comparisons. It does not
    define a strict weak order, so replacing this with Python min/sorted or
    binary insertion into a list changes the observed native tree endpoints.
    """

    def __init__(self):
        self.root = None

    @staticmethod
    def red(node):
        return node is not None and node.red

    def rotate(self, node, left):
        child = node.right if left else node.left
        middle = child.left if left else child.right
        if left:
            node.right = middle
        else:
            node.left = middle
        if middle is not None:
            middle.parent = node
        self.replace(node, child)
        if left:
            child.left = node
        else:
            child.right = node
        node.parent = child

    def insert(self, value):
        node = _Node(value)
        parent = None
        cursor = self.root
        while cursor is not None:
            parent = cursor
            cursor = cursor.left if value < cursor.value else cursor.right
        node.parent = parent
        if parent is None:
            self.root = node
        elif value < parent.value:
            parent.left = node
        else:
            parent.right = node
        inserted = node
        while node is not self.root and self.red(node.parent):
            parent = node.parent
            grand = parent.parent
            left = parent is grand.left
            uncle = grand.right if left else grand.left
            if self.red(uncle):
                parent.red = False
                uncle.red = False
                grand.red = True
                node = grand
            else:
                if node is (parent.right if left else parent.left):
                    node = parent
                    self.rotate(node, left)
                    parent = node.parent
                    grand = parent.parent
                parent.red = False
                grand.red = True
                self.rotate(grand, not left)
        self.root.red = False
        return inserted

    def replace(self, node, child):
        if node.parent is None:
            self.root = child
        elif node is node.parent.left:
            node.parent.left = child
        else:
            node.parent.right = child
        if child is not None:
            child.parent = node.parent

    def erase(self, node):
        removed = node
        was_red = removed.red
        if node.left is None:
            child = node.right
            parent = node.parent
            self.replace(node, child)
        elif node.right is None:
            child = node.left
            parent = node.parent
            self.replace(node, child)
        else:
            removed = node.right
            while removed.left is not None:
                removed = removed.left
            was_red = removed.red
            child = removed.right
            if removed.parent is node:
                parent = removed
                if child is not None:
                    child.parent = removed
            else:
                parent = removed.parent
                self.replace(removed, child)
                removed.right = node.right
                removed.right.parent = removed
            self.replace(node, removed)
            removed.left = node.left
            removed.left.parent = removed
            removed.red = node.red
        if was_red:
            return
        while child is not self.root and not self.red(child):
            left = child is parent.left
            sibling = parent.right if left else parent.left
            if self.red(sibling):
                sibling.red = False
                parent.red = True
                self.rotate(parent, left)
                sibling = parent.right if left else parent.left
            near = sibling.left if left else sibling.right
            far = sibling.right if left else sibling.left
            if not self.red(near) and not self.red(far):
                sibling.red = True
                child = parent
                parent = child.parent
            else:
                if not self.red(far):
                    if near is not None:
                        near.red = False
                    sibling.red = True
                    self.rotate(sibling, not left)
                    sibling = parent.right if left else parent.left
                    far = sibling.right if left else sibling.left
                sibling.red = parent.red
                parent.red = False
                if far is not None:
                    far.red = False
                self.rotate(parent, left)
                child = self.root
                break
        if child is not None:
            child.red = False

    def endpoint(self, last=False):
        node = self.root
        if node is None:
            return math.nan
        while (node.right if last else node.left) is not None:
            node = node.right if last else node.left
        return node.value


IO_MODES = {
    "io_simultaneous": 0,
    "io_size": 1,
    "io_bandwidth": 2,
    "io_count": 3,
    "io_attribute": 4,
}
MESSAGE_MODES = {
    "message_count": 0,
    "message_simultaneous": 0,
    "message_volume": 1,
    "message_rate": 2,
    "message_duration": 3,
}
REDUCERS = {"first": 0, "last": 1, "sum": 2, "min": 3, "max": 4, "mean": 5}


def operation_signal(
    operations, *, family, mode, tick_seconds, reducer="sum", charge=None
):
    """Return all native cursor states for normalized complete operations.

    Missing endpoint records and negative I/O lifetimes are explicitly counted
    in ``skipped``: their native ingestion contract has not been established.
    Message negative lifetimes follow the recovered per-mode clamp/skip rules.
    """
    if family not in ("io", "message"):
        raise ValueError("Operation family must be io or message")
    tick_seconds = float(tick_seconds)
    if not math.isfinite(tick_seconds) or tick_seconds <= 0:
        raise ValueError("tick_seconds must be positive and finite")
    modes = IO_MODES if family == "io" else MESSAGE_MODES
    mode = modes.get(mode, mode)
    reducer = REDUCERS.get(reducer, reducer)
    if mode not in modes.values():
        raise ValueError("Unknown operation source mode")
    if reducer not in REDUCERS.values():
        raise ValueError("Unknown I/O reduction")
    pending_charge = 0

    def account(flush=False):
        nonlocal pending_charge
        if charge is None:
            return
        pending_charge += not flush
        if pending_charge >= 1024 or (flush and pending_charge):
            charge(pending_charge)
            pending_charge = 0

    skipped = collections.Counter()
    rows = []
    for sequence, row in enumerate(operations):
        account()
        if row.get("start") is None or row.get("end") is None:
            skipped["missing-endpoint"] += 1
            continue
        start = _double(row["start"])
        end = _double(row["end"])
        if not math.isfinite(start) or not math.isfinite(end):
            skipped["nonfinite-time"] += 1
            continue
        if start < 0 or (family == "io" and end < start):
            skipped["invalid-time-order"] += 1
            continue
        rows.append((start, row.get("sequence", sequence), sequence, end, row))
    rows.sort(key=lambda row: row[:3])
    if family == "message":
        result = _messages(rows, mode, tick_seconds, skipped, account)
    else:
        result = _io(rows, mode, reducer, tick_seconds, skipped, account)
    account(True)
    return result


def _messages(rows, mode, tick, skipped, account):
    points = [(0.0, 0.0)]
    current = 0.0
    pending = {}
    queue = []
    index = 0
    while index < len(rows) or queue:
        account()
        if queue and (index == len(rows) or queue[0] < rows[index][0]):
            time = heapq.heappop(queue)
            current = max(current - pending.pop(time), 0.0)
            points.append((time, _public(current)))
            continue
        start, _, _, end, row = rows[index]
        index += 1
        duration = end - start
        if mode == 2 and duration <= 0:
            points.append((start, _public(current)))
            continue
        if mode == 0:
            value = 1.0
            finish = start + max(duration, 0.0)
        elif mode == 3:
            value = duration
            finish = start + tick
        else:
            value = _double(row.get("bytes", 0))
            finish = start + max(duration, 0.0)
            if mode == 2:
                value /= duration
        if mode == 3:
            current = value
        else:
            current += value
        if finish not in pending:
            pending[finish] = 0.0
            heapq.heappush(queue, finish)
        if mode == 3:
            pending[finish] = value
        else:
            pending[finish] += value
        points.append((start, _public(current)))
    return OperationSignal(points, 0x10200, dict(skipped))


def _io(rows, mode, reducer, tick, skipped, account):
    flags = (0x10200, 0x10200, 0x10200, 0x11200, 0x200)[mode]
    points = [(0.0, 0.0 if mode in (0, 3) else None)]
    active = {}
    completions = []
    ordered = []
    tree = _ValueTree()
    count = 0
    total = 0.0
    counter = 0.0
    index = 0

    def value():
        if mode in (0, 3):
            return counter
        if reducer in (2, 5):
            return total / (count if reducer == 5 else 1) if count else math.nan
        if reducer in (3, 4):
            return tree.endpoint(reducer == 4)
        while ordered and ordered[0][2] not in active:
            heapq.heappop(ordered)
        return active[ordered[0][2]][0] if ordered else math.nan

    while index < len(rows) or completions:
        account()
        if completions and (index == len(rows) or completions[0][0] < rows[index][0]):
            time, ident = heapq.heappop(completions)
            amount, node = active.pop(ident)
            if mode < 3:
                counter -= amount
            if reducer in (3, 4):
                tree.erase(node)
            elif reducer in (2, 5) and not math.isnan(amount):
                count -= 1
                total -= amount
                if abs(total) > sys.float_info.max:
                    total = 0.0
                    count = 0
                    for unused, remaining in sorted(completions):
                        account()
                        other = active[remaining][0]
                        if not math.isnan(other):
                            total += other
                            count += 1
            points.append((time, _public(value())))
            continue
        start, _, _, end, row = rows[index]
        ident = index
        index += 1
        if mode == 3:
            counter += 1
            points.append((start, counter))
            continue
        if mode == 0:
            amount = 1.0
        elif mode == 4:
            amount = _double(row.get("attribute"))
        else:
            size = row.get("bytes")
            amount = 0.0 if size in (None, -1, 0xFFFFFFFFFFFFFFFF) else _double(size)
            if mode == 2:
                amount /= max(end - start, tick)
        if mode < 3:
            counter += amount
        node = tree.insert(amount) if reducer in (3, 4) else None
        active[ident] = (amount, node)
        heapq.heappush(completions, (end, ident))
        if reducer == 0:
            heapq.heappush(ordered, (start, ident, ident))
        elif reducer == 1:
            heapq.heappush(ordered, (-start, -ident, ident))
        if reducer in (2, 5) and not math.isnan(amount):
            total += amount
            count += 1
        points.append((start, _public(value())))
    return OperationSignal(points, flags, dict(skipped))
