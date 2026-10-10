"""Import index builds, with large R-tree fills in worker processes.

R-tree fills are about half of an import's index build. Concurrent SQLite
connections in one process measured about twice as slow (they share SQLite's
allocator), so a large R-tree is filled by a separate Python process in a
scratch database next to the import, while the import connection builds the
B-tree indexes. An R-tree's content is its shadow tables (%_node, %_rowid,
%_parent): the same rows in the same order produce the same nodes, which are
then copied into the empty virtual table. Any worker failure falls back to the
in-process fill.

Worker usage: python -m viewer.trace.interval_index SCRATCH RTREE
"""

import contextlib
import pathlib
import sqlite3
import subprocess
import sys

from .schema import INDEX_OBJECTS, INTERVAL_FILL, INTERVAL_INDEX, INTERVAL_INDEXES

ROOT = pathlib.Path(__file__).resolve().parents[2]
# Below this many rows, starting a worker costs more than the fill itself.
WORKER_ROWS = 100_000


def fill(scratch, rtree):
    """Worker: build RTREE from the (id,start,end) rows of the scratch table source."""
    with contextlib.closing(sqlite3.connect(scratch)) as db:
        db.executescript(
            "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-64000;"
            + INTERVAL_INDEX.format(rtree)
            + INTERVAL_FILL.format(rtree, "source")
        )


def _start(db, scratch, rtree, table):
    """Copy TABLE's interval rows to SCRATCH and start filling RTREE there."""
    scratch.unlink(missing_ok=True)
    # The node size follows the page size; it must match the import's.
    page_size = db.execute("PRAGMA main.page_size").fetchone()[0]
    db.execute("ATTACH ? AS scratch", (str(scratch),))
    try:
        db.executescript(
            f"PRAGMA scratch.page_size={page_size};"
            "PRAGMA scratch.journal_mode=OFF; PRAGMA scratch.synchronous=OFF;"
            f"CREATE TABLE scratch.source AS SELECT id,start,end FROM main.{table};"
        )
    finally:
        db.execute("DETACH scratch")
    return subprocess.Popen(
        [sys.executable, "-m", __name__, str(scratch), rtree], cwd=ROOT
    )


def build_indexes(db):
    """executescript(INDEXES) on an import connection, filling large R-trees in workers."""
    path = db.execute("PRAGMA database_list").fetchone()[2]
    workers = {}
    try:
        for rtree, table in INTERVAL_INDEXES:
            rows = db.execute(f"SELECT max(rowid) FROM {table}").fetchone()[0] or 0
            if path and rows >= WORKER_ROWS:
                scratch = pathlib.Path(f"{path}.{rtree}")
                try:
                    workers[rtree] = _start(db, scratch, rtree, table), scratch
                except (OSError, sqlite3.Error):
                    scratch.unlink(missing_ok=True)
        db.executescript(INDEX_OBJECTS)
        for rtree, table in INTERVAL_INDEXES:
            process, scratch = workers.get(rtree, (None, None))
            if process is not None and process.wait() == 0:
                db.execute("ATTACH ? AS scratch", (str(scratch),))
                for shadow in ("node", "rowid", "parent"):
                    db.execute(f"DELETE FROM main.{rtree}_{shadow}")
                    db.execute(
                        f"INSERT INTO main.{rtree}_{shadow} SELECT * FROM scratch.{rtree}_{shadow}"
                    )
                db.commit()
                db.execute("DETACH scratch")
            else:
                db.execute(INTERVAL_FILL.format(rtree, table))
                db.commit()
    finally:
        for process, scratch in workers.values():
            process.kill()  # no-op once the worker has exited
            process.wait()
            scratch.unlink(missing_ok=True)


if __name__ == "__main__":
    fill(*sys.argv[1:])
