"""Recorded OTF2 RMA lock availability, separate from CPU blocked time.

RequestLock is the earliest possible grant, including nonblocking requests.
Only complete incompatible ownership and request/grant pairs establish a
required release prerequisite. This is an OTF2 contract, not a recovered
blocked-time formula.
"""

from __future__ import annotations

import collections
import dataclasses
import json

from ..causality.operations import operation
from .rma_lock_intervals import _union
from .rma_lock_model import build_rma_lock_model
from .rma_lock_replay import LOCK_EVENTS

RMA_LOCK_EVENTS = LOCK_EVENTS + (
    "RmaWinCreate",
    "RmaWinDestroy",
    "RmaCollectiveBegin",
    "RmaCollectiveEnd",
)


def rma_lock_analysis(trace, events=None, *, cap=150000, complete=True):
    if events is None:
        counts = trace.meta.get("eventTypes", {})
        if counts and not any(counts.get(kind, 0) for kind in LOCK_EVENTS):
            return build_rma_lock_model(trace.defs, (), complete=complete)
        marks = ",".join("?" for _ in RMA_LOCK_EVENTS)
        events = trace.rows(
            f"SELECT id,location,time,kind,data FROM events WHERE kind IN ({marks}) ORDER BY id LIMIT ?",
            [*RMA_LOCK_EVENTS, cap + 1],
        )
        complete = complete and len(events) <= cap
        events = events[:cap]
        for row in events:
            row["data"] = json.loads(row["data"])
    budget = max(1000, cap * 16)

    def charge():
        nonlocal budget
        budget -= 1
        if budget < 0:
            raise OverflowError("RMA lock analysis work limit")

    try:
        return build_rma_lock_model(
            trace.defs, events, complete=complete, charge=charge
        )
    except OverflowError:
        return dict(
            attempts=[],
            ownership=[],
            tests=[],
            diagnostics=collections.Counter({"rma-lock-work-limit": 1}),
            messages={
                "rma-lock-work-limit": "RMA lock analysis exceeded its work bound; required attribution is suppressed."
            },
            partial=True,
        )


def rma_lock_causes(trace, resolve_event, analysis=None):
    """Attach complete request/grant pairs to the same proven invocation.

    ``resolve_event`` must use original boundary order at equal timestamps.
    Deferred grants remain available in ``attempts`` without being relabelled
    as a thread's blocked routine.
    """
    model = analysis if analysis is not None else rma_lock_analysis(trace)
    result = dict(
        model,
        by_span={},
        diagnostics=model["diagnostics"].copy(),
        messages=dict(model["messages"]),
    )
    releases = {
        owner["release"]["id"]: owner["release"]
        for owner in model["ownership"]
        if owner["release"] is not None
    }
    for attempt in model["attempts"]:
        if attempt["status"] != "complete" or not attempt["causes"]:
            continue
        request, grant = attempt["request"], attempt["grant"]
        first, last = resolve_event(request), resolve_event(grant)
        if (
            first is None
            or last is None
            or first.id != last.id
            or first.location != last.location
            or first.incomplete
            or first.sampled
            or str(request["location"]) != str(grant["location"])
        ):
            result["diagnostics"]["rma-lock-grant-outside-request-routine"] += 1
            result["messages"][
                "rma-lock-grant-outside-request-routine"
            ] = "A recorded RMA lock request and grant do not share one complete enclosing routine; event-level request latency remains available."
            continue
        row = result["by_span"].setdefault(
            first.id,
            dict(
                causes=[],
                evidence=dict(rmaLockAttempts=[], blockedTime=None),
                deadline=first.start,
                peer=None,
            ),
        )
        row["evidence"]["rmaLockAttempts"].append(
            dict(
                requestEvent=request["id"],
                grantEvent=grant["id"],
                window=attempt["window"],
                lock=attempt["lock"],
                remoteRank=attempt["remoteRank"],
                requestTime=request["time"],
                grantTime=grant["time"],
                unavailableSeconds=attempt["unavailableSeconds"],
            )
        )
        for cause in attempt["causes"]:
            target = operation(first, event=grant["id"])
            target.update(requestEvent=request["id"], grantTime=grant["time"])
            source = cause.source
            release = releases.get(source.event)
            source_span = resolve_event(release) if release else None
            if (
                source_span is not None
                and not source_span.incomplete
                and not source_span.sampled
            ):
                source = operation(source_span, event=cause.source.event)
                source.update(
                    **(cause.source.extra or {}),
                    ownershipStart=cause.source.start,
                    ownershipEnd=cause.source.end,
                )
            mapped = dataclasses.replace(
                cause,
                id=cause.id + ":span:" + str(first.id),
                source=source,
                target=target,
                start=max(cause.start, first.start),
                extra=dict(cause.extra or {}),
            )
            row["causes"].append(mapped)
            if mapped.ready >= row["deadline"]:
                row.update(deadline=mapped.ready, peer=mapped.source.location)
        row["evidence"]["rmaLockUnavailableSeconds"] = _union(
            (cause.start, cause.end) for cause in row["causes"]
        )
    return result
