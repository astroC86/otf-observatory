"""Attribute resolution shared by Stack, CallingContext and I/O sources."""

from functools import cached_property
import json

from .attribute_references import AttributeReferences
from .parameter_attributes import parameter_attribute_values, parameter_attributes
from .state_tree_attributes import StateTreeAttributeMap
from .task_attributes import task_attribute_values
from .values import MISSING_ATTRIBUTE, attribute_choice, number


def attribute_choices(kind, spec):
    choices = spec.get("values", []) if kind == "function_attribute_active" else []
    if not isinstance(choices, list):
        raise ValueError("Attribute choices must be a list")
    return {str(value) for value in choices}


def attribute_reducer(spec):
    reducer = spec.get("attributeReduction", "top")
    if reducer not in ("top", "bottom", "sum", "min", "max", "mean"):
        raise ValueError(
            "Attribute reduction must be top, bottom, sum, min, max or mean"
        )
    return reducer


class AttributeContext:
    """Resolve attributes using the query runtime's bounded fetch and charge hooks."""

    def __init__(self, trace):
        self.trace = trace
        self.task_attributes = {}
        self.parameter_attributes = {}
        self.attribute_reference_diagnostics = {}

    @cached_property
    def attribute_references(self):
        return AttributeReferences(
            self.fetch("SELECT kind,ref,data FROM definitions ORDER BY rowid"),
            self.charge,
        )

    def attribute_omission(self, reason, unresolved=False):
        source = self.source_names[-1] if self.source_names else "attribute"
        key = (source, unresolved)
        if key not in self.attribute_reference_diagnostics:
            diagnosis = dict(
                source=source, location="all", kind="attribute", skipped={}
            )
            if unresolved:
                diagnosis["uncertain"] = {}
            self.attribute_reference_diagnostics[key] = diagnosis
            self.source_diagnostics.append(diagnosis)
        counts = self.attribute_reference_diagnostics[key][
            "uncertain" if unresolved else "skipped"
        ]
        counts[reason] = counts.get(reason, 0) + 1

    def attribute_name(self, ref, default=""):
        definition = self.trace.defs.get("Attribute", {}).get(str(ref), {})
        return (
            self.trace.defs.get("String", {})
            .get(str(definition.get("name")), {})
            .get("string", default)
        )

    def attribute(self, raw, wanted, default=None, decode_strings=True):
        if not isinstance(raw, dict):
            return default
        if str(wanted) in raw and not isinstance(raw[str(wanted)], (list, dict)):
            return raw[str(wanted)]
        for attribute in raw.get("attributes", []):
            ref = str(attribute.get("ref", ""))
            name = self.attribute_name(ref)
            if str(wanted) not in (ref, name):
                continue
            value = attribute.get("value")
            if self.trace.meta.get("format") != "OTF":
                references = self.attribute_references
                if not references.registered(ref):
                    self.attribute_omission("unregistered-metric-attribute")
                    continue
                result = references.convert(value, attribute.get("type"))
                if not result.accepted:
                    self.attribute_omission(result.reason, result.unresolved)
                    if result.unresolved:
                        return None
                    continue
                return (
                    result.text
                    if decode_strings and attribute.get("type") == 11
                    else result.value
                )
            # OTF2_TYPE_STRING is 11 in the installed public OTF2 definitions.
            from ..trace.definitions import ENUMS

            if decode_strings and attribute.get("type") == ENUMS.get(
                "OTF2_TYPE_STRING", 11
            ):
                value = (
                    self.trace.defs.get("String", {}).get(str(value), {}).get("string")
                )
            return value
        return default

    def task_attribute(self, wanted):
        return self.attribute_name(wanted, str(wanted)) == "Task ID"

    def synthesized_task_attributes(self, loc):
        if loc not in self.task_attributes:
            events = self.fetch(
                "SELECT id,kind,data FROM events WHERE location=? AND kind IN ('Enter','Leave','CallingContextEnter','CallingContextLeave','OmpTaskSwitch','ThreadTaskSwitch','OmpTaskCreate','ThreadTaskCreate') ORDER BY id",
                (loc,),
            )
            decoded = (dict(row, data=json.loads(row["data"])) for row in events)
            roles = {
                str(ref): definition.get("regionRole")
                for ref, definition in self.trace.defs.get("Region", {}).items()
            }
            for region in self.trace.meta["regions"]:
                roles.setdefault(region["id"], region.get("role"))
            self.task_attributes[loc] = task_attribute_values(
                decoded,
                roles,
                self.trace.defs.get("CallingContext", {}),
                lambda raw: self.attribute(
                    raw, "Task ID", MISSING_ATTRIBUTE, decode_strings=False
                )
                is not MISSING_ATTRIBUTE,
                self.charge,
            )
        return self.task_attributes[loc]

    def parameter_reference(self, wanted):
        wanted = str(wanted)
        parameters = self.trace.defs.get("Parameter", {})
        if wanted.startswith("parameter:"):
            ref = wanted[10:]
            if ref not in parameters or parameters[ref].get("parameterType") not in (
                0,
                1,
                2,
            ):
                raise ValueError("Unknown profiling parameter: " + ref)
            return ref
        if wanted == "Task ID" or wanted in self.trace.defs.get("Attribute", {}):
            return None
        strings = self.trace.defs.get("String", {})
        if any(
            strings.get(str(d.get("name")), {}).get("string") == wanted
            for d in self.trace.defs.get("Attribute", {}).values()
        ):
            return None
        matches = [
            row["parameter"]
            for row in parameter_attributes(self.trace.defs)
            if row["name"] == wanted
        ]
        if len(matches) > 1:
            raise ValueError("Ambiguous profiling parameter name; use parameter:N")
        return matches[0] if matches else None

    def synthesized_parameter_attributes(self, loc):
        if loc not in self.parameter_attributes:
            events = self.fetch(
                "SELECT id,kind,data FROM events WHERE location=? AND kind IN ('Enter','Leave','CallingContextEnter','CallingContextLeave','ParameterInt','ParameterUnsignedInt','ParameterString') ORDER BY id",
                (loc,),
            )
            decoded = (dict(row, data=json.loads(row["data"])) for row in events)
            self.parameter_attributes[loc] = parameter_attribute_values(
                decoded, self.trace.defs, self.charge
            )
        return self.parameter_attributes[loc]

    def parameter_value(self, parameters, event, ref, choices):
        value = parameters.get(event, {}).get(ref, MISSING_ATTRIBUTE)
        if (
            value is not MISSING_ATTRIBUTE
            and choices
            and self.trace.defs["Parameter"][ref]["parameterType"] == 0
        ):
            return (
                self.trace.defs.get("String", {}).get(str(int(value)), {}).get("string")
            )
        return value

    def state_tree_properties(self, loc, events, selected, kind, spec):
        """Native context-index lookup into the separately event-indexed map."""
        wanted = str(spec.get("attribute", "duration"))
        if wanted in ("duration", "exclusive", "depth"):
            return None
        parameter_ref = self.parameter_reference(wanted)
        wanted_name = self.attribute_name(wanted, wanted)
        choices = attribute_choices(kind, spec)
        properties = {}
        records = []
        reducer = attribute_reducer(spec)
        references = self.attribute_references

        def converted(result, value_type):
            if not result.accepted:
                self.attribute_omission(result.reason, result.unresolved)
                # Unknown native remapping is not a proved omitted value.
                # Keep a gap to prevent a global/Leave fallback from becoming
                # a fabricated numeric result while its local value is unknown.
                return None if result.unresolved else MISSING_ATTRIBUTE
            if choices and value_type == 11:
                return attribute_choice(result.text, choices)
            value = number(result.value)
            return attribute_choice(value, choices) if choices else value

        for prop, conversion in references.properties:
            name = (
                self.trace.defs.get("String", {})
                .get(str(prop.get("name")), {})
                .get("string", "")
            )
            if parameter_ref is not None or name != wanted_name:
                continue
            self.charge(1)
            value = converted(conversion, prop.get("type"))
            if value is not MISSING_ATTRIBUTE:
                properties.setdefault(str(prop.get("callingContext")), []).append(
                    ("value", value)
                )
        for event in events:
            attributes = []
            if parameter_ref is None:
                for attr in event["raw"].get("attributes", []):
                    self.charge(1)
                    ref = str(attr.get("ref"))
                    name = self.attribute_name(ref)
                    if wanted not in (ref, name):
                        continue
                    if not references.registered(ref):
                        self.attribute_omission("unregistered-metric-attribute")
                        continue
                    value = converted(
                        references.convert(attr.get("value"), attr.get("type")),
                        attr.get("type"),
                    )
                    if value is not MISSING_ATTRIBUTE:
                        attributes.append(("value", value))
            records.append(
                dict(id=event["id"], kind=event["kind"], attributes=attributes)
            )
        attachments = {}
        overrides = {}
        if parameter_ref is not None:
            parameter_type = self.trace.defs["Parameter"][parameter_ref][
                "parameterType"
            ]
            for event, values in self.synthesized_parameter_attributes(loc).items():
                if parameter_ref not in values:
                    continue
                value = values[parameter_ref]
                # String parameters carry the original StringRef as a double.
                if parameter_type == 0:
                    value = int(value)
                value_type = 11 if parameter_type == 0 else 10
                value = converted(references.convert(value, value_type), value_type)
                if value is not MISSING_ATTRIBUTE:
                    attachments[event] = [("value", value)]
        elif self.task_attribute(wanted):
            overrides = {
                event: [("value", converted(references.convert(value, 10), 10))]
                for event, value in self.synthesized_task_attributes(loc).items()
            }
        attributes = StateTreeAttributeMap(
            self.trace.defs.get("CallingContext", {}),
            records,
            properties,
            attachments,
            overrides,
            self.charge,
        )
        if attributes.skipped:
            self.source_diagnostics.append(
                dict(
                    source=self.source_names[-1] if self.source_names else kind,
                    location=loc,
                    kind=kind,
                    skipped=attributes.skipped,
                )
            )
        values = []
        for event in events:
            chain = event["chain"][:-1] if event["kind"] == 3 else event["chain"]
            chain = [ref for ref, region in chain if region in selected]
            self.charge(len(chain) + 1)
            if reducer == "top":
                value = attributes.lookup(chain[-1], "value", None) if chain else None
            else:
                present = [
                    value
                    for ref in chain
                    if (value := attributes.lookup(ref, "value", MISSING_ATTRIBUTE))
                    is not MISSING_ATTRIBUTE
                ]
                if not present:
                    value = None
                elif reducer == "bottom":
                    value = present[-1]
                elif reducer in ("sum", "mean"):
                    value = (
                        number(sum(present))
                        if all(v is not None for v in present)
                        else None
                    )
                    if reducer == "mean" and value is not None:
                        value = number(value / len(present))
                else:
                    value = present[0]
                    for incoming in present[1:]:
                        if (
                            value is None
                            or incoming is None
                            or (
                                incoming < value
                                if reducer == "min"
                                else incoming > value
                            )
                        ):
                            value = incoming
            values.append(value)
        return values
