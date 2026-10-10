"""Static ports of signal-property virtual methods (vtable +0x38).

These are executable rules, including conservative and surprising flags; do
not replace them with mathematical inference from a selected output window.
Addresses and constructor paths are recorded in docs/binary-metrics.md.
"""

import math

TIMING = 0x700
INCREASING = 0x1000
DECREASING = 0x2000
MONOTONE = 0x3000
POSITIVE = 0x10000
NEGATIVE = 0x20000
PROPERTIES = 0x33000

_LIMIT_OPERATIONS = (
    "combine_min",
    "combine_max",
    "min",
    "max",
    "lower_limit",
    "upper_limit",
)


def constant_flags(value):
    if value is None:
        return 0
    return MONOTONE | (POSITIVE if value >= 0 else 0) | (NEGATIVE if value <= 0 else 0)


def reversed_monotonic(flags):
    return (DECREASING if flags & INCREASING else 0) | (
        INCREASING if flags & DECREASING else 0
    )


def _negative_scale_monotonic(flags):
    """Native negative scaling gives increasing precedence over decreasing."""
    if flags & INCREASING:
        return DECREASING
    return INCREASING if flags & DECREASING else 0


def temporal_flags(operation, flags):
    if operation in ("differentiate", "derivative"):
        # 0x1115590 deliberately retains property bits, but drops timing.
        return flags & PROPERTIES | (
            POSITIVE if flags & INCREASING else NEGATIVE if flags & DECREASING else 0
        )
    if operation in ("difference", "diff"):
        return (
            flags & TIMING
            | (POSITIVE if flags & INCREASING else 0)
            | (NEGATIVE if flags & DECREASING else 0)
        )
    if operation in ("cumsum", "integrate", "integral"):
        return (
            flags & TIMING
            | (0x11000 if flags & POSITIVE else 0)
            | (0x22000 if flags & NEGATIVE else 0)
        )
    if operation == "shift":
        return flags
    return None


def add_flags(a, b):
    timing = (a | b) & TIMING
    if b & PROPERTIES == PROPERTIES:
        return timing | a
    if a & PROPERTIES == PROPERTIES:
        return timing | b
    return timing | (a & b & PROPERTIES)


def multiply_flags(a, b):
    timing = (a | b) & TIMING
    result = timing | (POSITIVE if (a & b & POSITIVE or a & b & NEGATIVE) else NEGATIVE)
    if b & MONOTONE == MONOTONE:
        variable, constant = a, b
    elif a & MONOTONE == MONOTONE:
        variable, constant = b, a
    else:
        return result
    if constant & POSITIVE:
        return result | (variable & MONOTONE)
    if constant & NEGATIVE:
        return result | _negative_scale_monotonic(variable)
    return result


def scalar_flags(operation, flags, value):
    timing = flags & TIMING
    if value is None:
        return timing
    constant = constant_flags(value)
    if operation == "add":
        return (
            flags
            if value == 0
            else (
                constant
                if flags & PROPERTIES == PROPERTIES
                else add_flags(flags, constant)
            )
        )
    if operation == "subtract":
        return flags  # 0xed12b0, all finite scalars
    if operation == "divide" and value == 0:
        return timing
    if operation in ("multiply", "divide"):
        # 0xed0920/0xed1370 use the same multiplication property helper.
        return multiply_flags(
            flags, constant_flags(1 / value) if operation == "divide" else constant
        )
    if operation in _LIMIT_OPERATIONS:
        return timing | (flags & MONOTONE)
    if operation == "logical_and":
        return timing | (PROPERTIES if (constant | flags) & NEGATIVE else POSITIVE)
    if operation == "logical_or":
        return (
            timing
            | (PROPERTIES if value <= 0 and flags & NEGATIVE else POSITIVE)
            | (MONOTONE if value > 0 else 0)
        )
    if operation == "logical_xor":
        return timing | (PROPERTIES if value <= 0 and flags & NEGATIVE else POSITIVE)
    if operation == "lt":
        return (
            timing
            | POSITIVE
            | (0x23000 if flags & NEGATIVE and value > 0 else 0)
            | (MONOTONE if flags & POSITIVE and value < 0 else 0)
            | reversed_monotonic(flags)
        )
    if operation == "le":
        return (
            timing
            | POSITIVE
            | (MONOTONE if value <= 0 and flags & NEGATIVE else 0)
            | reversed_monotonic(flags)
        )
    if operation == "gt":
        return (
            timing
            | POSITIVE
            | (0x23000 if value >= 0 and flags & NEGATIVE else 0)
            | (flags & MONOTONE)
        )
    if operation == "ge":
        return (
            timing
            | POSITIVE
            | (MONOTONE if value <= 0 and flags & NEGATIVE else 0)
            | (flags & MONOTONE)
        )
    if operation in ("eq", "ne"):
        return (
            timing
            | POSITIVE
            | (
                (MONOTONE if operation == "eq" else 0x23000)
                if flags & PROPERTIES == PROPERTIES and value == 0
                else 0
            )
        )
    if operation == "log":
        # The scalar in this class is log(base), computed by its factory.
        divisor = math.log(value if value > 0 else 10)
        if divisor == 0:
            return timing
        return (
            timing
            | NEGATIVE
            | ((flags & MONOTONE) if divisor > 0 else _negative_scale_monotonic(flags))
        )
    return None


