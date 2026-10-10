"""Matched-message and send-request completion prerequisites."""

from ..causality.operations import operation, prerequisite
from .wait_models import SEND, RECEIVE, SENDRECV, WAIT

NONBLOCKING_SENDS = {"isend", "issend", "ibsend", "irsend"}
SENDERS = SEND | SENDRECV | NONBLOCKING_SENDS
RECEIVERS = RECEIVE | SENDRECV
RECEIVE_POSTINGS = {"irecv"}


class MessageWaits:
    def __init__(
        self, trace, lookup, records, requests, completions, diagnostics, continuity
    ):
        self.trace = trace
        self.lookup = lookup
        self.records = records
        self.requests = requests
        self.completions = completions
        self.diagnostics = diagnostics
        self.continuity = continuity

    @staticmethod
    def posting_time(request, receiver):
        if request and request.kind == "receive" and request.status == "completed":
            return request.start
        return receiver.start if receiver and receiver.complete else None

    def posting_operation(self, request, receiver, location, event, time):
        span = (
            self.lookup.at(
                request.location,
                time,
                RECEIVE_POSTINGS,
                event=request.initiation_event,
            )
            if request
            else receiver
        )
        return operation(
            span,
            location=request.location if request else location,
            event=request.initiation_event if request else event,
            time=time,
            routine="MpiIrecvRequest" if request else "MPI_Recv",
        )

    def annotate_continuity(self, evidence, sender, receiver, request):
        for affected in (
            sender,
            receiver,
            request.completion_span if request else None,
        ):
            if affected and affected.id in self.records:
                self.records[affected.id].evidence["recordingContinuity"] = evidence

    def analyze(self):
        self.matched_messages()
        self.send_requests()

    @staticmethod
    def message_lookups(row):
        """The sender and blocking-receiver at() calls for one message row."""
        _, source, target, start, end, _, _, status, send, receive = row[:10]
        recv_kind, send_location, recv_location = row[11:]
        if status == "matched":
            yield send_location or source, start, SENDERS, send
            if recv_kind == "MpiRecv":
                yield recv_location or target, end, RECEIVERS, receive

    def matched_messages(self):
        with self.trace.connect() as db:
            cursor = db.cursor()
            cursor.row_factory = None
            rows = cursor.execute(
                """SELECT m.id,m.source,m.target,m.start,m.end,m.comm,m.tag,m.status,m.send_event,m.recv_event,
                    s.kind,r.kind,s.location,r.location FROM messages m
                    LEFT JOIN events s ON s.id=m.send_event LEFT JOIN events r ON r.id=m.recv_event ORDER BY m.id"""
            )
            for (
                message,
                message_source,
                message_target,
                start,
                end,
                comm,
                tag,
                status,
                send_event,
                recv_event,
                send_kind,
                recv_kind,
                send_location,
                recv_location,
            ) in self.lookup.prefetched(rows, self.message_lookups):
                if status != "matched":
                    self.diagnostics[
                        (
                            "clock_inverted_messages"
                            if status == "clock inversion"
                            else "unmatched_messages"
                        )
                    ] += 1
                    continue
                sender_location = send_location or message_source
                receiver_location = recv_location or message_target
                sender = self.lookup.at(
                    sender_location, start, SENDERS, event=send_event
                )
                receiver = (
                    self.lookup.at(receiver_location, end, RECEIVERS, event=recv_event)
                    if recv_kind == "MpiRecv"
                    else None
                )
                receive_request = self.completions.get(recv_event)
                recording_issue = self.continuity.issue(
                    [sender_location, receiver_location],
                    end,
                    comm=comm,
                    start=min(
                        start,
                        (
                            receive_request.start
                            if receive_request and receive_request.start is not None
                            else receiver.start if receiver else end
                        ),
                    ),
                )
                if recording_issue:
                    self.diagnostics["message_recording_gap"] += 1
                    self.annotate_continuity(
                        recording_issue, sender, receiver, receive_request
                    )
                    continue
                recording_proof = self.continuity.proof(
                    [sender_location, receiver_location], end, comm
                )
                if recording_proof.get("freshCommunicatorEvidence"):
                    self.annotate_continuity(
                        recording_proof, sender, receiver, receive_request
                    )
                posting = self.posting_time(receive_request, receiver)
                sender_entry = sender.start if sender and sender.complete else None
                # A receive cannot complete before its matched send initiation.
                # The OTF2 send timestamp is that initiation, unlike the enclosing
                # routine entry used by the older arrival-skew display.
                receive_targets = []
                if receiver and receiver.id in self.records:
                    receive_targets.append((receiver, None))
                if (
                    receive_request
                    and receive_request.status == "completed"
                    and receive_request.completion_span
                    and receive_request.completion_span.routine in WAIT
                ):
                    receive_targets.append(
                        (receive_request.completion_span, receive_request)
                    )
                for target, request in receive_targets:
                    if target.id not in self.records or not target.complete:
                        continue
                    required = target.routine not in {"waitany", "waitsome"}
                    edge = prerequisite(
                        f"message:{message}:receive:span:{target.id}",
                        "late_sender",
                        operation(
                            sender,
                            location=sender_location,
                            event=send_event,
                            time=start,
                            routine=send_kind,
                        ),
                        operation(target, event=recv_event),
                        start,
                        required=required,
                        request=(
                            dict(id=request.request, generation=request.generation)
                            if request
                            else None
                        ),
                        message=message,
                        communicator=comm,
                        reason=(
                            "This recorded receive completion requires the matched send initiation."
                            if required
                            else "This receive completed in a Waitany/Waitsome call; its full awaited alternative set is not recorded, so call-level delay remains conditional."
                        ),
                    )
                    if edge:
                        self.records[target.id].causes.append(edge)
                if (
                    sender
                    and sender.id in self.records
                    and sender.routine not in {"bsend", "rsend"}
                    and sender.complete
                    and posting is not None
                ):
                    source = self.posting_operation(
                        receive_request,
                        receiver,
                        receiver_location,
                        recv_event,
                        posting,
                    )
                    edge = prerequisite(
                        f"message:{message}:send:span:{sender.id}",
                        "late_receiver",
                        source,
                        operation(sender, event=send_event),
                        posting,
                        required=sender.routine == "ssend",
                        confidence=(
                            "recorded-dependency"
                            if sender.routine == "ssend" and receive_request
                            else (
                                "recorded-routine-bound"
                                if sender.routine == "ssend"
                                else "conditional"
                            )
                        ),
                        message=message,
                        communicator=comm,
                        reason=(
                            "Synchronous send completion requires a matching receive to have started."
                            if sender.routine == "ssend"
                            else "Standard send may use eager buffering; receiver arrival alone does not prove that it delayed this send."
                        ),
                    )
                    if edge:
                        self.records[sender.id].causes.append(edge)
                causes = []
                if receiver and receiver.id in self.records:
                    causes.append(
                        (receiver, "late_sender", sender_entry, message_source)
                    )
                if (
                    sender
                    and sender.id in self.records
                    and sender.routine not in {"bsend", "rsend"}
                ):
                    # A send which already returned before the receiver posted is
                    # evidence for buffering, not late-receiver blocking.
                    deadline = (
                        posting
                        if posting is not None and posting <= sender.end
                        else None
                    )
                    causes.append((sender, "late_receiver", deadline, message_target))
                for request, dependency, peer, category in (
                    (receive_request, sender_entry, message_source, "late_sender_wait"),
                    (
                        self.completions.get(send_event),
                        posting,
                        message_target,
                        "late_receiver_wait",
                    ),
                ):
                    if (
                        request
                        and request.completion_span
                        and request.completion_span.routine in WAIT
                    ):
                        span = request.completion_span
                        if request.status == "completed":
                            causes.append((span, category, dependency, peer))
                # Send completions carry a different event ID from MpiIsend. The
                # initiation index below supplies the send request's completion.
                for span, category, deadline, peer in causes:
                    record = self.records.get(span.id)
                    if record is None:
                        continue
                    evidence = record.evidence
                    if len(evidence["messages"]) < 16:
                        evidence["messages"].append(
                            dict(
                                message=message,
                                sendEvent=send_event,
                                receiveEvent=recv_event,
                                communicator=comm,
                                tag=tag,
                                senderEntry=sender_entry,
                                sendRecorded=start,
                                receiverPosted=posting,
                                receiveRecorded=end,
                            )
                        )
                    evidence["messageCount"] = evidence.get("messageCount", 0) + 1
                    if deadline is not None and span.complete:
                        deadline = min(span.end, max(span.start, deadline))
                        if deadline > record.inferred_end:
                            record.inferred_end = deadline
                            record.category = category
                            record.peer = peer
                            record.confidence = "conditional"
                    elif deadline is None:
                        self.diagnostics["dependency_entry_not_observed"] += 1

    def send_requests(self):
        # Complete send-request associations without rescanning events per request.
        send_requests = {}
        for request in self.requests:
            if (
                request.kind != "send"
                or request.initiation_event is None
                or not request.completion_span
                or request.completion_span.routine not in WAIT
                or request.completion_span.id not in self.records
            ):
                continue
            ambiguous, limited = self.lookup.order.ambiguous, self.lookup.order.limited
            initiation = self.lookup.at(
                request.location,
                request.start,
                NONBLOCKING_SENDS,
                event=request.initiation_event,
            )
            if not initiation or initiation.routine not in {"ibsend", "irsend"}:
                send_requests[request.initiation_event] = (
                    request,
                    bool(initiation and initiation.routine == "issend"),
                    self.lookup.order.ambiguous - ambiguous,
                    self.lookup.order.limited - limited,
                )
        if send_requests:
            with self.trace.connect() as db:
                cursor = db.cursor()
                cursor.row_factory = None
                for (
                    message,
                    send_event,
                    recv_event,
                    message_target,
                    end,
                    comm,
                    recv_location,
                ) in cursor.execute(
                    "SELECT m.id,m.send_event,m.recv_event,m.target,m.end,m.comm,r.location FROM messages m LEFT JOIN events r ON r.id=m.recv_event WHERE m.status='matched'"
                ):
                    association = send_requests.get(send_event)
                    if association is None:
                        continue
                    request, synchronous, ambiguous, limited = association
                    if request.status != "completed":
                        continue
                    receiver_location = recv_location or message_target
                    recording_issue = self.continuity.issue(
                        [
                            request.location,
                            request.completion_location or request.location,
                            receiver_location,
                        ],
                        max(end, request.end),
                        comm=comm,
                        start=request.start,
                    )
                    if recording_issue:
                        self.diagnostics["send_request_recording_gap"] += 1
                        self.records[request.completion_span.id].evidence[
                            "recordingContinuity"
                        ] = recording_issue
                        continue
                    receiver = self.lookup.at(
                        receiver_location, end, RECEIVERS, event=recv_event
                    )
                    receive_request = self.completions.get(recv_event)
                    posted = self.posting_time(receive_request, receiver)
                    span = request.completion_span
                    record = self.records[span.id]
                    if posted is not None and span.complete:
                        # Reuse the initiation match, retaining logical diagnostic counts.
                        self.lookup.order.ambiguous += ambiguous
                        self.lookup.order.limited += limited
                        source = self.posting_operation(
                            receive_request,
                            receiver,
                            receiver_location,
                            recv_event,
                            posted,
                        )
                        edge = prerequisite(
                            f"message:{message}:send-request:span:{span.id}",
                            "late_receiver",
                            source,
                            operation(span, event=request.completion_event),
                            posted,
                            required=synchronous
                            and span.routine not in {"waitany", "waitsome"},
                            request=dict(
                                id=request.request, generation=request.generation
                            ),
                            message=message,
                            communicator=comm,
                            reason=(
                                "The synchronous send request requires a matching receive to start; only its recorded wait routine is charged."
                                if synchronous
                                else "Standard nonblocking send can complete using eager buffering; this receive-posting delay is conditional."
                            ),
                        )
                        if edge:
                            record.causes.append(edge)
                    record.evidence["messageCount"] = (
                        record.evidence.get("messageCount", 0) + 1
                    )
                    if posted is not None and posted <= span.end and span.complete:
                        if posted > record.inferred_end:
                            record.inferred_end = max(span.start, posted)
                            record.category = "late_receiver_wait"
                            record.peer = message_target
                            record.confidence = "conditional"
                        if len(record.evidence["messages"]) < 16:
                            record.evidence["messages"].append(
                                dict(
                                    message=message,
                                    sendEvent=send_event,
                                    receiveEvent=recv_event,
                                    receiverPosted=posted,
                                )
                            )
