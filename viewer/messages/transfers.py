"""Shared MPI/RMA transfer selection in original double clock ticks."""

from __future__ import annotations

import collections
import contextlib
import functools
import json
import math
import threading

import numpy as np

from ..metrics.rma_sources import rma_transfer_rows
from ..trace.callsites import SourceCallsites

_UINT64 = (1 << 64) - 1


def _relative_tick(value, offset):
    """OTF2's (tick - globalOffset) mod 2**64 as a double; NaN when unusable."""
    try:
        return float((int(value) - offset) & _UINT64)
    except (TypeError, ValueError, OverflowError):
        return math.nan


def _relative_ticks(values, offset):
    """_relative_tick of every value.

    numpy parses with int() and wraps the uint64 subtraction exactly like the
    scalar rule; any value it cannot hold (None, junk text, out of range) sends
    the whole column through the scalar rule instead.
    """
    try:
        ticks = np.array(values, dtype=np.uint64)
    except (TypeError, ValueError, OverflowError):
        return np.array([_relative_tick(value, offset) for value in values], float)
    return (ticks - np.uint64(offset & _UINT64)).astype(float)


def _clock_bounds(start, end, emitter, first, last, clock):
    """Clock-corrected (start, end) ticks of transfers, and how many lack a raw tick.

    start and end are the recorded bounds in seconds, used without a usable raw
    tick. emitter is "send" or "receive" for proven MPI emissions and None for
    RMA. first and last are the raw ticks (None when the original event is
    missing).
    """
    resolution, offset = int(clock.get("resolution", 1)), int(clock.get("offset", 0))
    # OTF2 wrapper 0x1091990 subtracts uint64 globalOffset before converting
    # the relative integer timestamp to double. Keep its finite precision.
    a, b = _relative_ticks(first, offset), _relative_ticks(last, offset)
    missing = np.isnan(a) | np.isnan(b)
    emitter = np.array(emitter, object)
    inverted = b < a
    b = np.where(inverted & (emitter == "send"), a + 1.0, b)
    a = np.where(inverted & (emitter == "receive"), np.maximum(b - 1.0, 0.0), a)
    # Old hand-built indexes may contain proven bounds without the original
    # event. Retain their values with explicit provenance.
    rows = np.flatnonzero(missing).tolist()
    a[rows] = [start[row] * resolution for row in rows]
    b[rows] = [end[row] * resolution for row in rows]
    # f4cd70 stores (start, end-start); f352e0 reconstructs the endpoint.
    return a, a + (b - a), len(rows)


class Transfers:
    """Normalized transfers as columns, in candidate order.

    Grouping and filter fields are integer codes into per-field lists of
    distinct values, so selections and reductions are array operations. tag and
    comm hold their str() form, the only form summaries and filters read.
    """

    FIELDS = dict(
        bytes=None,
        sender=None,
        receiver=None,
        nativeType=None,
        callsite=None,
        tag=str,
        comm=str,
    )

    def __init__(self, start, end, sequence, fields):
        self.start = np.array(start, dtype=float)
        self.end = np.array(end, dtype=float)
        # Emission order: by start, then the retained sequence, then candidate order.
        sequence = np.array(sequence, dtype=np.int64).reshape(-1, 2)
        self.rank = np.empty(len(self.start), np.intp)
        self.rank[np.lexsort((sequence[:, 1], sequence[:, 0], self.start))] = np.arange(
            len(self.start)
        )
        self.codes, self.values = {}, {}
        for name, convert in self.FIELDS.items():
            column = (
                fields[name] if convert is None else list(map(convert, fields[name]))
            )
            values = list(dict.fromkeys(column))
            index = {value: code for code, value in enumerate(values)}
            self.codes[name] = np.fromiter(
                map(index.__getitem__, column), np.intp, len(self.start)
            )
            self.values[name] = values
        # The native constructor clamps a negative or NaN amount before conversion.
        self.size = np.array(
            [0.0 if not size >= 0 else float(size) for size in self.values["bytes"]],
            dtype=float,
        )[self.codes["bytes"]]

    def __len__(self):
        return len(self.start)

    def take(self, rows):
        """Transfers at an index array or mask, sharing the distinct values."""
        part = object.__new__(Transfers)
        part.start, part.end = self.start[rows], self.end[rows]
        part.size, part.rank = self.size[rows], self.rank[rows]
        part.codes = {name: codes[rows] for name, codes in self.codes.items()}
        part.values = self.values
        return part

    def member(self, field, test):
        """Per-transfer test(value) of one field, evaluated once per distinct value."""
        table = np.array([bool(test(value)) for value in self.values[field]], bool)
        return table[self.codes[field]]

    def recode(self, field, convert):
        """Codes and distinct values of convert(value), merging equal results."""
        index = {}
        table = np.array(
            [
                index.setdefault(convert(value), len(index))
                for value in self.values[field]
            ],
            np.intp,
        )
        return table[self.codes[field]], list(index)

    def endpoints(self):
        """str() of senders and receivers by first appearance, sender first."""
        first = []
        for column, field in enumerate(("sender", "receiver")):
            codes = self.codes[field]
            _, rows = np.unique(codes, return_index=True)
            first += [
                (2 * row + column, str(self.values[field][codes[row]]))
                for row in rows.tolist()
            ]
        return [name for _, name in sorted(first)]


