"""Definition lookups shared by dependency and synchronization analysis."""

from ..tasks.identity import process_scope

GPU_PARADIGMS = {"CUDA", "HIP", "OPENCL", "OPENACC", "OPENMP_TARGET"}


def _string(trace, ref):
    return trace.defs.get("String", {}).get(str(ref), {}).get("string", "")


def _owner(trace, location):
    return process_scope(trace.defs, location)


def _members(trace, comm):
    definition = trace.defs.get("Comm", {}).get(str(comm), {})
    group = trace.defs.get("Group", {}).get(str(definition.get("group")), {})
    members = group.get("members", [])
    if group.get("groupType") == 5:
        world = next(
            (
                g.get("members", [])
                for g in trace.defs.get("Group", {}).values()
                if g.get("groupType") == 4
                and g.get("paradigm") == group.get("paradigm")
            ),
            [],
        )
        return [str(world[i]) for i in members if 0 <= i < len(world)]
    return list(map(str, members))
