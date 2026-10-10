"""Explicit, transactional recovery of the OTF2 reference allocator seed.

Usage: python -m viewer.metrics.attribute_metadata CACHE.sqlite [...]
Trace startup requests creator recovery only for older indexes whose recorded
OMPT declarations require producer identification. Other recovery is explicit.
Only our libOTF2-based definitions-only reader is run; existing event/definition
records remain in their original order.
"""

import collections
import contextlib
import hashlib
import json
import pathlib
import re
import sqlite3
import subprocess

from ..gpu.clocks import ROOT, _definition_digest, definitions_only_records

VERSION = 1


def _valid(data):
    return all(
        isinstance(data.get(key), int)
        and not isinstance(data[key], bool)
        and 0 <= data[key] < bound
        for key, bound in (("numberOfLocations", 2**64), ("major", 256))
    )


def recover_attribute_reference_metadata(index_path, *, require_creator=False):
    """Verify the source and global definitions, then recover ArchiveProperties."""
    from ..trace.cache import signature

    path = pathlib.Path(index_path).resolve()
    unavailable = lambda reason, **extra: dict(
        status="unavailable", reason=reason, version=VERSION, **extra
    )
    try:
        with contextlib.closing(
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        ) as db:
            raw = db.execute("SELECT value FROM metadata WHERE key='trace'").fetchone()
            meta = json.loads(raw[0]) if raw else {}
            if meta.get("format") != "OTF2":
                return dict(status="not-applicable")
            archives = list(
                db.execute(
                    "SELECT rowid,data FROM definitions WHERE kind='ArchiveProperties' ORDER BY rowid"
                )
            )
            if archives and all(
                _valid(data := json.loads(row[1]))
                and (not require_creator or isinstance(data.get("creator"), str))
                for row in archives
            ):
                return dict(status="current", version=VERSION)
            original = db.execute(
                "SELECT value FROM metadata WHERE key='source_signature'"
            ).fetchone()
            expected = (
                original[0]
                if original
                else path.stem if re.fullmatch("[0-9a-f]{20}", path.stem) else None
            )
            if expected is None:
                return unavailable("original-source-signature-unavailable")
            anchor = pathlib.Path(meta.get("path", ""))
            if not anchor.is_file():
                return unavailable("archive-unavailable")
            source_signature = signature(anchor)
            if source_signature != expected:
                return unavailable("archive-signature-mismatch")
            definition_digest = _definition_digest(
                db.execute("SELECT kind,ref,data FROM definitions ORDER BY rowid")
            )
            trace_record = raw[0]
        counters = collections.Counter()
        fresh = []
        archive = None
        for row in definitions_only_records(anchor):
            kind, data = row["kind"], row["data"]
            ref = str(data.get("self", counters[kind]))
            counters[kind] += 1
            if kind == "ArchiveProperties":
                if archive is not None:
                    return unavailable("multiple-reader-archive-properties")
                archive = data
            fresh.append((kind, ref, data))
        if archive is None or not _valid(archive):
            return unavailable("reader-archive-properties-missing")
        if require_creator and not isinstance(archive.get("creator"), str):
            return unavailable("reader-archive-creator-missing")
        if _definition_digest(fresh) != definition_digest:
            return unavailable("archive-global-definitions-mismatch")
        if signature(anchor) != source_signature:
            return unavailable("archive-changed-during-read")
        provenance = dict(
            version=VERSION,
            sourceSignature=source_signature,
            globalDefinitionSha256=definition_digest,
            readerSha256=hashlib.sha256(
                (ROOT / "native/build/otf2_reader").read_bytes()
            ).hexdigest(),
            method="OTF2_Reader_GetVersion, OTF2_Reader_GetNumberOfLocations and OTF2_Reader_GetCreator; definitions-only",
            archiveProperties=archive,
        )
        encoded = json.dumps(archive, separators=(",", ":"), allow_nan=False)
        with contextlib.closing(
            sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=60)
        ) as db, db:
            db.execute("BEGIN IMMEDIATE")
            if (
                db.execute("SELECT value FROM metadata WHERE key='trace'").fetchone()[0]
                != trace_record
            ):
                return unavailable("index-changed-during-read")
            if (
                _definition_digest(
                    db.execute("SELECT kind,ref,data FROM definitions ORDER BY rowid")
                )
                != definition_digest
            ):
                return unavailable("index-definitions-changed-during-read")
            if signature(anchor) != source_signature:
                return unavailable("archive-changed-before-commit")
            current = list(
                db.execute(
                    "SELECT rowid,data FROM definitions WHERE kind='ArchiveProperties' ORDER BY rowid"
                )
            )
            if current != archives:
                return unavailable("index-archive-properties-changed-during-read")
            if current:
                # Keep metadata row positions; never delete/reinsert actual
                # definitions or normalize away duplicate recorded definitions.
                db.execute(
                    "UPDATE definitions SET data=? WHERE kind='ArchiveProperties'",
                    (encoded,),
                )
            else:
                db.execute(
                    "INSERT INTO definitions(kind,ref,data) VALUES('ArchiveProperties','0',?)",
                    (encoded,),
                )
            db.executemany(
                "INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                [
                    (
                        "attribute_reference_metadata",
                        json.dumps(provenance, separators=(",", ":")),
                    ),
                    ("source_signature", source_signature),
                ],
            )
        return dict(
            status="recovered",
            version=VERSION,
            **{
                key: provenance[key]
                for key in (
                    "sourceSignature",
                    "globalDefinitionSha256",
                    "readerSha256",
                    "archiveProperties",
                )
            },
        )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        sqlite3.Error,
        subprocess.TimeoutExpired,
    ) as error:
        return unavailable("metadata-recovery-failed", detail=str(error))


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("indexes", nargs="+", type=pathlib.Path)
    parser.add_argument(
        "--creator",
        action="store_true",
        help="Also recover the recorded archive creator when absent",
    )
    args = parser.parse_args()
    failed = False
    for path in args.indexes:
        result = recover_attribute_reference_metadata(
            path, require_creator=args.creator
        )
        print(json.dumps(dict(index=str(path), **result), sort_keys=True))
        failed |= result["status"] == "unavailable"
    raise SystemExit(int(failed))


if __name__ == "__main__":
    main()