def native_transfer_records(trace, q, *, point_window=False, tick_window=None):
    """Shared MPI/RMA producer of the native summary, timeline and matrix views.

    locations selects sender locations. receiverLocations is independently
    available; tag/comm/minBytes/maxBytes/transferTypes restrict the records.
    Matrix queries allow exact-time start selection; MessageSummary does not.
    One producer keeps clock correction and RMA normalization identical.
    """
    start, end, _, _ = trace.scope(q, regions=False)
    resolution = int(trace.meta.get("clock", {}).get("resolution", 1))
    if resolution <= 0:
        raise ValueError("Invalid recorded clock resolution")
    selected = frozenset(q["locations"].split(",")) if q.get("locations") else None
    allowed = dict(
        sender=selected,
        receiver=(
            set(q["receiverLocations"].split(","))
            if q.get("receiverLocations")
            else None
        ),
        nativeType=None,
        tag=None if q.get("tag") in (None, "") else {str(q["tag"])},
        comm=None if q.get("comm") in (None, "") else {str(q["comm"])},
    )
    if q.get("transferTypes") not in (None, ""):
        raw = q["transferTypes"]
        allowed["nativeType"] = {
            int(value) for value in (raw.split(",") if isinstance(raw, str) else raw)
        }
        if any(value < -4 or value > 255 for value in allowed["nativeType"]):
            raise ValueError("Invalid native transfer type")
    minimum, maximum = (
        int(q[key]) if q.get(key) not in (None, "") else None
        for key in ("minBytes", "maxBytes")
    )
    if minimum is not None and minimum < 0 or maximum is not None and maximum < 0:
        raise ValueError("Message byte filters must be nonnegative")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("Message minimum byte filter exceeds maximum")
    start_tick, end_tick = start * resolution, end * resolution
    if tick_window is not None:
        start_tick, end_tick = tick_window
        if (
            not all(math.isfinite(value) for value in tick_window)
            or end_tick < start_tick
        ):
            raise ValueError("Invalid native transfer tick window")
    transfers, positions, diagnostics = _transfer_candidates(trace, selected)
    # Only point_window callers (the matrix) select starts in an exact-time window.
    accepted = (
        (point_window or start_tick != end_tick)
        & (start_tick <= transfers.start)
        & (transfers.start <= end_tick)
    )
    for field, values in allowed.items():
        if values is not None:
            accepted &= transfers.member(field, values.__contains__)
    if minimum is not None or maximum is not None:
        accepted &= transfers.member(
            "bytes",
            lambda size: not (
                minimum is not None
                and size < minimum
                or maximum is not None
                and size > maximum
            ),
        )
    return dict(
        transfers=transfers.take(accepted),
        start=start,
        end=end,
        startTick=start_tick,
        endTick=end_tick,
        resolution=resolution,
        callsites={
            position["key"]: position for row, position in positions if accepted[row]
        },
        diagnostics=[
            dict(code=code, count=count) for code, count in sorted(diagnostics.items())
        ],
    )


class _KeyLocks:
    """Per-key locks that stay registered while any caller holds or waits for them.

    A failed load leaves nothing cached; the callers already waiting and any newcomer
    must still share one lock so the retry also runs once.
    """

    def __init__(self):
        self._guard = threading.Lock()
        self._entries = {}  # key -> (lock, callers holding or waiting)

    @contextlib.contextmanager
    def hold(self, key):
        with self._guard:
            lock, callers = self._entries.get(key) or (threading.Lock(), 0)
            self._entries[key] = (lock, callers + 1)
        try:
            with lock:
                yield
        finally:
            with self._guard:
                lock, callers = self._entries[key]
                if callers == 1:
                    del self._entries[key]
                else:
                    self._entries[key] = (lock, callers - 1)


_LOADING = _KeyLocks()


def _transfer_candidates(trace, selected):
    """Cached candidates, loaded once per key even when requests arrive together.

    The communication view requests summary, matrix and timeline at the same time;
    without one load per key each request would scan every transfer itself.
    """
    with _LOADING.hold((trace, selected)):
        return _load_transfer_candidates(trace, selected)


# A proven native MPI emission: the sender or receiver emitted it with both bounds.
_VERIFIED = """(e.emitter IN ('send','receive') AND e.native_start IS NOT NULL
    AND e.native_end IS NOT NULL)"""


