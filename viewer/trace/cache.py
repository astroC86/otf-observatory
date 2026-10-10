"""Source signatures and transactional upgrades of retained trace indexes."""

import contextlib
import hashlib
import json
import pathlib
import sqlite3
import time

from ..mpi.rma_matching import RMA_EVENTS, RMA_INDEX_VERSION
from .encoding import dumps
from .indexer import Indexer
from .message_index import normalize_otf_message
from .schema import (
    MESSAGE_INDEX_VERSION,
    METRIC_INDEX,
    MPI_MESSAGE_EVENTS,
    STATE_TRANSITION_INDEX,
    VERSION,
)


def signature(path):
    files = [path] + list(path.parent.glob(path.stem + ".def"))
    if path.suffix == ".otf2":
        files += list((path.parent / path.stem).glob("*"))
    else:
        files += list(path.parent.glob(path.stem + ".*"))
    s = "|".join(
        f"{p}:{p.stat().st_size}:{p.stat().st_mtime_ns}"
        for p in sorted(set(files))
        if p.is_file()
    )
    return hashlib.sha256((str(VERSION) + s).encode()).hexdigest()[:20]


def ensure_state_transition_index(path, *, timeout=60):
    """Add a sparse predecessor index without changing retained trace data.

    Old importer-owned caches need it only if CallingContext records exist.
    Read-only/foreign fixtures remain usable without this performance index.
    SQLite cancellation rolls the optional build back as one transaction.
    """
    uri = pathlib.Path(path).resolve().as_uri()
    try:
        with contextlib.closing(sqlite3.connect(uri + "?mode=ro", uri=True)) as db:
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name='ev_state_transition'"
            ).fetchone():
                return dict(status="current")
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
            ).fetchone():
                return dict(status="not-applicable")
            row = db.execute("SELECT value FROM metadata WHERE key='trace'").fetchone()
            meta = json.loads(row[0]) if row else {}
            if not all(key in meta for key in ("path", "version", "counts")):
                return dict(status="not-applicable")
            if not db.execute(
                "SELECT 1 FROM events WHERE kind IN ('CallingContextEnter','CallingContextLeave','CallingContextSample') LIMIT 1"
            ).fetchone():
                return dict(status="not-applicable")
        with contextlib.closing(
            sqlite3.connect(uri + "?mode=rw", uri=True, timeout=timeout)
        ) as db, db:
            db.execute("BEGIN IMMEDIATE")
            deadline = time.monotonic() + timeout
            db.set_progress_handler(lambda: time.monotonic() > deadline, 1000)
            db.execute(STATE_TRANSITION_INDEX)
            db.set_progress_handler(None, 0)
        return dict(status="created")
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        return dict(status="unavailable", detail=str(error))


