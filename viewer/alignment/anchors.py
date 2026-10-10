"""Select semantic anchors and enrich them with recorded call context."""

from __future__ import annotations

import bisect
import collections
import json
import math
import re


def _symbol(name):
    name = re.sub(r"\s+", " ", str(name)).strip()
    if re.match(r"(?i)^p?mpi_", name):
        name = re.sub(r"(?i)^p?mpi_", "MPI_", name).rstrip("_").upper()
    return name


_RUNTIME_NAMES = {
    "malloc",
    "calloc",
    "realloc",
    "free",
    "operator new",
    "operator delete",
    "read",
    "write",
    "pread",
    "pwrite",
    "open",
    "open64",
    "close",
    "lseek",
    "lseek64",
    "fread",
    "fwrite",
    "fopen",
    "fclose",
    "memcpy",
    "memset",
    "sync",
    "dup",
    "dup2",
}


def _symbol_statistics(trace, location, start, end):
    if location is None:
        return {}
    result = {}
    original = getattr(trace, "original", "1")
    sql = f"""SELECT s.region,COUNT(*) count,MIN(s.depth) depth,MIN(s.start) first,MAX(s.start) last
            FROM spans s WHERE s.location=? AND s.start>=? AND s.start<=?
            AND s.sampled=0 AND s.incomplete=0 AND {original} GROUP BY s.region"""
    for row in trace.rows(sql, (location, start, end)):
        definition = trace.regions[row["region"]]
        key = _symbol(definition["name"])
        item = result.setdefault(
            key, dict(count=0, depth=row["depth"], first=row["first"], last=row["last"])
        )
        item["count"] += row["count"]
        item["depth"] = min(item["depth"], row["depth"])
        item["first"] = min(item["first"], row["first"])
        item["last"] = max(item["last"], row["last"])
    return result


def _phase_symbols(a, b, duration_a, duration_b):
    meaningful = {
        key
        for key in a.keys() & b.keys()
        if key.casefold() not in _RUNTIME_NAMES and not key.startswith("MPI_")
    }
    if not meaningful:
        return None
    shallow = min(max(a[k]["depth"], b[k]["depth"]) for k in meaningful) + 3
    candidates = {
        k
        for k in meaningful
        if max(a[k]["depth"], b[k]["depth"]) <= shallow
        and max(a[k]["count"], b[k]["count"]) <= 64
        and max(a[k]["count"], b[k]["count"]) / min(a[k]["count"], b[k]["count"])
        <= 1.25
    }
    if len(candidates) < 4:
        return None
    coverage_a = (
        max(a[k]["last"] for k in candidates) - min(a[k]["first"] for k in candidates)
    ) / max(duration_a, 1e-12)
    coverage_b = (
        max(b[k]["last"] for k in candidates) - min(b[k]["first"] for k in candidates)
    ) / max(duration_b, 1e-12)
    return candidates if min(coverage_a, coverage_b) >= 0.5 else None


