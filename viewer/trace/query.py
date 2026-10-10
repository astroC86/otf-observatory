"""Read-only analysis queries. All time units are seconds relative to the trace offset."""

import collections
import concurrent.futures
import contextlib
import json
import math
import pathlib
import re
import sqlite3
import threading

from .columns import ColumnCache
from .definitions import enum
from .cache import (
    ensure_metric_index,
    ensure_message_index,
    ensure_rma_index,
    ensure_state_transition_index,
)
from ..gpu.clocks import ensure_clock_metadata
from ..tasks.identity import task_index_status, TASK_REIMPORT_WARNING
from ..tasks.index import ensure_task_index
from .query_profiles import ProfileQueries
from .query_timeline import TimelineQueries
from .query_events import EventQueries
from .query_metrics import MetricQueries
from .query_messages import MessageQueries

# SQLite releases the GIL while stepping, so independent read-only scans overlap.
_QUERY_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4)
# Idle read connections kept per trace: the query pool plus concurrent HTTP requests.
_POOL_SIZE = 8
# Sorts and temporary b-trees stay in memory instead of the system temp directory;
# memory-mapped reads skip copying pages into SQLite's cache (SQLite caps the size).
_READ_PRAGMAS = (
    "PRAGMA query_only=ON; PRAGMA cache_size=-32000; PRAGMA temp_store=MEMORY;"
    " PRAGMA mmap_size=4294967296;"
)


