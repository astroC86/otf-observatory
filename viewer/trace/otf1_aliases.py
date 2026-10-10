"""OTF1 process substitutions used by native stack/tree metric sources.

The reader callback at 0x1104220 assigns each known member's canonical process
to a known representative. Metric constructors follow that assignment once;
it is not a graph traversal. Original records remain available to the caller.
"""

from __future__ import annotations

import re

_HEX = r"[0-9a-fA-F]+"
_SHORT = re.compile(r"DPS(" + _HEX + r")M(.*)")
_LONG = re.compile(r"DEFPROCESSSUBSTITUTES\s+(" + _HEX + r")\s+MEMBERS\s*(.*)")
_PROCESS = re.compile(
    r"(?:DP(" + _HEX + r")NM|DEFPROCESS\s+(" + _HEX + r')\s+NAME\s*)"'
)
_UINT32_MAX = (1 << 32) - 1


def parse_process_substitutes(raw):
    """Parse the short/long OTF1 writer syntax, or return None for other rows.

    Tokens are hexadecimal unsigned 32-bit process IDs. The native writer uses a
    comma after every member; accepting the final comma as optional also permits
    the reader's list terminator at end of line. Malformed recognized records raise
    ValueError so replay can report their omission rather than silently aliasing.
    """
    raw = raw.strip()
    if not raw.startswith(("DPS", "DEFPROCESSSUBSTITUTES")):
        return None
    match = _SHORT.fullmatch(raw) or _LONG.fullmatch(raw)
    if match is None:
        raise ValueError("Malformed OTF1 process substitution")
    representative = int(match[1], 16)
    tail = match[2].strip().removesuffix(",")
    tokens = tail.split(",") if tail else []
    if any(re.fullmatch(_HEX, token.strip()) is None for token in tokens):
        raise ValueError("Malformed OTF1 process substitution member list")
    members = [int(token.strip(), 16) for token in tokens]
    if representative > _UINT32_MAX or any(member > _UINT32_MAX for member in members):
        raise ValueError("OTF1 process substitution exceeds uint32")
    return dict(representative=representative, members=members, raw=raw)


class Otf1ProcessAliases:
    """Replay raw definitions, preserving validation and assignment order.

    Known processes come from preceding DefProcess rows. An unknown representative
    discards the substitution; an unknown member discards only that member. A
    representative listed as its own member does not overwrite an earlier alias.
    Duplicate assignments use the last valid record. No mutation of trace data or
    automatic counter/operation redirection occurs here.
    """

    def __init__(self, raw_definitions=(), charge=lambda work: None):
        self.aliases = {}
        self.skipped = {}
        self.known = set()
        self.assignments = []
        for definition in raw_definitions:
            charge(1)
            raw = (
                definition.get("raw", "")
                if isinstance(definition, dict)
                else definition
            )
            raw = raw.strip()
            process = _PROCESS.match(raw)
            if process:
                ident = int(process[1] or process[2], 16)
                if ident <= _UINT32_MAX:
                    self.known.add(str(ident))
                else:
                    self._skip("process-out-of-range")
                continue
            try:
                record = parse_process_substitutes(raw)
            except ValueError:
                self._skip("malformed-process-substitution")
                continue
            if record is None:
                continue
            representative = str(record["representative"])
            if representative not in self.known:
                self._skip("unknown-substitution-representative")
                continue
            for member in record["members"]:
                charge(1)
                member = str(member)
                if member == representative:
                    continue
                if member not in self.known:
                    self._skip("unknown-substitution-member")
                    continue
                self.aliases[member] = representative
                self.assignments.append((member, representative))

    @classmethod
    def from_definitions(cls, definitions, charge=lambda work: None):
        # Raw definitions were retained even by indexes preceding the dedicated
        # Otf1ProcessSubstitutes record, so no cache rewrite is necessary.
        records = definitions.get("Otf1Definition", {})
        return cls(records.values() if isinstance(records, dict) else records, charge)

    def _skip(self, reason):
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def canonical(self, location):
        location = str(location)
        return self.aliases.get(location, location)