def ensure_metric_index(path, *, timeout=60):
    """Replace the metric lookup index with an ordered covering index atomically.

    Only importer-owned caches are changed. Current/foreign indexes are inspected
    read-only; unavailable optional upgrades leave the previous index usable.
    """
    uri = pathlib.Path(path).resolve().as_uri()

    def state(db):
        index = db.execute(
            "SELECT tbl_name FROM sqlite_master WHERE type='index' AND name='met'"
        ).fetchone()
        columns = None
        if index:
            spec = next(
                (
                    row
                    for row in db.execute("PRAGMA index_list(metrics)")
                    if row[1] == "met"
                ),
                None,
            )
            keys = [row for row in db.execute("PRAGMA index_xinfo(met)") if row[5]]
            columns = (
                tuple(row[2] for row in keys)
                if index[0] == "metrics"
                and spec is not None
                and not spec[2]
                and not spec[4]
                and all(not row[3] and row[4] == "BINARY" for row in keys)
                else ()
            )
        if columns == ("metric", "location", "time", "id", "value", "raw"):
            return "current"
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
        ).fetchone():
            return "not-applicable"
        row = db.execute("SELECT value FROM metadata WHERE key='trace'").fetchone()
        meta = json.loads(row[0]) if row else {}
        if not all(key in meta for key in ("path", "version", "counts")):
            return "not-applicable"
        if columns is not None and columns != ("metric", "location", "time"):
            raise ValueError("Unrecognized importer-owned metric index")
        return "legacy" if columns is not None else "missing"

    try:
        with contextlib.closing(sqlite3.connect(uri + "?mode=ro", uri=True)) as db:
            previous = state(db)
            if previous in ("current", "not-applicable"):
                return dict(status=previous)
        with contextlib.closing(
            sqlite3.connect(uri + "?mode=rw", uri=True, timeout=max(0, timeout))
        ) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = state(db)
            if previous in ("current", "not-applicable"):
                return dict(status=previous)
            deadline = time.monotonic() + timeout
            db.set_progress_handler(lambda: time.monotonic() >= deadline, 1000)
            try:
                if previous == "legacy":
                    db.execute("DROP INDEX met")
                db.execute(METRIC_INDEX)
            finally:
                db.set_progress_handler(None, 0)
        return dict(status="upgraded" if previous == "legacy" else "created")
    except sqlite3.OperationalError as error:
        # Optional I/O, lock or cancellation failures are not query failures.
        # Invalid SQL/schema and programming errors must still reach the caller.
        code = getattr(error, "sqlite_errorcode", 0) & 0xFF
        if code not in (
            sqlite3.SQLITE_PERM,
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
            sqlite3.SQLITE_READONLY,
            sqlite3.SQLITE_INTERRUPT,
            sqlite3.SQLITE_IOERR,
            sqlite3.SQLITE_FULL,
            sqlite3.SQLITE_CANTOPEN,
        ):
            raise
        return dict(status="unavailable", detail=str(error))


class _IndexUpgrade:
    warning_names = ()

    def current(self, db):
        marker = db.execute(
            f"SELECT value FROM metadata WHERE key='{self.key}'"
        ).fetchone()
        return bool(marker and int(marker[0]) >= self.version)

    def run(self, path):
        uri = pathlib.Path(path).resolve().as_uri()
        with contextlib.closing(sqlite3.connect(uri + "?mode=ro", uri=True)) as db:
            if self.current(db):
                return
            row = db.execute("SELECT value FROM metadata WHERE key='trace'").fetchone()
            meta = json.loads(row[0]) if row else {}
            # Foreign/minimal query fixtures are not importer-owned caches.
            if not all(k in meta for k in ("path", "version", "counts")):
                return
        try:
            with contextlib.closing(
                sqlite3.connect(uri + "?mode=rw", uri=True, timeout=60)
            ) as db, db:
                db.execute("BEGIN IMMEDIATE")
                if self.current(db):
                    return
                meta = json.loads(
                    db.execute(
                        "SELECT value FROM metadata WHERE key='trace'"
                    ).fetchone()[0]
                )
                idx = Indexer(db)
                self.replay(db, idx, meta)
                meta["counts"][self.table] = db.execute(
                    f"SELECT count(*) FROM {self.table}"
                ).fetchone()[0]
                warnings = meta.setdefault("warnings", {})
                for name in tuple(warnings):
                    if (
                        name.startswith(self.warning_prefixes)
                        or name in self.warning_names
                    ):
                        warnings.pop(name)
                warnings.update(idx.warnings)
                db.execute(
                    "UPDATE metadata SET value=? WHERE key='trace'", (dumps(meta),)
                )
                db.execute(
                    f"INSERT OR REPLACE INTO metadata VALUES ('{self.key}',?)",
                    (str(self.version),),
                )
        except (sqlite3.Error, ValueError, KeyError, TypeError) as error:
            raise ValueError(
                self.label
                + "-index upgrade failed; the previous index was retained: "
                + str(error)
            ) from error


