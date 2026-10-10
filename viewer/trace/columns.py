"""Columnar numpy copies of the span and slice tables for vectorized range queries.

The tables are immutable once a trace index is loaded, so one copy per index file serves
every range query. Location and region identities are dense codes assigned in sorted text
order: grouping by code therefore reproduces SQLite's GROUP BY output order.
"""

import contextlib
import dataclasses
import os
import threading
import zipfile

import numpy as np

# Paths are positive INTEGER PRIMARY KEYs; NULL references are stored as this sentinel.
MISSING = -1


@dataclasses.dataclass(frozen=True)
class Slices:
    location: np.ndarray
    region: np.ndarray
    path: np.ndarray
    start: np.ndarray
    end: np.ndarray
    span: np.ndarray

    def window(self, start, end):
        return (self.start < end) & (self.end > start)


@dataclasses.dataclass(frozen=True)
class Spans:
    id: np.ndarray  # ascending rowids
    location: np.ndarray
    region: np.ndarray
    path: np.ndarray
    start: np.ndarray
    end: np.ndarray
    sampled: np.ndarray
    incomplete: np.ndarray
    original: np.ndarray  # 1 unless the span continues an earlier invocation
    invocation_group: np.ndarray  # dense (region, invocation) identity
    invocation_region: np.ndarray  # region code of each invocation group
    path_invocation: np.ndarray  # dense (path, invocation) identity
    path_invocation_path: np.ndarray  # path of each (path, invocation) identity

    def window(self, start, end):
        # Zero-length spans at the window start still overlap it.
        return (self.start < end) & (
            (self.end > start) | ((self.start == self.end) & (self.start >= start))
        )

    def paths_of(self, ids):
        """Path of each span id (MISSING when absent), like a scalar subquery by rowid."""
        if not len(self.id):
            return np.full(len(ids), MISSING, dtype=np.int64)
        index = np.minimum(np.searchsorted(self.id, ids), len(self.id) - 1)
        return np.where(self.id[index] == ids, self.path[index], MISSING)


@dataclasses.dataclass(frozen=True)
class Columns:
    locations: tuple  # code -> location id text
    regions: tuple  # code -> region id text
    location_codes: dict
    region_codes: dict
    location_first: np.ndarray  # first slice row of each location code (or row count)
    region_first: np.ndarray  # first slice row of each region code (or row count)
    slices: Slices
    spans: Spans

    def mask(self, table, start, end, locations, regions):
        """Rows of table overlapping [start, end] in the optional id selections."""
        mask = table.window(start, end)
        for column, codes, names in (
            (table.location, self.location_codes, locations),
            (table.region, self.region_codes, regions),
        ):
            if names is not None:
                selected = np.zeros(len(codes), dtype=bool)
                selected[[codes[name] for name in names if name in codes]] = True
                mask &= selected[column]
        return mask


def _dense(*keys):
    """Dense identity of each row's key tuple, and the first row of each identity."""
    combined = np.zeros(len(keys[0]), dtype=np.int64)
    for key in keys:
        span = int(key.max()) + 1 if len(key) else 1
        combined = combined * span + key
    _, first, inverse = np.unique(combined, return_index=True, return_inverse=True)
    return inverse.astype(np.int32), first


def _table(db, sql, codes, dtype):
    """Fetch rows into separate contiguous arrays.

    The second and third selected columns are location and region ids, translated
    to codes; all other columns are stored as selected.
    """
    location_codes, region_codes = codes
    rows = np.fromiter(
        (
            (first, location_codes[location], region_codes[region], *rest)
            for first, location, region, *rest in db.execute(sql)
        ),
        dtype=dtype,
    )
    return {name: np.ascontiguousarray(rows[name]) for name in rows.dtype.names}