class Trace(
    ProfileQueries, TimelineQueries, EventQueries, MetricQueries, MessageQueries
):
    """Own the connection path and metadata shared by all analysis queries."""

    def __init__(self, path):
        ensure_message_index(path)
        ensure_rma_index(path)
        self.task_index_upgrade_status = ensure_task_index(path)
        self.state_transition_index_status = ensure_state_transition_index(path)
        self.metric_index_status = ensure_metric_index(path)
        self.clock_metadata_status = ensure_clock_metadata(path)
        self.path = str(path)
        self._uri = pathlib.Path(path).resolve().as_uri() + "?mode=ro"
        self._pool = []
        self._pool_lock = threading.Lock()
        self._columns = ColumnCache()
        with self.connect() as db:
            self.meta = json.loads(
                db.execute("SELECT value FROM metadata WHERE key='trace'").fetchone()[0]
            )
        self.meta["taskIndexStatus"] = task_index_status(self.meta)
        if self.meta["taskIndexStatus"]["requiresReimport"]:
            self.meta.setdefault("warnings", {})[TASK_REIMPORT_WARNING] = 1
        self.regions = {r["id"]: r for r in self.meta["regions"]}
        self.locations = {r["id"]: r for r in self.meta["locations"]}
        self.defs = collections.defaultdict(dict)
        with self.connect() as db:
            # Native context indices and execution representatives depend on
            # recorded definition order, not numeric reference sorting.
            for row in db.execute(
                "SELECT kind,ref,data FROM definitions ORDER BY rowid"
            ):
                self.defs[row["kind"]][row["ref"]] = json.loads(row["data"])
            columns = {r["name"] for r in db.execute("PRAGMA table_info(spans)")}
        # Older caches omitted the anchor creator. Recover only when the
        # recorded OMPT declarations need it to identify a producer contract;
        # source signature and global definitions are verified transactionally.
        archives = list(self.defs.get("ArchiveProperties", {}).values())
        if not archives or any("creator" not in row for row in archives):
            from ..tasks.contracts import has_scorep_ompt_wait_definitions

            if has_scorep_ompt_wait_definitions(self.defs):
                from ..metrics.attribute_metadata import (
                    recover_attribute_reference_metadata,
                )

                self.meta["creatorMetadataStatus"] = (
                    recover_attribute_reference_metadata(
                        self.path, require_creator=True
                    )
                )
                if self.meta["creatorMetadataStatus"]["status"] in (
                    "current",
                    "recovered",
                ):
                    self.defs["ArchiveProperties"] = {
                        row["ref"]: json.loads(row["data"])
                        for row in self.rows(
                            "SELECT ref,data FROM definitions WHERE kind='ArchiveProperties' ORDER BY rowid"
                        )
                    }
        self.invocation = (
            "coalesce(s.invocation,s.id)" if "invocation" in columns else "s.id"
        )
        self.original = "s.continuation=0" if "continuation" in columns else "1"
        # Early indexes retained the OTF1 record but translated its timing bits
        # incorrectly. Recover effective metadata from that original record.
        if self.meta.get("format") == "OTF":
            metrics = {m["id"]: m for m in self.meta["metrics"]}
            for definition in self.defs.get("Otf1Definition", {}).values():
                raw = definition.get("raw", "")
                match = re.match(r"DCNT([0-9a-fA-F]+)G", raw)
                properties = re.search(r'P([0-9a-fA-F]+)U"', raw) if match else None
                member = str(int(match[1], 16)) if match else None
                if properties and member in metrics:
                    prop = int(properties[1], 16)
                    mode = (prop & 1) | ((prop & 12) << 2)
                    metrics[member].update(
                        modeValue=mode,
                        mode=enum("OTF2_METRIC_", mode),
                        otfProperties=prop,
                    )

    @contextlib.contextmanager
    def connect(self):
        """Borrow a pooled read-only connection; the index is immutable while loaded."""
        with self._pool_lock:
            db = self._pool.pop() if self._pool else None
        if db is None:
            db = sqlite3.connect(self._uri, uri=True, check_same_thread=False)
            db.row_factory = sqlite3.Row
            db.executescript(_READ_PRAGMAS)
        try:
            yield db
        finally:
            db.set_progress_handler(None, 0)
            with self._pool_lock:
                if len(self._pool) < _POOL_SIZE:
                    self._pool.append(db)
                    db = None
            if db is not None:
                db.close()

    def rows(self, sql, args=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def rows_many(self, *queries):
        """Run independent (sql, args) queries concurrently; results keep query order."""
        return list(_QUERY_POOL.map(lambda query: self.rows(*query), queries))

    def columns(self):
        """Columnar span/slice copies shared by vectorized range queries."""
        return self._columns.get(self)

    def scope_filters(self, q, regions=True):
        """Clamped (start, end, empty, location ids or None, region ids or None) of a request."""
        start = float(q.get("start", 0))
        end = float(q.get("end", self.meta["duration"]))
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError("Invalid time interval")
        start = max(0, min(self.meta["duration"], start))
        end = max(0, min(self.meta["duration"], end))
        ids = q.get("locations", "")
        locations = ids.split(",") if ids else None
        selected = None
        if regions:
            include = q.get("region", "").casefold()
            exclude = q.get("exclude", "").casefold()
            group = q.get("group", "")
            if include or exclude or group:
                selected = [
                    r["id"]
                    for r in self.meta["regions"]
                    if (not include or include in r["name"].casefold())
                    and (not exclude or exclude not in r["name"].casefold())
                    and (not group or group == r["group"])
                ]
        return start, end, start == end, locations, selected

    def scope(self, q, alias="", regions=True):
        a = (alias + ".") if alias else ""
        start, end, empty, locations, selected = self.scope_filters(q, regions)
        clauses = ["0"] if empty else []
        args = []
        if locations is not None:
            clauses.append(f'{a}location IN ({",".join("?" for _ in locations)})')
            args += locations
        if selected is not None:
            clauses.append(
                f'{a}region IN ({",".join("?" for _ in selected)})' if selected else "0"
            )
            args += selected
        return start, end, (" AND " + " AND ".join(clauses) if clauses else ""), args

    def interval(self, table, q):
        if table not in ("spans", "slices"):
            raise ValueError("Invalid interval table")
        start, end, where, args = self.scope(q, "s")
        rt = "span_time" if table == "spans" else "slice_time"
        # The R-tree uses outward-rounded float32 coordinates; exact REAL checks are essential.
        overlap = (
            "(s.end>? OR (s.start=s.end AND s.start>=?))"
            if table == "spans"
            else "s.end>?"
        )
        sql = (
            f"{table} s JOIN {rt} ix ON ix.id=s.id WHERE ix.start<=? AND ix.end>=? AND s.start<? AND "
            + overlap
            + where
        )
        if table == "spans":
            return start, end, sql, [end, start, end, start, start] + args
        return start, end, sql, [end, start, end, start] + args
