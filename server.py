#!/usr/bin/env python3
"""Offline OTF/OTF2 analysis server. Bind to loopback; open its UI in any browser."""

import argparse
import pathlib
from http.server import ThreadingHTTPServer

from viewer.http import runtime

runtime.initialize()
from viewer.http import handler, store

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--trace", action="append", default=[])
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args()
    paths = [
        p
        for p in runtime.ROOT.rglob("*")
        if p.suffix in (".otf2", ".otf")
        and (".cache" not in p.parts or p.is_relative_to(runtime.CACHE / "uploads"))
    ]
    energy = pathlib.Path.home() / "energy/run-396831/trace/traces.otf2"
    if energy.exists():
        paths.insert(0, energy)
    paths = list(
        dict.fromkeys([pathlib.Path(p).expanduser() for p in args.trace] + paths)
    )
    handler.Handler.store = store.Store(paths)
    if args.index_only:
        for p in paths:
            handler.Handler.store.open(str(p))
        handler.Handler.store.pool.shutdown(wait=True)
        if any(j["state"] == "error" for j in handler.Handler.store.jobs.values()):
            raise SystemExit(1)
    else:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler.Handler)
        print(f"OTF Observatory: http://127.0.0.1:{args.port}", flush=True)
        print("All processing is local. Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()
            handler.Handler.store.pool.shutdown(wait=False, cancel_futures=True)
