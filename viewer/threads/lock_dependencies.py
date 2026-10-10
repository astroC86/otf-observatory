"""Graph presentation of validated thread-lock ownership and wait causes."""

from .lock_waits import collect_locks, ownership_pairs
from ..causality.operations import clipped, totals
from ..trace.definitions import enum


def analyze_thread_locks(out, events):
    # Use the same cached analysis as the cause inspector, keeping graph cause
    # IDs and timing identical to Wait analysis.
    from .synchronization import _analysis, _MESSAGES
    from collections import Counter

    diagnostics = Counter()
    locks = collect_locks(
        out.trace, events, diagnostics, complete=not out.scan_truncated
    )
    for key, orders in locks.items():
        previous = None
        for pair in ownership_pairs(orders, diagnostics):
            acquire, release = pair["acquire"], pair["release"]
            data = dict(
                process=key[0],
                model=enum("OTF2_PARADIGM_", int(key[1])),
                lock=key[2],
                acquisitionOrder=pair["order"],
                releaseEvent=release["id"] if release else None,
                recordedAcquireEvents=[e["id"] for e in pair["acquisitions"]],
                recordedReleaseEvents=[e["id"] for e in pair["releases"]],
            )
            if pair["valid"]:
                if pair["nestedOwnership"] is not None:
                    data["nestedOwnership"] = pair["nestedOwnership"]
                out.interval(acquire, release, "lock", "Lock " + key[2], data)
                out.edge(
                    acquire,
                    release,
                    "lock-ownership",
                    "Lock acquired → released",
                    data=data,
                )
                for nested_acquire, nested_release, depth in pair["nestedPairs"]:
                    if depth > 1:
                        out.edge(
                            nested_acquire,
                            nested_release,
                            "lock-recursion",
                            "Recursive acquisition → nesting level released",
                            data=dict(
                                process=key[0],
                                lock=key[2],
                                acquisitionOrder=pair["order"],
                                recursionDepth=depth,
                                outerReleaseEvent=release["id"],
                                freesLock=False,
                                causal=False,
                                measuredWait=False,
                            ),
                        )
            elif not pair["ambiguous"] and acquire and release is None:
                out.interval(
                    acquire,
                    None,
                    "lock",
                    "Lock " + key[2],
                    data,
                    status="missing release",
                )
                out.warn("open-lock", "Lock ownership is missing its release endpoint.")
            else:
                # Keep every conflicting acquire visible as an observation,
                # without counting a duration between incompatible endpoints.
                for candidate in pair["acquisitions"]:
                    out.interval(
                        candidate,
                        candidate,
                        "lock",
                        "Lock " + key[2],
                        data,
                        confidence="unresolved-ownership",
                        status=pair["status"],
                    )
                if not pair["ambiguous"] and acquire is None:
                    out.warn(
                        "open-lock", "Lock ownership is missing its acquire endpoint."
                    )
            if previous and previous["valid"] and acquire and not pair["ambiguous"]:
                out.edge(
                    previous["release"],
                    acquire,
                    "lock-handoff",
                    "Recorded release → later acquisition ordinal",
                    data=dict(
                        data,
                        causal=False,
                        measuredWait=False,
                        previousAcquisitionOrder=previous["order"],
                        consecutive=pair["order"] == previous["order"] + 1,
                    ),
                )
            previous = pair
    for code, count in diagnostics.items():
        out.warn(code, _MESSAGES.get(code, code.replace("_", " ")), count)
    if not locks:
        return
    if out.scan_truncated:
        out.warn(
            "thread-lock-context-partial",
            "The graph has incomplete lock context; routine attribution is suppressed.",
        )
        return
    model = _analysis(out.trace)
    for code, count in model["diagnostics"].items():
        if code.startswith("lock_") and count and code not in diagnostics:
            out.warn(code, _MESSAGES.get(code, code.replace("_", " ")), count)
    if any(
        model["diagnostics"][code]
        for code in (
            "context_limit",
            "routine_limit",
            "lock_attribution_limit",
            "lock_context_incomplete",
        )
    ):
        out.scan_truncated = True
        out.warn(
            "thread-lock-context-partial",
            "Synchronization context was incomplete; no partial owner set is presented as complete.",
        )
    by_id = {event["id"]: event for event in events}
    selected = []
    for record in model["records"]:
        event_id = record.evidence.get("acquireEvent")
        if event_id not in by_id or record.span.sampled:
            continue
        acquire = by_id[event_id]
        end = record.upper_end
        causes = [cause for cause in record.causes if cause.type == "lock_handoff"]
        fields = dict(
            record.evidence,
            routine=record.span.name,
            span=record.span.id,
            routineStart=record.span.start,
            routineEnd=record.span.end,
            blockedTime=None,
            causes=clipped(causes, out.start, out.end),
        )
        item = dict(
            id=f"thread-lock-acquisition:{record.span.id}",
            kind="thread-lock-acquisition",
            label=record.span.name,
            location=record.span.location,
            start=record.start,
            end=end,
            confidence=record.confidence,
            status=(
                "incomplete routine"
                if record.span.incomplete
                else "recorded acquisition"
            ),
            evidence=[event_id],
            data=fields,
        )
        out.intervals.append(item)
        if out.visible(record.start, end, [record.span.location]):
            selected.append((causes, out.start, out.end))
        for cause, detail in zip(causes, clipped(causes, out.start, out.end)):
            release = by_id.get(cause.source.event)
            if release is None:
                continue
            out.edge(
                release,
                acquire,
                "thread-lock-contention",
                ("Required" if cause.required else "Conditional")
                + " owner release → acquisition",
                confidence=cause.confidence,
                data=detail,
            )
            edge = out.edges[-1]
            edge["waitCause"] = dict(detail, analysis="synchronization")
            # Cause intervals can overlap the selected window before either
            # endpoint. Retain those endpoints as inspectable graph context.
            edge["context"] = out.visible(
                cause.start, cause.end, [cause.source.location, cause.target.location]
            )
    out.extra["threadLockAnalysis"] = dict(
        totals(selected, selected=True),
        interpretation="Owner availability intervals, unioned per waiting thread. Exact CPU blocked time remains unknown.",
    )
