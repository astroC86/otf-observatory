"""Composed metric cursors recovered from the supplied native executable.

Current time, next time and value are deliberately independent. A filtered
Stack source can seek beyond the request; combining it with another source
then advances several states without advancing the composite current time.
No target executable code is loaded or executed by this module.
Prefix and integral cursors share replay-to-start policy, but retain their
distinct clock and value ownership.
"""

import copy
import math

from .state_tree import StateTreeCursor


def valid(value):
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def normalized(value):
    return value if valid(value) else None


def snapshot(cursor, charge=lambda count: None):
    """Copy cursor state, sharing immutable sources instead of their records."""
    charge(1)
    result = copy.copy(cursor)
    if isinstance(cursor, StateTreeCursor):
        # Unlike raw Stack cursors, CallingContext counters own a mutable
        # three-element accumulator. Its source/prefix tables remain shared.
        result.counts = cursor.counts.copy()
    if hasattr(cursor, "children"):
        result.children = [snapshot(child, charge) for child in cursor.children]
    if hasattr(cursor, "child"):
        result.child = snapshot(cursor.child, charge)
    return result


def _replay_to_start(cursor, start):
    """Do not consume a tied next state once the current clock reaches start."""
    while cursor.current_time < start and cursor.next_time <= start:
        cursor.advance()


class SeriesCursor:
    """A stored/custom series cursor, without converting exact values to double."""

    def __init__(self, series, start):
        self.series = series
        self.index = series.seek_index(start)
        self.constant = series.interpolation == "constant"

    @property
    def current_time(self):
        return 0.0 if self.constant or self.index < 0 else self.series.times[self.index]

    @property
    def next_time(self):
        index = self.index + 1
        return (
            self.series.times[index]
            if not self.constant and index < len(self.series.times)
            else math.inf
        )

    def current_value(self):
        return self.value(0.0)

    def value(self, t):
        return self.series.cursor_value(self.index, t)

    def advance(self):
        if math.isfinite(self.next_time):
            self.index += 1


def factory(series):
    return getattr(series, "native_cursor", None) or (
        lambda start: SeriesCursor(series, start)
    )


class ComposedCursor:
    """ecd870/ecd8a0/ecd8e0/1115c90: max current, min next, tied advance."""

    def __init__(self, children, evaluate, timed, charge):
        self.children, self.evaluate, self.timed, self.charge = (
            children,
            evaluate,
            timed,
            charge,
        )

    @property
    def current_time(self):
        return max(self.children[i].current_time for i in self.timed)

    @property
    def next_time(self):
        return min(self.children[i].next_time for i in self.timed)

    def current_value(self):
        return self.value(0.0)

    def value(self, t):
        self.charge(len(self.children))
        return self.evaluate(
            [child.value(0.0 if t <= 0 else t) for child in self.children]
        )

    def advance(self):
        when = self.next_time
        if math.isfinite(when):
            # Snapshot all child clocks before any mutation, including ties.
            indices = [i for i in self.timed if self.children[i].next_time == when]
            self.charge(len(indices))
            for i in indices:
                self.children[i].advance()


class InterpolCursor:
    """1115790/1115c30 cache next TIME before advancing the child."""

    def __init__(self, child, charge):
        self.child, self.charge = child, charge
        self.current_time = child.current_time
        self.current = child.current_value()
        self._lookahead()

    def _lookahead(self):
        self.next_time = self.child.next_time
        if math.isfinite(self.next_time):
            self.charge(1)
            self.child.advance()
            self.following = self.child.current_value()
        else:
            self.following = self.current

    def current_value(self):
        return self.current

    def value(self, t):
        if t == 0 or t == self.current_time or not valid(self.following):
            return self.current
        if t == self.next_time:
            return self.following
        if (
            t < self.current_time
            or t > self.next_time
            or not valid(self.current)
            or self.next_time == self.current_time
        ):
            return None
        return normalized(
            self.current
            + (self.following - self.current)
            * ((t - self.current_time) / (self.next_time - self.current_time))
        )

    def advance(self):
        if math.isfinite(self.next_time):
            self.current_time, self.current = self.next_time, self.following
            self._lookahead()


