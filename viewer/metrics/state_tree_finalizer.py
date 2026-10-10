"""Closing records emitted by native TdbStateTree finalization (0xea85e0)."""

import math


def finalize_state_tree_records(
    records, trace_end, tick_seconds, charge=lambda work: None, allocated=True
):
    """Return copied records and the finalizer's updated running end time.

    The caller supplies one allocated location's full normalized record sequence,
    without its dummy root. Records contain ``time``, ``kind``, and ``chain`` (a
    root-to-leaf sequence of context/region pairs). A missing/undefined leaf region
    clears the finalizer's open explicit-context stack. Samples never push it.

    An allocated location always receives a final sentinel Leave. Each still-open
    Enter receives a Leave first, in reverse order, retaining its original context
    chain. All generated records share ``max(last_time + one_tick, trace_end)``.
    The caller passes the returned end into the next execution location, preserving
    the native finalizer's location-order dependence. An allocated but empty source
    has the implicit dummy record at time zero; an unallocated source is untouched.

    Generated records have no recorded event ID or raw attributes. This function
    does not modify or claim that a corresponding Leave was present in the archive.
    """
    if (
        not math.isfinite(trace_end)
        or not math.isfinite(tick_seconds)
        or tick_seconds <= 0
    ):
        raise ValueError(
            "State-tree finalization requires a finite end and positive tick duration"
        )
    result = []
    stack = []
    for record in records:
        charge(1)
        result.append(dict(record))
        chain = record["chain"]
        if not chain or str(chain[-1][1]) in ("-1", "4294967295"):
            stack.clear()
        elif record["kind"] == 2:
            stack.append(record)
        elif record["kind"] == 3 and stack:
            stack.pop()
    if not allocated:
        return result, trace_end
    last_time = result[-1]["time"] if result else 0.0
    final_time = max(last_time + tick_seconds, trace_end)

    def close(chain):
        charge(1)
        result.append(
            dict(
                id=None,
                time=final_time,
                kind=3,
                chain=chain,
                raw={},
                attributes=(),
                has_attributes=False,
                synthetic="native-state-tree-finalization",
            )
        )

    for record in reversed(stack):
        close(record["chain"])
    close(())
    return result, final_time
