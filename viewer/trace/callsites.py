"""Resolve the native OTF2 reader's reserved, typed source-callsite fields.

This is source-position evidence, never a dynamic invocation identifier. The
producer contract is recovered in docs/binary-gpu-correlations.md. Raw event
attributes and definition references remain unchanged.
"""

UINT32_MAX = (1 << 32) - 1
CALLSITE_LABEL = "Recorded source callsite"
RESERVED_TYPES = {
    "SOURCE_CODE_LOCATION": 20,
    "OTF2::CALLSITE_REGION": 14,
    "OTF2::CALLSITE_LINE": 3,
}


def _u32(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        result = int(value)
    except ValueError:
        return None
    return result if 0 <= result <= UINT32_MAX else None


class SourceCallsites:
    """Prepare definition lookups once, then resolve individual event lists.

    Attribute definitions must be in recorded order: the last correctly typed
    definition of each reserved name wins. Exact reserved names with other types
    are excluded from automatic GPU callsite matching, but remain raw attributes.
    """

    def __init__(self, definitions):
        self.definitions = definitions
        self.attributes = {}
        self.reserved_refs = set()
        strings = definitions.get("String", {})
        for ref, definition in definitions.get("Attribute", {}).items():
            name = strings.get(str(definition.get("name")), {}).get("string", "")
            if name in RESERVED_TYPES:
                self.reserved_refs.add(str(ref))
                if definition.get("type") == RESERVED_TYPES[name]:
                    self.attributes[name] = str(ref)
        self.attribute_refs = set(self.attributes.values())
        self.region_files = {}
        for ref, definition in definitions.get("Region", {}).items():
            file_ref = _u32(definition.get("sourceFile"))
            begin = _u32(definition.get("beginLineNumber", 0))
            end = _u32(definition.get("endLineNumber", 0))
            line = begin if begin not in (None, 0, UINT32_MAX) else end
            if file_ref not in (None, UINT32_MAX) and line not in (None, 0, UINT32_MAX):
                self.region_files[str(ref)] = file_ref
        # Score-P may declare the reserved attribute without recording any
        # source definitions. Avoid scanning millions of events for a field
        # that cannot resolve in this archive.
        self.scan_refs = set()
        modern = self.attributes.get("SOURCE_CODE_LOCATION")
        if modern is not None and definitions.get("SourceCodeLocation"):
            self.scan_refs.add(modern)
        region = self.attributes.get("OTF2::CALLSITE_REGION")
        line = self.attributes.get("OTF2::CALLSITE_LINE")
        if region is not None and line is not None and self.region_files:
            self.scan_refs.update((region, line))

    def _position(self, file_ref, line, **evidence):
        file_ref, line = _u32(file_ref), _u32(line)
        if file_ref in (None, UINT32_MAX) or line in (None, 0):
            return None
        return dict(
            key=f"source-file:{file_ref}:line:{line}",
            fileRef=str(file_ref),
            file=self.definitions.get("String", {})
            .get(str(file_ref), {})
            .get("string", ""),
            line=line,
            **evidence,
        )

    def extract(self, attributes):
        """Return one resolved position, applying modern then legacy precedence.

        A legacy pair only overrides when its region is in the reader's eligible
        region/file map. With an eligible region, line zero invalidates an earlier
        modern position. Incomplete legacy pairs do not establish any source site.
        """
        values = {}
        for attribute in attributes:
            ref = str(attribute.get("ref"))
            if ref in self.attribute_refs and ref not in values:
                expected = (
                    self.definitions.get("Attribute", {}).get(ref, {}).get("type")
                )
                if attribute.get("type", expected) == expected:
                    values[ref] = attribute.get("value")
        result = None
        modern = self.attributes.get("SOURCE_CODE_LOCATION")
        if modern in values:
            source_ref = _u32(values[modern])
            source = self.definitions.get("SourceCodeLocation", {}).get(str(source_ref))
            if source is not None:
                result = self._position(
                    source.get("file"),
                    source.get("lineNumber"),
                    encoding="SOURCE_CODE_LOCATION",
                    attributes=[modern],
                    sourceCodeLocation=str(source_ref),
                )
        region = self.attributes.get("OTF2::CALLSITE_REGION")
        line = self.attributes.get("OTF2::CALLSITE_LINE")
        if region in values and line in values:
            region_ref = str(_u32(values[region]))
            if region_ref in self.region_files:
                result = self._position(
                    self.region_files[region_ref],
                    values[line],
                    encoding="OTF2::CALLSITE_REGION + OTF2::CALLSITE_LINE",
                    attributes=[region, line],
                    region=region_ref,
                )
        return result
