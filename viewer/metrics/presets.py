"""Executable programs translated from the embedded defaultCustomMetrics graph.

The resource and translator were inspected statically; see binary-metrics.md.
Unavailable recordings are reported, rather than replaced by another counter.
"""

from copy import deepcopy
from .patterns import (
    function_matches,
    function_patterns,
    io_paradigm_ids,
    io_paradigms,
)

_PRESETS = [
    (
        "instructions-per-cycle",
        "Instructions per Cycle",
        "IPC",
        {
            "instructions": dict(type="counter", metric="PAPI_TOT_INS", mode="rate"),
            "cycles": dict(type="counter", metric="PAPI_TOT_CYC", mode="rate"),
        },
        "instructions / cycles",
        [0, 0],
        [1, 1],
    ),
    (
        "flops-in-user-defined-function",
        "FLOPS in User Defined Function",
        "FLOPS",
        {
            "flops": dict(type="counter", metric="PAPI_FP_OPS", mode="rate"),
            "active": dict(type="function_active", functionPattern="*", inclusive=True),
        },
        "flops * active",
        [0, 1],
        [1, 3],
    ),
    (
        "io-bandwidth-iso-c",
        "I/O Bandwidth (ISO C)",
        "bytes per second",
        {"x": dict(type="io_bandwidth", paradigm="ISO C I/O")},
        "x",
        [12],
        [0],
    ),
    (
        "io-volume-iso-c",
        "I/O Volume in Transit (ISO C)",
        "number of bytes",
        {"x": dict(type="io_size", paradigm="ISO C I/O")},
        "x",
        [11],
        [0],
    ),
    (
        "message-data-rate",
        "Message Data Rate",
        "bytes per second",
        {"x": dict(type="message_rate")},
        "x",
        [8],
        [0],
    ),
    (
        "message-transfer-times",
        "Message Transfer Times",
        "seconds",
        {"x": dict(type="message_duration")},
        "x",
        [9],
        [0],
    ),
    (
        "message-volume",
        "Message Volume in Transit",
        "number of bytes",
        {"x": dict(type="message_volume")},
        "x",
        [7],
        [0],
    ),
    (
        "mpi-latencies",
        "MPI Latencies",
        "seconds",
        {"x": dict(type="function_duration", functionPattern="MPI_*", inclusive=True)},
        "x",
        [3],
        [3],
    ),
    (
        "number-of-hits",
        "Number of Hits",
        "number of hits",
        {"x": dict(type="function_hits", functionPattern="*")},
        "x",
        [14],
        [13],
    ),
    (
        "number-of-invocations",
        "Number of Invocations",
        "number of invocations",
        {"x": dict(type="function_count", functionPattern="*", endpoint="enter")},
        "x",
        [13],
        [10],
    ),
    (
        "simultaneous-io-iso-c",
        "Simultaneous I/O Operations (ISO C)",
        "number of ops",
        {"x": dict(type="io_simultaneous", paradigm="ISO C I/O")},
        "x",
        [10],
        [0],
    ),
    (
        "simultaneous-messages",
        "Simultaneous Messages",
        "number of messages",
        {"x": dict(type="message_count")},
        "x",
        [6],
        [0],
    ),
    (
        "time-spent-in-mpi-wait",
        "Time Spent in MPI_Wait",
        "seconds",
        {
            "x": dict(
                type="function_duration", functionPattern="MPI_Wait*", inclusive=True
            )
        },
        "x",
        [3],
        [3],
    ),
]


def presets(trace, paradigm=None):
    """List all 13 native graphs, with trace-resolved sources and availability."""
    metrics = {m["name"]: str(m["id"]) for m in reversed(trace.meta.get("metrics", []))}
    regions = trace.meta.get("regions", [])
    paradigms = io_paradigms(trace)
    numeric_paradigms = [
        row for row in paradigms if row["id"].isdigit() and int(row["id"]) < 255
    ]
    selected = io_paradigm_ids(trace, paradigm) if paradigm not in (None, "") else set()
    default = next((row for row in paradigms if row["id"] in selected), None)
    if default is None and numeric_paradigms:
        default = min(numeric_paradigms, key=lambda row: int(row["id"]))
    with trace.connect() as db:
        has_samples, has_messages, has_io, has_rma = (
            bool(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone())
            for table in ("samples", "messages", "io", "rma")
        )
    catalog = []
    for ident, name, unit, original, expression, types, settings in _PRESETS:
        sources = deepcopy(original)
        reasons = []
        notes = []
        for source in sources.values():
            kind = source["type"]
            if kind == "counter":
                wanted = source["metric"]
                if wanted not in metrics:
                    reasons.append("Counter " + wanted + " is not recorded")
                else:
                    source["metric"] = metrics[wanted]
            elif kind.startswith("function_"):
                if not any(
                    function_matches(
                        r["name"], function_patterns(source["functionPattern"])
                    )
                    for r in regions
                ):
                    reasons.append("No function matches " + source["functionPattern"])
                if kind == "function_hits" and not has_samples:
                    reasons.append("Calling-context samples are not recorded")
            elif kind.startswith("message_"):
                if not has_messages and not has_rma:
                    reasons.append("Message or RMA transfers are not recorded")
            elif kind.startswith("io_"):
                if not io_paradigm_ids(trace, source["paradigm"]):
                    if default:
                        notes.append(
                            source["paradigm"]
                            + " is absent; native fallback uses "
                            + (default["name"] or default["id"])
                        )
                        source["paradigm"] = default["id"]
                    else:
                        reasons.append(
                            "I/O paradigm " + source["paradigm"] + " is not recorded"
                        )
                if not has_io:
                    reasons.append("I/O operations are not recorded")
        catalog.append(
            dict(
                id=ident,
                name=name,
                unit=unit,
                available=not reasons,
                reason="; ".join(dict.fromkeys(reasons)),
                notes=notes,
                program=dict(
                    name=name, unit=unit, sources=sources, expression=expression
                ),
                native=dict(
                    resource="defaultCustomMetrics.json",
                    sourceTypes=types,
                    settings=settings,
                ),
            )
        )
    return catalog
