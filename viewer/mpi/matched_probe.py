"""Conditional matched-probe correlations from retained OTF2 wire records.

The four event layouts are verified, but this installation has no independent
3.2 producer contract for messageId scope. Consequently even a unique lifecycle
is a candidate, never a required causal edge or a native message-index row.
"""

from __future__ import annotations

import collections
import json
import math

from ..causality.operations import operation, prerequisite
from .communicators import Communicators

KINDS = ("MpiProbe", "MpiMrecv", "MpiImrecvRequest", "MpiImrecv")
LIMIT = 200_000
SEND_LIMIT = 1_000_000
CANDIDATE_LIMIT = 16
SCOPE = "Equal identifiers are compared within a recorded process/location group; producer message-handle scope is unverified."


def _episode(ident, data, status):
    return dict(
        id="matched-probe:" + str(ident),
        messageId=str(data["messageId"]) if "messageId" in data else None,
        generation=None,
        status=status,
        scopeAssumption=SCOPE,
        probe=None,
        receive=None,
        completion=None,
        request=None,
        sendCandidates=[],
        candidateCount=0,
        unresolvedReasons=[],
    )


def analyze(trace, lookup, requests, records, diagnostics, continuity=None):
    event_types = trace.meta.get("eventTypes")
    if event_types is not None and not any(event_types.get(k, 0) for k in KINDS):
        return []
    with trace.connect() as db:
        rows = db.execute(
            "SELECT id,location,time,kind,data FROM events WHERE kind IN ('MpiProbe','MpiMrecv','MpiImrecvRequest','MpiImrecv') ORDER BY id LIMIT ?",
            (LIMIT + 1,),
        ).fetchall()
    if not rows:
        return []
    if len(rows) > LIMIT:
        diagnostics["matched_probe_context_limit"] += 1
        # An omitted record could consume or replace any pending identity.
        item = _episode("limit", {}, "context-limit")
        item["unresolvedReasons"].append(
            "Matched-probe record limit exceeded; no lifecycle correspondence was inferred."
        )
        return [item]
    resolver = Communicators(trace.defs)
    by_init = {
        r.initiation_event: r for r in requests if r.initiation_event is not None
    }
    completion_data = {
        r["id"]: json.loads(r["data"]) for r in rows if r["kind"] == "MpiImrecv"
    }
    pending = collections.defaultdict(list)
    generations = collections.Counter()
    episodes = []
    claimed_completions = set()

    def endpoint(row, routines=None):
        span = lookup.at(row["location"], row["time"], routines, event=row["id"])
        result = operation(
            span,
            location=row["location"],
            event=row["id"],
            time=row["time"],
            routine=row["kind"],
        ).as_dict()
        result.update(eventTime=row["time"], eventKind=row["kind"])
        return result, span

    for row in rows:
        data = json.loads(row["data"])
        kind = row["kind"]
        if kind == "MpiImrecv":
            # Request lifecycle replay below supplies the owning initiation.
            continue
        key = (resolver.request_scope(row["location"]), str(data.get("messageId")))
        if kind == "MpiProbe":
            item = _episode(row["id"], data, "pending-receive")
            item["probe"], span = endpoint(row, {"mprobe", "improbe"})
            item["_probeEvent"] = dict(row)
            item["_envelope"] = None
            item["_probeSpan"] = span
            episodes.append(item)
            # MpiProbe also names an ordinary probing observation. Its record
            # alone does not establish that a message handle was acquired.
            if span is None or not span.complete:
                item["status"] = "unverified-probe-kind"
                item["unresolvedReasons"].append(
                    "No complete MPI_Mprobe/MPI_Improbe invocation identifies this probe as handle acquisition."
                )
                continue
            generations[key] += 1
            item["generation"] = generations[key]
            if "messageId" not in data:
                item["status"] = "missing-handle"
                item["unresolvedReasons"].append("The probe record has no messageId.")
                continue
            try:
                comm = str(data["communicator"])
                src = resolver.peer(comm, data["sender"], row["location"])
                dst = resolver.local(comm, row["location"])
                if src is not None and dst is not None:
                    item["_envelope"] = (comm, src, dst, str(data["tag"]))
            except (KeyError, ValueError, TypeError):
                pass
            if item["_envelope"] is None:
                item["unresolvedReasons"].append(
                    "The recorded source/communicator/tag cannot be resolved to an exact message envelope."
                )
            pending[key].append(item)
            if len(pending[key]) > 1:
                for candidate in pending[key]:
                    candidate["status"] = "ambiguous-handle-reuse"
                    if (
                        "Overlapping acquisitions reuse this handle in the assumed process scope."
                        not in candidate["unresolvedReasons"]
                    ):
                        candidate["unresolvedReasons"].append(
                            "Overlapping acquisitions reuse this handle in the assumed process scope."
                        )
            continue
        item = _episode(row["id"], data, "orphan-receive")
        item["receive"], receive_span = endpoint(
            row, {"mrecv"} if kind == "MpiMrecv" else {"imrecv"}
        )
        candidates = pending.get(key, [])
        if len(candidates) != 1 or candidates[0]["status"] == "ambiguous-handle-reuse":
            item["unresolvedReasons"].append(
                "No unique active probe has this handle in the assumed process scope."
            )
            item["probeCandidates"] = [p["id"] for p in candidates[:CANDIDATE_LIMIT]]
            item["probeCandidateCount"] = len(candidates)
            episodes.append(item)
            continue
        item = pending.pop(key)[0]
        item["receive"], receive_span = endpoint(
            row, {"mrecv"} if kind == "MpiMrecv" else {"imrecv"}
        )
        item["_receiveSpan"] = receive_span
        item["_receiveEvent"] = dict(row)
        item["_length"] = data.get("msgLength")
        if row["time"] < item["_probeEvent"]["time"]:
            item["status"] = "inconsistent-time"
            item["unresolvedReasons"].append(
                "Receive initiation precedes the recorded probe timestamp."
            )
        elif kind == "MpiMrecv":
            item["status"] = "completed-conditional"
            item["completion"] = item["receive"].copy()
        else:
            req = by_init.get(row["id"])
            item["_request"] = req
            if req is None or req.kind != "matched-receive":
                item["status"] = "request-unresolved"
                item["unresolvedReasons"].append(
                    "No consistent matched-receive request lifecycle is recorded."
                )
            else:
                item["request"] = dict(
                    id=req.request,
                    generation=req.generation,
                    status=req.status,
                    initiationEvent=req.initiation_event,
                    completionEvent=req.completion_event,
                    location=req.location,
                    completionLocation=req.completion_location,
                )
                item["status"] = (
                    "completed-conditional" if req.status == "completed" else req.status
                )
                if req.completion_event is not None:
                    claimed_completions.add(req.completion_event)
                    item["completion"] = operation(
                        req.completion_span,
                        location=req.completion_location,
                        event=req.completion_event,
                        time=req.end,
                        routine=(
                            "MpiImrecv" if req.status == "completed" else req.status
                        ),
                    ).as_dict()
                    item["completion"].update(
                        eventTime=req.end,
                        eventKind=(
                            "MpiImrecv"
                            if req.status == "completed"
                            else (
                                "MpiRequestCancelled"
                                if req.status == "cancelled"
                                else None
                            )
                        ),
                    )
                    item["_length"] = completion_data.get(req.completion_event, {}).get(
                        "msgLength"
                    )
                if req.end is not None and req.end < row["time"]:
                    item["status"] = "inconsistent-time"
                if item["status"] != "completed-conditional":
                    item["unresolvedReasons"].append(
                        "The matched-receive request did not complete consistently: "
                        + item["status"]
                        + "."
                    )
        if item["status"] == "completed-conditional" and (
            receive_span is None or not receive_span.complete
        ):
            item["unresolvedReasons"].append(
                "The receiving call has no complete observed invocation bracket."
            )

    for row in rows:
        if row["kind"] == "MpiImrecv" and row["id"] not in claimed_completions:
            item = _episode(row["id"], json.loads(row["data"]), "orphan-completion")
            item["completion"], _ = endpoint(row)
            item["unresolvedReasons"].append(
                "No unique probe-to-request lifecycle owns this completion."
            )
            episodes.append(item)

    # Do not steal a send already associated with an ordinary recorded receive.
    # Exact envelope uniqueness is deliberately stronger than timestamp order:
    # request completion order and concurrent sender order need not be matching
    # order, and the producer's message-handle contract remains unavailable.
    envelopes = {p.get("_envelope") for p in episodes if p.get("_envelope") is not None}
    sends = collections.defaultdict(lambda: dict(count=0, rows=[]))
    sends_truncated = False
    if envelopes:
        with trace.connect() as db:
            for index, row in enumerate(
                db.execute(
                    "SELECT e.id,e.location,e.time,e.kind,e.data FROM events e WHERE e.kind IN ('MpiSend','MpiIsend') AND e.id NOT IN (SELECT m.send_event FROM messages m WHERE m.send_event IS NOT NULL AND m.recv_event IS NOT NULL) ORDER BY e.id LIMIT ?",
                    (SEND_LIMIT + 1,),
                )
            ):
                if index >= SEND_LIMIT:
                    sends_truncated = True
                    diagnostics["matched_probe_send_scan_limit"] += 1
                    break
                data = json.loads(row["data"])
                try:
                    comm = str(data["communicator"])
                    key = (
                        comm,
                        resolver.local(comm, row["location"]),
                        resolver.peer(comm, data["receiver"], row["location"]),
                        str(data["msgTag"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if key not in envelopes:
                    continue
                req = by_init.get(row["id"])
                if row["kind"] == "MpiIsend" and (
                    req is None
                    or req.status
                    not in (
                        "completed",
                        "pending-at-trace-end",
                        "completion-or-release",
                        "released-completion-unknown",
                    )
                ):
                    continue
                bucket = sends[key]
                bucket["count"] += 1
                if len(bucket["rows"]) < CANDIDATE_LIMIT:
                    bucket["rows"].append((dict(row), data))
    by_envelope = collections.Counter(
        p.get("_envelope") for p in episodes if p.get("_envelope") is not None
    )
    for item in episodes:
        envelope = item.get("_envelope")
        bucket = sends.get(envelope, dict(count=0, rows=[]))
        candidates = bucket["rows"]
        item["candidateCount"] = bucket["count"]
        item["candidateCountComplete"] = not sends_truncated
        for row, data in candidates:
            source, _ = endpoint(
                row,
                {
                    "send",
                    "ssend",
                    "bsend",
                    "rsend",
                    "isend",
                    "issend",
                    "ibsend",
                    "irsend",
                    "sendrecv",
                    "sendrecv_replace",
                },
            )
            item["sendCandidates"].append(
                dict(operation=source, time=row["time"], bytes=data.get("msgLength"))
            )
        if sends_truncated:
            item["unresolvedReasons"].append(
                "Send scan limit reached; candidate counts are lower bounds and no send correspondence was selected."
            )
        elif item["candidateCount"] != 1 or by_envelope[envelope] != 1:
            item["unresolvedReasons"].append(
                "The otherwise-unclaimed send envelope is missing or nonunique; send order is not guessed."
            )
        elif (
            item.get("_probeSpan") is not None
            and item["status"] == "completed-conditional"
        ):
            row, data = candidates[0]
            probe_event = item["_probeEvent"]
            if not math.isfinite(row["time"]) or row["time"] > probe_event["time"]:
                item["unresolvedReasons"].append(
                    "The send initiation is later than the probe observation; clocks/order are inconsistent."
                )
            elif (
                item.get("_length") is not None
                and data.get("msgLength") != item["_length"]
            ):
                item["unresolvedReasons"].append(
                    "Recorded send and matched receive lengths differ."
                )
            else:
                source_span = lookup.at(row["location"], row["time"], event=row["id"])
                targets = [(item["_probeSpan"], probe_event["id"])]
                req = item.get("_request")
                if (
                    req is not None
                    and req.status == "completed"
                    and req.completion_span
                    and req.completion_span.routine
                    in {"wait", "waitall", "waitany", "waitsome"}
                ):
                    targets.append((req.completion_span, req.completion_event))
                elif (
                    item.get("_receiveSpan") is not None
                    and item["_receiveSpan"].routine == "mrecv"
                ):
                    targets.append((item["_receiveSpan"], item["_receiveEvent"]["id"]))
                for target, event in targets:
                    # Improbe/Test duration is a polling observation, never a
                    # positive waiting interval. A zero-delay relation remains
                    # inspectable when the prerequisite already existed.
                    if target.id not in records or not target.complete:
                        continue
                    recording_issue = (
                        continuity.issue(
                            [row["location"], target.location],
                            target.end,
                            comm=envelope[0],
                            start=min(row["time"], target.start),
                        )
                        if continuity is not None
                        else None
                    )
                    if recording_issue:
                        diagnostics["matched_probe_recording_gap"] += 1
                        item["recordingContinuity"] = recording_issue
                        records[target.id].evidence[
                            "recordingContinuity"
                        ] = recording_issue
                        reason = "Recording suspension can hide message-handle/request reuse or another matching send; observed candidates do not establish a dependency interval."
                        if reason not in item["unresolvedReasons"]:
                            item["unresolvedReasons"].append(reason)
                        continue
                    edge = prerequisite(
                        item["id"] + ":sender:span:" + str(target.id),
                        "matched_probe_sender",
                        operation(
                            source_span,
                            location=row["location"],
                            event=row["id"],
                            time=row["time"],
                            routine=row["kind"],
                        ),
                        operation(target, event=event),
                        row["time"],
                        required=False,
                        confidence="conditional-handle-scope",
                        communicator=envelope[0],
                        request=item["request"],
                        target_start=(
                            target.end if target.routine == "improbe" else target.start
                        ),
                        reason="Unique recorded envelope and handle/request chain under an unverified process-scoped message-handle assumption; this is not a native matching result or measured blocked time.",
                    )
                    if edge:
                        edge["matchedProbe"] = item["id"]
                        records[target.id].causes.append(edge)
        for field in ("probe", "receive", "completion"):
            endpoint_data = item.get(field)
            record = records.get(endpoint_data["span"]) if endpoint_data else None
            if record is not None:
                ids = record.evidence.setdefault("matchedProbes", [])
                if len(ids) < CANDIDATE_LIMIT and item["id"] not in ids:
                    ids.append(item["id"])
        if item["status"] != "completed-conditional":
            diagnostics["matched_probe_" + item["status"].replace("-", "_")] += 1
        diagnostics["matched_probe_scope_unverified"] += 1
        for key in [k for k in item if k.startswith("_")]:
            item.pop(key)
    return episodes
