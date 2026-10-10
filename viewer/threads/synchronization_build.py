"""Build synchronization observations before query filtering and serialization.

Attribution stages mutate the same records in native replay order. Cache
ownership stays in synchronization, shared by the wait and cause views.
"""

import collections
import json

from ..gpu.waits import gpu_waits
from ..tasks.contracts import scorep_ompt_taskgroup_contracts
from ..trace.event_spans import EventSpans
from .barriers import native_barriers
from .barrier_waits import attribute_barriers
from .gpu_identifiers import attribute_gpu_identifiers
from .join_waits import (
    attribute_task_joins,
    attribute_team_joins,
    attribute_thread_joins,
    collect_thread_joins,
)
from .lock_waits import attribute_locks, collect_locks
from .synchronization_model import Lookup, Record, Span, routine_category

_CAP = 600000


def _read_events(trace, kinds, diagnostics):
    marks = ",".join("?" for _ in kinds)
    rows = trace.rows(
        f"SELECT id,location,time,kind,data FROM events WHERE kind IN ({marks}) ORDER BY time,id LIMIT ?",
        [*kinds, _CAP + 1],
    )
    if len(rows) > _CAP:
        diagnostics["context_limit"] += 1
        rows = rows[:_CAP]
    for row in rows:
        row["data"] = json.loads(row["data"])
    return rows


def build(trace):
    taskgroups = scorep_ompt_taskgroup_contracts(trace)
    diagnostics = collections.Counter()
    spans = []
    regions = {
        r["id"]: (r, category)
        for r in trace.meta.get("regions", [])
        if (category := routine_category(r, str(r["id"]) in taskgroups))
    }
    if regions:
        marks = ",".join("?" for _ in regions)
        invocation = getattr(trace, "invocation", "s.id")
        rows = trace.rows(
            f"SELECT s.id,s.location,s.region,s.start,s.end,s.depth,s.incomplete,s.sampled,{invocation} invocation FROM spans s WHERE region IN ({marks}) ORDER BY start,id LIMIT ?",
            [*regions, _CAP + 1],
        )
        if len(rows) > _CAP:
            diagnostics["routine_limit"] += 1
            rows = rows[:_CAP]
        # Task switches split one still-open barrier into execution segments.
        # Its native operation is associated with the original Enter/Leave,
        # not a second observed call for each resumed segment. Retain location
        # scope: migration alone cannot supply another thread's barrier entry.
        barriers = {}
        logical = []
        for row in rows:
            if regions[row["region"]][1] not in ("openmp_barrier", "thread_barrier"):
                logical.append(row)
                continue
            key = (row["invocation"], row["location"], row["region"])
            if key not in barriers:
                barriers[key] = row
                logical.append(row)
            else:
                original = barriers[key]
                original["end"] = max(original["end"], row["end"])
                original["incomplete"] |= row["incomplete"]
                original["sampled"] |= row["sampled"]
        for r in logical:
            definition, category = regions[r["region"]]
            spans.append(
                Span(
                    r["id"],
                    r["location"],
                    r["region"],
                    r["start"],
                    r["end"],
                    r["depth"],
                    r["incomplete"],
                    r["sampled"],
                    definition["name"],
                    category,
                )
            )
    lookup = Lookup(spans, trace)
    records = {
        s.id: Record(
            s,
            s.start,
            s.end,
            s.category,
            s.start,
            upper_end=(
                s.start
                if s.category in ("lock_test", "gpu_dependency_enqueue")
                else s.end
            ),
        )
        for s in spans
        if s.category != "critical_acquire"
    }
    for record in records.values():
        if record.category == "task_group":
            record.confidence = "observed-taskgroup-construct"
            record.evidence.update(
                recordingContract=taskgroups[record.span.region],
                waitEntryUnrecorded=True,
                blockedTime=None,
                interpretation="Whole taskgroup construct, including its useful body. The duration is only a mathematical upper bound; the terminal wait entry and blocked time were not recorded.",
            )
            diagnostics["task_group_wait_entry_unrecorded"] += 1
    native = native_barriers(trace, spans, diagnostics)
    events = _read_events(
        trace,
        (
            "ThreadAcquireLock",
            "ThreadReleaseLock",
            "OmpAcquireLock",
            "OmpReleaseLock",
            "ThreadWait",
            "ThreadBegin",
            "ThreadEnd",
        ),
        diagnostics,
    )
    locks = collect_locks(
        trace, events, diagnostics, complete=not diagnostics["context_limit"]
    )
    waits, ends = collect_thread_joins(events, diagnostics)
    cohorts = attribute_barriers(trace, native, records, spans, diagnostics)
    attribute_team_joins(trace, native, records, spans, diagnostics)
    attribute_task_joins(trace, native, records, diagnostics, cap=_CAP)
    locks_complete = attribute_locks(
        locks,
        lookup,
        records,
        diagnostics,
        complete=not (diagnostics["context_limit"] or diagnostics["routine_limit"]),
        release_lookup=EventSpans(trace, diagnostics, "lock_release"),
    )
    attribute_thread_joins(trace, waits, ends, lookup, records, diagnostics, cap=_CAP)
    # TASK_WAIT and condition-wait routines have no encoded awaited task/set or
    # condition-variable identity in standard OTF2 region events.
    for record in records.values():
        if record.category == "task_wait":
            diagnostics["task_dependency_set_unrecorded"] += 1
        elif record.category == "condition_wait":
            diagnostics["condition_dependency_unrecorded"] += 1
        elif record.category == "gpu_synchronization":
            diagnostics["gpu_sync_dependency_unrecorded"] += 1
        if record.span.sampled or record.span.incomplete:
            record.deadline = record.start
            record.confidence = "incomplete-or-sampled"
        if record.span.sampled:
            diagnostics["sampled_routine_excluded"] += 1
    gpu = gpu_waits(trace, records)
    diagnostics.update(gpu["diagnostics"])
    for ident, matched in gpu["by_span"].items():
        record = records[ident]
        record.causes.extend(matched["causes"])
        record.evidence.update(matched["evidence"])
        record.deadline = matched["deadline"]
        record.peer = matched["peer"]
        record.confidence = matched["confidence"]
    diagnostics["gpu_sync_dependency_unrecorded"] -= len(gpu["by_span"])
    if not gpu["partial"]:
        attribute_gpu_identifiers(trace, records, diagnostics, gpu["fields"], cap=_CAP)
    if lookup.order.ambiguous:
        diagnostics["ambiguous_same_tick_synchronization"] += lookup.order.ambiguous
    return dict(
        records=list(records.values()),
        cohorts=cohorts,
        diagnostics=diagnostics,
        messages=gpu["messages"],
        partial=bool(
            gpu["partial"]
            or not locks_complete
            or diagnostics["context_limit"]
            or diagnostics["routine_limit"]
            or diagnostics["thread_lifecycle_context_limit"]
        ),
    )
