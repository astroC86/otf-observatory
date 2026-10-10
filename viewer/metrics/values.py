"""Numeric, missing-value and unit semantics shared by metric operators."""

from fractions import Fraction
import math
import re
import statistics

MISSING_ATTRIBUTE = object()

REDUCERS = (
    "sum",
    "mean",
    "min",
    "max",
    "count",
    "median",
    "stddev",
    "variance",
    "first",
    "last",
    "p95",
)


def finite(value):
    try:
        return (
            isinstance(value, (int, float, Fraction))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    except OverflowError:
        return False


def number(value):
    if isinstance(value, bool):
        return int(value)
    # IEEE infinities are valid operands in the native signal operators. Only
    # NaN becomes the internal missing sentinel; JSON conversion happens later.
    if isinstance(value, (int, Fraction)):
        return value
    return value if isinstance(value, float) and not math.isnan(value) else None


def source_number(value):
    # Native JSON preserves IEEE values as explicit strings because standard
    # JSON has no nonfinite numeric literal. Decode only these source tokens.
    if isinstance(value, str) and value in ("Infinity", "-Infinity", "NaN"):
        value = float(value)
    return number(value)


def attribute_choice(value, choices):
    if str(value) in choices:
        return 1
    if isinstance(value, (int, float, Fraction)):
        # Selected numeric attribute values are native doubles. In particular,
        # synthesized Task ID 7.0 must match the displayed selection "7".
        try:
            numeric = float(value)
        except OverflowError:
            numeric = math.inf if value > 0 else -math.inf
        for choice in choices:
            try:
                if numeric == float(choice):
                    return 1
            except (ValueError, TypeError, OverflowError):
                pass
    return 0


def json_number(value):
    return float(value) if finite(value) else None


def _reduce_values(values, reducer):
    values = [v for v in values if v is not None]
    if not values:
        return None
    if reducer == "sum":
        return sum(values)
    if reducer == "mean":
        return sum(values) / len(values)
    if reducer == "min":
        return min(values)
    if reducer == "max":
        return max(values)
    if reducer == "count":
        return len(values)
    if reducer == "first":
        return values[0]
    if reducer == "last":
        return values[-1]
    if reducer == "median":
        return statistics.median(values)
    if reducer == "variance":
        return statistics.pvariance(values)
    if reducer == "stddev":
        return statistics.pstdev(values)
    if re.fullmatch(r"p(?:100|[0-9]{1,2})(?:\.[0-9]+)?", reducer):
        quantile = float(reducer[1:]) / 100
        if not 0 <= quantile <= 1:
            raise ValueError("Percentile must be between p0 and p100")
        ordered = sorted(values)
        index = (len(values) - 1) * quantile
        lo = math.floor(index)
        hi = math.ceil(index)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)
    raise ValueError("Unknown reducer: " + str(reducer))


def reduce_values(values, reducer):
    try:
        return number(_reduce_values(values, reducer))
    except (OverflowError, ZeroDivisionError):
        return None


def reducer_valid(name):
    reduce_values([1, 2], str(name))
    return str(name)


def unit_join(left, right, op):
    a, b = left.unit, right.unit
    if op in ("add", "sub", "min", "max", "compare", "replace"):
        if a and b and a != b:
            raise ValueError(
                "Incompatible metric units: "
                + a
                + " and "
                + b
                + "; set matching source units explicitly"
            )
        return a or b
    if op == "multiply":
        return a + "*" + b if a and b else a or b
    if op == "divide":
        return "" if a == b else (a + "/" + b if a and b else ("1/" + b if b else a))
    return a


def safe_power(a, b):
    if abs(b) > 1024 or (abs(a) > 1 and b > 0 and b * math.log2(abs(a)) > 1024):
        return None
    value = a**b
    return value if isinstance(value, (int, float, Fraction)) else None


def positive(value):
    # COMISD/SETA in the recovered SignalAnd/Or/Xor/Not value methods:
    # unordered (NaN) comparisons are false, just like nonpositive values.
    return value is not None and value > 0


def compare_nan(function, left, right):
    # Preserve exact integer comparisons while mapping only missing operands
    # to IEEE NaN. In particular, NaN != NaN is true; None != None is false.
    return function(
        math.nan if left is None else left, math.nan if right is None else right
    )


def signed_log(value, base=10):
    # Factory e8e580 replaces nonpositive bases with 10, then stores log(base).
    # Value ed04a0 explicitly special-cases zero and negates log(abs(x)) for x<0.
    if value == 0:
        return 0
    denominator = math.log(base if base > 0 else 10)
    return (
        math.copysign(1, value) * math.log(abs(value)) / denominator
        if denominator
        else None
    )
