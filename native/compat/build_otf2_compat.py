#!/usr/bin/env python3
"""Build the narrowly extended OTF2 3.1 reader library from an offline archive.

No downloads, system installation, or execution of proprietary software. See
docs/otf2-matched-probe.md for wire-layout evidence and capability boundaries.
"""

import argparse
import hashlib
import json
import pathlib
import subprocess
import tarfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
ARCHIVE_SHA256 = "09dff2eda692486b88ad5ee189bbc9d7ebc1f17c863108c44ccf9631badbada4"
EVENTS = ["MpiProbe", "MpiMrecv", "MpiImrecvRequest", "MpiImrecv"]


def run_build_command(command, build_dir, cache, stage):
    """Never let an omitted/misdirected cwd generate files in the workspace."""
    build_dir, cache = pathlib.Path(build_dir).resolve(), pathlib.Path(cache).resolve()
    if (
        build_dir == ROOT.resolve()
        or build_dir.parent != cache
        or not build_dir.name.startswith("build-")
    ):
        raise ValueError(
            "Build commands require a private build-* directory under the compatibility cache."
        )
    log = cache / (stage + ".log")
    with log.open("w") as output:
        result = subprocess.run(
            command, cwd=build_dir, stdout=output, stderr=subprocess.STDOUT
        )
    if result.returncode:
        raise RuntimeError(
            stage + " failed; see " + str(log) + "\n" + log.read_text()[-4000:]
        )


def build(archive, jobs=2):
    archive = pathlib.Path(archive).expanduser().resolve()
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError(
            "Expected the reviewed OTF2 3.1 source archive; SHA-256 differs."
        )
    patch = ROOT / "native/compat/otf2-3.1-matched-probe.patch"
    patch_hash = hashlib.sha256(patch.read_bytes()).hexdigest()
    cache = ROOT / ".cache/otf2-compat"
    install = cache / "install"
    marker = install / "viewer-capabilities.json"
    if (
        marker.exists()
        and json.loads(marker.read_text()).get("patchSha256") == patch_hash
    ):
        return install
    source = cache / ("source-" + patch_hash[:12])
    source.mkdir(parents=True, exist_ok=True)
    # The exact archive is hashed above; data filtering also rejects unsafe paths.
    with tarfile.open(archive) as contents:
        contents.extractall(source, filter="data")
    source = source / "otf2-3.1"
    subprocess.run(
        ["patch", "-p1", "--batch", "--forward", "-i", str(patch)],
        cwd=source,
        check=True,
    )
    build_dir = cache / ("build-" + patch_hash[:12])
    build_dir.mkdir(exist_ok=True)

    def run(command, stage):
        run_build_command(command, build_dir, cache, stage)

    run(
        [
            str(source / "configure"),
            "--prefix=" + str(install),
            "--disable-shared",
            "--enable-static",
            "--without-sionlib",
        ],
        "configure",
    )
    run(["make", "-j" + str(max(1, min(16, jobs)))], "build")
    run(["make", "install"], "install")
    # The upstream library version remains 3.1. These are specific extensions,
    # not a claim of implementing every addition to the OTF2 3.2 specification.
    marker.write_text(
        json.dumps(
            dict(
                baseVersion="3.1",
                extension="matched-probe-wire-records",
                typedEvents=EVENTS,
                archiveSha256=ARCHIVE_SHA256,
                patchSha256=patch_hash,
            ),
            indent=2,
        )
        + "\n"
    )
    return install


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", help="Local otf2-3.1.tar.gz source archive")
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    print(build(args.archive, args.jobs))
