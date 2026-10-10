"""Ordered MPI request matching and retained native emission evidence."""

import collections
import re

from .definitions import DefinitionIndex

_OTF_PEER = re.compile(r"^([SR])([0-9a-fA-F]+)L").match


def normalize_otf_message(data):
    """Old caches normalized OTF process tokens as zero-based ranks."""
    match = _OTF_PEER(data.get("raw", "")) if data.get("otfPeer") else None
    if match:
        key = "receiver" if match[1] == "S" else "sender"
        peer = int(match[2], 16)
        if data.get(key) != peer:
            data[key] = peer
            return True
    return False


class MessageIndex(DefinitionIndex):
    def __init__(self, db, progress=lambda **kw: None):
        super().__init__(db, progress)
        self.sends = collections.defaultdict(collections.deque)
        self.recvs = collections.defaultdict(collections.deque)
        self.receive_order = collections.defaultdict(collections.deque)
        self.receive_requests = {}
        self.send_order = collections.defaultdict(collections.deque)
        self.send_requests = {}
        self.message_emission_event = None

    def peer(self, comm, rank, loc):
        return self.communicators.endpoint(self.communicators.peer(comm, rank, loc))

    def message_envelope(self, loc, k, d):
        normalize_otf_message(d)
        send = k in ("MpiSend", "MpiIsend")
        rank = d["receiver" if send else "sender"]
        # OTF1 stores process tokens directly, independently of group ordering.
        peer = (
            str(rank)
            if d.get("otfPeer")
            else self.communicators.peer(d["communicator"], rank, loc)
        )
        local = (
            loc
            if d.get("otfPeer")
            else self.communicators.local(d["communicator"], loc)
        )
        src, dst = (local, peer) if send else (peer, local)
        return (str(d["communicator"]), src, dst, str(d["msgTag"]))

    def message(self, loc, t, k, d, eid, native_verified=True):
        key = self.message_envelope(loc, k, d)
        send = k in ("MpiSend", "MpiIsend")
        item = (t, d["msgLength"], eid, loc, bool(d.get("otfPeer")), native_verified)
        mine, other = (self.sends, self.recvs) if send else (self.recvs, self.sends)
        if key[1] is not None and key[2] is not None and other[key]:
            pair = other[key].popleft()
            s, r = (item, pair) if send else (pair, item)
            status = "matched" if r[0] >= s[0] else "clock inversion"
            if s[1] != r[1]:
                self.warnings["MPI matched message length differs"] += 1
            # Rank representatives are matching keys; retain the actual
            # executing threads as the visualization/dependency endpoints.
            self.add(
                "messages",
                (
                    None,
                    s[3],
                    r[3],
                    s[0],
                    r[0],
                    key[0],
                    key[3],
                    s[1],
                    status,
                    s[2],
                    r[2],
                ),
            )
            native_start, native_end = s[0], r[0]
            emitter = "send" if send else "receive"
            corrected = int(status == "clock inversion")
            if s[4] or r[4]:
                # The recovered correction belongs to the OTF2 reader path.
                native_start = native_end = None
                emitter = "otf1-unverified"
                corrected = 0
            elif not (s[5] and r[5]):
                native_start = native_end = None
                emitter = "incomplete-unverified"
                corrected = 0
            elif corrected:
                tick = 1 / self.resolution
                if send:
                    native_end = native_start + tick
                else:
                    native_start = max(0.0, native_end - tick)
            self.add(
                "message_evidence",
                (
                    s[2],
                    r[2],
                    native_start,
                    native_end,
                    emitter,
                    corrected,
                    self.message_emission_event if s[5] and r[5] else None,
                ),
            )
        else:
            mine[key].append(item)

    def mpi_event(self, loc, t, k, d, eid):
        self.message_emission_event = eid
        # Completion order of nonblocking receives need not be their matching
        # order. Reserve a receive position at the request initiation event;
        # fill it once the completed receive supplies source/tag/communicator.
        scope = self.communicators.request_scope(loc)
        key = (scope, str(d.get("requestID")))
        if k in ("MpiSend", "MpiIsend"):
            envelope = (scope, self.message_envelope(loc, k, d))
            intent = dict(
                message=(loc, t, k, d, eid),
                ready=k == "MpiSend",
                cancelled=False,
                envelope=envelope,
            )
            if k == "MpiIsend":
                if key in self.send_requests:
                    self.warnings["MPI send request reused before completion"] += 1
                self.send_requests[key] = intent
            self.send_order[envelope].append(intent)
            self.drain_sends(envelope)
        elif k == "MpiIsendComplete":
            intent = self.send_requests.pop(key, None)
            if intent is not None:
                intent["ready"] = True
                self.drain_sends(intent["envelope"])
            elif key in self.receive_requests:
                self.warnings["MPI send completion has receive request type"] += 1
            else:
                self.warnings["MPI send completion without request"] += 1
        elif k == "MpiIrecvRequest":
            if key in self.receive_requests:
                self.receive_requests.pop(key)["cancelled"] = True
                self.warnings["MPI receive request reused before completion"] += 1
            intent = dict(message=None, cancelled=False)
            self.receive_requests[key] = intent
            self.receive_order[scope].append(intent)
        elif k == "MpiRequestCancelled":
            intent = self.receive_requests.pop(key, None)
            if intent is not None:
                intent["cancelled"] = True
            intent = self.send_requests.pop(key, None)
            if intent is not None:
                intent["cancelled"] = True
                self.drain_sends(intent["envelope"])
        elif k == "MpiIrecv":
            if key in self.send_requests and key not in self.receive_requests:
                self.warnings["MPI receive completion has send request type"] += 1
                return
            intent = self.receive_requests.pop(key, None)
            if intent is None:
                self.warnings["MPI receive completion without request"] += 1
                intent = dict(message=None, cancelled=False)
                self.receive_order[scope].append(intent)
            intent["message"] = (loc, t, k, d, eid)
        elif k == "MpiRecv":
            self.receive_order[scope].append(
                dict(message=(loc, t, k, d, eid), cancelled=False)
            )
        self.drain_receives(scope)

    def drain_sends(self, envelope, final=False):
        queue = self.send_order[envelope]
        while queue:
            intent = queue[0]
            if not intent["ready"] and not intent["cancelled"] and not final:
                break
            queue.popleft()
            if intent["cancelled"]:
                continue
            if not intent["ready"]:
                self.warnings["MPI send initiation without completion"] += 1
            self.message(*intent["message"], native_verified=not final)
        if not queue:
            self.send_order.pop(envelope, None)

    def drain_receives(self, loc, final=False):
        queue = self.receive_order[loc]
        while queue:
            intent = queue[0]
            if intent["message"] is None and not intent["cancelled"] and not final:
                break
            queue.popleft()
            if intent["message"] is not None:
                self.message(*intent["message"], native_verified=not final)
            elif not intent["cancelled"]:
                self.warnings["MPI receive initiation without completion"] += 1

    def finish_messages(self):
        # An observed receive can still establish delivery when a send's local
        # completion was not recorded. Keep that evidence, with a diagnostic;
        # canceled sends, in contrast, must never consume a receive.
        for envelope in list(self.send_order):
            self.drain_sends(envelope, True)
        self.send_requests.clear()
        for loc in self.receive_order:
            self.drain_receives(loc, True)
        self.receive_requests.clear()
        for queues, send in [(self.sends, True), (self.recvs, False)]:
            for (comm, src, dst, tag), q in queues.items():
                for t, size, eid, loc, _, _ in q:
                    self.add(
                        "messages",
                        (
                            None,
                            loc if send else self.communicators.endpoint(src),
                            self.communicators.endpoint(dst) if send else loc,
                            t if send else None,
                            None if send else t,
                            comm,
                            tag,
                            size,
                            "unmatched send" if send else "unmatched receive",
                            eid if send else None,
                            None if send else eid,
                        ),
                    )
            queues.clear()
