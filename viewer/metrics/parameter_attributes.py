"""Profiling parameters appended to the native reader's current invocation.

Parameter and Attribute references occupy different namespaces. The native
reader allocates a distinct attribute ID for each Parameter definition. Values
here stay keyed by the recorded parameter reference so callers can expose an
unambiguous ``parameter:N`` selection without guessing an internal native ID.
"""

PARAMETER_TYPES = {"ParameterString": 0, "ParameterInt": 1, "ParameterUnsignedInt": 2}


def parameter_attributes(definitions):
    """Describe valid recorded parameters as synthetic invocation attributes."""
    strings = definitions.get("String", {})
    result = []
    for ref, definition in definitions.get("Parameter", {}).items():
        kind = definition.get("parameterType")
        if kind not in (0, 1, 2):
            continue
        result.append(
            dict(
                id=f"parameter:{ref}",
                parameter=str(ref),
                name=strings.get(str(definition.get("name")), {}).get("string", ""),
                parameterType=kind,
                nativeValueType=7 if kind == 0 else 0,
                description="Profiling parameter",
            )
        )
    return result


def parameter_attribute_values(events, definitions, charge=lambda work: None):
    """Map entry event IDs to first parameter values, represented as binary64.

    The caller supplies one location's full events in recorded order. Parameter
    updates attach to the current explicit Enter/CallingContextEnter invocation;
    they do not change a sampled calling-context tree. Repeated updates append in
    the native backend and lookup returns the first matching generated ID. The
    value belongs to the invocation, including its time before the parameter event.
    String values are recorded StringRefs (binary64), resolved by the caller only
    when presenting or filtering string-valued attributes.
    """
    parameters = definitions.get("Parameter", {})
    strings = definitions.get("String", {})
    stack, values = [], {}
    for event in events:
        charge(1)
        kind, raw = event["kind"], event["data"]
        if kind in ("Enter", "CallingContextEnter"):
            stack.append(event["id"])
        elif kind in ("Leave", "CallingContextLeave"):
            if stack:
                stack.pop()
        elif kind in PARAMETER_TYPES and stack:
            ref = str(raw.get("parameter"))
            expected = PARAMETER_TYPES[kind]
            if parameters.get(ref, {}).get("parameterType") != expected:
                continue
            value = raw.get("string" if expected == 0 else "value")
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            if expected == 0:
                if not 0 <= value < 2**32 or str(value) not in strings:
                    continue
            elif expected == 1:
                if not -(2**63) <= value < 2**63:
                    continue
            elif not 0 <= value < 2**64:
                continue
            values.setdefault(stack[-1], {}).setdefault(ref, float(value))
    return values
