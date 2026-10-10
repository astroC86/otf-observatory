"""Call-stack, calling-context and migrating task interval accounting."""

import collections

from ..tasks.identity import task_identity, process_scope
from .definitions import DefinitionIndex


class SpanIndex(DefinitionIndex):
    def __init__(self, db, progress=lambda **kw: None):
        super().__init__(db, progress)
        self.stacks = collections.defaultdict(list)
        self.active_tasks = {}
        self.task_stacks = {}
        self.last = {}
        self.last_events = {}
        self.task_locations = {}
        self.task_conflicts = set()
        self.incomplete_task_spans = set()
        self.paths = {}
        self.path_depth = {}
        self.next_span = 0

    def path(self, parent, region):
        key = (parent, str(region))
        ident = self.paths.get(key)
        if ident is None:
            ident = len(self.paths) + 1
            depth = self.path_depth.get(parent, -1) + 1
            self.paths[key] = ident
            self.path_depth[ident] = depth
            self.add("paths", (ident, parent, str(region), depth))
        return ident

    def leaf(self, loc, t):
        stack = self.stacks[loc]
        last = self.last.get(loc, t)
        if t < last:
            self.warnings["Non-monotonic location timestamps"] += 1
            return
        if stack and t > last:
            f = stack[-1]
            f["exclusive"] += t - last
            self.add("slices", (None, loc, f["region"], f["path"], last, t, f["id"]))
        self.last[loc] = t

    def enter(self, loc, region, t, sampled=0):
        self.leaf(loc, t)
        stack = self.stacks[loc]
        self.next_span += 1
        parent = stack[-1] if stack else None
        p = self.path(parent["path"] if parent else 0, region)
        stack.append(
            {
                "id": self.next_span,
                "invocation": self.next_span,
                "continuation": 0,
                "region": str(region),
                "start": t,
                "depth": len(stack),
                "parent": parent["id"] if parent else 0,
                "path": p,
                "exclusive": 0,
                "sampled": sampled,
            }
        )

    def save_frame(self, loc, f, t, incomplete=0):
        self.add(
            "spans",
            (
                f["id"],
                loc,
                f["region"],
                f["start"],
                max(t, f["start"]),
                f["depth"],
                f["parent"],
                f["path"],
                f["exclusive"],
                int(bool(incomplete or f.get("incomplete"))),
                f["sampled"],
                f["continuation"],
                f["invocation"],
            ),
        )

    def close(self, loc, t, incomplete=0):
        self.leaf(loc, t)
        if not self.stacks[loc]:
            return
        f = self.stacks[loc].pop()
        self.save_frame(loc, f, t, incomplete)

    def leave(self, loc, region, t):
        stack = self.stacks[loc]
        if not stack:
            self.warnings["Leave without matching enter"] += 1
            return
        if region is None:
            region = stack[-1]["region"]
        region = str(region)
        if stack[-1]["region"] != region:
            self.warnings["Mismatched region nesting"] += 1
            if not any(f["region"] == region for f in stack):
                return
            while stack and stack[-1]["region"] != region:
                self.close(loc, t, 1)
        self.close(loc, t)

    def context_chain(self, ref):
        chain = []
        seen = set()
        while str(ref) in self.defs["CallingContext"] and str(ref) not in seen:
            seen.add(str(ref))
            d = self.defs["CallingContext"][str(ref)]
            chain.append(str(d["region"]))
            ref = d["parent"]
        return chain[::-1]

    def calling_context(self, loc, t, k, d):
        chain = self.context_chain(d["callingContext"])
        stack = self.stacks[loc]
        if not chain:
            self.warnings["Unresolved calling context"] += 1
            return
        distance = (
            1 if k == "CallingContextLeave" else d.get("unwindDistance", 4294967295)
        )
        common = 0
        while (
            common < min(len(chain), len(stack))
            and stack[common]["region"] == chain[common]
        ):
            common += 1
        # OTF2 CallingContext: distance-1 leaf nodes are NEW invocations, even
        # when their region/context references are identical to the last sample.
        # Distance 1 preserves the progress frame, 0 preserves the whole stack.
        if distance == 4294967295:
            self.warnings[
                "Undefined calling-context unwind distance (estimated nesting)"
            ] += 1
        else:
            keep = max(0, len(chain) - max(0, distance - 1))
            if distance > len(chain) + 1 or common < keep:
                self.warnings["Inconsistent calling-context unwind distance"] += 1
            common = min(common, keep)
        while len(stack) > common:
            self.close(loc, t)
        for i, region in enumerate(chain[common:], common):
            # Only the leaf of an instrumented ENTER has an observed entry.
            # Ancestors recovered from unwinding and samples have estimated bounds.
            self.enter(
                loc, region, t, int(k != "CallingContextEnter" or i != len(chain) - 1)
            )
        if k == "CallingContextLeave" and stack:
            self.close(loc, t)
        if k == "CallingContextSample" and stack:
            self.add(
                "samples", (None, loc, t, stack[-1]["path"], str(d["callingContext"]))
            )

    def discard_task_stack(self, key):
        # Suspended frames have already been saved, possibly still in a batch.
        # Their terminal segment lacks a leave; retain that fact after discard.
        self.incomplete_task_spans.update(
            f["id"] for f in self.task_stacks.pop(key, [])
        )

    def invalidate_task_stack(self, loc, t):
        old = self.active_tasks.get(loc)
        if self.task_locations.get(old) == loc:
            self.task_locations.pop(old, None)
        while self.stacks[loc]:
            self.close(loc, t, 1)
        self.active_tasks[loc] = None

    def task_event(self, loc, t, k, d):
        key = task_identity(
            k, d, loc, lambda location: process_scope(self.defs, location)
        )
        if key is None:
            self.warnings[
                "Task event has invalid identity fields; execution context unresolved"
            ] += 1
            if not k.endswith("Create"):
                self.invalidate_task_stack(loc, t)
            return
        if k.endswith("Create"):
            if key in self.task_locations or key in self.task_stacks:
                self.warnings["Task identity recreated before recorded completion"] += 1
                self.task_conflicts.add(key)
                self.discard_task_stack(key)
            return
        old = self.active_tasks.get(loc, ("implicit", loc))
        self.leaf(loc, t)
        if "Complete" in k:
            if key != old:
                self.warnings["Task completion does not identify the active task"] += 1
                self.invalidate_task_stack(loc, t)
                other = self.task_locations.get(key)
                if other is not None:
                    self.warnings["Task completed on another active location"] += 1
                    self.invalidate_task_stack(other, self.last_event_time(other))
                self.discard_task_stack(key)
                self.task_conflicts.discard(key)
                return
            while self.stacks[loc]:
                self.close(loc, t, 1)
            self.active_tasks[loc] = None
            self.task_locations.pop(key, None)
            self.discard_task_stack(key)
            self.task_conflicts.discard(key)
            # Completion alone does not identify which task executes next. A
            # following TaskSwitch supplies that identity (OTF2 event contract).
            return
        if old == key:
            return
        if old is not None:
            suspended = self.stacks[loc]
            if self.task_locations.get(old) == loc:
                self.task_locations.pop(old, None)
            conflict = old in self.task_conflicts
            for f in suspended:
                self.save_frame(loc, f, t, int(conflict))
            if conflict:
                self.discard_task_stack(old)
            else:
                self.task_stacks[old] = suspended
        else:
            # Region records after an unresolved transition belong to an
            # unknown task. A later switch cannot adopt their open stack.
            while self.stacks[loc]:
                self.close(loc, t, 1)
        other = self.task_locations.get(key)
        if other is not None:
            self.warnings["Task identity active on multiple locations"] += 1
            self.task_conflicts.add(key)
            self.discard_task_stack(key)
            self.invalidate_task_stack(other, self.last_event_time(other))
        if key in self.task_conflicts:
            self.discard_task_stack(key)
        self.stacks[loc] = self.task_stacks.pop(key, [])
        self.active_tasks[loc] = key
        self.task_locations[key] = loc
        parent = 0
        for f in self.stacks[loc]:
            self.next_span += 1
            f.update(
                id=self.next_span, start=t, exclusive=0, parent=parent, continuation=1
            )
            parent = f["id"]
        self.last[loc] = t

    def stack_event(self, loc, t, k, d):
        if k == "Enter":
            self.enter(loc, d["region"], t)
        elif k == "Leave":
            self.leave(loc, d.get("region"), t)
        elif k in (
            "CallingContextEnter",
            "CallingContextLeave",
            "CallingContextSample",
        ):
            self.calling_context(loc, t, k, d)
        elif k in (
            "OmpTaskCreate",
            "ThreadTaskCreate",
            "OmpTaskSwitch",
            "ThreadTaskSwitch",
            "OmpTaskComplete",
            "ThreadTaskComplete",
        ):
            self.task_event(loc, t, k, d)

    def finish_stacks(self):
        for loc, stack in list(self.stacks.items()):
            while stack:
                self.warnings["Unclosed region (clipped at last event)"] += 1
                self.close(loc, self.last_event_time(loc), 1)
        self.warnings["Unclosed suspended task frames (clipped at suspension)"] += sum(
            map(len, self.task_stacks.values())
        )
        # The terminal saved segment of a suspended/discarded invocation has
        # no leave boundary and is already clipped at its last observation.
        self.incomplete_task_spans.update(
            f["id"] for stack in self.task_stacks.values() for f in stack
        )
        self.flush("spans")
        self.db.executemany(
            "UPDATE spans SET incomplete=1 WHERE id=?",
            ((sid,) for sid in self.incomplete_task_spans),
        )

    def last_event_time(self, loc):
        return self.last_events.get(loc, self.max_time)
