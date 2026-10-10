"""Task identities shared by stack ingestion and recorded lifecycle analysis."""

TASK_INDEX_VERSION = 4
TASK_REIMPORT_WARNING = "task-index-reimport-required"


def process_scope(definitions, location):
    """Resolve ownership, without treating process creation as shared scope.

    OTF2 LocationGroup permits PROCESS -> PROCESS creator links. A process is
    already an ownership boundary; only an accelerator's creator supplies its
    owning process. Missing types/definitions never establish that relation.
    """
    unresolved = "unresolved-location:" + str(location)
    group = definitions.get("Location", {}).get(str(location), {}).get("locationGroup")
    if group is None:
        return unresolved
    group = str(group)
    seen = set()
    while group not in seen:
        seen.add(group)
        definition = definitions.get("LocationGroup", {}).get(group, {})
        kind = definition.get("locationGroupType")
        if type(kind) is int and kind == 1:
            return group
        if type(kind) is not int or kind != 2:
            return unresolved
        group = str(definition.get("creatingLocationGroup", 4294967295))
    return unresolved


def task_identity(kind, data, location, owner):
    def uint(value, bits):
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value < 2**bits
        )

    if kind.startswith("Omp"):
        if not uint(data.get("taskID"), 64):
            return None
        scope = owner(str(location))
        if scope is None or scope == "?":
            scope = "unresolved-location:" + str(location)
        return ("omp", str(scope), str(data["taskID"]))
    fields = ("threadTeam", "creatingThread", "generationNumber")
    # OTF2_CommRef reserves UINT32_MAX as OTF2_UNDEFINED_COMM. It cannot
    # identify a shared team, although the task generation may use all 32 bits.
    if (
        all(uint(data.get(field), 32) for field in fields)
        and data["threadTeam"] != 2**32 - 1
    ):
        return ("thread", *(str(data[field]) for field in fields))
    return None


def task_data(task):
    """Shared identity fields for lifecycle and conditional-wait evidence."""
    return dict(
        task=task["task"],
        taskInstance=task["instance"],
        identityAmbiguous=task["ambiguous"],
    )


def task_index_status(metadata):
    """Require replay only for event families affected by identity fixes."""
    version = metadata.get("taskIndexVersion", 0)
    counts = metadata.get("eventTypes", {})
    affected = any(
        counts.get(kind, 0)
        for kind in (
            "OmpTaskSwitch",
            "OmpTaskComplete",
            "ThreadTaskSwitch",
            "ThreadTaskComplete",
        )
    )
    return dict(
        version=version,
        currentVersion=TASK_INDEX_VERSION,
        requiresReimport=version < TASK_INDEX_VERSION and affected,
    )