def binary_flags(operation, a, b):
    timing = (a | b) & TIMING
    if operation == "add":
        return add_flags(a, b)
    if operation == "subtract":
        # 0xecf480 retains existing sign bits while adding the opposite sign.
        negative = (
            (b & ~MONOTONE)
            | reversed_monotonic(b)
            | (POSITIVE if b & NEGATIVE else 0)
            | (NEGATIVE if b & POSITIVE else 0)
        )
        return timing | add_flags(a, negative)
    if operation == "multiply":
        return multiply_flags(a, b)
    if operation == "divide":
        return timing
    if operation in _LIMIT_OPERATIONS:
        return timing | (a & b & MONOTONE)
    if operation == "logical_and":
        return timing | (PROPERTIES if (a | b) & NEGATIVE else POSITIVE)
    if operation in ("logical_or", "logical_xor"):
        return timing | (PROPERTIES if a & b & NEGATIVE else POSITIVE)
    if operation == "lt":
        return timing | (PROPERTIES if a & POSITIVE and b & NEGATIVE else POSITIVE)
    if operation == "gt":
        return timing | (PROPERTIES if b & POSITIVE and a & NEGATIVE else POSITIVE)
    if operation in ("le", "ge"):
        return timing | (0x13000 if a & b & NEGATIVE else POSITIVE)
    if operation in ("eq", "ne"):
        return (
            timing
            | POSITIVE
            | (
                (MONOTONE if operation == "eq" else 0x23000)
                if a & b & PROPERTIES == PROPERTIES
                else 0
            )
        )
    return None


def pointwise_flags(operation, series, literals):
    if operation is None:
        return None
    flags = [s.flags for s in series]
    if operation in ("isnan", "replace_nan"):
        return flags[0] & TIMING | POSITIVE
    if operation == "logical_not":
        return flags[0] & TIMING | (
            0x13000
            if flags[0] & 0x22000 == 0x22000 or flags[0] & MONOTONE == MONOTONE
            else POSITIVE
        )
    if operation == "identity":
        return flags[0]
    if operation == "negate":
        return scalar_flags("multiply", flags[0], -1)
    if operation == "log" and len(series) == 1:
        return scalar_flags("log", flags[0], 10)
    if len(series) < 2:
        return None
    if len(series) == 2:
        if literals[1]:
            return scalar_flags(operation, flags[0], series[1].at(0))
        if literals[0] and operation in (
            "add",
            "multiply",
            "logical_and",
            "logical_or",
            "logical_xor",
            "eq",
            "ne",
            "min",
            "max",
            "combine_min",
            "combine_max",
        ):
            return scalar_flags(operation, flags[1], series[0].at(0))
    result = flags[0]
    for other in flags[1:]:
        result = binary_flags(operation, result, other)
        if result is None:
            return None
    return result
