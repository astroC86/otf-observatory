"""Shared typed CUPTI fields and explicit external-correlation associations.

Only complete typed members on one recorded event form a mapping. CUPTI's
external IDs name client-managed ranges, not necessarily launch invocations.
No timestamp proximity or implicit push/pop lifetime is synthesized here.
"""

from __future__ import annotations
import collections
import re

KINDS = {1: "UNKNOWN", 2: "OPENACC", 3: "CUSTOM0", 4: "CUSTOM1", 5: "CUSTOM2"}
BRIDGE = "CUpti_ActivityExternalCorrelation"
OPENACC = {
    "CUpti_ActivityOpenAcc": None,
    "CUpti_ActivityOpenAccData": 33,
    "CUpti_ActivityOpenAccLaunch": 34,
    "CUpti_ActivityOpenAccOther": 35,
}
MEMBERS = {
    BRIDGE: {"kind": 3, "externalKind": 3, "externalId": 4, "correlationId": 3},
    **{name: {"kind": 3, "deviceType": 3, "externalId": 3} for name in OPENACC},
}


def unsigned_integer(value, bits):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        value = (
            int(value, 0)
            if isinstance(value, str) and value.startswith(("0x", "0X"))
            else int(value)
        )
    except ValueError:
        return None
    return value if 0 <= value < (1 << bits) else None


def cupti_correlation_member(name):
    """Known public activity layouts, not arbitrary qualified field aliases."""
    if name in ("cupti.correlationId", "cupti_correlationId"):
        return "correlationId"
    if name == "cupti.runtimeCorrelationId":
        return "runtimeCorrelationId"
    parts = name.split(".")
    if len(parts) != 2:
        return None
    struct, member = parts
    if member not in ("correlationId", "runtimeCorrelationId"):
        return None
    if struct == "CUpti_ActivityAPI":
        return member if member == "correlationId" else None
    # These exact versions are declared in CUDA 13.4's public/deprecated
    # headers. Do not accept a future layout solely from a numeric suffix.
    if re.fullmatch(
        r"CUpti_ActivityKernel(?:[2-9]|1[0-3])?|CUpti_ActivityMemcpy(?:[3-7])?|CUpti_ActivityMemcpyPtoP(?:[2-4])?|CUpti_ActivityMemset(?:[2-5])?",
        struct,
    ):
        if member == "runtimeCorrelationId" and struct not in (
            "CUpti_ActivityKernel",
            "CUpti_ActivityMemcpy",
            "CUpti_ActivityMemcpy3",
            "CUpti_ActivityMemcpy4",
            "CUpti_ActivityMemcpy5",
            "CUpti_ActivityMemcpy6",
            "CUpti_ActivityMemcpy7",
        ):
            return None
        return member
    return None


def cupti_activity_correlation_scope(name):
    """API domain stated by a qualified public activity struct member.

    Newer kernel records may identify a runtime OR driver call. A different
    activity's runtimeCorrelationId cannot decide which API launched them.
    """
    member = cupti_correlation_member(name)
    if member is None or not name.startswith("CUpti_Activity"):
        return None
    struct = name.split(".")[0]
    if struct == "CUpti_ActivityAPI":
        return None
    if member == "runtimeCorrelationId":
        return "runtime-correlation"
    if (
        struct == "CUpti_ActivityKernel"
        or struct.startswith("CUpti_ActivityMemset")
        or re.fullmatch(r"CUpti_ActivityMemcpy(?:[3-7])?", struct)
    ):
        return "driver-correlation"
    return "either-api"


