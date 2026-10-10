"""Atomic stack reconstruction for old importer-owned task indexes."""

import contextlib
import json
import pathlib
import sqlite3
import time

from ..trace.indexer import Indexer
from ..trace.schema import STACK_EVENTS
from ..trace.encoding import dumps
from .identity import TASK_INDEX_VERSION, TASK_REIMPORT_WARNING, task_index_status

DERIVED = ("paths", "spans", "slices", "samples")
STACK_WARNINGS = {
    "Non-monotonic location timestamps",
    "Leave without matching enter",
    "Mismatched region nesting",
    "Unresolved calling context",
    "Undefined calling-context unwind distance (estimated nesting)",
    "Inconsistent calling-context unwind distance",
    "Task event has invalid identity fields; stack transition ignored",
    "Task event has invalid identity fields; execution context unresolved",
    "Task completion does not identify the active task",
    "Task completed on another active location",
    "Task identity active on multiple locations",
    "Task identity recreated before recorded completion",
    "Unclosed region (clipped at last event)",
    "Unclosed suspended task frames (clipped at suspension)",
    TASK_REIMPORT_WARNING,
}


def ensure_task_index(path, *, timeout=120):
    """Replay original event order, replacing only derived stack tables.

    No original archive is needed. Unrelated evidence, raw IDs and metadata
    survive unchanged. A failed/expired/read-only rebuild leaves the previous
    index intact and eligible for retry or explicit reimport.
    """
    uri = pathlib.Path(path).resolve().as_uri()
    deadline = time.monotonic() + timeout

    def metadata(db):
        row = db.execute("SELECT value FROM metadata WHERE key='trace'").fetchone()
        return json.loads(row[0]) if row else {}

    def eligible(meta):
        return (
            all(key in meta for key in ("path", "version", "counts"))
            and task_index_status(meta)["requiresReimport"]
        )

    try:
        with contextlib.closing(sqlite3.connect(uri + "?mode=ro", uri=True)) as db:
            meta = metadata(db)
            if not eligible(meta):
                return dict(
                    status="not-needed", version=meta.get("taskIndexVersion", 0)
                )
        with contextlib.closing(
            sqlite3.connect(uri + "?mode=rw", uri=True, timeout=max(0, timeout))
        ) as db, db:
            db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            db.execute("BEGIN IMMEDIATE")
            meta = metadata(db)
            if not eligible(meta):
                return dict(
                    status="not-needed", version=meta.get("taskIndexVersion", 0)
                )
            previous = meta.get("taskIndexVersion", 0)
            if db.execute("SELECT count(*) FROM events").fetchone()[0] != meta[
                "counts"
            ].get("events"):
                raise ValueError("retained event count differs from imported metadata")
            idx = Indexer(db)
            for kind, ref, raw in db.execute(
                "SELECT kind,ref,data FROM definitions ORDER BY rowid"
            ):
                definition = json.loads(raw)
                if not isinstance(definition, dict):
                    raise ValueError("retained definition is not an object")
                idx.defs[kind][ref] = definition
            idx.initialize()
            # Older owned caches may predate invocation/continuation columns.
            columns = {row[1] for row in db.execute("PRAGMA table_info(spans)")}
            for name, declaration in (
                ("continuation", "INTEGER DEFAULT 0"),
                ("invocation", "INTEGER"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE spans ADD COLUMN {name} {declaration}")
            for table in (*DERIVED, "span_time", "slice_time"):
                db.execute("DELETE FROM " + table)
            replayed = 0
            for eid, loc, stamp, kind, raw in db.execute(
                "SELECT id,location,time,kind,data FROM events ORDER BY id"
            ):
                if time.monotonic() >= deadline:
                    raise TimeoutError("task replay deadline exceeded")
                # Preserve every observation, including metrics/messages, for
                # remote conflicts and incomplete stack finalization.
                idx.last_events[loc] = max(stamp, idx.last_events.get(loc, stamp))
                idx.max_time = max(idx.max_time, stamp)
                if kind in STACK_EVENTS:
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError("retained stack event is not an object")
                    idx.stack_event(loc, stamp, kind, data)
                    replayed += 1
            idx.finish_stacks()
            idx.flush()
            for table, intervals in (("spans", "span_time"), ("slices", "slice_time")):
                db.execute(f"INSERT INTO {intervals} SELECT id,start,end FROM {table}")
            for table in ("spans", "samples"):
                meta["counts"][table] = db.execute(
                    "SELECT count(*) FROM " + table
                ).fetchone()[0]
            warnings = meta.setdefault("warnings", {})
            for name in STACK_WARNINGS:
                warnings.pop(name, None)
            warnings.update(
                {name: count for name, count in idx.warnings.items() if count}
            )
            meta["taskIndexVersion"] = TASK_INDEX_VERSION
            meta.pop("taskIndexStatus", None)
            db.execute("UPDATE metadata SET value=? WHERE key='trace'", (dumps(meta),))
            return dict(
                status="upgraded",
                previousVersion=previous,
                version=TASK_INDEX_VERSION,
                records=replayed,
            )
    except (sqlite3.Error, ValueError, KeyError, TypeError, TimeoutError) as error:
        return dict(status="unavailable", reason=str(error), version=TASK_INDEX_VERSION)
