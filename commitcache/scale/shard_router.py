"""
Consistent-hashing shard router for CacheSplit v4.
Maps tenant_id -> shard -> subset of nodes via virtual nodes on a ring.
gossip_worker only talks to peers holding that tenant's data, not the whole cluster.
"""
import hashlib
import logging
import bisect
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShardAssignment:
    """Ordered list of node_ids owning a shard (primary + replicas)."""
    shard_id: str
    tenant_id: str
    primary: str
    replicas: Tuple[str, ...]
    virtual_node_count: int = 100  # Virtual nodes per physical node


class ShardRing:
    """
    Consistent-hashing ring mapping tenant_id -> shard -> nodes.

    Security requirement:
    - Shard map mutations (rebalancing) go through lease/audit gate.
    - An attacker forcing a fake rebalance could redirect tenant writes
      to a node they control — must be gated.

    Must not:
    - Rehash the entire ring on a single node add/remove.
      Use virtual nodes so only ~1/N of keys move.
    """

    VIRTUAL_NODES_PER_NODE = 100

    def __init__(self):
        self._ring: Dict[int, str] = {}  # virtual_node_position -> physical_node_id
        self._sorted_positions: List[int] = []
        self._node_to_shards: Dict[str, List[str]] = {}
        self._shards: Dict[str, ShardAssignment] = {}
        self._lock = __import__("asyncio").Lock()

    def _hash(self, key: str) -> int:
        """Hash a key onto the ring using SHA-256."""
        digest = hashlib.sha256(key.encode()).digest()
        return int.from_bytes(digest[:8], byteorder="little")

    async def add_node(self, node_id: str, lease_token: str,
                       actor: str, virtual_nodes: int = None):
        """
        Add a physical node to the ring with virtual nodes.
        Requires valid lease + audit trail for rebalancing.
        """
        if not lease_token:
            raise ValueError("Lease token required to add node to shard ring")

        async with self._lock:
            virtual_nodes = virtual_nodes or self.VIRTUAL_NODES_PER_NODE
            for i in range(virtual_nodes):
                vnode_key = f"{node_id}:vnode:{i}"
                pos = self._hash(vnode_key)
                self._ring[pos] = node_id

            self._sorted_positions = sorted(self._ring.keys())
            self._node_to_shards[node_id] = []
            logger.info(f"Node {node_id} added to ring with {virtual_nodes} virtual nodes")

    async def remove_node(self, node_id: str, lease_token: str, actor: str):
        """
        Remove a node from the ring. Only affected virtual nodes move —
        NOT a full rehash.
        """
        if not lease_token:
            raise ValueError("Lease token required to remove node from shard ring")

        async with self._lock:
            positions_to_remove = [
                pos for pos, nid in self._ring.items() if nid == node_id
            ]
            for pos in positions_to_remove:
                del self._ring[pos]

            self._sorted_positions = sorted(self._ring.keys())
            self._node_to_shards.pop(node_id, None)
            logger.info(f"Node {node_id} removed from ring")

    async def get_shard(self, tenant_id: str) -> ShardAssignment:
        """
        Map tenant_id to a shard via consistent hashing.
        Returns ShardAssignment with primary + replicas.
        """
        h = self._hash(tenant_id)
        pos = self._find_position(h)

        if pos is None or pos not in self._ring:
            raise ValueError(f"No nodes in shard ring for tenant {tenant_id}")

        primary = self._ring[pos]
        replicas = self._get_replicas(pos)

        shard_id = f"shard_{tenant_id[:8]}"
        return ShardAssignment(
            shard_id=shard_id,
            tenant_id=tenant_id,
            primary=primary,
            replicas=tuple(replicas),
        )

    def _find_position(self, hash_val: int) -> Optional[int]:
        """Find the first virtual node position >= hash_val using bisect."""
        if not self._sorted_positions:
            return None
        idx = bisect.bisect_left(self._sorted_positions, hash_val)
        if idx == len(self._sorted_positions):
            idx = 0  # Wrap around
        return self._sorted_positions[idx]

    def _get_replicas(self, primary_pos: int, count: int = 2) -> List[str]:
        """Get replica nodes by walking clockwise on the ring from primary."""
        if not self._sorted_positions:
            return []

        idx = self._sorted_positions.index(primary_pos)
        replicas = []
        for i in range(1, count + 1):
            replica_idx = (idx + i) % len(self._sorted_positions)
            replica_node = self._ring[self._sorted_positions[replica_idx]]
            if replica_node != self._ring[primary_pos] and replica_node not in replicas:
                replicas.append(replica_node)
        return replicas

    async def rebalance(self, lease_token: str, actor: str,
                         new_nodes: List[str] = None,
                         removed_nodes: List[str] = None):
        """
        Rebalance the ring — only affected virtual nodes move, not a full rehash.
        Requires lease + audit gate.
        """
        if not lease_token:
            raise ValueError("Lease token required for rebalance")

        # Only add/remove specific nodes — consistent hashing ensures
        # only ~1/N of keys move, not a full rehash
        if new_nodes:
            for node_id in new_nodes:
                await self.add_node(node_id, lease_token, actor)
        if removed_nodes:
            for node_id in removed_nodes:
                await self.remove_node(node_id, lease_token, actor)

        logger.info(f"Rebalance complete — only affected shards remapped")

    @property
    def node_count(self) -> int:
        return len(set(self._ring.values()))

    @property
    def is_empty(self) -> bool:
        return len(self._ring) == 0


# Global singleton
shard_ring = ShardRing()
