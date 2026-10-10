"""OTF2 metric attribute conversion recovered from native reader 0x1072500.

The raw OTF2 reference is not generally the value consumed by a metric.  Keep
conversion failure separate from a valid NaN: failed lookups are omitted by the
reader, allowing later invocation attributes or global properties to supply it.
Definition rows must be in original order, including duplicate definitions.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import struct

ACCEPTED_TYPES = frozenset(range(1, 12)) | {13, 14, 17, 19, 25}
RESERVED_ATTRIBUTES = {
    "SOURCE_CODE_LOCATION": 20,
    "OTF2::CALLSITE_REGION": 14,
    "OTF2::CALLSITE_LINE": 3,
}
REFERENCE_KINDS = {17: "communicator", 19: "rma-window", 25: "location-group"}
WINDOW_USES_COMM_DEFAULTS = frozenset((5, 13, 18, 19, 23, 24, 25))


@dataclass(frozen=True, slots=True)
class Conversion:
    value: float | None = None
    reason: str | None = None
    text: str | None = None

    @property
    def accepted(self):
        return self.reason is None

    @property
    def unresolved(self):
        return bool(self.reason and self.reason.startswith("unrecovered-"))


def _integer(value, bits, signed=False):
    """Validate the typed reader input without rounding uint64 through float."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a typed integer")
    if isinstance(value, str):
        value = int(value, 10)
    if not isinstance(value, int):
        raise ValueError("noninteger typed value")
    lower = -(1 << (bits - 1)) if signed else 0
    upper = 1 << (bits - 1 if signed else bits)
    if not lower <= value < upper:
        raise ValueError("integer outside type range")
    return value


def _signed32(value):
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


