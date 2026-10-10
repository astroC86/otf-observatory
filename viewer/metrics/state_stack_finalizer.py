"""StateStack end-of-read closes from static native producer 0xea98e0."""

import math


def finalize_state_stack_records(records, seed, tick_seconds, charge=lambda work: None):
    """Return copied normalized records and this location's close time.

    Input records contain time, kind (Enter/Leave), region, id, and optionally the
    matched entry ID for a Leave. They are accepted, chronologically normalized
    producer records, without the dummy root. Use a consistent time unit for the
    records, seed, and tick_seconds; passing native ticks with tick_seconds=1 keeps
    integer fixture boundaries exact.

    Every remaining Enter receives a synthetic Leave at max(last_time+tick, seed),
    in reverse nesting order. A balanced/empty stream receives no closing record.
    The caller reuses the original seed for every location: unlike StateTree,
    StateStack has no location-order carry. Malformed root pops cannot be silently
    treated as a valid prefix and raise ValueError for the adapter to diagnose.
    """
    if not math.isfinite(seed) or not math.isfinite(tick_seconds) or tick_seconds <= 0:
        raise ValueError(
            "State-stack finalization requires a finite seed and positive tick duration"
        )
    result, stack = [], []
    last_time = 0
    for record in records:
        charge(1)
        timestamp = record["time"]
        if not math.isfinite(timestamp) or timestamp < last_time:
            raise ValueError(
                "State-stack finalization requires normalized chronological records"
            )
        last_time = timestamp
        result.append(dict(record))
        if record["kind"] == "Enter":
            stack.append(record)
        elif record["kind"] == "Leave":
            if not stack:
                raise ValueError("State-stack finalization encountered a root pop")
            entry = stack.pop()
            if "entry" in record and record["entry"] != entry["id"]:
                raise ValueError(
                    "State-stack finalization encountered a mismatched entry"
                )
        else:
            raise ValueError("State-stack finalization requires Enter/Leave records")
    close_time = max(last_time + tick_seconds, seed)
    for entry in reversed(stack):
        charge(1)
        result.append(
            dict(
                id=None,
                time=close_time,
                kind="Leave",
                region=entry["region"],
                entry=entry["id"],
                raw={},
                synthetic="native-state-stack-finalization",
            )
        )
    return result, close_time