def _anchors(trace, location, start, end, common, anchor, maximum):
    markers = []
    functions = []
    diagnostics = []
    if start == end:
        return [], dict(total=0, retained=0, subsampled=False), diagnostics
    if location is not None and common:
        regions = [
            r["id"]
            for r in trace.meta["regions"]
            if _symbol(r["name"]) in common
            and (not anchor or anchor in r["name"].casefold())
        ]
        if regions:
            marks = ",".join("?" for _ in regions)
            original = getattr(trace, "original", "1")
            sql = f"""SELECT s.id,s.region,s.start,s.end,s.depth,s.path FROM spans s WHERE s.location=?
                    AND s.start>=? AND s.start<=? AND s.sampled=0 AND s.incomplete=0 AND {original}
                    AND s.region IN ({marks}) ORDER BY s.start,s.id"""
            with trace.connect() as db:
                for row in db.execute(sql, [location, start, end] + regions):
                    r = trace.regions[row["region"]]
                    name = _symbol(r["name"])
                    functions.append(
                        dict(
                            key="function:" + name,
                            label=r["name"],
                            kind="function",
                            time=row["start"],
                            end=row["end"],
                            span=row["id"],
                            location=location,
                            depth=row["depth"],
                            region=row["region"],
                            path=row["path"],
                        )
                    )
    for row in trace.rows(
        "SELECT id,time,name,category,location FROM markers WHERE time>=? AND time<=? ORDER BY time,id",
        (start, end),
    ):
        if row["location"] not in (None, "", location, "18446744073709551615"):
            continue
        if anchor and anchor not in row["name"].casefold():
            continue
        name = _symbol(row["name"])
        key = "marker:" + str(row["category"]) + ":" + name
        markers.append(
            dict(
                key=key,
                label=row["name"],
                kind="marker",
                time=row["time"],
                marker=row["id"],
                location=row["location"],
                depth=-1,
            )
        )
    total = len(markers) + len(functions)
    # Keep every marker and shallow function entry possible, distributing any
    # oversubscribed layer over the WHOLE run instead of truncating its tail.
    layers = collections.defaultdict(list)
    for entry in functions:
        layers[entry["depth"]].append(entry)
    chosen = []
    for layer in [markers] + [layers[d] for d in sorted(layers)]:
        room = maximum - len(chosen)
        if room <= 0:
            break
        if len(layer) <= room:
            chosen.extend(layer)
        elif room == 1:
            chosen.append(layer[len(layer) // 2])
        else:
            chosen.extend(
                layer[round(i * (len(layer) - 1) / (room - 1))] for i in range(room)
            )
    chosen.sort(
        key=lambda r: (r["time"], r["depth"], r.get("span", r.get("marker", 0)))
    )
    if total > len(chosen):
        diagnostics.append(
            dict(
                code="anchor_subsampling",
                message="Anchor budget selected shallow entries across the full run; some intervening events were omitted.",
            )
        )
    return (
        chosen,
        dict(total=total, retained=len(chosen), subsampled=total > len(chosen)),
        diagnostics,
    )


_IDENTITY_NAME = re.compile(
    r"(?i)(?:^|[^a-z])(iteration|iter|timestep|time.?step|step|phase|cycle|epoch|sweep|batch|frame)(?:[^a-z]|$)"
)


def _enrich(trace, anchors, q, diagnostics):
    """Attach recorded call paths and iteration identities, never trace IDs."""
    functions = [a for a in anchors if a["kind"] == "function"]
    if not functions:
        return
    paths = {r["id"]: r for r in trace.rows("SELECT id,parent,region FROM paths")}
    memo = {0: ()}

    def context(ident):
        if ident in memo:
            return memo[ident]
        trail = []
        seen = set()
        current = ident
        while current not in memo and current in paths and current not in seen:
            seen.add(current)
            trail.append(current)
            current = paths[current]["parent"]
        base = memo.get(current, ())
        for ref in reversed(trail):
            name = trace.regions.get(paths[ref]["region"], {}).get("name", "")
            if name:
                base = base + (_symbol(name),)
            memo[ref] = base
        return memo.get(ident, ())

    for a in functions:
        a["callPath"] = list(context(a.get("path", 0)))
    explicit = q.get("identityParameters", [])
    if isinstance(explicit, str):
        explicit = [n.strip().casefold() for n in explicit.split(",") if n.strip()]
    if not isinstance(explicit, list):
        raise ValueError("identityParameters must be a list or comma-separated names")
    explicit = {str(n).casefold() for n in explicit}

    def string(ref):
        return trace.defs.get("String", {}).get(str(ref), {}).get("string", "")

    parameters = {
        ref: string(d.get("name")) for ref, d in trace.defs.get("Parameter", {}).items()
    }
    parameters = {
        ref: name
        for ref, name in parameters.items()
        if _IDENTITY_NAME.search(name) or name.casefold() in explicit
    }
    if not parameters:
        return
    ordered = sorted(functions, key=lambda a: (a["time"], a["depth"], a["span"]))
    starts = [a["time"] for a in ordered]
    ends = []
    high = -math.inf
    for a in ordered:
        high = max(high, a["end"])
        ends.append(high)
    values = collections.defaultdict(lambda: collections.defaultdict(set))
    rows = trace.rows(
        "SELECT location,time,kind,data FROM events WHERE location=? AND time>=? AND time<=? AND kind IN ('ParameterInt','ParameterUnsignedInt','ParameterString') ORDER BY time,id LIMIT 100001",
        [functions[0]["location"], min(starts), max(ends)],
    )
    if len(rows) > 100000:
        diagnostics.append(
            dict(
                code="identity_parameter_limit",
                message="Parameter context exceeded its budget; parameter identities were omitted rather than partially inferred.",
            )
        )
        return
    for event in rows:
        data = json.loads(event["data"])
        name = parameters.get(str(data.get("parameter")))
        if not name:
            continue
        value = (
            string(data.get("string"))
            if event["kind"] == "ParameterString"
            else data.get("value")
        )
        if value is None:
            continue
        t = event["time"]
        index = bisect.bisect_right(starts, t) - 1
        owner = None
        while index >= 0 and ends[index] >= t:
            a = ordered[index]
            if a["time"] <= t < a["end"] and (
                owner is None
                or (a["depth"], a["time"]) > (owner["depth"], owner["time"])
            ):
                owner = a
            index -= 1
        if owner is not None:
            values[owner["span"]][name.casefold()].add(str(value))
    for a in functions:
        a["parameters"] = {
            name: next(iter(v)) for name, v in values[a["span"]].items() if len(v) == 1
        }


def _phase_names(stats, other, phases, depth):
    return phases | {
        k
        for k in stats.keys() - other.keys()
        if stats[k]["depth"] <= depth
        and stats[k]["count"] <= 64
        and k.casefold() not in _RUNTIME_NAMES
        and not k.startswith("MPI_")
    }


def _select_symbols(trace, other, q, loc_a, loc_b, range_a, range_b, anchor):
    """Choose phase landmarks without discarding unmatched gap evidence."""
    start, end = range_a
    start_b, end_b = range_b
    names_a = {_symbol(r["name"]) for r in trace.meta["regions"]}
    names_b = {_symbol(r["name"]) for r in other.meta["regions"]}
    selection = dict(strategy="ordered-function-and-marker-sequence")
    selection_diagnostics = []

    def has_identity_parameters(run):
        return any(
            _IDENTITY_NAME.search(
                run.defs.get("String", {}).get(str(d.get("name")), {}).get("string", "")
            )
            for d in run.defs.get("Parameter", {}).values()
        )

    parameter_context = (
        bool(q.get("identityParameters"))
        or has_identity_parameters(trace)
        and has_identity_parameters(other)
    )
    if parameter_context:
        selection = dict(strategy="recorded-parameter-context")
    if not anchor and q.get("strategy", "auto") != "sequence" and not parameter_context:
        stats_a = _symbol_statistics(trace, loc_a, start, end)
        stats_b = _symbol_statistics(other, loc_b, start_b, end_b)
        phases = _phase_symbols(stats_a, stats_b, end - start, end_b - start_b)
        if phases:
            depth_a = max(stats_a[k]["depth"] for k in phases)
            depth_b = max(stats_b[k]["depth"] for k in phases)
            names_a = _phase_names(stats_a, stats_b, phases, depth_a)
            names_b = _phase_names(stats_b, stats_a, phases, depth_b)
            selection = dict(
                strategy="shared-phase-landmarks",
                symbols=sorted(phases),
                counts=[
                    dict(
                        label=k, countA=stats_a[k]["count"], countB=stats_b[k]["count"]
                    )
                    for k in sorted(phases)
                ],
            )
            selection_diagnostics.append(
                dict(
                    code="phase_landmark_selection",
                    message="Automatic matching selected shared shallow phases with similar occurrence counts, excluding allocator/I/O plumbing and plentiful MPI calls.",
                )
            )
            mismatches = [
                dict(label=k, countA=stats_a[k]["count"], countB=stats_b[k]["count"])
                for k in stats_a.keys() & stats_b.keys()
                if k.casefold() not in _RUNTIME_NAMES
                and not k.startswith("MPI_")
                and min(stats_a[k]["count"], stats_b[k]["count"]) >= 2
                and max(stats_a[k]["count"], stats_b[k]["count"])
                / min(stats_a[k]["count"], stats_b[k]["count"])
                > 1.5
            ]
            if mismatches:
                selection["differentRepetitionCounts"] = sorted(
                    mismatches,
                    key=lambda r: max(r["countA"], r["countB"]),
                    reverse=True,
                )[:20]
                selection_diagnostics.append(
                    dict(
                        code="different_work_counts",
                        message="Some repeated functions have substantially different call counts; phase alignment does not imply equal iteration count or equal work.",
                    )
                )
        else:
            clean_a = {k for k in names_a if k.casefold() not in _RUNTIME_NAMES}
            clean_b = {k for k in names_b if k.casefold() not in _RUNTIME_NAMES}
            if len(clean_a & clean_b) >= 3:
                names_a, names_b = clean_a, clean_b
    return names_a, names_b, selection, selection_diagnostics
