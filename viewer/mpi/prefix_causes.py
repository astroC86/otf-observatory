"""Communicator-prefix prerequisites with linear shared storage.

Paging follows communicator rank; bounded overlap inspection uses a shared
segment tree of readiness maxima rather than scanning each receiver's prefix.
"""

from __future__ import annotations
import heapq
import math
from ..causality.lazy_causes import BarrierCohort, BarrierView


class PrefixCohort(BarrierCohort):
    __slots__ = ("ranks", "prefix_ready", "tree", "base")

    def __init__(
        self,
        ident,
        communicator,
        peers,
        *,
        ranks,
        kind="collective_payload",
        reason="",
        expected_prerequisites=None,
        extra=None,
    ):
        self.id = ident
        self.communicator = communicator
        self.ranks = dict(ranks)
        n = max(0, len(ranks) - 1)
        if set(ranks.values()) != set(range(len(ranks))):
            raise ValueError("Prefix ranks must be contiguous and unique")
        ordered = [None] * n
        for peer in peers:
            rank = ranks.get(str(peer[0]))
            if rank is None or rank >= n or ordered[rank] is not None:
                raise ValueError("Invalid or duplicate prefix contributor")
            if not math.isfinite(peer[2]):
                raise ValueError("Prefix readiness must be finite")
            ordered[rank] = peer
        if any(peer is None for peer in ordered):
            raise ValueError("Missing prefix contributor")
        self.peers = tuple(ordered)
        self.ready = tuple(peer[2] for peer in ordered)
        self.positions = {str(peer[0]): rank for rank, peer in enumerate(ordered)}
        self.kind = kind
        self.reason = reason
        self.expected_prerequisites = n
        self.extra = extra or {}
        maximum = -math.inf
        prefix = [maximum]
        for ready in self.ready:
            maximum = max(maximum, ready)
            prefix.append(maximum)
        self.prefix_ready = tuple(prefix)
        self.base = 1 << (max(1, n) - 1).bit_length()
        self.tree = [-math.inf] * (2 * self.base)
        self.tree[self.base : self.base + n] = self.ready
        for node in range(self.base - 1, 0, -1):
            self.tree[node] = max(self.tree[2 * node], self.tree[2 * node + 1])

    @property
    def storage_weight(self):
        return (
            1
            + len(self.peers)
            + len(self.ranks)
            + len(self.prefix_ready)
            + len(self.tree)
        )

    def view(self, participant, target, target_id, *, required=True, request=None):
        return PrefixView(
            self, participant, target, target_id, required=required, request=request
        )


class PrefixView(BarrierView):
    __slots__ = ("rank",)

    def _select(self, participant, end, valid):
        cohort = self.cohort
        self.rank = cohort.ranks.get(str(participant), 0)
        self.excluded = -1
        self.stop = self.rank if valid and cohort.prefix_ready[self.rank] <= end else 0
        self.ready = cohort.prefix_ready[self.stop] if self.stop else None

    def _cause(self, position):
        cause = super()._cause(position)
        cause.extra.update(
            expectedPrerequisites=self.rank, sourceRank=position, targetRank=self.rank
        )
        return cause

    def _overlap_indices(self, threshold):
        tree = self.cohort.tree
        base = self.cohort.base
        # Disjoint segment-tree cover of ranks [0,stop), without examining
        # ranks outside the receiver's communicator prefix.
        left = base
        right = base + self.stop
        heap = []
        while left < right:
            if left & 1:
                if tree[left] > threshold:
                    heapq.heappush(heap, (-tree[left], left))
                left += 1
            if right & 1:
                right -= 1
                if tree[right] > threshold:
                    heapq.heappush(heap, (-tree[right], right))
            left //= 2
            right //= 2
        while heap:
            _, node = heapq.heappop(heap)
            if node >= base:
                yield node - base
            else:
                for child in (node * 2, node * 2 + 1):
                    if tree[child] > threshold:
                        heapq.heappush(heap, (-tree[child], child))
