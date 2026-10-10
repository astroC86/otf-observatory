"""Selected-marker translation in shared seconds; never modifies recorded clocks.

The reference callback 0x8310c0 chooses max(0, min(selected positions)) and applies
oldOffset - (selectedPosition - target / conversionFactor). Here every trace
is already normalized to seconds, so the conversion factor is one.
"""

import math


def _number(value, label):
    if isinstance(value, bool) or value is None:
        raise ValueError(label + " must be finite")
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(label + " must be finite")
    if not math.isfinite(value):
        raise ValueError(label + " must be finite")
    return value


def _runs(entries, get_trace, baseline):
    if not isinstance(entries, list) or not 2 <= len(entries) <= 16:
        raise ValueError("Select between 2 and 16 runs")
    result = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError("Every run needs a trace ID")
        ident = entry["id"]
        if ident in seen:
            raise ValueError("Trace IDs must be distinct")
        seen.add(ident)
        trace = get_trace(ident)
        result.append((entry, trace, _number(entry.get("offset", 0), "Time offset")))
    if baseline not in seen:
        raise ValueError("Selected runs must include the baseline")
    return result


def marker_options(trace, q):
    limit = max(1, min(1000, int(q.get("limit", 200))))
    search = str(q.get("search", "")).casefold()
    where = "instr(lower(name),?)>0" if search else "1"
    args = [search] if search else []
    rows = trace.rows(
        "SELECT id,time,name,category,location FROM markers WHERE "
        + where
        + " ORDER BY time,id LIMIT ?",
        args + [limit],
    )
    total = trace.rows("SELECT count(*) n FROM markers WHERE " + where, args)[0]["n"]
    return dict(
        markers=rows,
        total=total,
        truncated=total > len(rows),
        duration=trace.meta["duration"],
    )


def align_markers(entries, get_trace, baseline):
    runs = []
    for entry, trace, offset in _runs(entries, get_trace, baseline):
        marker = None
        label = "Selected time"
        if "marker" in entry:
            if isinstance(entry["marker"], bool):
                raise ValueError("Invalid marker ID")
            rows = trace.rows(
                "SELECT id,time,name FROM markers WHERE id=?", (str(entry["marker"]),)
            )
            if not rows:
                raise ValueError(
                    "Selected marker was not found in " + trace.meta["name"]
                )
            marker = rows[0]["id"]
            time = rows[0]["time"]
            label = rows[0]["name"]
        else:
            time = entry.get("time")
        time = _number(time, "Recorded marker time")
        duration = _number(trace.meta["duration"], "Trace duration")
        if not 0 <= time <= duration:
            raise ValueError(
                "Recorded marker time must lie within " + trace.meta["name"]
            )
        position = _number(time + offset, "Displayed marker time")
        runs.append(
            dict(
                id=entry["id"],
                name=trace.meta["name"],
                time=time,
                marker=marker,
                label=label,
                previousOffset=offset,
                previousPosition=position,
                duration=duration,
            )
        )
    target = max(0.0, min(run["previousPosition"] for run in runs))
    for run in runs:
        # Preserve the recovered subtraction order rather than cancelling
        # terms symbolically; repeated alignment does not accumulate a shift.
        run["offset"] = _number(
            run["previousOffset"] - (run["previousPosition"] - target), "Aligned offset"
        )
        run["position"] = _number(run["time"] + run["offset"], "Aligned marker time")
        run["range"] = dict(
            start=run["offset"],
            end=_number(run["duration"] + run["offset"], "Aligned trace end"),
        )
    return dict(
        method="selected-marker-translation",
        baseline=baseline,
        target=target,
        runs=runs,
        range=dict(
            start=min(r["range"]["start"] for r in runs),
            end=max(r["range"]["end"] for r in runs),
        ),
        semantics="All selected traces move in shared seconds. Recorded times and physical durations remain unchanged.",
    )


