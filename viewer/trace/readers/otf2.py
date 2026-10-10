"""Streaming OTF2 records from the native reader process."""

import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[3]


def otf2_records(path):
    binary = ROOT / "native/build/otf2_reader"
    if not binary.exists():
        subprocess.run(["python3", str(ROOT / "native/build_reader.py")], check=True)
    # stderr is a file: a full diagnostics pipe must never block the reader.
    import tempfile

    with tempfile.TemporaryFile(mode="w+t") as errors:
        p = subprocess.Popen(
            [str(binary), str(path)],
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            bufsize=1 << 20,
        )
        try:
            # One decode per chunk of lines (one record each) amortizes the
            # per-call decoder overhead that dominates for small records.
            while lines := p.stdout.readlines(1 << 20):
                yield from json.loads("[" + ",".join(lines) + "]")
            code = p.wait()
            errors.seek(0)
            diagnostics = errors.read()
            if code:
                raise ValueError(f"OTF2 reader failed ({code}): {diagnostics[-4000:]}")
        finally:
            if p.poll() is None:
                p.terminate()
                p.wait()
            p.stdout.close()
