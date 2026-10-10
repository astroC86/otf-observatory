"""Raw instrumented-stack signal cursors recovered from the native binary.

Activity/exclusive-duration sources advance every record. Attribute sources
advance selected function records and have a separate forward-filtering seek.
Input records retain their original equal-time ordering; interval sweeps cannot
represent these contracts.
"""

import bisect
import math

from .state_tree import _StateSource


class StateStackSource(_StateSource):
    def __init__(
        self,
        records,
        selected,
        mode,
        charge=lambda n: None,
        attribute_value=None,
        tick_seconds=1.0,
    ):
        if mode not in (0, 1, 2, 3, 4):
            raise ValueError("Unsupported raw stack source mode")
        self.selected = frozenset(selected)
        super().__init__(
            [dict(time=0.0, kind="Enter", region=None, id=None)] + records, mode, charge
        )
        self.native_times = [0.0] + [
            r.get("native_time", r["time"] / tick_seconds) for r in records
        ]
        self.tick_seconds = tick_seconds
        self.values, self.accepted = [], []
        self.outer, self.matches = [], {}
        # Index zero is the dummy root, never a selected open invocation.
        stack = []
        for index, record in enumerate(self.records):
            charge(1)
            if index:
                if record["kind"] == "Enter":
                    stack.append(index)
                elif stack:
                    self.matches[stack.pop()] = index
            if record["region"] in selected:
                self.accepted.append(index)
            self.outer.append(
                next((i for i in stack if self.records[i]["region"] in selected), 0)
                if mode == 3
                else 0
            )
            if mode == 0:
                active = [
                    self.records[i]
                    for i in reversed(stack)
                    if self.records[i]["region"] in selected
                ]
                charge(len(stack))
                value = attribute_value(active)
            else:
                active = (
                    any(self.records[i]["region"] in selected for i in stack)
                    if mode == 1
                    else bool(stack) and self.records[stack[-1]]["region"] in selected
                )
                if mode in (1, 3):
                    charge(len(stack))
                value = (
                    (self.native_times[index + 1] - self.native_times[index])
                    * tick_seconds
                    if mode == 4 and active and index + 1 < len(self.times)
                    else 0 if mode == 4 else int(active)
                )
            self.values.append(value)
        self.flags = 0x200 if mode == 0 else 0x10200

    def cursor(self, start):
        return (
            StackInclusiveCursor(self, start)
            if self.mode == 3
            else StateStackCursor(self, start)
        )


class StateStackCursor:
    def __init__(self, source, start):
        self.source = source
        # e819c0 / eb90f0: upper_bound-1, then first actual equal record.
        index = max(0, bisect.bisect_right(source.times, start) - 1)
        index = source.rewind_equal(index, start)
        if source.mode == 0:
            # 1111c40 filters the reconstructed frames, then advances an
            # unselected current raw record to the next selected event. This
            # may put current_time AFTER the requested seek timestamp.
            position = bisect.bisect_left(source.accepted, index)
            index = (
                source.accepted[position]
                if position < len(source.accepted)
                else len(source.records)
            )
        self.index = index
        self.next_position = bisect.bisect_right(source.accepted, index)

    @property
    def current_time(self):
        return self.source.times[min(self.index, len(self.source.times) - 1)]

    @property
    def next_time(self):
        source = self.source
        if source.mode == 0:
            return (
                source.times[source.accepted[self.next_position]]
                if self.next_position < len(source.accepted)
                else math.inf
            )
        return (
            source.times[self.index + 1]
            if self.index + 1 < len(source.times)
            else math.inf
        )

    def current_value(self):
        return (
            self.source.values[self.index]
            if self.index < len(self.source.values)
            else None
        )

    def value(self, t):
        return self.current_value()

    def advance(self):
        if not math.isfinite(self.next_time):
            return
        self.source.charge(1)
        if self.source.mode == 0:
            self.index = self.source.accepted[self.next_position]
            self.next_position += 1
        else:
            self.index += 1


class StackInclusiveCursor:
    """111d1d0 / 1119b20: outermost selected invocation and idle gaps."""

    def __init__(self, source, start):
        self.source = source
        raw = max(0, bisect.bisect_right(source.times, start) - 1)
        first = source.rewind_equal(raw, start)
        outer = source.outer[first]
        if outer:
            self.time = source.times[outer]
            self.index = outer
            self.next_index = source.matches.get(outer, len(source.records))
            while self.time < start and self.next_time <= start:
                self.advance()
        else:
            # Search backwards for a selected record, then rewind all records
            # sharing its timestamp and consume the first selected one there.
            pos = bisect.bisect_right(source.accepted, raw) - 1
            if pos < 0:
                self.next_index = 0
            else:
                raw = source.accepted[pos]
                while raw > 0 and source.times[raw - 1] == source.times[raw]:
                    raw -= 1
                self.next_index = source.accepted[
                    bisect.bisect_left(source.accepted, raw)
                ]
            self.advance()

    @property
    def current_time(self):
        return self.time

    @property
    def next_time(self):
        return (
            self.source.times[self.next_index]
            if self.next_index < len(self.source.times)
            else math.inf
        )

    def current_value(self):
        if (
            self.next_index >= len(self.source.records)
            or self.source.records[self.next_index]["kind"] == "Enter"
        ):
            return 0
        return (
            self.source.native_times[self.next_index]
            - self.source.native_times[self.index]
        ) * self.source.tick_seconds

    def value(self, t):
        return self.current_value()

    def advance(self):
        source = self.source
        index = self.next_index
        if index >= len(source.records):
            self.index = source.accepted[-1] if source.accepted else 0
            self.time = source.times[self.index]
            return
        source.charge(1)
        self.time = source.times[index]
        self.index = index
        if (
            index in source.matches
            and source.records[index]["region"] in source.selected
        ):
            self.next_index = source.matches[index]
        else:
            position = bisect.bisect_right(source.accepted, index)
            while (
                position < len(source.accepted)
                and source.records[source.accepted[position]]["kind"] != "Enter"
            ):
                source.charge(1)
                position += 1
            self.next_index = (
                source.accepted[position]
                if position < len(source.accepted)
                else len(source.records)
            )