def compare_offsets(entries, get_trace, baseline, q):
    """Map a shared window independently into each run, including the baseline.

    Do not clip against the baseline first: other traces may have recorded
    activity in display intervals where the baseline has none.
    """
    selected = _runs(entries, get_trace, baseline)
    selected_location = q.get("profileSelectedLocation", False)
    if not isinstance(selected_location, bool):
        raise ValueError("profileSelectedLocation must be a boolean")
    default_start = min(offset for _, _, offset in selected)
    default_end = max(offset + trace.meta["duration"] for _, trace, offset in selected)
    start = _number(q.get("displayStart", default_start), "Display start")
    end = _number(q.get("displayEnd", default_end), "Display end")
    if end <= start:
        raise ValueError("Display end must follow display start")
    rows = {}
    runs = []
    for entry, trace, offset in selected:
        raw_start = _number(start - offset, "Recorded window start")
        raw_end = _number(end - offset, "Recorded window end")
        a = max(0.0, min(trace.meta["duration"], raw_start))
        b = max(0.0, min(trace.meta["duration"], raw_end))
        filters = {k: q[k] for k in ("region", "exclude", "group") if k in q}
        window = dict(filters, start=a, end=b)
        locations = trace.meta["locations"]
        location = entry.get("location")
        if location is None:
            location = next(
                (loc["id"] for loc in locations if loc.get("type") == "CPU_THREAD"),
                locations[0]["id"] if locations else None,
            )
        if location is not None and str(location) not in trace.locations:
            raise ValueError("Timeline location not found in " + trace.meta["name"])
        location = str(location) if location is not None else None
        if selected_location:
            window["locations"] = location or "__none__"
        profile = trace.summary(window)
        names = {}
        for item in profile:
            total = names.setdefault(item["name"], dict(time=0, calls=0))
            total["time"] += item["exclusive"]
            total["calls"] += item["calls"]
        for name, value in names.items():
            rows.setdefault(name, dict(name=name, values={}))["values"][entry["id"]] = (
                value
            )
        timeline = trace.timeline(
            dict(
                window,
                locations=location or "__none__",
                bins=max(32, min(1000, int(q.get("bins", 600)))),
            )
        )
        for item in timeline["rows"]:
            definition = trace.regions.get(item["region"], {})
            item.update(
                name=definition.get("name", item["region"]),
                group=definition.get("group", "Unknown"),
                displayStart=max(start, item["start"] + offset),
                displayEnd=min(end, item["end"] + offset),
            )
        groups = {g["id"]: g["name"] for g in trace.meta.get("groups", [])}
        choices = [
            dict(
                id=loc["id"],
                name=" · ".join(
                    v for v in (groups.get(loc.get("group")), loc["name"]) if v
                ),
            )
            for loc in locations
        ]
        runs.append(
            dict(
                id=entry["id"],
                name=trace.meta["name"],
                offset=offset,
                range=dict(start=a, end=b),
                requestedRange=dict(start=raw_start, end=raw_end),
                location=location,
                locations=choices,
                timeline=timeline,
                fullRange=dict(start=offset, end=offset + trace.meta["duration"]),
            )
        )
    for row in rows.values():
        for entry, _, _ in selected:
            row["values"].setdefault(entry["id"], dict(time=0, calls=0))
        base = row["values"][baseline]["time"]
        for value in row["values"].values():
            value.update(
                delta=value["time"] - base, ratio=value["time"] / base if base else None
            )
    return dict(
        baseline=baseline,
        range=dict(start=start, end=end),
        runs=runs,
        rows=sorted(
            rows.values(),
            key=lambda row: (
                -max(abs(v["delta"]) for v in row["values"].values()),
                row["name"],
            ),
        ),
        durationSemantics="Physical seconds within each independently mapped window. Timeline lanes show selected locations; profiles cover "
        + ("those locations." if selected_location else "all locations."),
    )
