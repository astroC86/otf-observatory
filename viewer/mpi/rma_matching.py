"""OTF2 RMA completion vectors recovered from the native reader.

Raw operation origins remain distinct from the native transfer endpoint, which
uses the completing location for a process-scoped window. See the GPU audit.
"""

from collections import defaultdict

from .communicators import Communicators

RMA_BEGIN = ("RmaPut", "RmaGet", "RmaAtomic")
RMA_COMPLETE = (
    "RmaOpCompleteBlocking",
    "RmaOpCompleteNonBlocking",
    "RmaOpCompleteRemote",
)
RMA_EVENTS = RMA_BEGIN + RMA_COMPLETE + ("RmaWinCreate", "RmaWinDestroy")
RMA_INDEX_VERSION = 1


class RmaMatcher:
    def __init__(self, definitions, emit, warnings):
        self.defs = definitions
        self.comms = Communicators(definitions)
        self.emit = emit
        self.warnings = warnings
        self.pending = defaultdict(list)
        self.known = set()
        self.windows = set()

    def scope(self, location, window):
        win = self.defs.get("RmaWin", {}).get(str(window), {})
        comm = self.defs.get("Comm", {}).get(str(win.get("comm")), {})
        group = self.comms.group(comm.get("group"))
        world = self.comms.world(group.get("paradigm"))
        if group.get("groupType") == 7 or world.get("groupType") == 7:
            return self.comms.request_scope(str(location))
        return str(location)

    def _emit(
        self,
        key,
        row,
        end=None,
        completion_event=None,
        completion_location=None,
        status="incomplete",
    ):
        location, start, kind, data, begin_event = row
        win = self.defs.get("RmaWin", {}).get(str(data["win"]), {})
        peer = self.comms.peer(win.get("comm"), data["remote"], location)
        size = data.get(
            "bytes", data.get("bytesSent", 0) + data.get("bytesReceived", 0)
        )
        initiator = completion_location if completion_location is not None else location
        source, target = (peer, initiator) if kind == "RmaGet" else (initiator, peer)
        self.emit(
            (
                None,
                location,
                peer,
                start,
                end,
                kind,
                str(data["win"]),
                size,
                status,
                begin_event,
            ),
            (
                begin_event,
                completion_event,
                completion_location,
                key[0],
                source,
                target,
                key[2],
                status,
            ),
        )

    def event(self, location, time, kind, data, event):
        location = str(location)
        window = str(data["win"])
        scope = self.scope(location, window)
        if kind in ("RmaWinCreate", "RmaWinDestroy"):
            definition = self.defs.get("RmaWin", {}).get(window)
            if definition is None:
                self.warnings["RMA lifecycle for undefined window"] += 1
                return
            if not definition.get("flags", 0) & 1:
                self.warnings["RMA lifecycle event without create/destroy flag"] += 1
                return
        if kind == "RmaWinCreate":
            # Native 0x10f8f80 rejects a duplicate map entry, without clearing
            # its vectors. Keep evidence available and report the bad lifecycle.
            if (scope, window) in self.windows:
                self.warnings["RMA duplicate window creation"] += 1
            self.windows.add((scope, window))
            return
        if kind == "RmaWinDestroy":
            # Native 0x1043a70 drains every matching-ID vector at destroy time.
            for key in [k for k in self.pending if k[:2] == (scope, window)]:
                for row in self.pending.pop(key):
                    self._emit(key, row, time, event, location, kind)
            self.known = {k for k in self.known if k[:2] != (scope, window)}
            self.windows.discard((scope, window))
            return
        key = (scope, window, str(data["matchingId"]))
        if kind in RMA_BEGIN:
            self.pending[key].append((location, time, kind, data, event))
            self.known.add(key)
        elif kind in RMA_COMPLETE:
            rows = self.pending.pop(key, ())
            if not rows and key not in self.known:
                self.warnings["RMA completion without begin"] += 1
            for row in rows:
                self._emit(key, row, time, event, location, kind)

    def finish(self):
        for key, rows in self.pending.items():
            for row in rows:
                self.warnings["Unfinished RMA operations"] += 1
                self._emit(key, row)
        self.pending.clear()
