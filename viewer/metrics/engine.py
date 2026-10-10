"""Public bounded offline metric API: capabilities, attribute catalog and evaluation.

Sources, expression operators and rendering live in focused modules. Missing values
remain JSON null; no Python eval, arbitrary SQL or dynamic user code is executed."""

from . import limits
from .catalog import OPERATIONS, SOURCE_LABELS, source_options
from .parameter_attributes import parameter_attributes
from .values import REDUCERS


def capabilities():
    return {
        "version": 1,
        "sources": [
            {"type": kind, "label": label, "options": source_options(kind)}
            for kind, label in SOURCE_LABELS.items()
        ],
        "operations": [
            {"name": name, "syntax": syntax, "description": description}
            for name, syntax, description in OPERATIONS
        ],
        "reducers": list(REDUCERS),
        "temporalReducers": list(REDUCERS) + ["integral"],
        "scopes": ["all", "group", "system"],
        "limits": dict(
            inputPoints=limits.MAX_INPUT_POINTS,
            workPoints=limits.MAX_WORK_POINTS,
            sources=limits.MAX_SOURCES,
            locations=limits.MAX_LOCATIONS,
            expressionNodes=limits.MAX_NODES,
            seconds=limits.MAX_SECONDS,
        ),
        "semantics": {
            "alignment": "Union of timestamps with previous-sample alignment, or explicit recursive linear interpolation.",
            "gaps": "JSON null represents missing/NaN. Arithmetic propagates gaps. Comparisons and positive-value logic use the statically verified operator rules; cumsum skips gaps.",
            "countSources": "Function Count, Function Hits and I/O Operation Count are cumulative counters. CallingContext leave count resets on seek; enter/both/hits retain the prefix. Explicit impulses:true exposes function event impulses. Message Number and Simultaneous Messages both count active messages.",
            "functionSources": "Stack exclusive duration uses adjacent stack events; inclusive:true uses the outermost selected invocation duration. CallingContext sources seek unfiltered records, advance selected leaves, and use adjacent raw-record intervals for both durations. Inactive duration/activity is zero. Attribute reductions select top, bottom, sum, min, max or mean over active frames; unsupported producer paths are reported in sourceDiagnostics.",
            "overlappingOperations": "I/O values reduce the active operations using first/last/sum/min/max/mean; empty value reductions are missing. Message volume/rate/count sum active transfers. Transfer Time is a one-trace-tick pulse overwritten at each start. Starts precede completions on ties. Unsupported incomplete records are reported in sourceDiagnostics.",
            "integration": "Default: recovered SignalIntegrate state machine, accumulated from trace start; skip NaN states, commit at recorded boundaries, hold the final total. Explicit left/right/linear methods remain selection-relative mathematical extensions.",
            "hierarchy": "sum/mean/min/max use uniform metric pixels: each descendant contributes its interval-weighted value once per pixel. Other reducers align samples as viewer extensions. Only selected descendants contribute.",
            "temporalReduction": "Sample reductions over original evaluated points before display reduction, ignoring missing samples and reporting missingSamples. integral uses the recovered prefix accumulator.",
            "units": "Conservative symbolic inference. Addition requires matching known units; literal constants can share the other operand unit. Override with query.unit.",
        },
    }


def attribute_catalog(trace):
    strings = trace.defs.get("String", {})
    rows = [
        dict(
            id=str(ref),
            name=strings.get(str(definition.get("name")), {}).get("string", str(ref)),
            kind="attribute",
            type=definition.get("type"),
            description=strings.get(str(definition.get("description")), {}).get(
                "string", ""
            ),
        )
        for ref, definition in trace.defs.get("Attribute", {}).items()
    ]
    rows.extend(
        dict(row, kind="parameter", type=row["parameterType"])
        for row in parameter_attributes(trace.defs)
    )
    if any(
        region.get("role") in ("TASK", "TASK_CREATE")
        for region in trace.meta.get("regions", [])
    ):
        rows.append(
            dict(
                id="Task ID",
                name="Task ID",
                kind="synthetic",
                type="double",
                description="Task identity attached to the recorded invocation",
            )
        )
    return rows


def evaluate(trace, q):
    """Evaluate a named-source metric program and return JSON-safe chart data.

    sources may be a dict or JSON string. Missing values are explicit nulls.
    Computation always precedes display reduction. This function never writes.
    """
    if not isinstance(q, dict):
        raise ValueError("Metric query must be an object")
    if len(str(q.get("expression", ""))) > 8192:
        raise ValueError("Expression is too large")
    from .context import Context

    context = Context(trace, q)
    try:
        return context.output.evaluate()
    finally:
        # Source components point back at the context. Unlinking them lets
        # reference counting free cached signals now, instead of a later
        # cyclic collection that must traverse every cached point.
        context.source = context.functions = context.operations = None