def _build(db, invocation, original):
    """Arrays of both tables; text ids become codes in sorted text order."""
    names = {
        column: sorted(
            r[0]
            for r in db.execute(
                f"SELECT {column} FROM spans UNION SELECT {column} FROM slices"
            )
        )
        for column in ("location", "region")
    }
    codes = tuple(
        {name: code for code, name in enumerate(names[column])}
        for column in ("location", "region")
    )
    slices = _table(
        db,
        "SELECT coalesce(span,-1),location,region,coalesce(path,-1),start,end FROM slices ORDER BY id",
        codes,
        [
            ("span", "i8"),
            ("location", "i4"),
            ("region", "i4"),
            ("path", "i4"),
            ("start", "f8"),
            ("end", "f8"),
        ],
    )
    spans = _table(
        db,
        f"""SELECT s.id,s.location,s.region,coalesce(s.path,-1),s.start,s.end,
        coalesce(s.sampled,0),coalesce(s.incomplete,0),coalesce({original},0),
        {invocation} FROM spans s ORDER BY s.id""",
        codes,
        [
            ("id", "i8"),
            ("location", "i4"),
            ("region", "i4"),
            ("path", "i4"),
            ("start", "f8"),
            ("end", "f8"),
            ("sampled", "i1"),
            ("incomplete", "i1"),
            ("original", "i1"),
            ("invocation", "i8"),
        ],
    )
    invocation = spans.pop("invocation")
    group, first = _dense(spans["region"], invocation)
    spans.update(invocation_group=group, invocation_region=spans["region"][first])
    group, first = _dense(spans["path"] - MISSING, invocation)
    spans.update(path_invocation=group, path_invocation_path=spans["path"][first])
    arrays = {"locations": np.array(names["location"], dtype=str)}
    arrays["regions"] = np.array(names["region"], dtype=str)
    for column in ("location", "region"):
        first = np.full(len(names[column]), len(slices["start"]), dtype=np.int64)
        codes, rows = np.unique(slices[column], return_index=True)
        first[codes] = rows
        arrays[column + "_first"] = first
    arrays.update(("slices." + name, values) for name, values in slices.items())
    arrays.update(("spans." + name, values) for name, values in spans.items())
    return arrays


def _columns(arrays):
    tables = {"slices": {}, "spans": {}}
    for name, values in arrays.items():
        if "." in name:
            table, column = name.split(".")
            tables[table][column] = values
    locations = tuple(arrays["locations"].tolist())
    regions = tuple(arrays["regions"].tolist())
    return Columns(
        locations,
        regions,
        {name: code for code, name in enumerate(locations)},
        {name: code for code, name in enumerate(regions)},
        arrays["location_first"],
        arrays["region_first"],
        Slices(**tables["slices"]),
        Spans(**tables["spans"]),
    )


# Bump when the derived arrays change so stale sidecars are rebuilt.
_FORMAT = 1
_ARRAYS = frozenset(
    ["locations", "regions", "location_first", "region_first"]
    + ["slices." + field.name for field in dataclasses.fields(Slices)]
    + ["spans." + field.name for field in dataclasses.fields(Spans)]
)


def _read(path, key):
    """Stored arrays for key, or None when the sidecar is missing, stale or malformed.

    The sidecar is only a cache: any damage (a truncated write, a foreign file)
    must fall back to rebuilding from the index. Zip CRCs catch corrupt members.
    """
    try:
        with open(path, "rb") as file:
            stored = np.load(file)
            # A plain .npy file loads as one array rather than an archive.
            if not isinstance(stored, np.lib.npyio.NpzFile):
                return None
            if set(stored.files) != _ARRAYS | {"key"}:
                return None
            if stored["key"].tolist() != [_FORMAT, *key]:
                return None
            return {name: stored[name] for name in _ARRAYS}
    except (OSError, EOFError, ValueError, zipfile.BadZipFile):
        return None


def _write(path, key, arrays):
    """Store arrays next to the index; an unwritable directory only costs a rebuild."""
    temporary = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temporary, "wb") as file:
            np.savez(file, key=np.array([_FORMAT, *key], dtype=np.int64), **arrays)
        os.replace(temporary, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temporary)


class ColumnCache:
    """Single-flight columnar copy of one trace index, reloaded if the file changes.

    The arrays persist in a sidecar keyed by the index file's size and mtime, so
    later server runs skip the row-by-row SQLite fetch.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.key = None
        self.value = None

    def get(self, trace):
        stat = os.stat(trace.path)
        key = (stat.st_mtime_ns, stat.st_size)
        with self.lock:
            if self.key != key:
                self.value = None
                sidecar = trace.path + ".columns.npz"
                arrays = _read(sidecar, key)
                if arrays is None:
                    with trace.connect() as db:
                        arrays = _build(db, trace.invocation, trace.original)
                    _write(sidecar, key, arrays)
                self.value = _columns(arrays)
                self.key = key
            return self.value