class _MessageUpgrade(_IndexUpgrade):
    key = "message_index_version"
    version = MESSAGE_INDEX_VERSION
    table = "messages"
    label = "Message"
    warning_prefixes = ("MPI receive ", "MPI send ")
    warning_names = ("MPI matched message length differs",)

    def replay(self, db, idx, meta):
        idx.resolution = int(meta.get("clock", {}).get("resolution", 1))
        if idx.resolution <= 0:
            raise ValueError("Invalid recorded trace clock resolution")
        for kind, ref, data in db.execute(
            "SELECT kind,ref,data FROM definitions WHERE kind IN ('Location','Comm','InterComm','Group')"
        ):
            idx.defs[kind][ref] = json.loads(data)
        db.execute("DELETE FROM messages")
        db.execute(
            "CREATE TABLE IF NOT EXISTS message_evidence(send_event INTEGER PRIMARY KEY,recv_event INTEGER,native_start REAL,native_end REAL,emitter TEXT,corrected INTEGER,emission_event INTEGER)"
        )
        if "emission_event" not in {
            row[1] for row in db.execute("PRAGMA table_info(message_evidence)")
        }:
            db.execute("ALTER TABLE message_evidence ADD COLUMN emission_event INTEGER")
        db.execute("DELETE FROM message_evidence")
        db.execute("CREATE INDEX IF NOT EXISTS coll_event ON collectives(event)")
        replay_kinds = MPI_MESSAGE_EVENTS + (
            "NonBlockingCollectiveRequest",
            "NonBlockingCollectiveComplete",
        )
        kinds = ",".join("?" for _ in replay_kinds)
        collective_requests = {}
        for eid, loc, t, kind, raw in db.execute(
            "SELECT id,location,time,kind,data FROM events WHERE kind IN ("
            + kinds
            + ") ORDER BY id",
            replay_kinds,
        ):
            data = json.loads(raw)
            if normalize_otf_message(data):
                db.execute("UPDATE events SET data=? WHERE id=?", (dumps(data), eid))
            if kind.startswith("NonBlockingCollective"):
                key = (idx.communicators.request_scope(loc), str(data["requestID"]))
                if kind == "NonBlockingCollectiveRequest":
                    collective_requests[key] = t
                else:
                    start = collective_requests.pop(key, t)
                    db.execute(
                        "UPDATE collectives SET start=? WHERE event=?", (start, eid)
                    )
            else:
                idx.mpi_event(loc, t, kind, data, eid)
        idx.finish_messages()
        idx.flush("messages")
        idx.flush("message_evidence")


class _RmaUpgrade(_IndexUpgrade):
    key = "rma_index_version"
    version = RMA_INDEX_VERSION
    table = "rma"
    label = "RMA"
    warning_prefixes = ("RMA ", "Unfinished RMA ")

    def replay(self, db, idx, meta):
        for kind, ref, data in db.execute(
            "SELECT kind,ref,data FROM definitions WHERE kind IN ('Location','LocationGroup','Comm','InterComm','Group','RmaWin')"
        ):
            idx.defs[kind][ref] = json.loads(data)
        db.execute(
            "CREATE TABLE IF NOT EXISTS rma_evidence(begin_event INTEGER PRIMARY KEY,completion_event INTEGER,completion_location TEXT,scope TEXT,native_source TEXT,native_target TEXT,matching_id TEXT,completion_kind TEXT)"
        )
        db.execute("DELETE FROM rma")
        db.execute("DELETE FROM rma_evidence")
        kinds = ",".join("?" for _ in RMA_EVENTS)
        for eid, loc, t, kind, raw in db.execute(
            "SELECT id,location,time,kind,data FROM events WHERE kind IN ("
            + kinds
            + ") ORDER BY id",
            RMA_EVENTS,
        ):
            idx.rma.event(loc, t, kind, json.loads(raw), eid)
        idx.rma.finish()
        idx.flush("rma")
        idx.flush("rma_evidence")


def ensure_message_index(path):
    """Upgrade old derived message rows atomically, using retained raw events."""
    _MessageUpgrade().run(path)


def ensure_rma_index(path):
    """Replay retained RMA records transactionally, preserving original events."""
    _RmaUpgrade().run(path)
