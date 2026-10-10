"""Taskwait encodings positively identified in the local Score-P 10 source.

This classifies the recording, not application dataflow. Score-P's OMPT
adapter omits undeferred/merged task identities and does not register OMPT
dependence callbacks, so even an ordinary wait does not prove a full task set.
"""

import re

NAMES = {
    "!$omp taskwait": "all-direct-children",
    "!$omp taskwait depend": "depend-clause",
    "!$omp taskwait depend nowait": "depend-nowait",
}


def has_scorep_ompt_wait_definitions(definitions):
    strings = definitions.get("String", {})
    text = lambda ref: strings.get(str(ref), {}).get("string", "")
    # The OMPT adapter registers all three fallback regions at initialization.
    # This distinguishes its names from OPARI2/user regions in the same archive.
    fallback = {
        text(row.get("name"))
        for row in definitions.get("Region", {}).values()
        if type(row.get("regionRole")) is int
        and row["regionRole"] == 22
        and type(row.get("paradigm")) is int
        and row["paradigm"] == 3
        and text(row.get("sourceFile")) == "OMP"
        and text(row.get("canonicalName")) == text(row.get("name"))
        and type(row.get("beginLineNumber")) is int
        and row["beginLineNumber"] == 0
        and type(row.get("endLineNumber")) is int
        and row["endLineNumber"] == 0
    }
    return set(NAMES) <= fallback


def scorep_ompt_recording(trace):
    """Require both the archive creator and the adapter's fallback regions."""
    archives = list(trace.defs.get("ArchiveProperties", {}).values())
    return (
        len(archives) == 1
        and archives[0].get("creator") == "Score-P 10.0"
        and has_scorep_ompt_wait_definitions(trace.defs)
    )


def scorep_ompt_taskwait_contracts(trace):
    return _scorep_ompt_contracts(trace, NAMES, 22)


def scorep_ompt_taskgroup_contracts(trace):
    """The adapter records the taskgroup body, not its terminal wait portion."""
    contracts = _scorep_ompt_contracts(
        trace, {"!$omp taskgroup": "bound-descendants"}, 15
    )
    # Like the three taskwait names, this fallback is registered at startup.
    strings = trace.defs.get("String", {})
    text = lambda ref: strings.get(str(ref), {}).get("string", "")
    if not any(
        text(trace.defs["Region"][ref].get("name")) == "!$omp taskgroup"
        and text(trace.defs["Region"][ref].get("sourceFile")) == "OMP"
        for ref in contracts
    ):
        return {}
    for contract in contracts.values():
        contract.update(
            completionOnly=False,
            fullRegion=True,
            waitStartRecorded=False,
            limitation="Score-P records the whole taskgroup region and a subset of task identities, but not its terminal wait entry, dependence lists, or detached-task fulfillment.",
        )
    return contracts


def scorep_ompt_cancellation_contracts(trace):
    return _scorep_ompt_contracts(
        trace, {"!$omp cancel": "activated", "!$omp cancellation point": "detected"}, 39
    )


def _scorep_ompt_contracts(trace, names, role):
    if not scorep_ompt_recording(trace):
        return {}
    strings = trace.defs.get("String", {})
    text = lambda ref: strings.get(str(ref), {}).get("string", "")
    regions = trace.defs.get("Region", {})
    result = {}
    for ref, row in regions.items():
        if (
            type(row.get("regionRole")) is not int
            or row["regionRole"] != role
            or type(row.get("paradigm")) is not int
            or row["paradigm"] != 3
        ):
            continue
        name = text(row.get("name"))
        match = re.fullmatch(
            "("
            + "|".join(re.escape(name) for name in names)
            + r")(?: @(0x[0-9a-f]{8,16}|[^/]+:[0-9]{1,10}))?",
            name,
        )
        if match is None:
            continue
        # All three producer paths retain identical name/canonicalName.
        if text(row.get("canonicalName")) != name:
            continue
        line = row.get("beginLineNumber")
        if (
            type(line) is not int
            or not 0 <= line < 2**32
            or type(row.get("endLineNumber")) is not int
            or row["endLineNumber"] != 0
        ):
            continue
        suffix = match[2]
        if suffix is None:
            if text(row.get("sourceFile")) != "OMP" or line != 0:
                continue
        elif re.fullmatch(r"0x[0-9a-f]{8,16}", suffix):
            if int(suffix, 16) == 0 or "/" in text(row.get("sourceFile")):
                continue
        else:
            file, encoded_line = suffix.rsplit(":", 1)
            source = text(row.get("sourceFile"))
            if (
                "/" not in source
                or source.rsplit("/", 1)[-1] != file
                or str(line) != encoded_line
            ):
                continue
        semantics = names[match[1]]
        result[str(ref)] = dict(
            producer="Score-P 10.0",
            adapter="OMPT",
            region=str(ref),
            semantics=semantics,
            completionOnly=semantics != "all-direct-children",
            taskContextComplete=False,
            dependenceListsRecorded=False,
            evidence="Archive creator, OMPT fallback-region declarations and the recorded region definition.",
            limitation="This adapter omits undeferred/merged task identities and does not record OMPT dependence lists.",
        )
    return result
