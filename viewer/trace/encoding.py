"""Stable JSON encoding for trace storage and browser responses."""

import json
import math

_SAFE_INTEGER = 9007199254740991


def js_safe(obj):
    """Copy for JavaScript: integers beyond 2**53 become strings, non-finite floats null.

    Responses hold hundreds of thousands of scalars, so the exact built-in types are
    handled inline (x - x == 0 only for finite floats); subclasses take the generic path.
    """
    kind = type(obj)
    if kind is dict:
        out = {}
        for key, value in obj.items():
            kind = type(value)
            if kind is str or value is None or kind is bool:
                out[key] = value
            elif kind is float:
                out[key] = value if value - value == 0.0 else None
            elif kind is int:
                safe = -_SAFE_INTEGER <= value <= _SAFE_INTEGER
                out[key] = value if safe else str(value)
            else:
                out[key] = js_safe(value)
        return out
    if kind is list or kind is tuple:
        out = []
        append = out.append
        for value in obj:
            kind = type(value)
            if kind is str or value is None or kind is bool:
                append(value)
            elif kind is float:
                append(value if value - value == 0.0 else None)
            elif kind is int:
                safe = -_SAFE_INTEGER <= value <= _SAFE_INTEGER
                append(value if safe else str(value))
            else:
                append(js_safe(value))
        return out
    if isinstance(obj, int) and abs(obj) > _SAFE_INTEGER:
        return str(obj)
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: js_safe(v) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return [js_safe(v) for v in obj]
    return obj


_encoder = json.JSONEncoder(separators=(",", ":"), ensure_ascii=False, allow_nan=False)
dumps = _encoder.encode

# JSONEncoder.encode builds a new C encoder for every call, which dominates the
# cost of small import records. Records decoded from JSON or built by readers
# are acyclic, so one encoder without circular-reference markers yields the
# same text as dumps.
_record_encoder = json.encoder.c_make_encoder(
    None,
    _encoder.default,
    json.encoder.encode_basestring,
    None,
    ":",
    ",",
    False,
    False,
    False,
)


def record_dumps(obj):
    return "".join(_record_encoder(obj, 0))
