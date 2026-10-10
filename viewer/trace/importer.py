"""Streaming trace ingestion and exact interval accounting. Python stdlib only."""

import os
import pathlib
import sqlite3

from .indexer import Indexer
from .readers.otf1 import otf1_records
from .readers.otf2 import otf2_records
from .schema import SCHEMA


def import_trace(path, db_path, progress=lambda **kw: None):
    path = pathlib.Path(path).expanduser().resolve()
    temp = pathlib.Path(str(db_path) + ".partial")
    if temp.exists():
        temp.unlink()
    conn = sqlite3.connect(temp)
    conn.executescript(
        "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=MEMORY; PRAGMA cache_size=-64000;"
        + SCHEMA
    )
    idx = Indexer(conn, progress)
    initialized = False
    event = idx.event
    try:
        for record in (
            otf2_records(path) if path.suffix == ".otf2" else otf1_records(path)
        ):
            if record["record"] == "definition":
                idx.definition(record["kind"], record["data"])
            elif record["record"] == "marker":
                idx.marker(record["kind"], record["data"])
            else:
                if not initialized:
                    idx.initialize()
                    initialized = True
                event(record)
        meta = idx.finish(path)
        conn.close()
        os.replace(temp, db_path)
        return meta
    except BaseException:
        conn.close()
        temp.unlink(missing_ok=True)
        raise