def _mpi_rows(cursor, selected):
    """Proven MPI emissions of the selected senders, with the rejected row counts.

    Rejected rows are only counted, so they never read their original events.
    Each row is (sequence, id, bytes, sender, receiver, tag, comm, native_start,
    native_end, emitter, send tick, receive tick). Returns
    (rows, (unverified, unresolved)).
    """
    senders, args = "", ()
    if selected is not None:
        senders = f" AND m.source IN ({','.join('?' for _ in selected)})"
        args = tuple(selected)
    total = cursor.execute(
        f"SELECT count(*) FROM messages m WHERE 1{senders}", args
    ).fetchone()[0]
    evidence = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_evidence'"
    ).fetchone()
    if not evidence:
        return [], (total, 0)
    proven = """FROM messages m JOIN message_evidence e
        ON e.send_event=m.send_event AND e.recv_event=m.recv_event"""
    unresolved = cursor.execute(
        f"""SELECT count(*) {proven} WHERE (m.source IS NULL OR m.target IS NULL)
        AND {_VERIFIED}{senders}""",
        args,
    ).fetchone()[0]
    rows = cursor.execute(
        f"""SELECT coalesce(nullif(e.emission_event, 0), m.id),m.id,
        m.bytes,m.source,m.target,m.tag,m.comm,
        e.native_start,e.native_end,e.emitter,s.tick,r.tick {proven}
        LEFT JOIN events s ON s.id=m.send_event
        LEFT JOIN events r ON r.id=m.recv_event
        WHERE {_VERIFIED} AND m.source IS NOT NULL AND m.target IS NOT NULL
        {senders} ORDER BY m.id""",
        args,
    ).fetchall()
    # Every other selected row lacks a proven native emission.
    return rows, (total - unresolved - len(rows), unresolved)


@functools.lru_cache(maxsize=4)
def _load_transfer_candidates(trace, selected):
    """Clock-corrected MPI/RMA transfers of the selected senders with their callsites.

    Window and filter tests are applied per query, so summary, matrix and timeline
    requests over one sender selection share these candidates. Returns
    (Transfers, [(row, callsite position)], diagnostics).
    """
    diagnostics = collections.Counter()
    positions = []
    with trace.connect() as db:
        cursor = db.cursor()
        cursor.row_factory = None  # plain tuples for the per-transfer columns
        rows, counts = _mpi_rows(cursor, selected)
        kinds, callsites = [-2] * len(rows), [-1] * len(rows)
        for code, count in zip(
            ("unverified-mpi-emission", "unresolved-mpi-endpoint"), counts
        ):
            if count:
                diagnostics[code] += count
        rma = rma_transfer_rows(trace, locations=selected)
        diagnostics.update(rma["skipped"])
        source_callsites = SourceCallsites(trace.defs)
        event_columns = "id,tick,data" if source_callsites.scan_refs else "id,tick"
        # Bounded batches avoid a per-operation SQL query and a second complete
        # event dictionary for large RMA archives.
        for batch_start in range(0, len(rma["rows"]), 400):
            batch = rma["rows"][batch_start : batch_start + 400]
            ids = {
                op["provenance"][field]
                for op in batch
                for field in ("beginEvent", "completionEvent")
            }
            events = {
                row[0]: row
                for row in cursor.execute(
                    f'SELECT {event_columns} FROM events WHERE id IN ({",".join("?" for _ in ids)})',
                    tuple(ids),
                )
            }
            for operation in batch:
                first = events.get(operation["provenance"]["beginEvent"])
                last = events.get(operation["provenance"]["completionEvent"])
                position = None
                if source_callsites.scan_refs and first:
                    position = source_callsites.extract(
                        json.loads(first[2]).get("attributes", [])
                    )
                    if position:
                        positions.append((len(rows), position))
                # The _mpi_rows layout; RMA transfers have no MPI emitter.
                rows.append(
                    (
                        *operation["sequence"],
                        operation["bytes"],
                        operation["sender"],
                        operation["receiver"],
                        operation["tag"],
                        operation["comm"],
                        operation["start"],
                        operation["end"],
                        None,
                        first[1] if first else None,
                        last[1] if last else None,
                    )
                )
                kinds.append(operation["nativeType"])
                callsites.append(position["key"] if position else -1)
    columns = list(zip(*rows)) or [()] * 12
    start, end, missing = _clock_bounds(*columns[7:], trace.meta.get("clock", {}))
    if missing:
        diagnostics["missing-original-clock-ticks"] += missing
    sequence, ident, size, sender, receiver, tag, comm = columns[:7]
    transfers = Transfers(
        start,
        end,
        np.column_stack((sequence, ident)),
        dict(
            bytes=size,
            sender=sender,
            receiver=receiver,
            nativeType=kinds,
            callsite=callsites,
            tag=tag,
            comm=comm,
        ),
    )
    return transfers, positions, diagnostics
