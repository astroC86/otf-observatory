"""Shared native state-record normalization and Tree finalization.

The finalizer seed comes from the four completed backend ranges. Tree closing
time then carries across every allocated execution location in definition order,
including locations outside the current display selection.
"""

import collections
import heapq
import json
import math

from .state_tree_finalizer import finalize_state_tree_records
from .state_stack_finalizer import finalize_state_stack_records
from ..trace.schema import STATE_TRANSITION_PREDICATE

TREE_KINDS = "('CallingContextEnter','CallingContextLeave','CallingContextSample')"


class StateRecordStore:
    """Own cached records and the shared direct-read/lifecycle input allowance.

    Lazy session caches remain unset until their full computation succeeds.
    Caller-supplied fetchers retain their own input accounting.
    """

    def __init__(
        self, trace, fetch=None, charge=lambda work: None, limit=1_000_000, seed=None
    ):
        self.trace, self._fetch, self.charge, self.limit = trace, fetch, charge, limit
        self._seed = seed
        self._ends = None
        self._tree = {}
        self._stack = {}
        self._chains = {}
        self._resets = None
        self.diagnostics = collections.Counter()
        self._read = 0
        clock = trace.meta.get("clock", {})
        self.resolution = int(clock.get("resolution", 0))
        self.offset = int(clock.get("offset", 0))
        if self.resolution <= 0:
            raise ValueError(
                "State sources require a positive recorded clock resolution"
            )
        self.tick_seconds = 1 / self.resolution
        self.recorded_ticks = trace.meta.get("format") in ("OTF", "OTF2")

    def _account(self, work):
        self._read += work
        self.charge(work)
        if self._read > self.limit:
            raise ValueError("State source input limit exceeded")

    def fetch(self, sql, args=()):
        if self._fetch is not None:
            yield from self._fetch(sql, args)
            return
        with self.trace.connect() as db:
            for row in db.execute(sql, args):
                self._account(1)
                yield dict(row)

    @property
    def seed(self):
        if self._seed is None:
            from .state_finalization import native_state_end_seed

            self._seed = native_state_end_seed(
                self.trace, charge=self.charge, limit=self.limit
            )
            for row in self._seed.get("diagnostics", []):
                self.diagnostics[row["code"]] += row["count"]
        return self._seed

    def native_time(self, row):
        if self.recorded_ticks:
            try:
                delta = int(row["tick"]) - self.offset
                # Indexes created by the importer retain this exact seconds
                # conversion alongside the original integer tick string.
                expected = delta / self.resolution
                if expected != row["time"] and not math.isclose(
                    expected, row["time"], rel_tol=2e-15, abs_tol=0
                ):
                    raise ValueError
                return float(delta)
            except (ValueError, TypeError, KeyError, OverflowError):
                self.diagnostics["state-original-tick-unavailable"] += 1
        # Independently constructed normalized fixtures and legacy indexes
        # can still supply time in seconds without fabricated integer ticks.
        return row["time"] * self.resolution

    def location_order(self):
        definitions = self.trace.defs.get("Location", {})
        if definitions:
            return [
                str(ref)
                for ref, definition in definitions.items()
                if definition.get("locationType") != 3
            ]
        return [
            str(ref)
            for ref, definition in self.trace.locations.items()
            if definition.get("type") != "METRIC"
        ]

    def tree_resets(self):
        """Recover lifecycle-produced empty snapshots, without copying attrs.

        Reader mode +0x1a4 is changed by context records and thread/team Begin.
        Accepted non-primary TeamEnd changes it to2 after emitting; ThreadEnd
        emits while mode1 but changes only the remembered context, not mode.
        A predecessor query avoids decoding complete unselected sample streams
        merely to establish the mode at a sparse lifecycle endpoint.
        """
        if self._resets is not None:
            return self._resets
        resets = collections.defaultdict(list)
        if self.trace.meta.get("format") == "OTF":
            self._resets = resets
            return resets
        ends = list(
            self.fetch(
                "SELECT id,location,time,tick,kind,data FROM events WHERE kind IN ('ThreadEnd','ThreadTeamEnd') AND location IN (SELECT DISTINCT location FROM events WHERE kind IN "
                + TREE_KINDS
                + ") ORDER BY location,id"
            )
        )
        if not ends:
            self._resets = resets
            return resets
        accepted_teams = set()
        if any(row["kind"] == "ThreadTeamEnd" for row in ends):
            from ..threads.barriers import native_barriers

            controls = native_barriers(
                self.trace,
                diagnostics=self.diagnostics,
                tick_domain=True,
                charge=self._account,
                include_regions=False,
            )
            accepted_teams = {
                row["event"]
                for row in controls["operations"]
                if row["operation"] == "JOIN" and row["location"] != row["primary"]
            }
        definitions = self.trace.defs

        def known_comm(ref):
            if type(ref) is not int or not 0 <= ref < 4294967295:
                return False
            comm = definitions.get("Comm", {}).get(str(ref))
            inter = definitions.get("InterComm", {}).get(str(ref))
            refs = (
                [comm.get("group")]
                if comm
                else [inter.get("groupA"), inter.get("groupB")] if inter else []
            )
            groups = [
                definitions.get("Group", {}).get(str(group), {}) for group in refs
            ]
            return (
                bool(groups)
                and all(group.get("groupType") in (5, 6) for group in groups)
                and all(
                    group.get("paradigm") == groups[0].get("paradigm")
                    for group in groups
                )
            )

        cleared = {}
        for row in ends:
            self.charge(1)
            loc = str(row["location"])
            team = row["kind"] == "ThreadTeamEnd"
            if team:
                if row["id"] not in accepted_teams:
                    continue
            elif not known_comm(json.loads(row["data"]).get("threadContingent")):
                continue
            previous = next(
                self.fetch(
                    "SELECT id,kind,json_extract(data,'$.callingContext') ref FROM events WHERE location=? AND id<? AND "
                    + STATE_TRANSITION_PREDICATE
                    + " ORDER BY id DESC LIMIT 1",
                    (loc, row["id"]),
                ),
                None,
            )
            active = bool(
                previous
                and previous["id"] > cleared.get(loc, -1)
                and (
                    previous["kind"] in ("CallingContextEnter", "CallingContextLeave")
                    or previous["kind"] == "CallingContextSample"
                    and str(previous["ref"]) != "4294967295"
                )
            )
            if active:
                resets[loc].append(
                    dict(
                        row,
                        raw={},
                        native_kind=0,
                        chain=(),
                        source_kind=row["kind"],
                        synthetic=(
                            "native-thread-team-end-reset"
                            if team
                            else "native-thread-end-reset"
                        ),
                    )
                )
            if team:
                cleared[loc] = row["id"]
        self._resets = resets
        return resets

    def tree_ends(self):
        if self._ends is None:
            latest = {}
            # All rows tied for the largest normalized timestamp are retained
            # so original-tick rounding cannot pick an earlier tied endpoint.
            sql = (
                "WITH last AS (SELECT location,max(time) time FROM events WHERE kind IN "
                + TREE_KINDS
                + " GROUP BY location) SELECT e.location,e.time,e.tick FROM events e JOIN last l "
                "ON e.location=l.location AND e.time=l.time WHERE e.kind IN "
                + TREE_KINDS
            )
            for row in self.fetch(sql):
                t = self.native_time(row)
                loc = str(row["location"])
                latest[loc] = max(latest.get(loc, 0.0), t)
            for loc, rows in self.tree_resets().items():
                for row in rows:
                    t = self.native_time(row)
                    latest[loc] = max(latest.get(loc, 0.0), t)
            running = self.seed["endTicks"]
            ends = {}
            for loc in self.location_order():
                self.charge(1)
                running = max(running, latest.get(loc, 0.0) + 1.0)
                ends[loc] = running
            self._ends = ends
        return self._ends

    def chain(self, ref):
        if ref not in self._chains:
            definitions = self.trace.defs.get("CallingContext", {})
            chain = []
            seen = set()
            current = ref
            while current in definitions and current not in seen:
                self.charge(1)
                seen.add(current)
                definition = definitions[current]
                chain.append((current, str(definition["region"])))
                current = str(definition.get("parent"))
            if current in seen:
                self.diagnostics["cyclic-calling-context"] += 1
            if not chain and ref != "4294967295":
                self.diagnostics["missing-calling-context"] += 1
            self._chains[ref] = tuple(reversed(chain))
        return self._chains[ref]

    def _to_seconds(self, records):
        """Retain native ticks before converting normalized records in place."""
        for row in records:
            row["native_time"] = row["time"]
            row["time"] *= self.tick_seconds

    def tree(self, loc):
        if loc not in self._tree:
            normalized = []
            previous = 0.0
            rows = self.fetch(
                "SELECT id,time,tick,kind,data FROM events WHERE location=? AND kind IN "
                + TREE_KINDS
                + " ORDER BY id",
                (loc,),
            )
            for row in heapq.merge(
                rows,
                self.tree_resets().get(str(loc), ()),
                key=lambda record: record["id"],
            ):
                self.charge(1)
                previous = max(previous, self.native_time(row))
                if "native_kind" in row:
                    normalized.append(
                        dict(
                            id=row["id"],
                            time=previous,
                            kind=0,
                            chain=(),
                            raw={},
                            attributes=(),
                            has_attributes=False,
                            source_kind=row["source_kind"],
                            synthetic=row["synthetic"],
                        )
                    )
                    continue
                raw = json.loads(row["data"])
                ref = str(raw.get("callingContext"))
                kind = {
                    "CallingContextEnter": 2,
                    "CallingContextLeave": 3,
                    "CallingContextSample": 1,
                }[row["kind"]]
                if row["kind"] == "CallingContextSample" and ref == "4294967295":
                    kind = 0
                normalized.append(
                    dict(
                        id=row["id"],
                        time=previous,
                        kind=kind,
                        chain=self.chain(ref),
                        raw=raw,
                    )
                )
            end = self.tree_ends().get(str(loc))
            if end is None:
                raise ValueError(
                    "StateTree location has no native execution-location allocation"
                )
            normalized, _ = finalize_state_tree_records(
                normalized, end, 1.0, self.charge
            )
            self._to_seconds(normalized)
            self._tree[loc] = normalized
        return self._tree[loc]

    def stack(self, loc):
        if loc not in self._stack:
            normalized = []
            stack = []
            previous = 0.0
            issues = collections.Counter()
            for row in self.fetch(
                "SELECT id,time,tick,kind,data FROM events WHERE location=? AND kind IN ('Enter','Leave') ORDER BY id",
                (loc,),
            ):
                self.charge(1)
                raw = json.loads(row["data"])
                region = str(raw.get("region"))
                previous = max(previous, self.native_time(row))
                record = dict(
                    id=row["id"],
                    time=previous,
                    kind=row["kind"],
                    raw=raw,
                    region=region,
                )
                if row["kind"] == "Enter":
                    if raw.get("region") is None:
                        issues["unresolved-stack-region"] += 1
                    stack.append(record)
                elif stack:
                    entry = stack.pop()
                    record["entry"] = entry["id"]
                    record["region"] = entry["region"]
                    if raw.get("region") is not None and region != entry["region"]:
                        issues["mismatched-stack-leave"] += 1
                else:
                    issues["unmatched-stack-leave"] += 1
                normalized.append(record)
            if stack:
                if issues:
                    issues["unclosed-stack-entry"] = len(stack)
                else:
                    # Unlike Tree, each Stack location receives the original
                    # seed independently, without a previous-location carry.
                    normalized, _ = finalize_state_stack_records(
                        normalized, self.seed["endTicks"], 1.0, self.charge
                    )
            self._to_seconds(normalized)
            self._stack[loc] = (normalized, dict(issues))
        return self._stack[loc]
