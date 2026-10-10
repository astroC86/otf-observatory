"""Expose recorded OTF2 clock correction evidence without correcting twice.

The global event reader already interpolates local ClockOffset records and
returns global ticks. A single offset record does not form a correction
interval in libOTF2; standardDeviation describes the calibration observation,
not a guaranteed bound on every interpolated event timestamp.
"""

from __future__ import annotations
import collections
import contextlib
import hashlib
import json
import pathlib
import re
import sqlite3
import subprocess
import tempfile

CLOCK_METADATA_VERSION = 1
ROOT = pathlib.Path(__file__).resolve().parents[2]
_CLOCK_KINDS = ("ClockOffset", "ReaderProperties")


def _definition_digest(rows):
    digest = hashlib.sha256()
    for kind, ref, data in rows:
        if kind in (*_CLOCK_KINDS, "ArchiveProperties"):
            continue
        value = json.loads(data) if isinstance(data, str) else data
        digest.update(
            json.dumps(
                [kind, str(ref), value],
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        )
        digest.update(b"\n")
    return digest.hexdigest()


def definitions_only_records(anchor, *, timeout=60, byte_limit=256 * 1024 * 1024):
    """Run our reader's metadata-only branch; no event files are opened.

    Temporary files bound Python memory and keep stderr from blocking stdout.
    The native process has a time limit and output is size-checked before parse.
    """
    binary = ROOT / "native/build/otf2_reader"
    if not binary.is_file():
        raise ValueError("The native OTF2 reader is not built")
    with tempfile.TemporaryFile(mode="w+t") as output, tempfile.TemporaryFile(
        mode="w+t"
    ) as errors:
        process = subprocess.run(
            [str(binary), "--definitions-only", str(anchor)],
            stdout=output,
            stderr=errors,
            timeout=timeout,
        )
        if process.returncode:
            errors.seek(0)
            raise ValueError("OTF2 definition reader failed: " + errors.read()[-4000:])
        if output.tell() > byte_limit:
            raise ValueError("OTF2 definition metadata exceeded the output limit")
        output.seek(0)
        for line in output:
            row = json.loads(line)
            if row.get("record") != "definition":
                raise ValueError("Metadata-only reader emitted a non-definition record")
            yield row


def ensure_clock_metadata(index_path):
    """Recover calibration definitions for a matching old cache, atomically.

    Only definition/provenance rows change. Existing event ticks, seconds and
    derived intervals are never replayed or shifted. A legacy cache's hash
    filename establishes its original source signature; foreign/renamed caches
    need an explicit stored source_signature rather than a guessed identity.
    """
    from ..trace.cache import signature

    path = pathlib.Path(index_path).resolve()
    uri = path.as_uri()
    unavailable = lambda reason, **extra: dict(
        status="unavailable", reason=reason, version=CLOCK_METADATA_VERSION, **extra
    )
    try:
        with contextlib.closing(sqlite3.connect(uri + "?mode=ro", uri=True)) as db:
            raw = db.execute("SELECT value FROM metadata WHERE key='trace'").fetchone()
            meta = json.loads(raw[0]) if raw else {}
            if meta.get("format") != "OTF2":
                return dict(status="not-applicable")
            marker = db.execute(
                "SELECT value FROM metadata WHERE key='clock_metadata_version'"
            ).fetchone()
            if marker and int(marker[0]) >= CLOCK_METADATA_VERSION:
                return dict(status="current", version=int(marker[0]))
            reader = db.execute(
                "SELECT data FROM definitions WHERE kind='ReaderProperties' LIMIT 1"
            ).fetchone()
            if reader and "localClockDefinitionsRetained" in json.loads(reader[0]):
                return dict(status="current", version=CLOCK_METADATA_VERSION)
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
            before = signature(anchor)
            if before != expected:
                return unavailable("archive-signature-mismatch")
            global_digest = _definition_digest(
                db.execute("SELECT kind,ref,data FROM definitions ORDER BY rowid")
            )
            trace_record = raw[0]
        counters = collections.Counter()
        clocks = []
        globals_hash = hashlib.sha256()
        reader = None
        for record in definitions_only_records(anchor):
            kind = record["kind"]
            data = record["data"]
            ref = str(data.get("self", counters[kind]))
            counters[kind] += 1
            if kind == "ClockOffset":
                clocks.append(
                    (
                        kind,
                        ref,
                        json.dumps(data, separators=(",", ":"), allow_nan=False),
                    )
                )
            elif kind == "ReaderProperties":
                reader = (
                    kind,
                    ref,
                    json.dumps(data, separators=(",", ":"), allow_nan=False),
                )
            elif kind != "ArchiveProperties":
                globals_hash.update(
                    json.dumps(
                        [kind, ref, data],
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode()
                )
                globals_hash.update(b"\n")
        if reader is None:
            return unavailable("reader-properties-missing")
        if globals_hash.hexdigest() != global_digest:
            return unavailable("archive-global-definitions-mismatch")
        if signature(anchor) != before:
            return unavailable("archive-changed-during-read")
        with contextlib.closing(
            sqlite3.connect(uri + "?mode=rw", uri=True, timeout=60)
        ) as db, db:
            db.execute("BEGIN IMMEDIATE")
            marker = db.execute(
                "SELECT value FROM metadata WHERE key='clock_metadata_version'"
            ).fetchone()
            if marker and int(marker[0]) >= CLOCK_METADATA_VERSION:
                return dict(status="current", version=int(marker[0]))
            if (
                db.execute("SELECT value FROM metadata WHERE key='trace'").fetchone()[0]
                != trace_record
            ):
                return unavailable("index-changed-during-read")
            if (
                _definition_digest(
                    db.execute("SELECT kind,ref,data FROM definitions ORDER BY rowid")
                )
                != global_digest
            ):
                return unavailable("index-definitions-changed-during-read")
            if signature(anchor) != before:
                return unavailable("archive-changed-before-commit")
            db.execute(
                "DELETE FROM definitions WHERE kind IN ('ClockOffset','ReaderProperties')"
            )
            db.executemany(
                "INSERT INTO definitions(kind,ref,data) VALUES(?,?,?)",
                [reader, *clocks],
            )
            db.executemany(
                "INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",
                [
                    ("clock_metadata_version", str(CLOCK_METADATA_VERSION)),
                    ("source_signature", before),
                ],
            )
        return dict(
            status="recovered",
            version=CLOCK_METADATA_VERSION,
            calibrationRecords=len(clocks),
            sourceSignature=before,
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


def clock_provenance(trace):
    reader = next(iter(trace.defs.get("ReaderProperties", {}).values()), {})
    retained = bool(reader.get("localClockDefinitionsRetained"))
    grouped = collections.defaultdict(list)
    for ref, row in trace.defs.get("ClockOffset", {}).items():
        grouped[str(row.get("location"))].append(dict(reference=str(ref), **row))
    locations = []
    for loc in trace.locations:
        samples = grouped.get(str(loc), [])
        intervals = []
        for first, last in zip(samples, samples[1:]):
            a, b = int(first["time"]), int(last["time"])
            if b <= a:
                continue
            intervals.append(
                dict(
                    startTick=str(a),
                    endTick=str(b),
                    offsetTicks=str(first["offset"]),
                    slope=(int(last["offset"]) - int(first["offset"])) / (b - a),
                    startStandardDeviation=first.get("standardDeviation"),
                    endStandardDeviation=last.get("standardDeviation"),
                )
            )
        state = (
            "recorded-linear-offsets"
            if intervals
            else (
                "single-offset-no-interval"
                if samples
                else "no-local-offsets" if retained else "provenance-unavailable"
            )
        )
        locations.append(
            dict(location=str(loc), status=state, samples=samples, intervals=intervals)
        )
    format = str(getattr(trace, "meta", {}).get("format", "")).upper()
    domain = (
        "OTF2 global ticks normalized by ClockProperties"
        if reader or format == "OTF2"
        else (
            "OTF1 recorded ticks normalized by timer resolution"
            if format in ("OTF", "OTF1")
            else "Indexed trace timestamps; decoder provenance unavailable"
        )
    )
    return dict(
        eventTimeDomain=domain,
        correctionsApplied=reader.get("clockOffsetsApplied"),
        localDefinitionsRetained=retained,
        locations=locations,
        interpolation="Binary64 slope between successive offsets; nearest-even integer tick correction. First/last interval extrapolates beyond its calibration endpoints.",
        additionalDeviceClockAdjustment=False,
        uncertainty="Recorded calibration standard deviations are observations, not hard event-time error bounds.",
        recovery=getattr(trace, "clock_metadata_status", None),
    )
