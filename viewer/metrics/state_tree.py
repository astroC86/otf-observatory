"""Recovered CallingContext metric cursor (static ELF audit, no execution).

The source seeks an unfiltered record but advances through selected leaves.
Keeping this cursor distinct from custom-counter lower-bound alignment matters
for sampled stacks, count resets, and the native pixel producer.
"""

import bisect
import math


class _StateSource:
    """Own the recorded grid; cursor variants preserve their native seek rules."""

    def __init__(self, records, mode, charge):
        self.mode, self.charge = mode, charge
        self.records = records
        self.times = [r["time"] for r in records]

    def rewind_equal(self, index, start):
        """Find the first equal-time record without rewinding into the dummy root."""
        while index > 1 and self.times[index - 1] == start:
            index -= 1
        return index

    def points(self, start, end):
        cursor = self.cursor(start)
        points = [(cursor.current_time, cursor.current_value())]
        while math.isfinite(cursor.next_time) and cursor.next_time <= end:
            cursor.advance()
            points.append((cursor.current_time, cursor.current_value()))
        return points


class StateTreeSource(_StateSource):
    def __init__(
        self,
        records,
        selected,
        mode,
        charge=lambda n: None,
        attribute_values=None,
        tick_seconds=1.0,
    ):
        if mode not in range(9):
            raise ValueError("Unsupported state-tree source mode")
        super().__init__(
            [dict(time=0.0, native_time=0.0, kind=0, chain=())] + records, mode, charge
        )
        self.selected = [
            bool(r["chain"]) and r["chain"][-1][1] in selected for r in self.records
        ]
        self.accepted = [
            i
            for i, r in enumerate(self.records)
            if self.selected[i]
            and (
                mode <= 4
                or mode == 5
                and r["kind"] == 2
                or mode == 6
                and r["kind"] == 3
                or mode == 7
                and r["kind"] != 1
                or mode == 8
                and r["kind"] == 1
            )
        ]
        self.prefix = [(0, 0, 0)]
        self.values = []
        counts = [0, 0, 0]
        for i, r in enumerate(self.records):
            charge(1 + len(r["chain"]))
            if self.selected[i] and r["kind"] in (1, 2, 3):
                counts[r["kind"] - 1] += 1
            self.prefix.append(tuple(counts))
            chain = r["chain"][:-1] if r["kind"] == 3 else r["chain"]
            active = (
                any(region in selected for _, region in chain)
                if mode in (1, 3)
                else bool(chain) and chain[-1][1] in selected
            )
            if mode == 0:
                value = None if i == 0 else attribute_values[i - 1]
            elif mode in (1, 2):
                value = int(active)
            elif mode in (3, 4):
                if active and i + 1 < len(self.times):
                    following = self.records[i + 1]
                    value = (
                        (following["native_time"] - r["native_time"]) * tick_seconds
                        if "native_time" in following and "native_time" in r
                        else self.times[i + 1] - r["time"]
                    )
                else:
                    value = 0
            else:
                value = 0
            self.values.append(value)
        self.flags = 0x200 if mode == 0 else 0x11200 if mode >= 5 else 0x10200

    def cursor(self, start):
        return StateTreeCursor(self, start)


class StateTreeCursor:
    def __init__(self, source, start):
        self.source = source
        # 1110e10: upper_bound-1, then backtrack exact equality to the first
        # actual record (index 1), preserving the dummy root at index 0.
        self.index = max(0, bisect.bisect_right(source.times, start) - 1)
        self.index = source.rewind_equal(self.index, start)
        # Mode 6 deliberately does not run the prefix loop. Modes 5/7/8 do.
        self.counts = (
            list(source.prefix[self.index + 1])
            if source.mode in (5, 7, 8)
            else [0, 0, 0]
        )
        self.next_position = bisect.bisect_right(source.accepted, self.index)

    @property
    def current_time(self):
        return self.source.times[self.index]

    @property
    def next_time(self):
        accepted = self.source.accepted
        return (
            self.source.times[accepted[self.next_position]]
            if self.next_position < len(accepted)
            else math.inf
        )

    def current_value(self):
        mode = self.source.mode
        if mode <= 4:
            return self.source.values[self.index]
        if mode == 5:
            return self.counts[1]
        if mode == 6:
            return self.counts[2]
        if mode == 7:
            return self.counts[1] + self.counts[2]
        return self.counts[0]

    def value(self, t):
        return self.current_value()

    def advance(self):
        if self.next_position >= len(self.source.accepted):
            return
        self.source.charge(1)
        self.index = self.source.accepted[self.next_position]
        self.next_position += 1
        kind = self.source.records[self.index]["kind"]
        if kind in (1, 2, 3):
            self.counts[kind - 1] += 1
