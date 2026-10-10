"""Build native instrumented Stack function signals."""

from .attributes import attribute_choices, attribute_reducer
from .series import Data
from .state_stack import StateStackSource
from .sweeps import reduce_attribute_entries
from .values import MISSING_ATTRIBUTE, attribute_choice, source_number


def function_mode(kind, inclusive):
    if kind == "function_duration":
        return 3 if inclusive else 4
    return 1 if inclusive else 2


def count_endpoint(spec):
    endpoint = spec.get("endpoint", "enter")
    if endpoint not in ("enter", "leave", "both"):
        raise ValueError("Function count endpoint must be enter, leave or both")
    return endpoint


def raw_stack_source(ctx, kind, spec, locs, allowed):
    """Recovered raw cursor for balanced, instrumented source records."""
    attribute = kind in ("function_attribute", "function_attribute_active")
    wanted = spec.get("attribute", "duration")
    inclusive = spec.get("inclusive", False) in (True, 1, "1", "true")
    reducer = (
        attribute_reducer(spec) if attribute else spec.get("attributeReduction", "top")
    )
    choices = attribute_choices(kind, spec)
    parameter = ctx.parameter_reference(wanted) if attribute else None
    results = {}
    fallback = []
    for loc in locs:
        records, issues = ctx.functions.records.stack(loc)
        if issues:
            fallback.append(loc)
            ctx.source_diagnostics.append(
                dict(
                    source=ctx.source_names[-1] if ctx.source_names else kind,
                    location=loc,
                    kind=kind,
                    skipped={},
                    uncertain=issues,
                )
            )
            continue
        values = {}
        if attribute:
            parameters = (
                ctx.synthesized_parameter_attributes(loc)
                if parameter is not None
                else {}
            )
            task = (
                ctx.synthesized_task_attributes(loc)
                if parameter is None and ctx.task_attribute(wanted)
                else {}
            )
            for record in records:
                ctx.charge(1)
                if record["kind"] == "Enter":
                    entry = record["id"]
                    if parameter is not None:
                        value = ctx.parameter_value(
                            parameters, entry, parameter, choices
                        )
                    else:
                        value = ctx.attribute(
                            record["raw"],
                            wanted,
                            MISSING_ATTRIBUTE,
                            decode_strings=bool(choices),
                        )
                        if entry in task:
                            value = task[entry]
                    values[entry] = value
                elif (
                    parameter is None
                    and values.get(record["entry"], MISSING_ATTRIBUTE)
                    is MISSING_ATTRIBUTE
                ):
                    values[record["entry"]] = ctx.attribute(
                        record["raw"],
                        wanted,
                        MISSING_ATTRIBUTE,
                        decode_strings=bool(choices),
                    )
            for entry, value in values.items():
                if value is not MISSING_ATTRIBUTE:
                    values[entry] = (
                        attribute_choice(value, choices)
                        if choices
                        else source_number(value)
                    )

        def attribute_value(frames, values=values):
            return reduce_attribute_entries(
                [values.get(frame["id"], MISSING_ATTRIBUTE) for frame in frames],
                reducer,
                bool(choices),
            )

        mode = 0 if attribute else function_mode(kind, inclusive)
        source = StateStackSource(
            records,
            allowed,
            mode,
            ctx.charge,
            attribute_value,
            ctx.functions.records.tick_seconds,
        )
        results[loc] = ctx.state_source_series(source)
    if fallback:
        from .span_sources import stack_function_source

        results.update(
            stack_function_source(
                ctx, kind, dict(spec, locations=fallback), False
            ).series
        )
    return Data(results, "s" if kind == "function_duration" else "")