class CuptiRecords:
    """Template decoder for qualified SDK layouts and their required members."""

    def __init__(self, defs):
        self.attributes = {}
        for ref, definition in defs.get("Attribute", {}).items():
            name = (
                defs.get("String", {})
                .get(str(definition.get("name")), {})
                .get("string", "")
            )
            parts = name.split(".")
            if (
                len(parts) == 2
                and parts[0] in self.members
                and parts[1] in self.members[parts[0]]
            ):
                self.attributes[ref] = (
                    parts[0],
                    parts[1],
                    self.members[parts[0]][parts[1]],
                    definition.get("type"),
                )
        self.scan_refs = set(self.attributes)
        self.reserved_refs = self.scan_refs

    def records(self, event):
        """Yield each layout once; None preserves invalid-record diagnostics."""
        groups = collections.defaultdict(lambda: collections.defaultdict(set))
        invalid = set()
        for attribute in event["data"].get("attributes", []):
            ref = str(attribute.get("ref"))
            if ref not in self.attributes:
                continue
            struct, member, expected, declared = self.attributes[ref]
            value = unsigned_integer(
                attribute.get("value"), 64 if expected == 4 else 32
            )
            if (
                declared != expected
                or attribute.get("type", declared) != expected
                or value is None
            ):
                invalid.add(struct)
            else:
                groups[struct][member].add(value)
        for struct in groups.keys() | invalid:
            fields = groups[struct]
            required = self.required_members(struct, fields)
            valid = (
                struct not in invalid
                and all(len(fields.get(key, ())) == 1 for key in required)
                and all(len(values) == 1 for values in fields.values())
            )
            yield struct, (
                {key: next(iter(found)) for key, found in fields.items()}
                if valid
                else None
            )


class ExternalRecords(CuptiRecords):
    members = MEMBERS

    def required_members(self, struct, fields):
        return (
            ("externalKind", "externalId", "correlationId")
            if struct == BRIDGE
            else ("deviceType", "externalId")
        )

    def extract(self, event, owner, warn):
        mappings = []
        external = []
        errors = 0
        for struct, values in self.records(event):
            if values is None:
                warn(
                    "gpu-external-record-invalid",
                    "A qualified CUPTI record lacks complete, consistently typed members on the same event.",
                )
                errors += 1
                continue
            base = dict(
                event=event["id"],
                location=str(event["location"]),
                time=event["time"],
                process=owner,
                recordType=struct,
                producer="CUPTI",
                evidence=[event["id"]],
            )
            if struct == BRIDGE:
                if values["externalKind"] not in KINDS or values.get("kind", 39) != 39:
                    warn(
                        "gpu-external-record-invalid",
                        "The qualified CUPTI mapping has an invalid activity or external-kind enum.",
                    )
                    errors += 1
                    continue
                mappings.append(
                    dict(
                        base,
                        id="cupti-external:" + str(event["id"]),
                        externalKind=values["externalKind"],
                        externalKindName=KINDS[values["externalKind"]],
                        externalId=str(values["externalId"]),
                        correlationId=str(values["correlationId"]),
                        causal=False,
                    )
                )
            else:
                expected = OPENACC[struct]
                if (
                    values["deviceType"] != 5
                    or not values["externalId"]
                    or "kind" in values
                    and (
                        values["kind"] != expected
                        if expected is not None
                        else values["kind"] not in (33, 34, 35)
                    )
                ):
                    warn(
                        "gpu-external-openacc-unavailable",
                        "OpenACC external IDs require a nonzero ID, NVIDIA deviceType and a compatible activity kind.",
                    )
                    errors += 1
                    continue
                external.append(
                    dict(
                        base,
                        id="event:" + str(event["id"]),
                        externalKind=2,
                        externalId=str(values["externalId"]),
                    )
                )
        return mappings, external, errors


