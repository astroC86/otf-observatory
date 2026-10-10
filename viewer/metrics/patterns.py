"""Function-name selectors recovered from the native custom-metric translator."""


def function_patterns(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError(
            "Function patterns must be a string of at most 4096 characters"
        )
    return [pattern for item in value.split(";") if (pattern := item.strip(" \n\r\t"))]


def function_matches(name, patterns):
    """Case-sensitive whole-name matching: only asterisk is a wildcard."""
    for pattern in patterns:
        if pattern == "*":
            return True
        pieces = pattern.split("*")
        if len(pieces) == 1:
            if name == pattern:
                return True
            continue
        if not name.startswith(pieces[0]):
            continue
        cursor = len(pieces[0])
        matched = True
        for piece in pieces[1:-1]:
            index = name.find(piece, cursor)
            if index < 0:
                matched = False
                break
            cursor = index + len(piece)
        if (
            matched
            and name.endswith(pieces[-1])
            and len(name) - len(pieces[-1]) >= cursor
        ):
            return True
    return False


def io_paradigm_ids(trace, value):
    """Exact recorded display name, with numeric IDs as an explicit extension."""
    wanted = str(value)
    return {
        row["id"]
        for row in io_paradigms(trace)
        if wanted in (row["id"], row["name"], row["recordedName"])
    }


def io_paradigms(trace):
    strings = trace.defs.get("String", {})
    rows = []
    for ref, definition in trace.defs.get("IoParadigm", {}).items():
        name = strings.get(str(definition.get("name")), {}).get("string", "")
        rows.append(
            dict(
                id=str(ref),
                recordedName=name,
                name="MPI I/O" if name == "MPI-IO" else name,
            )
        )
    return rows
