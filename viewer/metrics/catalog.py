"""Static metric source options and expression help text."""

SOURCE_LABELS = {
    "counter": "Trace Counter",
    "constant": "Constant Value",
    "custom": "Custom Metric",
    "function_duration": "Function Duration",
    "function_active": "Function is Active",
    "function_count": "Function Count",
    "function_hits": "Function Hits",
    "function_attribute": "Function Attribute",
    "function_attribute_active": "Function Attribute is Active",
    "io_attribute": "I/O Attribute",
    "io_bandwidth": "I/O Bandwidth",
    "io_count": "I/O Operation Count",
    "io_simultaneous": "I/O Simultaneous Operations",
    "io_size": "I/O Transaction Size",
    "message_rate": "Message Data Rate",
    "message_count": "Message Number",
    "message_duration": "Message Transfer Time",
    "message_volume": "Message Volume",
    "message_simultaneous": "Simultaneous Messages",
}

OPERATIONS = [
    (
        "arithmetic",
        "x + y; x - y; x * y; x / y",
        "Arithmetic. Missing operands, division by zero, and nonfinite results produce gaps.",
    ),
    (
        "comparison",
        "x < y; x <= y; x > y; x >= y; x == y; x != y",
        "IEEE-style comparison, 0 or 1. Missing/NaN operands compare false except !=, which returns 1.",
    ),
    (
        "logical_and",
        "logical_and(x, y)",
        "True only for values greater than zero, as documented.",
    ),
    ("logical_or", "logical_or(x, y)", "Positive-value logical OR."),
    ("logical_xor", "logical_xor(x, y)", "Positive-value logical exclusive OR."),
    (
        "logical_not",
        "logical_not(x)",
        "Positive-value logical negation. Missing/NaN is false, so its negation is 1.",
    ),
    ("isnan", "isnan(x)", "1 for missing/not-a-number input, otherwise 0."),
    (
        "replace_nan",
        "replace_nan(x, 0)",
        "Explicitly replace missing values with a specified constant or series.",
    ),
    (
        "combine_max",
        "combine_max(x, y)",
        "Maximum, returning the other value when only one operand is missing.",
    ),
    (
        "combine_min",
        "combine_min(x, y)",
        "Minimum, returning the other value when only one operand is missing.",
    ),
    (
        "lower_limit",
        "lower_limit(x, 0)",
        "Enforce a lower limit; missing input returns the specified limit.",
    ),
    (
        "upper_limit",
        "upper_limit(x, 100)",
        "Enforce an upper limit; missing input returns the specified limit.",
    ),
    (
        "differentiate",
        "differentiate(x)",
        "Forward interval slope after recursive interpolation. At the final finite sample and beyond, the derivative is zero.",
    ),
    (
        "interpolate",
        "interpolate(x)",
        "Linear interpolation; hold the current value when the next is missing, and hold the final value after the last measurement.",
    ),
    (
        "log",
        "log(x, 10)",
        "Signed logarithm: log(x)/log(base) for positive x, -log(-x)/log(base) for negative x, zero for x=0. Nonpositive bases use 10.",
    ),
    (
        "difference",
        "difference(x)",
        "Current sample minus the previous nonmissing sample, preserving integer precision. The baseline is the value at trace time zero; a later first reading without that baseline remains missing.",
    ),
    (
        "integrate",
        "integrate(x); integrate(x, 'linear')",
        "Prefix integral: commit previous-value rectangles at the next finite input state, skipping NaNs; no extrapolation after the last state. Explicit left/right/linear methods are selection-relative extensions.",
    ),
    (
        "cumsum",
        "cumsum(x)",
        "Cumulative sum from trace start, ignoring missing/NaN samples. Zooming preserves the accumulated prefix.",
    ),
    (
        "aggregate",
        "aggregate(x, 'sum', 'group')",
        "Reduce descendants on the recovered uniform pixel grid for sum/mean/min/max; scopes all, group, system. Other reducers are sample-aligned extensions.",
    ),
    (
        "moving_mean",
        "moving_mean(x, 0.1)",
        "Sample mean in a trailing window in seconds; missing samples yield a gap.",
    ),
    (
        "moving_sum",
        "moving_sum(x, 0.1)",
        "Trailing sample sum; also moving_min, moving_max, moving_stddev.",
    ),
    ("shift", "shift(x, 0.1)", "Shift sample timestamps by the specified seconds."),
    (
        "where",
        "where(x > 0, y, 0)",
        "Choose an operand by positive-value condition. Unknown condition stays missing.",
    ),
    ("clamp", "clamp(x, 0, 1)", "Clamp a finite value between lower and upper limits."),
    (
        "math",
        "abs(x); sqrt(x); exp(x); pow(x,2); floor(x); ceil(x); round(x)",
        "Bounded scalar mathematical functions, evaluated independently at each aligned time.",
    ),
]


def source_options(kind):
    common = {
        "locations": "Optional comma-separated location IDs; intersected with global selection."
    }
    if kind == "counter":
        return dict(
            common,
            metric="Metric member ID",
            mode="value|delta|rate",
            maxGap="Optional maximum hold time in seconds",
        )
    if kind == "constant":
        return dict(common, value="Finite numeric value", unit="Optional display unit")
    if kind == "custom":
        return dict(
            common,
            formula="Name from query.formulas, or inline expression and sources",
            expression="Inline nested expression",
            sources="Inline named sources",
        )
    if kind.startswith("function_"):
        return dict(
            common,
            region="Function name substring",
            functionPattern="Semicolon-separated, case-sensitive whole-name patterns; only * is a wildcard",
            functionStorage="native uses session-wide Stack/CallingContext selection; per-location is an extension that falls back to instrumented stacks",
            group="Function group",
            exclude="Excluded name substring",
            inclusive="false uses active leaf; true includes children",
            attribute="Attribute ID/name, parameter:N, Task ID, or duration/exclusive/depth",
            attributeReduction="top|bottom|sum|min|max|mean over active stack entries; default top",
            values="Selected attribute string values",
            endpoint="enter|leave|both for count",
            impulses="true selects event impulses instead of the native cumulative count",
        )
    if kind.startswith("io_"):
        return dict(
            common,
            operation="Case-insensitive operation name substring",
            paradigm="Exact recorded I/O paradigm name or ID",
            file="File ID/name substring",
            handle="Handle ID",
            attribute="Numeric attribute ID/name or bytes/duration",
            operationReduction="first|last|sum|min|max|mean over active operations; default sum",
        )
    return dict(
        common,
        direction="send is the native sender-owned source; receive|both redistribute the same transfer interval as viewer extensions",
        transferTypes="Optional comma-separated native types: -2 MPI, -3 RMA Put, -4 RMA Get, 0..7 RMA atomics",
        tag="Message tag; RMA uses -1",
        comm="Communicator ID",
        status="Match status",
        minBytes="Minimum size",
        maxBytes="Maximum size",
    )
