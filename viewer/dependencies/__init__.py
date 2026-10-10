"""Evidence-based synchronization and accelerator analysis of existing indexes.

Uses OTF2's recorded identifiers and local nesting. It never deduces a kernel
launch or task data dependency solely from timestamp proximity. All queries are
bounded, read-only, and preserve the events/spans that support each relation.
"""

from ..gpu.invocations import GpuSubmissionOrder
from ..gpu.links import stream_order, stream_dependencies
from ..gpu.event_links import event_dependencies
from ..gpu.default_streams import cuda_default_stream_dependencies
from ..gpu.records import (
    collect_gpu_fields,
    stream_definitions as gpu_stream_definitions,
)
from ..mpi.rma_lock_graph import analyze_rma_locks
from ..mpi.rma_lock_waits import RMA_LOCK_EVENTS
from ..tasks.dependencies import analyze_tasks
from ..tasks.barrier import append_task_join_dependencies
from ..tasks.identity import process_scope
from ..threads.lock_waits import LOCK_KINDS
from .activity import GpuActivity
from .associations import GpuAssociations
from .cache import _cached
from .common import _members, _owner, _string
from .events import _events
from .result import _Result
from .summary import finish_gpu
from .thread_graph import analyze_threads

DEPENDENCY_KINDS = (
    tuple(
        """OmpFork OmpJoin OmpAcquireLock OmpReleaseLock OmpTaskCreate OmpTaskSwitch OmpTaskComplete ThreadFork ThreadJoin ThreadTeamBegin ThreadTeamEnd ThreadAcquireLock ThreadReleaseLock ThreadTaskCreate ThreadTaskSwitch ThreadTaskComplete ThreadCreate ThreadBegin ThreadWait ThreadEnd""".split()
    )
    + RMA_LOCK_EVENTS
)


@_cached
def dependencies(trace, q):
    """Lock handoffs, thread lifecycles, team nesting, and task scheduling graph."""
    out = _Result(trace, q)
    events = _events(out, DEPENDENCY_KINDS)
    analyze_threads(out, events)
    analyze_tasks(out, events, lambda location: process_scope(trace.defs, location))
    append_task_join_dependencies(out)
    analyze_rma_locks(out, events, _members)
    if not events and not any(
        item["kind"] in ("task-wait", "task-group") for item in out.intervals
    ):
        out.warn(
            "no-synchronization-events",
            "This trace contains no supported recorded thread, lock, or task events.",
        )
    if any(e["kind"] in LOCK_KINDS for e in events):
        out.warn(
            "lock-wait-unavailable",
            "Acquire/release records delimit ownership. Instrumented acquisition routines can establish owner-availability intervals, but handoff gaps are not measured lock wait time.",
        )
    visible = [
        i for i in out.intervals if out.visible(i["start"], i["end"], [i["location"]])
    ]
    visible_tasks = {
        i["data"].get("taskInstance", tuple(i["data"]["task"]))
        for i in visible
        if "task" in i["data"]
    }
    visible_locks = {
        (i["data"]["process"], i["data"]["model"], i["data"]["lock"])
        for i in visible
        if i["kind"] == "lock"
    }
    visible_rma_locks = {
        (i["data"]["window"], i["data"]["remoteRank"], i["data"]["lock"])
        for i in visible
        if i["kind"].startswith("rma-lock")
    }
    execution_seconds = sum(
        max(0, min(i["end"], out.end) - max(i["start"], out.start))
        for i in visible
        if i["kind"] == "task-execution"
        and i["confidence"] == "recorded"
        and i["status"] == "complete"
    )
    return out.finish(
        dict(
            locks=len(visible_locks) + len(visible_rma_locks),
            threadLocks=len(visible_locks),
            rmaLocks=len(visible_rma_locks),
            tasks=len(visible_tasks),
            taskExecutionSeconds=execution_seconds,
            waitTimeAvailable=False,
        )
    )


@_cached
def gpu(trace, q):
    """GPU stream activity, RMA memory traffic, and identifier-backed correlation."""
    out = _Result(trace, q)
    activity = GpuActivity(out)
    fields = collect_gpu_fields(
        trace,
        activity.containing,
        activity.streams,
        _owner,
        _string,
        cap=out.cap,
        warn=out.warn,
    )
    out.scanned += fields.scanned
    out.scan_truncated |= fields.truncated
    associations = GpuAssociations(out, activity.streams, fields, q)
    submission_order = GpuSubmissionOrder(trace, activity.invocation_lookup, out.warn)
    if not fields.truncated:
        event_dependencies(
            out,
            fields.event_handles,
            before=submission_order.before,
            producer_records=fields.event_records,
        )
    stream_definitions, stream_properties = gpu_stream_definitions(
        trace, activity.streams, out.intervals, _owner, _string
    )
    stream_dependencies(
        out,
        {item["id"]: item for item in out.intervals},
        activity.streams,
        stream_definitions,
        before=submission_order.before,
        properties=stream_properties,
    )
    from ..gpu.context_events import context_event_dependencies

    context_frontiers = context_event_dependencies(
        trace,
        fields,
        {item["id"]: item for item in out.intervals},
        activity.streams,
        stream_properties,
        out,
        submission_order,
    )
    if not fields.truncated:
        cuda_default_stream_dependencies(
            out,
            {item["id"]: item for item in out.intervals},
            stream_properties,
            before=submission_order.before,
            frontiers=context_frontiers,
        )
    stream_order(out, activity.activity)
    return finish_gpu(out, activity, fields, associations)
