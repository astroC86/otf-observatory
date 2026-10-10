"""Native transfer statistics: column construction and reduction, record
dictionaries, and clock-unit conversion."""

import sys

import numpy as np

GROUPS = ("size", "tag", "type", "communicator", "callsite")
BOUND = sys.float_info.max

# Rows of statistics_columns(): count, then minimum/maximum/sum of duration and
# bytes, then minimum/maximum of rate, startTime and endTime.
_SUMS = [0, 3, 6]
_MINIMA = [1, 4, 7, 9, 11]
_MAXIMA = [2, 5, 8, 10, 12]


def merge_statistics(left, right):
    """Native min/max/sum/count merge, preserving the supplied reduction order."""
    if left is None:
        return {
            key: dict(value) if isinstance(value, dict) else value
            for key, value in right.items()
        }
    left["count"] += right["count"]
    for name in ("duration", "bytes", "rate", "startTime", "endTime"):
        a, b = left[name], right[name]
        # Same results as min()/max() of two values, including NaN ordering.
        if b["minimum"] < a["minimum"]:
            a["minimum"] = b["minimum"]
        if b["maximum"] > a["maximum"]:
            a["maximum"] = b["maximum"]
        if "sum" in b:
            a["sum"] += b["sum"]
            a["count"] += b["count"]
    return left


def statistics_columns(start, end, size):
    """Native constructor 0xf5abb0 of many records as a (13, records) array.

    Durations are ticks and rates bytes per tick; a zero duration counts as one
    tick. size must already be clamped to a nonnegative float, as the
    constructor does.
    """
    duration = end - start
    duration[~(duration >= 0)] = 0.0
    rate = np.divide(size, duration, out=size.copy(), where=duration != 0)
    columns = np.empty((13, len(start)))
    columns[0] = 1.0
    # Ordered comparisons preserve a NaN endpoint in the native constructor.
    for row, values in zip(_MINIMA, (duration, size, rate, start, end)):
        columns[row] = np.where(BOUND <= values, BOUND, values)
        columns[row + 1] = np.where(values <= -BOUND, -BOUND, values)
    columns[3] = duration + 0.0
    columns[6] = size + 0.0
    return columns


def merge_columns(columns, keys):
    """merge_statistics of records with equal nonnegative integer keys, in record order.

    np.bincount and ufunc.at visit records in order, so sums match the
    sequential scalar merge. Minimum and maximum ignore NaN unless a group's
    first record holds it, exactly as the ordered comparisons do. Returns
    (first record of each group, merged (13, groups) columns), with groups in
    ascending key order.
    """
    size = int(keys.max()) + 1 if len(keys) else 0
    if size > 4 * len(keys):
        # Sparse keys: renumber them densely, keeping their order.
        keys = np.unique(keys, return_inverse=True)[1]
        size = int(keys.max()) + 1
    first = np.full(size, len(keys))
    np.minimum.at(first, keys, np.arange(len(keys)))
    present = first < len(keys)
    first = first[present]
    merged = np.empty((13, len(first)))
    for row in _SUMS:
        merged[row] = np.bincount(keys, columns[row], size)[present]
    for rows, reduce in ((_MINIMA, np.fmin), (_MAXIMA, np.fmax)):
        for row in rows:
            extremum = np.full(size, np.nan)
            reduce.at(extremum, keys, columns[row])
            merged[row] = extremum[present]
    merged[np.isnan(columns[:, first])] = np.nan
    return first, merged


def statistics_record(values, **leading):
    """The merge_statistics dictionary of one statistics_columns() column.

    leading fields, such as a group key, come first in the dictionary.
    """
    count = int(values[0])
    return dict(
        **leading,
        count=count,
        duration=dict(minimum=values[1], maximum=values[2], sum=values[3], count=count),
        bytes=dict(minimum=values[4], maximum=values[5], sum=values[6], count=count),
        rate=dict(minimum=values[7], maximum=values[8]),
        startTime=dict(minimum=values[9], maximum=values[10]),
        endTime=dict(minimum=values[11], maximum=values[12]),
    )


def _seconds_record(row, resolution):
    """Convert a nonempty tick-domain record to seconds and bytes per second."""
    if not row["count"]:
        return
    for name in ("duration", "startTime", "endTime"):
        for field in ("minimum", "maximum", "sum"):
            if field in row[name]:
                row[name][field] /= resolution
    for field in ("minimum", "maximum"):
        row["rate"][field] *= resolution