class AttributeReferences:
    """Replay reader definitions for attribute-reference conversion.

    Rows have ``kind``, ``ref`` and decoded or JSON ``data`` fields. ``properties``
    retains (definition, Conversion) pairs evaluated at their definition position,
    so a later Location/String definition cannot repair an earlier failed lookup.
    Event attributes use ``convert`` after replay. Shared reference indices require
    ArchiveProperties.numberOfLocations, which initializes the native allocator;
    an old cache without it reports uncertainty rather than inferring a raw value.
    """

    def __init__(self, definitions=(), charge=lambda work: None):
        self.charge = charge
        self.strings = {}
        self.string_values = {}
        self.locations = {}
        self.attributes = {}
        self.properties = []
        self.next_location = 0
        self.next_shared = None
        self.shared_reason = "unrecovered-reference-archive-location-count"
        self.major = None
        self.location_groups = {}
        self.worlds = {}
        self.groups = {}
        self.ignored_groups = set()
        self.communicators = {}
        self.ignored_communicators = set()
        self.windows = {}
        self.window_uses_comm = dict.fromkeys(WINDOW_USES_COMM_DEFAULTS, True)
        rows = []
        for row in definitions:
            charge(1)
            kind = row["kind"]
            data = row["data"]
            if isinstance(data, str):
                data = json.loads(data)
            ref = str(row.get("ref", data.get("self", "")))
            rows.append((kind, ref, data))
            if kind == "ArchiveProperties":
                self.major = data.get("major")
                try:
                    self.next_shared = (
                        _integer(data["numberOfLocations"], 64) & 0xFFFFFFFF
                    )
                    self.shared_reason = None
                except (KeyError, ValueError, TypeError):
                    pass
        for kind, ref, data in rows:
            charge(1)
            if kind == "String":
                self.strings[ref] = data.get("string", "")
            elif kind == "Location":
                if data.get("locationType") == 3:
                    self.locations[ref] = -1
                else:
                    self.locations[ref] = _signed32(self.next_location)
                    self.next_location = (self.next_location + 1) & 0xFFFFFFFF
            elif kind == "Attribute":
                name = self.strings.get(str(data.get("name")), "")
                value_type = data.get("type")
                if (
                    value_type in ACCEPTED_TYPES
                    and RESERVED_ATTRIBUTES.get(name) != value_type
                ):
                    self.attributes[ref] = value_type
            elif kind == "CallingContextProperty":
                self.properties.append(
                    (data, self.convert(data.get("value"), data.get("type")))
                )
            else:
                self._shared_definition(kind, ref, data)

    def _allocate(self):
        if self.next_shared is None:
            return None
        result = _signed32(self.next_shared)
        self.next_shared = (self.next_shared + 1) & 0xFFFFFFFF
        return result

    def _shared_definition(self, kind, ref, data):
        """Replay only allocation/lookup effects, without changing raw IDs."""
        if kind == "SystemTreeNode":
            # 103fbb0 replaces duplicate node definitions and always allocates.
            self._allocate()
        elif kind == "LocationGroup":
            group_type = data.get("locationGroupType")
            if group_type != 1:
                if self.major is None:
                    self.next_shared = None
                    self.shared_reason = "unrecovered-reference-archive-version"
                    self.location_groups[ref] = None
                    return
                if self.major < 3:
                    return
            self.location_groups[ref] = self._allocate()
        elif kind == "Group":
            group_type, paradigm = data.get("groupType"), data.get("paradigm")
            members = data.get("members", ())
            self.charge(len(members))
            if group_type == 1:
                if all(self.locations.get(str(member), -1) >= 0 for member in members):
                    self._allocate()
            elif group_type in (4, 7) and members:
                # An invalid world member clears its vectors, but the first
                # world still consumed its ID before member validation.
                if paradigm not in self.worlds:
                    self._allocate()
                if group_type == 4:
                    valid = all(
                        self.locations.get(str(member), -1) >= 0 for member in members
                    )
                else:
                    valid = all(
                        str(member & 0xFFFFFFFF) in self.location_groups
                        for member in members
                    )
                self.worlds[paradigm] = len(members) if valid else 0
            elif group_type == 5 and paradigm in self.worlds:
                if all(0 <= member < self.worlds[paradigm] for member in members):
                    self.groups[ref] = paradigm
            elif group_type == 6 and paradigm == 4:
                self.ignored_groups.add(ref)
        elif kind in ("Comm", "InterComm"):
            group = str(data.get("group" if kind == "Comm" else "groupA"))
            if group not in self.groups:
                if kind == "Comm" and group in self.ignored_groups:
                    self.ignored_communicators.add(ref)
                return
            paradigm = self.groups[group]
            if kind == "InterComm":
                other = str(data.get("groupB"))
                if other not in self.groups or self.groups[other] != paradigm:
                    return
            self.communicators[ref] = (self._allocate(), paradigm)
        elif kind == "RmaWin":
            comm = str(data.get("comm"))
            if comm in self.ignored_communicators or comm not in self.communicators:
                return
            index, paradigm = self.communicators[comm]
            self.windows[ref] = (
                index
                if self.window_uses_comm.get(paradigm, False)
                else self._allocate()
            )
        elif (
            kind == "ParadigmProperty"
            and data.get("property") == 2
            and data.get("type") == 1
        ):
            self.window_uses_comm[data.get("paradigm")] = data.get("value") == 1

    def registered(self, ref):
        return str(ref) in self.attributes

    def convert(self, value, value_type):
        """Return native binary64 or an explicit omission/unrecovered reason.

        Registration rejects unsupported OTF2 attribute types before calling the
        converter. This interface applies that registration guard too. Values already
        read by OTF2 fit their declared union field; malformed hand-built rows are
        reported rather than masked into an unrelated reference.
        """
        self.charge(1)
        if value_type not in ACCEPTED_TYPES:
            return Conversion(reason="unsupported-attribute-type")
        try:
            if value_type in range(1, 9):
                bits = (8, 16, 32, 64)[(value_type - 1) % 4]
                return Conversion(float(_integer(value, bits, value_type >= 5)))
            if value_type in (9, 10):
                value = float(value)
                if value_type == 9:
                    try:
                        value = struct.unpack("f", struct.pack("f", value))[0]
                    except OverflowError:
                        value = math.copysign(math.inf, value)
                return Conversion(value)
            ref = str(_integer(value, 64 if value_type == 13 else 32))
        except (ValueError, TypeError, OverflowError):
            return Conversion(reason="invalid-typed-attribute-value")
        if value_type == 11:
            if ref not in self.strings:
                return Conversion(reason="undefined-string-reference")
            # e979f0 registers the text only on the first successful conversion.
            text = self.string_values.setdefault(ref, self.strings[ref])
            return Conversion(float(int(ref)), text=text)
        if value_type == 13:
            if ref not in self.locations:
                return Conversion(reason="undefined-location-reference")
            index = self.locations[ref]
            if index < 0:
                return Conversion(reason="nonexecution-location-reference")
            return Conversion(float(index))
        if value_type == 14:
            # Unlike the other reference paths, this has no definition lookup.
            return Conversion(float(int(ref)))
        mapping = {17: self.communicators, 19: self.windows, 25: self.location_groups}[
            value_type
        ]
        if ref not in mapping:
            # Missing archive metadata does not make a missing definition a
            # valid reference; the native lookup still fails in that case.
            return Conversion(
                reason="undefined-" + REFERENCE_KINDS[value_type] + "-reference"
            )
        index = mapping[ref][0] if value_type == 17 else mapping[ref]
        if index is None:
            return Conversion(
                reason=self.shared_reason or "unrecovered-shared-reference-index"
            )
        return Conversion(float(index))
