"""Score-P 10 OMPT recursive lock ordinals, from its recorded API contract."""

from ..trace.event_spans import EventSpans
from ..tasks.contracts import scorep_ompt_recording


def annotate_nested_locks(trace, locks, diagnostics):
    if not scorep_ompt_recording(trace):
        return
    strings = trace.defs.get("String", {})
    text = lambda ref: strings.get(str(ref), {}).get("string", "")
    regions = {}
    for ref, row in trace.defs.get("Region", {}).items():
        name = text(row.get("name"))
        if name not in (
            "omp_set_nest_lock",
            "omp_test_nest_lock",
            "omp_unset_nest_lock",
        ):
            continue
        if (
            any(
                type(row.get(field)) is not int or row[field] != value
                for field, value in (
                    ("paradigm", 3),
                    ("regionRole", 2),
                    ("beginLineNumber", 0),
                    ("endLineNumber", 0),
                )
            )
            or text(row.get("sourceFile")) != "OMP"
            or text(row.get("canonicalName")) != name
        ):
            continue
        regions[str(ref)] = "release" if name == "omp_unset_nest_lock" else "acquire"
    lookup = EventSpans(trace, diagnostics, "lock_nested")
    for (_, model, _), orders in locks.items():
        if model != "3":
            continue
        for events in orders.values():
            if len(events["acquire"]) <= 1 and len(events["release"]) <= 1:
                continue
            for action in ("acquire", "release"):
                for index, event in enumerate(events[action]):
                    if event["kind"] != (
                        "ThreadAcquireLock"
                        if action == "acquire"
                        else "ThreadReleaseLock"
                    ):
                        continue
                    span = lookup.at(event)
                    if span is not None and regions.get(span.region) == action:
                        events[action][index] = dict(
                            event,
                            _nestedLock=dict(
                                span=span.id,
                                region=span.region,
                                routine=span.name,
                                action=action,
                            ),
                        )


def nested_ownership(acquisitions, releases):
    """Collapse only one balanced, source-qualified ordinal into ownership.

    The producer keeps the same ordinal until the outermost release. An
    intermediate release lowers recursion depth but does not free the lock.
    Missing boundaries or two separate ownership cycles cannot be repaired.
    """
    events = sorted(acquisitions + releases, key=lambda event: event["id"])
    if len(acquisitions) < 2 or len(acquisitions) != len(releases):
        return None
    if (
        any("_nestedLock" not in event for event in events)
        or len({event["id"] for event in events}) != len(events)
        or len({event["location"] for event in events}) != 1
        or len({event["_nestedLock"]["span"] for event in events}) != len(events)
        or any(a["time"] > b["time"] for a, b in zip(events, events[1:]))
    ):
        return None
    stack = []
    pairs = []
    transitions = []
    maximum = 0
    for index, event in enumerate(events):
        if event["_nestedLock"]["action"] == "acquire":
            stack.append(event)
            maximum = max(maximum, len(stack))
        else:
            if not stack:
                return None
            pairs.append((stack.pop(), event, len(stack) + 1))
            if not stack and index != len(events) - 1:
                return None
        transitions.append(
            dict(
                event=event["id"],
                time=event["time"],
                depth=len(stack),
                **event["_nestedLock"]
            )
        )
    if stack:
        return None
    preview = (
        transitions if len(transitions) <= 128 else transitions[:64] + transitions[-64:]
    )
    evidence = dict(
        producer="Score-P 10.0",
        adapter="OMPT",
        maxDepth=maximum,
        acquisitionCount=len(acquisitions),
        releaseCount=len(releases),
        transitions=preview,
        transitionsTruncated=len(transitions) > len(preview),
        interpretation="One acquisition ordinal covers recursive ownership until the outermost release; intermediate releases do not make the lock available.",
    )
    return events[0], events[-1], pairs, evidence
