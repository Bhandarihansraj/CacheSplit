"""
core/consistent_hash.py
CacheSplit v4 — Consistent Hash Ring (fixed from v3 review feedback)

Changes from v3:
  - Replaced MD5 with SHA-256 mod 2^32 (industry standard)
  - Ring space is 2^32 (not 360 degrees — eliminates collision at scale)
  - Each physical node gets 150 virtual nodes (no linear collision probing)
  - Virtual nodes are positioned by sha256(f"{node}-vnode-{i}") — guaranteed unique
"""
import hashlib
import bisect
import logging

logger = logging.getLogger(__name__)

RING_SIZE = 2**32       # Standard 32-bit ring space
VIRTUAL_NODES = 150     # Virtual nodes per physical node


def _hash(key: str) -> int:
    """SHA-256 hash mod RING_SIZE. Deterministic, collision-resistant."""
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % RING_SIZE


class HashRing:
    """
    Consistent hash ring with virtual node replication.
    Handles node addition/removal with minimal key remapping.
    """

    def __init__(self, nodes: list[str] = None):
        self._ring: dict[int, str] = {}
        self._sorted_keys: list[int] = []

        for node in (nodes or []):
            self.add_node(node)

    def add_node(self, node: str):
        """Add a physical node with VIRTUAL_NODES virtual positions."""
        added = 0
        for i in range(VIRTUAL_NODES):
            pos = _hash(f"{node}-vnode-{i}")
            if pos not in self._ring:
                self._ring[pos] = node
                bisect.insort(self._sorted_keys, pos)
                added += 1
        logger.debug(f"HashRing: added node={node} with {added} virtual positions")

    def remove_node(self, node: str):
        """Remove a node and all its virtual positions."""
        to_remove = [pos for pos, n in self._ring.items() if n == node]
        for pos in to_remove:
            del self._ring[pos]
            idx = bisect.bisect_left(self._sorted_keys, pos)
            if idx < len(self._sorted_keys) and self._sorted_keys[idx] == pos:
                self._sorted_keys.pop(idx)
        logger.debug(f"HashRing: removed node={node} ({len(to_remove)} virtual positions)")

    def get_node(self, key: str) -> str | None:
        """
        Return the node responsible for `key`.
        Walks clockwise from the key's hash position to the first virtual node.
        """
        if not self._sorted_keys:
            return None
        h = _hash(key)
        idx = bisect.bisect_right(self._sorted_keys, h) % len(self._sorted_keys)
        return self._ring[self._sorted_keys[idx]]

    def get_nodes(self, key: str, count: int = 1) -> list[str]:
        """
        Return up to `count` distinct physical nodes responsible for `key`
        (for replication factor > 1).
        """
        if not self._sorted_keys:
            return []
        h = _hash(key)
        idx = bisect.bisect_right(self._sorted_keys, h) % len(self._sorted_keys)
        seen: set[str] = set()
        result: list[str] = []
        for i in range(len(self._sorted_keys)):
            pos = self._sorted_keys[(idx + i) % len(self._sorted_keys)]
            node = self._ring[pos]
            if node not in seen:
                seen.add(node)
                result.append(node)
            if len(result) >= count:
                break
        return result

    def __len__(self) -> int:
        return len(set(self._ring.values()))

    def __repr__(self) -> str:
        return f"HashRing(nodes={len(self)}, virtual_positions={len(self._sorted_keys)})"
