"""Trace registration and serialized background indexing for the HTTP server."""

import concurrent.futures
import hashlib
import pathlib
import threading
import traceback

from viewer.trace.cache import signature
from viewer.trace.importer import import_trace
from viewer.trace.query import Trace

from . import runtime


class Store:
    def __init__(self, paths):
        self.jobs = {}
        self.traces = {}
        self.paths = {}
        self.lock = threading.RLock()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.uploads = {}
        for p in paths:
            self.register(p)

    def register(self, path):
        p = pathlib.Path(path).expanduser().resolve()
        if not p.is_file() or p.suffix not in (".otf", ".otf2"):
            raise ValueError("Select an existing .otf2 or .otf anchor file")
        ident = hashlib.sha256(str(p).encode()).hexdigest()[:16]
        self.paths[ident] = p
        return ident

    def listing(self):
        return [
            dict(
                id=ident,
                path=str(path),
                name=f"{path.parent.name}/{path.name}",
                format=path.suffix[1:].upper(),
                loaded=ident in self.traces,
                job=self.jobs.get(ident),
            )
            for ident, path in list(self.paths.items())
        ]

    def open(self, path=None, ident=None):
        with self.lock:
            if path:
                ident = self.register(path)
            if ident not in self.paths:
                raise ValueError("Trace not found")
            if ident in self.traces:
                return dict(id=ident, state="ready")
            if self.jobs.get(ident, {}).get("state") in ("queued", "loading"):
                return dict(self.jobs[ident], id=ident)
            self.jobs[ident] = dict(
                state="queued", phase="Waiting to index", events=0, cancel=False
            )
            self.pool.submit(self.load, ident)
            return dict(id=ident, **self.jobs[ident])

    def load(self, ident):
        path = self.paths[ident]
        job = self.jobs[ident]
        try:
            job.update(state="loading", phase="Reading definitions")
            target = runtime.CACHE / (signature(path) + ".sqlite")

            def progress(**kw):
                if job.get("cancel"):
                    raise ValueError("Import cancelled")
                job.update(kw)

            if not target.exists():
                import_trace(path, target, progress)
            trace = Trace(target)
            job.update(phase="Preparing interval columns")
            trace.columns()
            self.traces[ident] = trace
            job.update(
                state="ready", phase="Ready", events=trace.meta["counts"]["events"]
            )
        except Exception as e:
            job.update(state="error", error=str(e))
            traceback.print_exc()

    def trace(self, ident):
        if ident not in self.traces:
            raise ValueError("Trace is not loaded")
        return self.traces[ident]
