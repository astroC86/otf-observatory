"""Native StateTree attribute storage and lookup, recovered by static audit.

The two integer namespaces deliberately remain separate. Producers store local
attributes under an event-record index; SignalSourceTreeXAttr looks them up with
a global context-definition index. Equal numbers can therefore select an
attribute from another record. See docs/binary-state-tree-attributes.md.
"""

from collections.abc import Mapping

MISSING_ATTRIBUTE = object()
UNDEFINED_CONTEXT = "4294967295"


def _pairs(values):
    return values.items() if isinstance(values, Mapping) else values


class StateTreeAttributeMap:
    """Build one location's native attribute maps from normalized records.

    ``context_refs`` preserves global CallingContext definition order. ``records``
    is the full local StateTree sequence, with ``id``, ``kind`` (0 reset, 1 sample,
    2 enter, 3 leave), and optional ``attributes`` pairs or mapping. Attribute keys
    are caller-defined stable identities; values have already undergone native
    type conversion. Undefined context has index zero; distinct definitions begin
    at one. Repeated definitions retain their initial index.

    ``global_attributes`` maps raw context references to pairs. ``entry_attributes``
    maps entry event IDs to later invocation attachments (e.g. Parameters), whereas
    ``entry_overrides`` replaces values in the initial entry map (e.g. TaskSwitch).
    Both attach before Leave attributes, as they do while the invocation is open.
    The caller supplies generated attributes in native append order.

    Lookup returns the first matching local ID, including NaN/None, and only uses
    global properties when that ID is absent locally. Passing ``default`` permits
    the caller to retain its own missing-value sentinel.
    """

    def __init__(
        self,
        context_refs,
        records,
        global_attributes=None,
        entry_attributes=None,
        entry_overrides=None,
        charge=lambda work: None,
    ):
        self.charge = charge
        self.context_indices = {UNDEFINED_CONTEXT: 0, "-1": 0}
        next_index = 1
        for ref in context_refs:
            charge(1)
            ref = str(ref)
            if ref not in self.context_indices:
                self.context_indices[ref] = next_index
                next_index += 1
        self.local_attributes, self.global_attributes = {}, {}
        self._local_first, self._global_first = {}, {}
        self.entry_indices = {}
        self.skipped = {}
        entry_attributes = entry_attributes or {}
        entry_overrides = entry_overrides or {}
        for ref, attributes in (global_attributes or {}).items():
            index = self.context_indices.get(str(ref))
            if index is not None:
                self._append(
                    self.global_attributes, self._global_first, index, attributes
                )
        stack = []
        self.record_count = 0
        for index, record in enumerate(records, 1):
            charge(1)
            self.record_count = index
            kind = record["kind"]
            attributes = record.get("attributes", ())
            attribute_index = index
            if kind == 2:
                entry = record["id"]
                self.entry_indices[entry] = index
                stack.append(index)
                # The reader mutates the event's initial attribute map before
                # the producer appends it. Dict assignment keeps other IDs.
                if entry in entry_overrides:
                    attributes = dict(_pairs(attributes))
                    for key, value in _pairs(entry_overrides[entry]):
                        charge(1)
                        attributes[key] = value
            elif kind == 3:
                if not stack:
                    # Native pop on an empty stack has no established useful
                    # result. Retain the record index but report the omission.
                    for _ in _pairs(attributes):
                        charge(1)
                        self.skipped["unmatched-leave-attributes"] = (
                            self.skipped.get("unmatched-leave-attributes", 0) + 1
                        )
                        break
                    continue
                attribute_index = stack.pop()
            self._append(
                self.local_attributes, self._local_first, attribute_index, attributes
            )
            if kind == 2:
                self._append(
                    self.local_attributes,
                    self._local_first,
                    index,
                    entry_attributes.get(entry, ()),
                )

    def _append(self, storage, first, index, attributes):
        for key, value in _pairs(attributes):
            self.charge(1)
            values = first.setdefault(index, {})
            previous = values.get(key, MISSING_ATTRIBUTE)
            # eeb8d0/eec0f0 suppress a value equal to the first existing value;
            # different values append, but lookup still returns the first.
            # None is the normalized native NaN and never compares equal.
            if (
                previous is MISSING_ATTRIBUTE
                or value is None
                or previous is None
                or value != previous
            ):
                storage.setdefault(index, []).append((key, value))
                values.setdefault(key, value)

    def lookup_index(self, context_index, attribute, default=MISSING_ATTRIBUTE):
        """Use a global context index to probe the event-indexed local map."""
        self.charge(1)
        local = self._local_first.get(context_index, {})
        if attribute in local:
            return local[attribute]
        return self._global_first.get(context_index, {}).get(attribute, default)

    def lookup(self, context_ref, attribute, default=MISSING_ATTRIBUTE):
        index = self.context_indices.get(str(context_ref))
        if index is None:
            return default
        return self.lookup_index(index, attribute, default)
