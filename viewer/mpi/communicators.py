"""OTF2 communicator rank identities, separate from executing locations.

COMM_LOCATIONS names locations; COMM_LOCATION_GROUPS (wire value 7) names
location groups. A group identity never implies which thread executed an event.
"""

GROUP_PREFIX = "location-group:"


class Communicators:
    """Rank identity resolution over a definitions mapping.

    Resolved local/peer identities are memoized; a caller that changes
    definitions after resolving must call invalidate().
    """

    def __init__(self, definitions):
        self.defs = definitions
        self._locals = {}
        self._peers = {}

    def invalidate(self):
        self._locals.clear()
        self._peers.clear()

    def group(self, reference):
        return self.defs.get("Group", {}).get(str(reference), {})

    def request_scope(self, location):
        location = str(location)
        owner = self.defs.get("Location", {}).get(location, {}).get("locationGroup")
        return GROUP_PREFIX + str(owner) if owner is not None else location

    def world(self, paradigm):
        return next(
            (
                g
                for g in self.defs.get("Group", {}).values()
                if g.get("groupType") in (4, 7) and g.get("paradigm") == paradigm
            ),
            {},
        )

    def members(self, reference, global_members=False):
        group = self.group(reference)
        kind = group.get("groupType")
        members = group.get("members", [])
        if kind == 5:
            world = self.world(group.get("paradigm"))
            domain = self.world_members(world)
            if global_members:
                return domain
            # Invalid members must not shift subsequent rank indices.
            return [
                domain[int(i)] if 0 <= int(i) < len(domain) else None for i in members
            ]
        return self.world_members(group) if kind in (1, 4, 7) else []

    @staticmethod
    def world_members(world):
        prefix = GROUP_PREFIX if world.get("groupType") == 7 else ""
        return [prefix + str(i) for i in world.get("members", [])]

    def representative(self, location, members):
        location = str(location)
        owner = self.defs.get("Location", {}).get(location, {}).get("locationGroup")
        if owner is not None and GROUP_PREFIX + str(owner) in members:
            return GROUP_PREFIX + str(owner)
        if location in members:
            return location
        if owner is None:
            return None
        matches = [
            m
            for m in members
            if m is not None
            and str(self.defs.get("Location", {}).get(m, {}).get("locationGroup"))
            == str(owner)
        ]
        return matches[0] if len(matches) == 1 else None

    def local(self, communicator, location):
        key = (str(communicator), str(location))
        if key not in self._locals:
            self._locals[key] = self._local(*key)
        return self._locals[key]

    def _local(self, communicator, location):
        inter = self.defs.get("InterComm", {}).get(communicator)
        if inter:
            return self.representative(
                location, self.members(inter["groupA"]) + self.members(inter["groupB"])
            )
        comm = self.defs.get("Comm", {}).get(communicator)
        if not comm:
            return None
        group = self.group(comm["group"])
        if group.get("groupType") == 6:
            world = self.world(group.get("paradigm"))
            return (
                self.representative(location, self.world_members(world))
                if world
                else location
            )
        return self.representative(location, self.members(comm["group"]))

    def peer(self, communicator, rank, location):
        key = (str(communicator), int(rank), str(location))
        if key not in self._peers:
            self._peers[key] = self._peer(*key)
        return self._peers[key]

    def _peer(self, communicator, rank, location):
        inter = self.defs.get("InterComm", {}).get(communicator)
        if inter:
            a, b = self.members(inter["groupA"]), self.members(inter["groupB"])
            local = self.representative(location, a + b)
            if local is None or (local in a) == (local in b):
                return None
            reference = inter["groupB"] if local in a else inter["groupA"]
        else:
            comm = self.defs.get("Comm", {}).get(communicator)
            if not comm:
                return None
            reference = comm["group"]
            if self.group(reference).get("groupType") == 6:
                return self.local(communicator, location) if rank == 0 else None
        members = self.members(
            reference, bool(self.group(reference).get("groupFlags", 0) & 1)
        )
        return members[rank] if 0 <= rank < len(members) else None

    @staticmethod
    def endpoint(identity):
        """An unmatched group rank does not identify an executing thread."""
        return (
            None if identity is None or identity.startswith(GROUP_PREFIX) else identity
        )
