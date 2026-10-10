"""Reconstruct function signals from indexed spans when native records cannot supply them."""

import collections
import json

from .attributes import attribute_choices, attribute_reducer
from .series import Data, Series
from .stack_sources import count_endpoint, raw_stack_source
from .sweeps import attribute_sweep, impulses, sweep
from .values import MISSING_ATTRIBUTE, attribute_choice, source_number


def event_region(trace, raw):
    region = raw.get("region")
    if region is None and raw.get("callingContext") is not None:
        region = (
            trace.defs.get("CallingContext", {})
            .get(str(raw["callingContext"]), {})
            .get("region")
        )
    return region


def stack_function_source(ctx, kind, spec, native=True):
    q, locs = ctx.scoped(spec)
    unit = "s" if kind == "function_duration" else ""
    allowed = ctx.selected_regions(q, spec)
    is_attribute = kind in ("function_attribute", "function_attribute_active")
    if (
        native
        and kind not in ("function_count", "function_hits")
        and not (
            is_attribute
            and spec.get("attribute", "duration") in ("duration", "exclusive", "depth")
        )
    ):
        return raw_stack_source(ctx, kind, spec, locs, allowed)
    source_end = float(ctx.trace.meta["duration"])
    q = dict(q, start=0.0, end=source_end)
    if kind in ("function_count", "function_hits"):
        if (
            native
            and kind == "function_count"
            and spec.get("impulses") not in (True, 1, "1", "true")
        ):
            endpoint = count_endpoint(spec)
            accepted = (
                {"Enter", "Leave"}
                if endpoint == "both"
                else {"Enter"} if endpoint == "enter" else {"Leave"}
            )
            signals = {}
            for loc in locs:
                records, issues = ctx.functions.records.stack(loc)
                if issues:
                    ctx.source_diagnostics.append(
                        dict(
                            source=(ctx.source_names[-1] if ctx.source_names else kind),
                            location=loc,
                            kind=kind,
                            skipped={},
                            uncertain=issues,
                        )
                    )
                    signals.update(
                        stack_function_source(
                            ctx, kind, dict(spec, locations=[loc]), False
                        ).series
                    )
                    continue
                points = [(0.0, 0)]
                count = 0
                for record in records:
                    ctx.charge(1)
                    if record["kind"] in accepted and record["region"] in allowed:
                        count += 1
                        points.append((record["time"], count))
                signals[loc] = Series(points, flags=0x11200)
            return Data(signals, "count")
        # StackCallNum filter 1119330 rejects every record in mode 3
        # (factory mode 8, sampling hits). Only the Tree producer has
        # sampled-context records. Explicit impulses are a viewer source.
        if kind == "function_hits" and spec.get("impulses") not in (
            True,
            1,
            "1",
            "true",
        ):
            return Data(
                {loc: Series([(0.0, 0)], flags=0x11200) for loc in locs}, "count"
            )
        events = collections.defaultdict(list)
        if kind == "function_hits":
            sql = "SELECT s.location,s.time,p.region FROM samples s JOIN paths p ON p.id=s.path WHERE s.time>=? AND s.time<=?"
            # Region filters refer to path definitions, not a samples column.
            start, end, locwhere, locargs = ctx.trace.scope(dict(q, locations=""), "p")
            marks = ",".join("?" for _ in locs) or "''"
            sql += (
                " AND s.location IN ("
                + marks
                + ")"
                + locwhere
                + " ORDER BY s.time,s.id"
            )
            for row in ctx.fetch(sql, [start, end] + locs + locargs):
                if row["region"] in allowed:
                    events[row["location"]].append((row["time"], 1))
        else:
            endpoint = count_endpoint(spec)
            kinds = []
            if endpoint in ("enter", "both"):
                kinds += ["Enter", "CallingContextEnter"]
            if endpoint in ("leave", "both"):
                kinds += ["Leave", "CallingContextLeave"]
            marks = ",".join("?" for _ in locs) or "''"
            sql = (
                "SELECT location,time,kind,data FROM events WHERE location IN ("
                + marks
                + ") AND time>=? AND time<=? AND kind IN ("
                + ",".join("?" for _ in kinds)
                + ") ORDER BY time,id"
            )
            unnamed_leaves = {}
            for row in ctx.fetch(sql, locs + [0.0, source_end] + kinds):
                raw = json.loads(row["data"])
                region = event_region(ctx.trace, raw)
                if region is None:
                    # OTF1 Leave without token: resolve the innermost ending call.
                    key = (row["location"], row["time"])
                    if key not in unnamed_leaves:
                        unnamed_leaves[key] = collections.deque(
                            r["region"]
                            for r in ctx.fetch(
                                "SELECT region FROM spans WHERE location=? AND end=? ORDER BY depth DESC",
                                key,
                            )
                        )
                    region = (
                        unnamed_leaves[key].popleft() if unnamed_leaves[key] else None
                    )
                if str(region) in allowed:
                    events[row["location"]].append((row["time"], 1))
        if spec.get("impulses") in (True, 1, "1", "true"):
            return Data(
                {loc: impulses(events[loc], 0.0, source_end) for loc in locs},
                "count",
            )
        # SignalSourceStackCallNum reset=0 and advance increments once for
        # each accepted event. Preserve an event at zero after the reset
        # state, and preserve multiple counted events at the same time.
        return Data(
            {
                loc: Series(
                    [(0.0, 0)]
                    + [(t, index + 1) for index, (t, _) in enumerate(events[loc])],
                    flags=0x11200,
                )
                for loc in locs
            },
            "count",
        )
    inclusive = spec.get("inclusive", False) in (True, 1, "1", "true")
    parameter_ref = (
        ctx.parameter_reference(spec.get("attribute", "duration"))
        if is_attribute
        else None
    )
    attribute_reduction = (
        attribute_reducer(spec)
        if is_attribute
        else spec.get("attributeReduction", "top")
    )
    choices = attribute_choices(kind, spec)
    whole_spans = inclusive or (is_attribute and attribute_reduction != "top")
    table = "spans" if whole_spans else "slices"
    _, _, sql, args = ctx.trace.interval(table, q)
    select = (
        "s.region,s.location,s.start,s.end,s.id span,s.depth,s.exclusive,s.end-s.start duration,"
        + ctx.trace.invocation
        + " invocation"
        if whole_spans
        else "s.region,s.location,s.start,s.end,s.span,p.depth,p.exclusive,p.end-p.start duration,"
        + ctx.trace.invocation.replace("s.", "p.")
        + " invocation"
    )
    if whole_spans:
        query = "SELECT " + select + " FROM " + sql
    else:
        query = (
            "SELECT "
            + select
            + " FROM "
            + sql.replace(" WHERE ", " JOIN spans p ON p.id=s.span WHERE ", 1)
        )
    intervals = collections.defaultdict(list)
    attribute_cache = {}
    leave_attributes = {}
    for row in ctx.fetch(query, args):
        if row["region"] not in allowed:
            continue
        value = 1
        if kind == "function_duration":
            value = row["duration"] if inclusive else row["end"] - row["start"]
        elif is_attribute:
            wanted = spec.get("attribute", "duration")
            value = row.get(wanted)
            if wanted not in row or parameter_ref is not None:
                span = row["invocation"]
                if span not in attribute_cache:
                    records = list(
                        ctx.fetch(
                            "SELECT e.id,e.data,p.region FROM events e JOIN spans p ON p.location=e.location AND p.start=e.time WHERE p.id=? AND e.kind IN ('Enter','CallingContextEnter') ORDER BY e.id",
                            (span,),
                        )
                    )
                    matching = []
                    for record in records:
                        raw = json.loads(record["data"])
                        region = event_region(ctx.trace, raw)
                        if str(region) == record["region"]:
                            matching.append((record["id"], raw))
                    # Equal-time recursive entries have distinct stack
                    # frames; choose the corresponding recorded entry.
                    prior = next(
                        ctx.fetch(
                            "SELECT count(*) n FROM spans p JOIN spans s ON s.location=p.location AND s.start=p.start AND s.region=p.region AND s.id<p.id WHERE p.id=? AND "
                            + ctx.trace.original,
                            (span,),
                        )
                    )["n"]
                    entry_event, raw = (
                        matching[prior] if prior < len(matching) else (None, {})
                    )
                    entry = ctx.attribute(
                        raw, wanted, MISSING_ATTRIBUTE, decode_strings=bool(choices)
                    )
                    if parameter_ref is not None:
                        entry = ctx.parameter_value(
                            ctx.synthesized_parameter_attributes(row["location"]),
                            entry_event,
                            parameter_ref,
                            choices,
                        )
                    elif ctx.task_attribute(wanted):
                        synthetic = ctx.synthesized_task_attributes(
                            row["location"]
                        ).get(entry_event, MISSING_ATTRIBUTE)
                        if synthetic is not MISSING_ATTRIBUTE:
                            entry = synthetic
                    if entry is MISSING_ATTRIBUTE and parameter_ref is None:
                        # Native per-invocation storage appends differing
                        # Leave attributes; lookup returns the first ID.
                        # Therefore Enter wins, including a present NaN,
                        # and only absent IDs fall back to Leave.
                        frame = next(
                            ctx.fetch(
                                "SELECT s.location,s.region,max(s.end) finish FROM spans s WHERE "
                                + ctx.trace.invocation
                                + "=?",
                                (span,),
                            )
                        )
                        key = (frame["location"], frame["finish"])
                        if key not in leave_attributes:
                            pending = list(
                                ctx.fetch(
                                    "SELECT "
                                    + ctx.trace.invocation
                                    + " invocation,s.region,max(s.depth) depth FROM spans s WHERE s.location=? AND s.end=? GROUP BY invocation ORDER BY depth DESC,invocation DESC",
                                    key,
                                )
                            )
                            mapped = {}
                            for record in ctx.fetch(
                                "SELECT data FROM events WHERE location=? AND time=? AND kind IN ('Leave','CallingContextLeave') ORDER BY id",
                                key,
                            ):
                                raw = json.loads(record["data"])
                                region = event_region(ctx.trace, raw)
                                index = next(
                                    (
                                        i
                                        for i, candidate in enumerate(pending)
                                        if region is None
                                        or str(region) == candidate["region"]
                                    ),
                                    None,
                                )
                                if index is not None:
                                    mapped[pending.pop(index)["invocation"]] = raw
                            leave_attributes[key] = mapped
                        raw = leave_attributes[key].get(span, {})
                        entry = ctx.attribute(
                            raw,
                            wanted,
                            MISSING_ATTRIBUTE,
                            decode_strings=bool(choices),
                        )
                    attribute_cache[span] = entry
                value = attribute_cache[span]
            if value is not MISSING_ATTRIBUTE:
                value = (
                    attribute_choice(value, choices)
                    if choices
                    else source_number(value)
                )
        intervals[row["location"]].append(
            (row["start"], row["end"], value, row.get("depth", 0))
        )
    if is_attribute:
        if (
            spec.get("attribute", "duration") in ("duration", "exclusive")
            and not choices
        ):
            unit = "s"
        return Data(
            {
                loc: attribute_sweep(
                    intervals[loc],
                    0.0,
                    source_end,
                    attribute_reduction,
                    bool(choices),
                    ctx.charge,
                )
                for loc in locs
            },
            unit,
        )
    method = (
        "max" if kind == "function_active" else "shallowest" if inclusive else "deepest"
    )
    signals = {loc: sweep(intervals[loc], 0.0, source_end, 0, method) for loc in locs}
    for series in signals.values():
        series.flags = 0x10200
    return Data(signals, unit)