def mapping_associations(
    model, streams, *, limit=2000, warn=lambda *args: None, visible=None
):
    """Resolve typed bridges without promoting an external range to a launch.

    Internal API IDs are unique per invocation. Reuse or runtime/driver domain
    collisions remain explicit; there is no inferred ID epoch from timestamps.
    """
    internal = collections.defaultdict(dict)
    for key, rows in model.correlations.items():
        process, paradigm, domain, value, _ = key
        if paradigm != "CUDA" or domain not in (
            "correlation",
            "runtime-correlation",
            "driver-correlation",
        ):
            continue
        numeric = unsigned_integer(value, 32)
        if numeric is None:
            continue
        for item, event, name, raw in rows.values():
            if cupti_correlation_member(name) is None:
                continue
            internal[(process, str(numeric))][(domain, item["id"])] = dict(
                id=item["id"],
                event=event["id"],
                location=item["location"],
                kind=item["kind"],
                label=item["label"],
                start=item["start"],
                end=item["end"],
                domain=domain,
            )
    external = collections.defaultdict(dict)
    for row in model.external_records:
        external[(row["process"], row["externalKind"], row["externalId"])][
            row["id"]
        ] = row
    # One CUDA invocation can be in one current external range for each kind.
    # Different complete mappings for the same kind/internal ID cannot be
    # resolved by their event times, which are not CUPTI buffer-order evidence.
    mapped = collections.defaultdict(set)
    for row in model.external_mappings:
        mapped[(row["process"], row["externalKind"], row["correlationId"])].add(
            row["externalId"]
        )
    rows = []
    links = []
    remaining = limit
    partial = model.truncated
    details = min(16, limit)
    internal_summary = {}
    for key, values in internal.items():
        refs = list(values.values())
        domains = {ref["domain"] for ref in refs}
        apis = {ref["id"] for ref in refs if ref["location"] not in streams}
        devices = {ref["id"] for ref in refs if ref["location"] in streams}
        selected = [ref for ref in refs if visible is None or visible(ref)]
        selected_ids = {(ref["domain"], ref["id"]) for ref in selected}
        preview = (
            selected
            + [ref for ref in refs if (ref["domain"], ref["id"]) not in selected_ids]
        )[:details]
        internal_summary[key] = (
            preview,
            len(refs),
            len(domains) > 1 or len(apis) > 1 or not apis and len(devices) > 1,
            bool(selected),
        )
    external_summary = {}
    for key, values in external.items():
        refs = list(values.values())
        selected = [ref for ref in refs if visible is None or visible(ref)]
        selected_ids = {ref["id"] for ref in selected}
        external_summary[key] = (
            (selected + [ref for ref in refs if ref["id"] not in selected_ids])[
                :details
            ],
            len(values),
            bool(selected),
        )
    for mapping in model.external_mappings:
        key = (mapping["process"], mapping["externalKind"], mapping["externalId"])
        refs, ref_count, ambiguous, internal_visible = internal_summary.get(
            (mapping["process"], mapping["correlationId"]), ([], 0, False, False)
        )
        origins, origin_count, external_visible = external_summary.get(
            key, ([], 0, False)
        )
        if visible is not None and not (
            visible(mapping) or internal_visible or external_visible
        ):
            continue
        conflict = (
            len(
                mapped[
                    (
                        mapping["process"],
                        mapping["externalKind"],
                        mapping["correlationId"],
                    )
                ]
            )
            > 1
        )
        status = "mapped"
        if model.truncated:
            status = "partial-scan"
        elif conflict:
            status = "conflicting-mappings"
        elif ambiguous:
            status = "ambiguous-internal-id"
        elif not refs:
            status = "internal-record-unavailable"
        elif origin_count > 1:
            status = "ambiguous-external-id"
        elif not origins:
            status = "external-record-unavailable"
        complete = status in ("mapped", "external-record-unavailable")
        row = dict(
            mapping,
            status=status,
            externalRecords=[
                {
                    key: value
                    for key, value in origin.items()
                    if key
                    in (
                        "id",
                        "event",
                        "location",
                        "recordType",
                        "span",
                        "label",
                        "start",
                        "end",
                        "time",
                    )
                }
                for origin in origins[:limit]
            ],
            externalRecordTotal=origin_count,
            internalRecords=refs,
            internalRecordTotal=ref_count,
            partial=ref_count > details or origin_count > details,
        )
        rows.append(row)
        if status == "conflicting-mappings":
            warn(
                "gpu-external-mapping-conflict",
                "Several external IDs of one kind claim the same CUDA invocation ID; all mappings remain inspectable.",
            )
        elif status == "ambiguous-internal-id":
            warn(
                "gpu-external-internal-ambiguous",
                "A bridge internal ID has reused invocations, distinct runtime/driver namespaces, or multiple device records without a unique API anchor; no external association is selected.",
            )
        elif status == "ambiguous-external-id":
            warn(
                "gpu-external-identity-ambiguous",
                "An external identity names several recorded regions; a mapping does not establish its lifetime.",
            )
        if row["partial"]:
            partial = True
        if not complete:
            continue
        origin = (
            origins[0]
            if origins
            else dict(
                id="cupti-external-id:" + ":".join(map(str, key)),
                event=mapping["event"],
                location=mapping["location"],
                time=mapping["time"],
                label=f"CUPTI {mapping['externalKindName']} external ID {mapping['externalId']}",
            )
        )
        for ref in refs:
            if remaining <= 0:
                partial = True
                break
            remaining -= 1
            links.append(dict(mapping=mapping, source=origin, target=ref))
    if partial and not model.truncated:
        warn(
            "gpu-external-association-limit",
            "External mapping associations exceeded the detail bound; mapping totals and evidence remain available.",
        )
    return rows, links, partial
