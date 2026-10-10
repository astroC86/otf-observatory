"""Loopback-only HTTP requests, API routing, uploads, and static responses."""

import importlib
import json
import mimetypes
import os
import pathlib
import secrets
import tempfile
import traceback
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from viewer.alignment.comparison import comparison, comparison_many
from viewer.trace.encoding import dumps, js_safe

from . import runtime
from .response_cache import ResponseCache
from .store import Store

# Encoded trace responses; keyed by the index file identity so reused trace ids never collide.
RESPONSES = ResponseCache(256 << 20)
TRACE_QUERIES = (
    "summary",
    "processes",
    "calltree",
    "timeline",
    "overview",
    "messages",
    "events",
    "definitions",
    "counters",
    "markers",
    "derived",
)
QUERY_ROUTES = {
    "marker-options": ("alignment.markers", "marker_options"),
    "waits": ("mpi.waits", "waits"),
    "wait-cause": ("causality.context", "wait_cause"),
    "synchronization": ("threads.synchronization", "synchronization"),
    "gpu/idle": ("gpu.idle_summary", "idle_summary"),
    "messages/summary": ("messages.summary", "native_message_summary"),
    "messages/matrix": ("messages.matrix", "native_communication_matrix"),
    "messages/timeline": ("messages.timeline", "native_message_timeline"),
    "dependencies": ("dependencies", "dependencies"),
    "gpu": ("dependencies", "gpu"),
}


