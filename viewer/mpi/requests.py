"""Process-scoped MPI request generations and completion observations."""

from __future__ import annotations

import collections
import dataclasses
import json

from .communicators import Communicators
from .wait_models import Span, TEST

REQUEST_KINDS = (
    "MpiIsend",
    "MpiIrecvRequest",
    "MpiIsendComplete",
    "MpiIrecv",
    "MpiImrecvRequest",
    "MpiImrecv",
    "MpiRequestTest",
    "MpiRequestCancelled",
    "NonBlockingCollectiveRequest",
    "NonBlockingCollectiveComplete",
)
_INITIATION_KINDS = {
    "MpiIsend": "send",
    "MpiIrecvRequest": "receive",
    "MpiImrecvRequest": "matched-receive",
    "NonBlockingCollectiveRequest": "collective",
}
_COMPLETION_KINDS = {
    "MpiIsendComplete": "send",
    "MpiIrecv": "receive",
    "MpiImrecv": "matched-receive",
    "NonBlockingCollectiveComplete": "collective",
}
# Matched-receive records name their handle field differently.
_ID_PATH = "CASE WHEN kind IN ('MpiImrecvRequest','MpiImrecv') THEN '$.requestId' ELSE '$.requestID' END"


@dataclasses.dataclass(slots=True)
class Request:
    location: str
    request: str
    generation: int
    kind: str
    start: float | None = None
    end: float | None = None
    status: str = ""
    tests: int = 0
    initiation_event: int | None = None
    completion_event: int | None = None
    completion_span: Span | None = None
    last_test: float | None = None
    ambiguous: bool = False
    completion_location: str | None = None


def _requests(trace, lookup, diagnostics):
    pending = {}
    generations = collections.Counter()
    requests = []
    tests = {}
    resolver = Communicators(trace.defs)
    scopes = {}  # A local memo saves ~10% of this scan over request_scope().
    marks = ",".join("?" for _ in REQUEST_KINDS)
    with trace.connect() as db:
        cursor = db.cursor()
        cursor.row_factory = None
        for event, loc, time, kind, id_type, value in cursor.execute(
            f"SELECT id,location,time,kind,json_type(data,{_ID_PATH}),json_extract(data,{_ID_PATH}) FROM events WHERE kind IN ("
            + marks
            + ") ORDER BY id",
            REQUEST_KINDS,
        ):
            if id_type is None:
                diagnostics["request_without_id"] += 1
                continue
            if id_type == "integer" and type(value) is int:
                ident = str(value)
            else:
                # SQLite turns integers beyond int64 into reals and booleans into
                # integers; keep Python's spelling of those rare identifiers.
                sql = "SELECT data FROM events WHERE id=?"
                data = json.loads(db.execute(sql, (event,)).fetchone()[0])
                field = (
                    "requestId"
                    if kind in ("MpiImrecvRequest", "MpiImrecv")
                    else "requestID"
                )
                ident = str(data[field])
            scope = scopes.get(loc)
            if scope is None:
                scope = scopes[loc] = resolver.request_scope(loc)
            key = (scope, ident)
            initiated = _INITIATION_KINDS.get(kind)
            if initiated is not None:
                reused = key in pending
                if reused:
                    old = pending.pop(key)
                    old.status = "reused-before-completion"
                    old.end = time
                    diagnostics["request_reused_while_active"] += 1
                generation = generations[key] = generations.get(key, 0) + 1
                request = Request(
                    loc,
                    ident,
                    generation,
                    initiated,
                    start=time,
                    status="pending-at-trace-end",
                    initiation_event=event,
                    ambiguous=reused,
                )
                pending[key] = request
                requests.append(request)
                continue
            if kind == "MpiRequestTest":
                request = pending.get(key)
                if request:
                    request.tests += 1
                    request.last_test = time
                else:
                    diagnostics["request_test_without_initiation"] += 1
                span = lookup.at(loc, time, TEST, event=event)
                if span:
                    item = tests.setdefault(span.id, [span, 0, []])
                    item[1] += 1
                    if len(item[2]) < 16:
                        item[2].append(event)
                continue
            expected = _COMPLETION_KINDS.get(kind)
            request = pending.get(key)
            span = lookup.at(loc, time, event=event)
            # The reference reader checks both ID and request type before consuming
            # the pending operation (0x10d117d..0x10d1187). An inconsistent
            # completion must not destroy a valid request of another type.
            if request is not None and expected and request.kind != expected:
                diagnostics["request_type_mismatch"] += 1
                requests.append(
                    Request(
                        loc,
                        ident,
                        request.generation,
                        expected,
                        end=time,
                        status="type-mismatch",
                        completion_event=event,
                        completion_span=span,
                    )
                )
                continue
            request = pending.pop(key, None)
            if request is None:
                diagnostics["completion_without_initiation"] += 1
                generations[key] += 1
                request = Request(loc, ident, generations[key], "unknown")
                requests.append(request)
            request.end = time
            request.completion_event = event
            request.completion_span = span
            request.completion_location = loc
            if kind == "MpiRequestCancelled":
                request.status = "cancelled"
            elif kind == "MpiIsendComplete" and span and span.routine == "request_free":
                request.status = "released-completion-unknown"
                diagnostics["send_request_released"] += 1
            elif kind == "MpiIsendComplete" and span is None:
                request.status = "completion-or-release"
                diagnostics["send_completion_without_routine"] += 1
            elif request.ambiguous:
                request.status = "ambiguous-reuse"
            else:
                request.status = (
                    "completed" if request.start is not None else "orphan-completion"
                )
    return requests, tests
