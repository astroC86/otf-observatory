"""Recorded CUDA driver context conversions and directed ownership.

The SDK distinguishes a converted green CUcontext from its primary context.
Only actual UINT64 handle values on the original API Leave supply outputs;
addresses of output parameters are never dereferenced or treated as handles.
"""

from __future__ import annotations
import collections
import bisect

from .api import api_result, cuda_api_name
from .stream_semantics import cuda_stream_epoch
from .mapping_records import GREEN, _GETTERS, MappingRecords

_EXPANDS_PRIMARY = {"cuctxsynchronize_v2", "cuctxrecordevent", "cuctxwaitevent"}


def context_mapping_api(item):
    return item["data"].get("paradigm") == "CUDA" and cuda_api_name(
        item["label"]
    ) in _GETTERS | {"cuctxfromgreenctx"}


class ContextMappings(MappingRecords):
    """Prove identities and answer queries over collected mapping records."""

    def __init__(self, trace, items, order, lifetimes, *, charge, warn, limit=150000):
        self.cache = {}
        self.conflicts = {}
        self.continuity = {}
        super().__init__(
            trace, items, order, lifetimes, charge=charge, warn=warn, limit=limit
        )

    def continuous(self, a, b):
        if self.incomplete or a["data"]["process"] != b["data"]["process"]:
            return False
        key = (a["id"], b["id"])
        if key in self.continuity:
            return self.continuity[key]
        first = min((a, b), key=lambda item: item["start"])
        last = max((a, b), key=lambda item: item["end"])
        start = first["start"]
        end = last["end"]
        valid = True
        for location, rows in self.measurement.get(a["data"]["process"], {}).items():
            if not self.charge():
                valid = False
                break
            index = bisect.bisect_left(rows, (start, -1, False))
            state = rows[index - 1][2] if index else True
            while index < len(rows) and rows[index][0] <= end:
                if not self.charge():
                    valid = False
                    break
                time, event, mode = rows[index]
                enter = (
                    self.order.boundary(first, "Enter")
                    if time == start and location == first["location"]
                    else None
                )
                leave = (
                    self.order.boundary(last, "Leave")
                    if time == end and location == last["location"]
                    else None
                )
                if enter is not None and event < enter:
                    state = mode
                    index += 1
                    continue
                if leave is not None and event > leave:
                    break
                if mode and state:
                    index += 1
                    continue
                valid = False
                break
            if not state or not valid:
                valid = False
                break
        if not valid:
            self.warn(
                "gpu-context-recording-gap",
                "Process recording gaps or unknown measurement state can hide handle destruction/reuse; no context identity proof crosses the gap.",
            )
        self.continuity[key] = valid
        return valid

    def _epoch_evidence(self, first, second, context):
        valid, epoch, old_evidence = self.lifetimes.at(first, context)
        current, now, new_evidence = self.lifetimes.at(second, context)
        if not valid or not current or (epoch and epoch["id"]) != (now and now["id"]):
            return None
        return old_evidence + new_evidence

    def _lifetime(self, observation, anchor, contexts):
        if (
            observation["data"]["process"] != anchor["data"]["process"]
            or observation["id"] != anchor["id"]
            and not self.order.before(observation, anchor)
        ):
            return None
        if not self.continuous(observation, anchor):
            return None
        evidence = []
        changes = self.invalidators.get(anchor["data"]["process"], []) + [
            change
            for context in contexts
            for change in self.primary_invalidators.get(
                (anchor["data"]["process"], context), []
            )
        ]
        for change in changes:
            if not self.charge():
                return None
            if self.order.before(change, observation) or self.order.before(
                anchor, change
            ):
                continue
            self.warn(
                "gpu-context-mapping-reset-unresolved",
                "A recorded primary-context release/reset may invalidate this mapping; a new ordered output is required.",
            )
            return None
        for context in contexts:
            current = self._epoch_evidence(observation, anchor, context)
            if current is None:
                return None
            evidence.extend(current)
        return list(dict.fromkeys(evidence))

    def _active(self, anchor, other):
        key = (anchor["id"], other["id"])
        if key in self.cache:
            return self.cache[key]
        rows = []
        for relation in self.relations:
            if not self.charge():
                return []
            contexts = (relation["source"], relation["target"])
            evidence = []
            valid = True
            witnesses = relation.get("witnesses", [relation["item"]])
            for witness in witnesses:
                a = self._lifetime(witness, anchor, contexts)
                b = self._lifetime(witness, other, contexts)
                if a is None or b is None:
                    valid = False
                    break
                evidence.extend(a + b)
            if valid and "witnesses" in relation:
                epochs = []
                for witness in witnesses + [anchor, other]:
                    live, epoch = cuda_stream_epoch(
                        witness,
                        self.lifecycle.get(relation["stream"], ()),
                        before=self.order.before,
                        charge=self.charge,
                    )
                    if not live:
                        valid = False
                        break
                    epochs.append(epoch["id"] if epoch is not None else None)
                    if epoch is not None:
                        evidence.extend(self.lifetimes.provenance(epoch))
                if len(set(epochs)) > 1:
                    valid = False
            if valid:
                rows.append(
                    dict(
                        relation,
                        evidence=list(dict.fromkeys(relation["evidence"] + evidence)),
                        status=(
                            "validated-recorded-getter-pair"
                            if "witnesses" in relation
                            else "recorded-output"
                        ),
                    )
                )
        converted = collections.defaultdict(set)
        parents = collections.defaultdict(set)
        for row in rows:
            if row["relation"] == "converted-green":
                converted[row["source"]].add(row["target"])
            else:
                parents[row["target"]].add(row["source"])
        bad = {source for source, targets in converted.items() if len(targets) > 1}
        bad |= {child for child, sources in parents.items() if len(sources) > 1}
        bad |= set(converted) & {
            source for sources in parents.values() for source in sources
        }
        regular = set()
        for row in self.regular:
            if not self.charge():
                return []
            if (
                self._lifetime(row["item"], anchor, [row["context"]]) is not None
                and self._lifetime(row["item"], other, [row["context"]]) is not None
            ):
                regular.add(row["context"])
        bad |= set(converted) & regular
        if bad:
            self.warn(
                "gpu-context-mapping-conflict",
                "Recorded conversion or primary ownership outputs conflict in a live context generation; the affected mapping is unresolved.",
            )
        rows = [
            row for row in rows if row["source"] not in bad and row["target"] not in bad
        ]
        self.conflicts[key] = bad
        self.cache[key] = rows
        return rows

    def proof(self, scope, context, anchor, other, *, containment=False):
        if self.incomplete:
            return None
        if scope is None or context is None:
            return None
        if not self.continuous(anchor, other):
            return None
        lifetime_evidence = []
        for value in {scope, context}:
            current = self._epoch_evidence(anchor, other, value)
            if current is None:
                return None
            lifetime_evidence.extend(current)
            observations = [
                item
                for item in self.observed.get((anchor["data"]["process"], value), [])
                if not self.order.before(anchor, item)
            ]
            if observations:
                witnessed = False
                for item in observations:
                    if not self.charge():
                        return None
                    a = self._lifetime(item, anchor, [value])
                    b = self._lifetime(item, other, [value])
                    if a is not None and b is not None:
                        lifetime_evidence.extend(item["evidence"] + a + b)
                        witnessed = True
                        break
                if not witnessed:
                    return None
        rows = self._active(anchor, other)
        adj = collections.defaultdict(list)
        if scope in self.conflicts.get(
            (anchor["id"], other["id"]), ()
        ) or context in self.conflicts.get((anchor["id"], other["id"]), ()):
            return None
        for candidate in (scope, context):
            known = False
            for row in self.converted.get((anchor["data"]["process"], candidate), []):
                if not self.charge():
                    return None
                if not self.order.before(anchor, row["item"]):
                    known = True
                    break
            if known and not any(
                row["relation"] == "converted-green" and row["source"] == candidate
                for row in rows
            ):
                return None
        if scope == context:
            proofs = [
                row
                for row in rows
                if row["relation"] == "converted-green" and row["source"] == context
            ]
            return self._proof_result(proofs, lifetime_evidence)
        for row in rows:
            if row["relation"] == "converted-green":
                adj[row["source"]].append((row["target"], row))
                adj[row["target"]].append((row["source"], row))
            elif containment and cuda_api_name(anchor["label"]) in _EXPANDS_PRIMARY:
                adj[row["source"]].append((row["target"], row))
        queue = [(scope, [])]
        seen = {scope}
        for node, path in queue:
            for target, row in adj[node]:
                if not self.charge():
                    return None
                if target in seen:
                    continue
                path2 = path + [row]
                if target == context:
                    return self._proof_result(path2, lifetime_evidence)
                seen.add(target)
                queue.append((target, path2))
        return None

    @staticmethod
    def _public(row):
        return {
            key: value for key, value in row.items() if key not in ("item", "witnesses")
        }

    def _proof_result(self, rows, evidence):
        return dict(
            evidence=list(
                dict.fromkeys(
                    evidence + [event for row in rows for event in row["evidence"]]
                )
            ),
            relations=[self._public(row) for row in rows],
        )

    def canonical(self, context, anchor):
        if self.proof(context, context, anchor, anchor) is None:
            return None
        for row in self._active(anchor, anchor):
            if row["relation"] == "converted-green" and row["source"] == context:
                return row["target"]
        return context

    def unify(self, contexts, anchor):
        contexts = set(contexts)
        if not contexts or None in contexts:
            return None
        chosen = min(contexts)
        evidence = []
        relations = []
        for context in contexts:
            proof = self.proof(chosen, context, anchor, anchor)
            if proof is None:
                return None
            evidence.extend(proof["evidence"])
            relations.extend(proof["relations"])
        return dict(
            context=chosen,
            evidence=list(dict.fromkeys(evidence)),
            relations=list({row["id"]: row for row in relations}.values()),
        )

    def stream_context(self, stream, anchor):
        rows = []
        for row in self.stream_rows.get(stream, []):
            if not self.charge():
                return None
            evidence = self._lifetime(
                row["item"], anchor, [row["scope"]] if row["scope"] is not None else []
            )
            if evidence is None:
                continue
            proof = (
                self.proof(row["scope"], row["scope"], anchor, row["item"])
                if row["scope"] is not None
                else dict(evidence=[], relations=[])
            )
            if proof is None:
                continue
            if row["api"] == "custreamgetctx" and not proof["relations"]:
                # Legacy GetCtx does not say whether its CUcontext represents
                # a green context. An unbridged green lifetime transition
                # cannot be dismissed by comparing the different handle bits.
                uncertain = False
                for change, _, _, _ in self.lifetimes.rows.get(
                    (anchor["data"]["process"], GREEN), []
                ):
                    if not self.charge():
                        return None
                    result = api_result(change)
                    if isinstance(result, int) and result != 0:
                        continue
                    if self.order.before(change, row["item"]) or self.order.before(
                        anchor, change
                    ):
                        continue
                    uncertain = True
                    break
                if uncertain:
                    continue
            valid, epoch = cuda_stream_epoch(
                row["item"],
                self.lifecycle.get(stream, ()),
                before=self.order.before,
                charge=self.charge,
            )
            current, now = cuda_stream_epoch(
                anchor,
                self.lifecycle.get(stream, ()),
                before=self.order.before,
                charge=self.charge,
            )
            if (
                not valid
                or not current
                or (epoch and epoch["id"]) != (now and now["id"])
            ):
                continue
            epoch_evidence = [
                event
                for change in (epoch, now)
                if change is not None
                for event in self.lifetimes.provenance(change)
            ]
            rows.append(
                dict(
                    row,
                    evidence=list(
                        dict.fromkeys(
                            row["evidence"]
                            + evidence
                            + proof["evidence"]
                            + epoch_evidence
                        )
                    ),
                )
            )
        if not rows:
            return None
        scopes = {row["scope"] for row in rows if row["scope"] is not None}
        no_green = any(row["noGreen"] for row in rows)
        if no_green and any(
            self.canonical(context, anchor) is not None
            and self.canonical(context, anchor)[0] == GREEN
            for context in scopes
        ):
            self.warn(
                "gpu-context-mapping-conflict",
                "A successful NULL-green observation contradicts the stream's recorded green context.",
            )
            return dict(conflict=True)
        unified = (
            self.unify(scopes, anchor)
            if scopes
            else dict(context=None, evidence=[], relations=[])
        )
        if unified is None:
            self.warn(
                "gpu-context-mapping-conflict",
                "Live stream context getters disagree without a proved converted-context equivalence.",
            )
            return dict(conflict=True)
        unified["evidence"] = list(
            dict.fromkeys(
                unified["evidence"]
                + [event for row in rows for event in row["evidence"]]
            )
        )
        unified["noGreen"] = no_green
        return unified
