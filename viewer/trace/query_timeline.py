"""Timeline detail and overview queries over shared Trace state."""

import numpy as np

from .columns import MISSING


def _runs(keys):
    """Start offsets of runs of equal values in a sorted key array."""
    if not len(keys):
        return np.zeros(0, dtype=np.int64)
    return np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])


class TimelineQueries:
    def timeline(self, q):
        detail = q.get("detail", "0") == "1"
        limit = 40000
        if detail:
            start, end, sp, args = self.interval("spans", q)
            rows = self.rows(
                f"SELECT s.* FROM {sp} ORDER BY s.start,s.depth LIMIT ?",
                [*args, limit + 1],
            )
            truncated = len(rows) > limit
            return dict(rows=rows[:limit], aggregated=False, truncated=truncated)
        start, end, empty, locations, regions = self.scope_filters(q)
        requested = (
            set(q["locations"].split(","))
            if q.get("locations")
            else set(self.locations)
        )
        location_count = max(1, len(requested.intersection(self.locations)))
        # Leaf slices do not overlap on a location. At most bins+2 intervals can
        # be longer than a pixel; at most bins short-interval cells remain.
        # Budget both sets rather than truncating the earliest 40k records.
        budget = limit // (2 * location_count) - 1
        if budget < 1:
            raise ValueError("Select fewer locations for the timeline")
        bins = min(3000, max(1, int(q.get("bins", 1200))), budget)
        step = max((end - start) / bins, 1e-15)
        result = dict(
            rows=[],
            aggregated=True,
            truncated=False,
            bins=bins,
            aggregation="dominant-region-per-pixel",
        )
        if empty:
            return result
        columns = self.columns()
        slices = columns.slices
        mask = columns.mask(slices, start, end, locations, regions)
        begin, finish = slices.start[mask], slices.end[mask]
        location, region = slices.location[mask], slices.region[mask]
        span, slice_path = slices.span[mask], slices.path[mask]
        seconds = np.minimum(finish, end) - np.maximum(begin, start)
        # Intervals shorter than a pixel coalesce per (location, pixel) cell into
        # their dominant region; longer intervals are drawn individually.
        short = finish - begin < step
        pixel = np.clip(((begin[short] - start) / step).astype(np.int64), 0, bins - 1)
        width = len(columns.regions)
        key = (location[short].astype(np.int64) * bins + pixel) * width + region[short]
        order = np.argsort(key)
        picked = np.flatnonzero(short)[order]
        key = key[order]
        groups = _runs(key)

        def per_group(reduce, values):
            return reduce.reduceat(values[picked], groups)

        group_cell, group_region = np.divmod(key[groups], width)
        group_seconds = per_group(np.add, seconds)
        group_span = per_group(np.minimum, span)
        # Dominant group per cell: longest total time, ties to the lower region id.
        ranked = np.lexsort((group_region, -group_seconds, group_cell))
        cells = _runs(group_cell[ranked])
        dominant = ranked[cells]

        def per_cell(reduce, values):
            return reduce.reduceat(values[ranked], cells)

        long = ~short
        ones = np.ones(np.count_nonzero(long), np.int64)
        # Coalesced cells first, then long intervals (the original UNION ALL order).
        fields = (
            np.r_[group_cell[dominant] // bins, location[long]],
            np.r_[group_region[dominant], region[long]],
            np.r_[columns.spans.paths_of(group_span[dominant]), slice_path[long]],
            np.r_[per_cell(np.minimum, per_group(np.minimum, begin)), begin[long]],
            np.r_[per_cell(np.maximum, per_group(np.maximum, finish)), finish[long]],
            np.r_[group_span[dominant], span[long]],
            np.r_[per_cell(np.add, np.diff(np.r_[groups, len(key)])), ones],
            np.r_[per_cell(np.add, group_seconds), seconds[long]],
            np.r_[group_seconds[dominant], seconds[long]],
            np.r_[np.ones(len(dominant), np.int64), ones * 0],
        )
        order = np.argsort(fields[3], kind="stable")
        names_l, names_r = columns.locations, columns.regions
        result["rows"] = [
            dict(
                location=names_l[loc],
                region=names_r[reg],
                path=None if path == MISSING else path,
                start=a,
                end=b,
                id=None if ident == MISSING else ident,
                count=count,
                duration=total,
                dominantDuration=top,
                coalesced=coalesced,
            )
            for loc, reg, path, a, b, ident, count, total, top, coalesced in zip(
                *(values[order].tolist() for values in fields)
            )
        ]
        return result

    def overview(self, q):
        start, end, empty, locations, regions = self.scope_filters(q)
        bins = max(32, min(1000, int(q.get("bins", 240))))
        step = max((end - start) / bins, 1e-15)
        result = dict(start=start, end=end, bins=bins, series={})
        if empty:
            return result
        columns = self.columns()
        slices = columns.slices
        mask = columns.mask(slices, start, end, locations, regions)
        if q.get("by") == "location":
            names = columns.locations
            series_of = np.arange(len(names))
            column, first_rows = slices.location, columns.location_first
        else:
            groups = [
                self.regions.get(region, {}).get("group", "Unknown")
                for region in columns.regions
            ]
            names = list(dict.fromkeys(groups))
            index = {name: code for code, name in enumerate(names)}
            series_of = np.array([index[g] for g in groups], dtype=np.int64)
            column, first_rows = slices.region, columns.region_first
        series = series_of[column[mask]]
        # Series keep the order of their first stored interval in the whole trace,
        # so zooming never reorders the stack.
        order = np.full(len(names), np.iinfo(np.int64).max)
        np.minimum.at(order, series_of, first_rows)
        a = np.maximum(slices.start[mask], start)
        b = np.minimum(slices.end[mask], end)
        i = np.clip(((a - start) / step).astype(np.int64), 0, bins - 1)
        j = np.clip(((b - start) / step).astype(np.int64), 0, bins - 1)
        split = i != j
        first = np.where(split, (start + (i + 1) * step - a) / step, (b - a) / step)
        last = (b[split] - start - j[split] * step) / step
        size = len(names) * bins
        values = np.bincount(series * bins + i, weights=first, minlength=size)
        values += np.bincount(
            series[split] * bins + j[split], weights=last, minlength=size
        )
        # Bins strictly between an interval's first and last bin are fully covered.
        width = bins + 1
        diffs = np.bincount(
            series[split] * width + i[split] + 1, minlength=len(names) * width
        ) - np.bincount(series[split] * width + j[split], minlength=len(names) * width)
        covered = np.cumsum(diffs.reshape(len(names), width)[:, :bins], axis=1)
        values = values.reshape(len(names), bins) + covered
        present = np.flatnonzero(np.bincount(series, minlength=len(names)))
        for code in present[np.argsort(order[present], kind="stable")].tolist():
            result["series"][names[code]] = values[code].tolist()
        return result