class _ChildCursor:
    """A transformed value whose clocks still belong to its child."""

    def __init__(self, child, charge):
        self.child, self.charge = child, charge

    @property
    def current_time(self):
        return self.child.current_time

    @property
    def next_time(self):
        return self.child.next_time


class PrefixCursor(_ChildCursor):
    """CumSum/DiffValue consume every child advance, including clamped clocks."""

    def __init__(self, child, operation, start, charge):
        super().__init__(child, charge)
        self.operation = operation
        initial = child.current_value()
        self.saved = (
            (initial if valid(initial) else 0) if operation == "cumsum" else initial
        )
        _replay_to_start(self, start)

    def current_value(self):
        if self.operation == "cumsum":
            return self.saved
        value = self.child.current_value()
        return (
            normalized(value - self.saved)
            if valid(value) and valid(self.saved)
            else None
        )

    def value(self, t):
        return self.current_value()

    def advance(self):
        self.charge(1)
        if self.operation != "cumsum":
            value = self.child.current_value()
            if valid(value):
                self.saved = value
        self.child.advance()
        if self.operation == "cumsum":
            value = self.child.current_value()
            if valid(value):
                self.saved = (
                    normalized(self.saved + value) if valid(self.saved) else None
                )


class IntegralCursor:
    """11181c0/11180e0/1118130: zero reset, finite-state rectangles."""

    def __init__(self, child, start, charge):
        self.child, self.charge = child, charge
        if not valid(child.current_value()):
            self._next_finite()
        self.current_time, self.current = child.current_time, child.current_value()
        self._next_finite()
        self.next_time, self.following = child.current_time, child.current_value()
        self.total = 0
        _replay_to_start(self, start)

    def _next_finite(self):
        self.charge(1)
        self.child.advance()
        while not valid(self.child.current_value()) and math.isfinite(
            self.child.next_time
        ):
            self.charge(1)
            self.child.advance()

    def current_value(self):
        return self.total

    def value(self, t):
        if (
            t != 0
            and t != self.current_time
            and valid(self.following)
            and not self.current_time <= t <= self.next_time
        ):
            return None
        return self.total

    def advance(self):
        self.charge(1)
        self.total = (
            normalized(self.total + (self.next_time - self.current_time) * self.current)
            if valid(self.current) and valid(self.total)
            else None
        )
        self.current_time, self.current = self.next_time, self.following
        if math.isinf(self.child.next_time):
            self.next_time = math.inf
        else:
            self._next_finite()
            self.next_time, self.following = (
                self.child.current_time,
                self.child.current_value(),
            )


class DerivativeCursor(_ChildCursor):
    """111d940/111dc40 and 11159d0: Interpol slope, skipping equal clocks."""

    def __init__(self, child, charge):
        super().__init__(child, charge)
        self._skip_equal()

    def _skip_equal(self):
        while (
            math.isfinite(self.child.next_time)
            and self.child.next_time == self.child.current_time
        ):
            self.charge(1)
            self.child.advance()

    def current_value(self):
        if math.isinf(self.next_time):
            return 0 if valid(self.child.current) else None
        if not valid(self.child.current) or not valid(self.child.following):
            return None
        return normalized(
            (self.child.following - self.child.current)
            / (self.next_time - self.current_time)
        )

    def value(self, t):
        if t != 0 and not self.current_time <= t <= self.next_time:
            return None
        return self.current_value()

    def advance(self):
        self.charge(1)
        self.child.advance()
        self._skip_equal()


class ShiftCursor:
    def __init__(self, child, offset):
        self.child, self.offset = child, offset

    @property
    def current_time(self):
        return self.child.current_time + self.offset

    @property
    def next_time(self):
        return self.child.next_time + self.offset

    def current_value(self):
        return self.child.current_value()

    def value(self, t):
        return (
            self.child.current_value() if t == 0 else self.child.value(t - self.offset)
        )

    def advance(self):
        self.child.advance()
