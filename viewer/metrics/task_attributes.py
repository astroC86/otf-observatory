"""One-shot task ID attributes synthesized by the native OTF2 reader.

Only explicit Enter/Leave events change this reader stack. Calling-context
samples and task completion callbacks do not consume a pending task switch.
"""

UNDEFINED_TASK = 2**64 - 1


def task_attribute_values(events, region_roles, contexts, has_task_attribute, charge):
    """Map entry event IDs to native binary64 synthetic Task ID values."""
    stack = []
    pending = UNDEFINED_TASK
    values = {}

    def identity(kind, raw):
        if kind.startswith("Omp"):
            value = raw.get("taskID")
        else:
            creator, generation = raw.get("creatingThread"), raw.get("generationNumber")
            if not all(
                isinstance(v, int) and not isinstance(v, bool) and 0 <= v < 2**32
                for v in (creator, generation)
            ):
                return UNDEFINED_TASK
            value = (creator << 32) | generation
        return (
            value
            if isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= UNDEFINED_TASK
            else UNDEFINED_TASK
        )

    for event in events:
        charge(1)
        kind = event["kind"]
        raw = event["data"]
        ident = event["id"]
        if kind in ("OmpTaskSwitch", "ThreadTaskSwitch"):
            pending = identity(kind, raw)
        elif kind in ("Enter", "CallingContextEnter"):
            region = raw.get("region")
            if region is None:
                region = contexts.get(str(raw.get("callingContext")), {}).get("region")
            role = region_roles.get(str(region))
            if pending != UNDEFINED_TASK and role in (20, "TASK"):
                # The synthesized entry map assignment overwrites an existing
                # raw Task ID, including a recorded NaN.
                values[ident] = float(pending)
            pending = UNDEFINED_TASK
            stack.append((ident, role, has_task_attribute(raw)))
        elif kind in ("Leave", "CallingContextLeave"):
            if stack:
                stack.pop()
        elif kind in ("OmpTaskCreate", "ThreadTaskCreate") and stack:
            entry, role, raw_present = stack[-1]
            value = identity(kind, raw)
            if role in (21, "TASK_CREATE") and not raw_present:
                # Post-entry attribute updates append; lookup returns the first
                # matching ID, so later creates cannot overwrite this value.
                values.setdefault(entry, float(value))
    return values
