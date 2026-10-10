"""Shared filesystem paths and the server's import-time initialization."""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache"


def initialize():
    CACHE.mkdir(exist_ok=True)
    if not (ROOT / "native/build/otf2_reader").exists():
        from native.build_reader import build

        build()