def _cache_key(trace, method, q):
    """Identity of an immutable index response, or None when there is no index file."""
    path = getattr(trace, "path", None)
    if path is None:
        return None
    index = os.stat(path)
    return (
        str(path),
        index.st_mtime_ns,
        index.st_size,
        method,
        tuple(sorted(q.items())),
    )


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    disable_nagle_algorithm = True
    store: Store

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def valid_request(self):
        # A loopback bind alone does not prevent a hostile DNS name from rebinding.
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1:
            return self.reject("A single loopback Host header is required", 403)
        host = hosts[0]
        try:
            parsed = urlparse("//" + host)
            valid = (
                parsed.hostname in ("localhost", "127.0.0.1", "::1")
                and (parsed.port or 80) == self.server.server_port
            )
            valid = valid and not any(
                (
                    parsed.username,
                    parsed.password,
                    parsed.path,
                    parsed.query,
                    parsed.fragment,
                )
            )
        except ValueError:
            valid = False
        if not valid:
            return self.reject("Only the local server address is allowed", 403)
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if (
                parsed.scheme != "http"
                or parsed.netloc.lower() != host.lower()
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                return self.reject("Cross-origin requests are disabled", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            return self.reject("Cross-site requests are disabled", 403)
        return True

    def reject(self, message, code=400):
        self.close_connection = True
        self.send(dict(error=message), code)
        return False

    def log_message(self, fmt, *args):
        if args and ("/api/status" in str(args[0]) or "/api/traces" in str(args[0])):
            return
        super().log_message(fmt, *args)

    @staticmethod
    def trace_query(trace, method, q):
        """Single-trace API result, or None for an unknown method."""
        if method == "span":
            return trace.span(int(q["span"]))
        if method in ("collectives", "io", "rma"):
            return trace.operations(q, method)
        if method == "metric/presets":
            from viewer.metrics.presets import presets

            return presets(trace, q.get("paradigm"))
        if method == "metric/attributes":
            from viewer.metrics.engine import attribute_catalog

            return attribute_catalog(trace)
        if method in QUERY_ROUTES:
            module, function = QUERY_ROUTES[method]
            return getattr(importlib.import_module("viewer." + module), function)(
                trace, q
            )
        if method in TRACE_QUERIES:
            return getattr(trace, method)(q)
        return None

    def send(self, body, code=200, content_type="application/json"):
        if not isinstance(body, bytes):
            body = dumps(js_safe(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        if self.close_connection:
            self.send_header("Connection", "close")
        embedded = urlparse(self.path).path == "/" and parse_qs(
            urlparse(self.path).query
        ).get("embed") == ["1"]
        ancestors = "'self'" if embedded else "'none'"
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; frame-ancestors "
            + ancestors,
        )
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        try:
            if not self.valid_request():
                return
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            path = url.path
            if path == "/api/traces":
                return self.send(self.store.listing())
            if path == "/api/status":
                return self.send(
                    self.store.jobs.get(q.get("id"), dict(state="unknown"))
                )
            if path == "/api/health":
                return self.send(dict(ok=True, offline=True))
            if path == "/api/metric/capabilities":
                from viewer.metrics.engine import capabilities

                return self.send(capabilities())
            if path.startswith("/api/"):
                trace = self.store.trace(q.pop("id", ""))
                method = path[5:]
                if method == "compare":
                    other = self.store.trace(q.pop("other", ""))
                    shift = float(q.pop("shift", 0))
                    scale = float(q.pop("scale", 1))
                    return self.send(comparison(trace, other, q, shift, scale))
                if method == "align":
                    from viewer.alignment.runs import align

                    return self.send(
                        align(trace, self.store.trace(q.pop("other", "")), q)
                    )
                if method == "meta":  # mutable in-memory metadata; never cached
                    return self.send(trace.meta)
                key = _cache_key(trace, method, q)
                body = RESPONSES.get(key) if key else None
                if body is None:
                    result = self.trace_query(trace, method, q)
                    if result is None:
                        return self.send(dict(error="Unknown API"), 404)
                    body = dumps(js_safe(result)).encode()
                    if key:
                        RESPONSES.put(key, body)
                return self.send(body)
            target = (
                runtime.ROOT
                / "web"
                / ("index.html" if path == "/" else path.lstrip("/"))
            ).resolve()
            if not target.is_relative_to(runtime.ROOT / "web") or not target.is_file():
                return self.send(dict(error="Not found"), 404)
            return self.send(
                target.read_bytes(),
                content_type=mimetypes.guess_type(target.name)[0]
                or "application/octet-stream",
            )
        except (ValueError, KeyError, TypeError, OverflowError) as e:
            self.send(dict(error=str(e)), 400)
        except Exception as e:
            traceback.print_exc()
            self.send(dict(error=str(e)), 500)

    def do_POST(self):
        try:
            if not self.valid_request():
                return
            if self.headers.get("Transfer-Encoding"):
                return self.reject("Transfer-Encoding is not supported")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) > 1:
                return self.reject("A single Content-Length header is required")
            length = int(lengths[0]) if lengths else 0
            if length < 0:
                return self.reject("Content-Length must not be negative")
            url = urlparse(self.path)
            path = url.path
            if path == "/api/upload/file":
                q = {k: v[-1] for k, v in parse_qs(url.query).items()}
                folder = self.store.uploads.get(q.get("token"))
                if folder is None:
                    raise ValueError("Unknown upload")
                target = (folder / q["path"]).resolve()
                if not target.is_relative_to(folder) or target == folder:
                    raise ValueError("Invalid file path")
                if length > 4 * 1024**3:
                    return self.reject("Each uploaded file must be at most 4 GiB", 413)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=target.parent, prefix=".upload-", delete=False
                    ) as f:
                        temporary = pathlib.Path(f.name)
                        left = length
                        while left:
                            b = self.rfile.read(min(left, 1 << 20))
                            if not b:
                                raise ValueError("Incomplete upload")
                            f.write(b)
                            left -= len(b)
                    os.replace(temporary, target)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
                return self.send(dict(ok=True))
            if length > 2_000_000:
                return self.reject("Request too large", 413)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete request body")
            data = json.loads(body or b"{}")
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            if path == "/api/metric/evaluate":
                from viewer.metrics.engine import evaluate

                return self.send(evaluate(self.store.trace(data.pop("id", "")), data))
            if path == "/api/align-many":
                from viewer.alignment.runs import align_many

                ids = data.pop("ids", None)
                baseline = data.get("baseline", data.pop("id", ""))
                if (
                    not isinstance(ids, list)
                    or not 2 <= len(ids) <= 16
                    or any(not isinstance(i, str) for i in ids)
                ):
                    raise ValueError("Select between 2 and 16 trace IDs")
                if len(set(ids)) != len(ids) or baseline not in ids:
                    raise ValueError(
                        "Trace IDs must be distinct and include the baseline"
                    )
                data["baseline"] = baseline
                return self.send(
                    align_many({ident: self.store.trace(ident) for ident in ids}, data)
                )
            if path == "/api/compare-many":
                ident = data.pop("id", "")
                mappings = data.pop("mappings", None)
                return self.send(
                    comparison_many(
                        self.store.trace(ident), ident, mappings, data, self.store.trace
                    )
                )
            if path in ("/api/align-markers", "/api/compare-offsets"):
                from viewer.alignment.markers import align_markers, compare_offsets

                baseline = data.pop("baseline", data.pop("id", ""))
                runs = data.pop("runs", None)
                return self.send(
                    align_markers(runs, self.store.trace, baseline)
                    if path == "/api/align-markers"
                    else compare_offsets(runs, self.store.trace, baseline, data)
                )
            if path == "/api/compare":
                trace = self.store.trace(data.pop("id", ""))
                other = self.store.trace(data.pop("other", ""))
                return self.send(
                    comparison(
                        trace,
                        other,
                        data,
                        float(data.pop("shift", 0)),
                        float(data.pop("scale", 1)),
                        data.pop("anchors", None),
                    )
                )
            if path == "/api/open":
                return self.send(self.store.open(data.get("path"), data.get("id")))
            if path == "/api/cancel":
                if data["id"] in self.store.jobs:
                    self.store.jobs[data["id"]]["cancel"] = True
                return self.send(dict(ok=True))
            if path == "/api/upload/start":
                token = secrets.token_hex(16)
                folder = (runtime.CACHE / "uploads" / token).resolve()
                folder.mkdir(parents=True)
                self.store.uploads[token] = folder
                return self.send(dict(token=token))
            if path == "/api/upload/finish":
                folder = self.store.uploads.get(data["token"])
                if folder is None:
                    raise ValueError("Unknown upload")
                anchor = (folder / data["anchor"]).resolve()
                if not anchor.is_relative_to(folder):
                    raise ValueError("Invalid anchor path")
                return self.send(self.store.open(str(anchor)))
            return self.send(dict(error="Unknown API"), 404)
        except (ValueError, KeyError, TypeError, TimeoutError, OverflowError) as e:
            self.reject(str(e), 400)
        except Exception as e:
            traceback.print_exc()
            self.send(dict(error=str(e)), 500)
