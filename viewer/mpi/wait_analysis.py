"""Full-context MPI wait analysis and immutable-index cache ownership."""

import collections
import contextlib
import gc
import pathlib
import threading

from ..causality.lazy_causes import CauseCollection
from .collectives import _collective_brackets, _collectives
from .requests import _requests
from .recording import MpiRecordingContinuity
from .wait_models import Record, SpanLookup, CATEGORY_BY_ROUTINE, COLLECTIVE, WAIT, TEST
from .point_to_point import MessageWaits
from .collective_waits import CollectiveWaits
from .matched_probe import analyze as analyze_matched_probes
from .rma_lock_waits import rma_lock_causes

_CACHE = collections.OrderedDict()
_CACHE_LOCK = threading.RLock()
_CACHE_BUDGET = 850_000  # Compact records; at most two immutable trace indexes.


@contextlib.contextmanager
def paused_gc():
    """Pause cyclic GC while building ~1M long-lived objects it would rescan."""
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            # Promote the new objects straight to the oldest generation so
            # young collections do not rescan them right after re-enabling.
            gc.freeze()
            gc.unfreeze()
            gc.enable()


@paused_gc()
def _analyze(trace):
    diagnostics = collections.Counter()
    lookup = SpanLookup(trace)
    records = {}
    brackets = _collective_brackets(trace, diagnostics)
    continuity = MpiRecordingContinuity(trace, brackets)
    if continuity.partial:
        diagnostics["mpi_recording_scan_limit"] += 1
    for spans in lookup.by_location.values():
        for span in spans:
            category = CATEGORY_BY_ROUTINE.get(span.routine, "")
            if category:
                if span.sampled:
                    diagnostics["sampled_routine_excluded"] += 1
                    continue
                records[span.id] = Record(
                    span,
                    category,
                    span.start,
                    evidence=dict(
                        messages=[], requestCount=0, requests=[], failedTests=0
                    ),
                )
                if span.incomplete:
                    diagnostics["incomplete_routine_bracket"] += 1
    requests, tests = _requests(trace, lookup, diagnostics)
    completions = {
        r.completion_event: r for r in requests if r.completion_event is not None
    }
    observed_completions = WAIT | TEST
    for request in requests:
        span = request.completion_span
        if span and span.id in records and span.routine in observed_completions:
            record = records[span.id]
            record.evidence["requestCount"] += 1
            if len(record.evidence["requests"]) < 16:
                record.evidence["requests"].append(
                    dict(
                        id=request.request,
                        generation=request.generation,
                        status=request.status,
                        initiationEvent=request.initiation_event,
                        completionEvent=request.completion_event,
                    )
                )
            record.confidence = "observed-routine"
    for span, count, events in tests.values():
        if span.id in records:
            records[span.id].evidence.update(failedTests=count, testEvents=events)
            records[span.id].confidence = "observed-routine"
    MessageWaits(
        trace, lookup, records, requests, completions, diagnostics, continuity
    ).analyze()
    matched_probes = analyze_matched_probes(
        trace, lookup, requests, records, diagnostics, continuity
    )
    collective_records, collectives = _collectives(
        trace, lookup, diagnostics, continuity, brackets
    )
    del brackets
    shared_cause_weight = CollectiveWaits(
        trace, lookup, records, completions, diagnostics
    ).analyze(collective_records, collectives)
    for record in collective_records:
        span_id = record.evidence.get("span")
        if span_id in records and records[span_id].span.routine in COLLECTIVE:
            records.pop(span_id)
    rma_locks = rma_lock_causes(
        trace,
        lambda event: lookup.at(
            str(event["location"]), event["time"], event=event["id"]
        ),
    )
    diagnostics.update(rma_locks["diagnostics"])
    for ident, matched in rma_locks["by_span"].items():
        record = records.get(ident)
        if record is None:
            target = matched["causes"][0].target
            evidence = matched["evidence"]["rmaLockAttempts"][0]
            span = lookup.at(
                target.location, evidence["grantTime"], event=evidence["grantEvent"]
            )
            if span is None or span.id != ident:
                continue
            record = records[ident] = Record(span, "rma_lock_wait", span.start)
        if not record.inferred_intervals:
            record.inferred_intervals = (
                [(record.span.start, record.inferred_end)]
                if record.inferred_end > record.span.start
                else []
            )
        record.inferred_intervals.extend(
            (cause.start, cause.end) for cause in matched["causes"]
        )
        record.causes.extend(matched["causes"])
        record.evidence.update(matched["evidence"])
        record.inferred_end = max(record.inferred_end, matched["deadline"])
        record.peer = matched["peer"]
        record.confidence = "recorded-rma-lock-availability"
    unfinished = trace.meta.get("warnings", {}).get(
        "Unfinished collective operations", 0
    )
    if unfinished:
        diagnostics["unfinished_collective_begin"] += unfinished
    if lookup.order.ambiguous:
        diagnostics["ambiguous_same_tick_invocation"] += lookup.order.ambiguous
    all_records = list(records.values()) + collective_records
    return dict(
        records=all_records,
        requests=requests,
        collectives=collectives,
        matchedProbes=matched_probes,
        rmaLockAttempts=rma_locks["attempts"],
        messages=rma_locks["messages"],
        partial=rma_locks["partial"] or continuity.partial,
        diagnostics=diagnostics,
        selectionLock=threading.Lock(),
        selection=None,
        weight=len(rma_locks["attempts"])
        + sum(len(a["causes"]) for a in rma_locks["attempts"])
        + len(all_records)
        + len(requests)
        + len(matched_probes)
        + sum(len(c["participants"]) for c in collectives)
        + shared_cause_weight
        + sum(
            (
                r.causes.storage_weight
                if isinstance(r.causes, CauseCollection)
                else len(r.causes)
            )
            for r in all_records
        ),
    )


def _analysis(trace):
    stat = pathlib.Path(trace.path).stat()
    key = (trace.path, stat.st_size, stat.st_mtime_ns)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        # Serialize cache misses to avoid building duplicate large histories
        # when two browser requests arrive during the first analysis.
        result = _analyze(trace)
        # Keep the newest analysis even beyond the budget: paging through one
        # large trace must not redo it. Older entries go first.
        _CACHE[key] = result
        while len(_CACHE) > 1 and (
            len(_CACHE) > 2 or sum(v["weight"] for v in _CACHE.values()) > _CACHE_BUDGET
        ):
            _CACHE.popitem(last=False)
        return result
