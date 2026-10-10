"""Region, process, and call-tree profiles over shared Trace state."""

import numpy as np


def _clipped(table, mask, start, end):
    """Seconds of each selected interval inside [start, end]."""
    return np.minimum(table.end[mask], end) - np.maximum(table.start[mask], start)


# Largest key space aggregated with dense bincount arrays (32 MB of float64).
_DENSE_KEYS = 1 << 22


def _sums(keys, size, weights=None):
    return np.bincount(keys, weights=weights, minlength=size)


def _extremes(reduce, initial, keys, size, values):
    """Per-key minimum or maximum (reduce is np.minimum or np.maximum)."""
    out = np.full(size, initial, dtype=values.dtype)
    reduce.at(out, keys, values)
    return out


def _key_sums(keys, size, weights):
    """{key: weight sum} of the observed keys, in ascending key order.

    Large key spaces (e.g. locations x regions) are compacted to the observed
    keys first, so memory follows the selected rows rather than the product.
    """
    if size <= _DENSE_KEYS:
        present = np.flatnonzero(_sums(keys, size))
        sums = _sums(keys, size, weights)[present]
    else:
        present, inverse = np.unique(keys, return_inverse=True)
        sums = _sums(inverse, len(present), weights)
    return dict(zip(present.tolist(), sums.tolist()))


def _calls(spans, mask, start, end):
    """Selected spans that begin a measured invocation inside the window."""
    begins = spans.start[mask]
    return (
        (begins >= start)
        & (begins < end)
        & (spans.sampled[mask] == 0)
        & (spans.original[mask] != 0)
    )


class ProfileQueries:
    def summary(self, q):
        start, end, empty, locations, regions = self.scope_filters(q)
        if empty:
            return []
        columns = self.columns()
        spans, slices = columns.spans, columns.slices
        mask = columns.mask(spans, start, end, locations, regions)
        # Inner aggregate: one row per invocation (continuations share it).
        group = spans.invocation_group[mask]
        size = len(spans.invocation_region)
        present = np.flatnonzero(_sums(group, size))
        group_calls = _sums(group, size, _calls(spans, mask, start, end))[present]
        group_seconds = _sums(group, size, _clipped(spans, mask, start, end))[present]
        incomplete = _extremes(np.maximum, 0, group, size, spans.incomplete[mask])
        sampled = _extremes(np.maximum, 0, group, size, spans.sampled[mask])
        # Outer aggregate over the invocations of each region.
        region = spans.invocation_region[present]
        size = len(columns.regions)
        overlapping = _sums(region, size)
        totals = dict(
            calls=_sums(region, size, group_calls).astype(np.int64),
            inclusive=_sums(region, size, group_seconds),
            minimum=_extremes(np.minimum, np.inf, region, size, group_seconds),
            maximum=_extremes(np.maximum, -np.inf, region, size, group_seconds),
            incomplete=_sums(region, size, incomplete[present]).astype(np.int64),
            estimated=_sums(region, size, sampled[present]).astype(np.int64),
        )
        totals = {name: values.tolist() for name, values in totals.items()}
        slice_mask = columns.mask(slices, start, end, locations, regions)
        exclusive = _key_sums(
            slices.region[slice_mask], size, _clipped(slices, slice_mask, start, end)
        )
        rows = []
        for code in np.flatnonzero(overlapping).tolist():
            name = columns.regions[code]
            r = dict(region=name, overlapping=int(overlapping[code]))
            r.update((field, values[code]) for field, values in totals.items())
            r.update(self.regions.get(name, {}))
            r["exclusive"] = exclusive.get(code, 0)
            r["average"] = r["inclusive"] / r["overlapping"]
            rows.append(r)
        return sorted(rows, key=lambda r: r["exclusive"], reverse=True)

    def processes(self, q):
        start, end, empty, locations, regions = self.scope_filters(q)
        result = {
            r["id"]: dict(r, exclusive=0, groups={}, regions={})
            for r in self.meta["locations"]
            if not q.get("locations") or r["id"] in q["locations"].split(",")
        }
        if not empty:
            columns = self.columns()
            slices = columns.slices
            mask = columns.mask(slices, start, end, locations, regions)
            width = len(columns.regions)
            pairs = slices.location[mask].astype(np.int64) * width + slices.region[mask]
            seconds = _key_sums(
                pairs,
                len(columns.locations) * width,
                _clipped(slices, mask, start, end),
            )
            for pair, value in seconds.items():
                item = result.get(columns.locations[pair // width])
                if item is None:
                    continue
                region = columns.regions[pair % width]
                group = self.regions.get(region, {}).get("group", "Unknown")
                item["exclusive"] += value
                item["groups"][group] = item["groups"].get(group, 0) + value
                item["regions"][region] = value
        for r in result.values():
            r["utilization"] = r["exclusive"] / max(end - start, 1e-30)
        return list(result.values())

    def calltree(self, q):
        start, end, empty, locations, regions = self.scope_filters(q)
        rows, exclusive = [], {}
        if not empty:
            columns = self.columns()
            spans, slices = columns.spans, columns.slices
            mask = columns.mask(spans, start, end, locations, regions)
            path = spans.path[mask]
            size = 1 + int(max(spans.path.max(initial=0), slices.path.max(initial=0)))
            pairs = spans.path_invocation[mask]
            distinct = np.flatnonzero(_sums(pairs, len(spans.path_invocation_path)))
            fields = dict(
                calls=_sums(path, size, _calls(spans, mask, start, end)).astype(
                    np.int64
                ),
                overlapping=_sums(spans.path_invocation_path[distinct], size),
                estimated=_sums(path, size, spans.sampled[mask]).astype(np.int64),
                inclusive=_sums(path, size, _clipped(spans, mask, start, end)),
            )
            fields = {name: values.tolist() for name, values in fields.items()}
            for code in np.flatnonzero(_sums(path, size)).tolist():
                r = dict(path=code)
                r.update((field, values[code]) for field, values in fields.items())
                rows.append(r)
            slice_mask = columns.mask(slices, start, end, locations, regions)
            exclusive = _key_sums(
                slices.path[slice_mask], size, _clipped(slices, slice_mask, start, end)
            )
        paths = {r["id"]: r for r in self.rows("SELECT * FROM paths")}
        out = {}
        for r in rows:
            r.update(paths[r["path"]])
            r["name"] = self.regions.get(r["region"], {}).get("name", r["region"])
            r["group"] = self.regions.get(r["region"], {}).get("group", "")
            r["exclusive"] = exclusive.get(r["path"], 0)
            out[r["id"]] = r
        # Preserve ancestors when a function filter hides their own measurements.
        for row in list(out.values()):
            parent = row["parent"]
            while parent and parent not in out:
                p = paths[parent]
                out[parent] = dict(
                    p,
                    path=parent,
                    name=self.regions.get(p["region"], {}).get("name", p["region"]),
                    group="",
                    inclusive=0,
                    exclusive=0,
                    calls=0,
                )
                parent = p["parent"]
        return list(out.values())
