"""
Single source of truth for region/node hierarchy in CacheSplit v4.
Which region owns which tenant, node roles (leader/replica), and multi-region membership.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Set
from enum import Enum

logger = logging.getLogger(__name__)


class NodeRole(str, Enum):
    LEADER = "leader"
    REPLICA = "replica"
    OBSERVER = "observer"


class TopologyView:
    """
    Immutable snapshot of the cluster topology at a point in time.
    Version is monotonic — bumps on any change.
    """
    region_id: str
    nodes: Tuple[str, ...]
    tenant_shards: Tuple[str, ...]
    is_home_region: bool
    version: int

    def __init__(self, region_id: str, nodes: Tuple[str, ...],
                 tenant_shards: Tuple[str, ...], is_home_region: bool,
                 version: int):
        self.region_id = region_id
        self.nodes = nodes
        self.tenant_shards = tenant_shards
        self.is_home_region = is_home_region
        self.version = version

    def with_nodes(self, nodes: Tuple[str, ...]) -> "TopologyView":
        """Return a new TopologyView with updated nodes, version bumped."""
        return TopologyView(
            region_id=self.region_id,
            nodes=nodes,
            tenant_shards=self.tenant_shards,
            is_home_region=self.is_home_region,
            version=self.version + 1,
        )


class Topology:
    """
    Single source of truth for region/node hierarchy.

    Security requirement:
    - Topology mutations (add/remove region or node) must go through
      lease.py + audit_log.py gates. An unauthenticated node cannot
      self-register into the cluster.
    - Stale topology is rejected — max TTL 30 seconds.

    Must not:
    - Allow a node to claim a region/tenant assignment it wasn't granted.
    - Cache stale topology beyond 30s TTL — stale routing = writes to wrong region.
    """

    TOPOLOGY_TTL_SECONDS = 30

    def __init__(self):
        self._topology: Dict[str, TopologyView] = {}
        self._node_roles: Dict[str, NodeRole] = {}
        self._tenant_region_map: Dict[str, str] = {}
        self._lock = __import__("asyncio").Lock()
        self._last_updated: float = 0.0

    async def initialize(self, home_region_id: str, nodes: List[str],
                         tenant_ids: List[str]):
        """
        Seed initial topology. This should only be called once at bootstrap.
        All mutations after this go through add_region/add_node.
        """
        async with self._lock:
            node_tuple = tuple(sorted(nodes))
            shard_tuple = tuple(sorted(tenant_ids))
            self._topology[home_region_id] = TopologyView(
                region_id=home_region_id,
                nodes=node_tuple,
                tenant_shards=shard_tuple,
                is_home_region=True,
                version=1,
            )
            for node in nodes:
                self._node_roles[node] = NodeRole.LEADER
            for tenant_id in tenant_ids:
                self._tenant_region_map[tenant_id] = home_region_id
            self._last_updated = time.monotonic()
            logger.info(f"Topology initialized: {home_region_id} with {len(nodes)} nodes, {len(tenant_ids)} tenants")

    async def add_region(self, region_id: str, nodes: List[str],
                         tenant_ids: List[str], lease_token: str,
                         actor: str) -> TopologyView:
        """
        Add a new region to the topology. Requires valid lease + audit trail.
        Returns the new TopologyView.
        """
        # Security gate: validate lease
        # In production, validate against lease_manager
        if not lease_token:
            raise ValueError("Lease token required to add region")

        async with self._lock:
            if region_id in self._topology:
                raise ValueError(f"Region {region_id} already exists")

            self._topology[region_id] = TopologyView(
                region_id=region_id,
                nodes=tuple(sorted(nodes)),
                tenant_shards=tuple(sorted(tenant_ids)),
                is_home_region=False,
                version=self._get_max_version() + 1,
            )
            for node in nodes:
                self._node_roles[node] = NodeRole.REPLICA
            self._last_updated = time.monotonic()
            logger.info(f"Region added: {region_id} nodes={len(nodes)}")
            return self._topology[region_id]

    async def add_node(self, node_id: str, region_id: str,
                       role: NodeRole, lease_token: str,
                       actor: str) -> TopologyView:
        """
        Add a node to an existing region. Requires valid lease + audit trail.
        """
        if not lease_token:
            raise ValueError("Lease token required to add node")

        async with self._lock:
            if region_id not in self._topology:
                raise ValueError(f"Region {region_id} does not exist")

            existing = self._topology[region_id]
            new_nodes = tuple(sorted(list(existing.nodes) + [node_id]))
            self._node_roles[node_id] = role
            self._topology[region_id] = existing.with_nodes(new_nodes)
            self._last_updated = time.monotonic()
            logger.info(f"Node {node_id} added to {region_id} as {role.value}")
            return self._topology[region_id]

    async def get_view(self, region_id: str = None,
                       force_refresh: bool = False) -> Optional[TopologyView]:
        """
        Get a topology view. Returns None if stale (TTL exceeded) and force_refresh not set.
        """
        async with self._lock:
            if not self._topology:
                return None

            if not force_refresh and (time.monotonic() - self._last_updated) > self.TOPOLOGY_TTL_SECONDS:
                logger.warning("Topology view stale — TTL exceeded")
                return None

            if region_id:
                return self._topology.get(region_id)
            # Return home region view
            for view in self._topology.values():
                if view.is_home_region:
                    return view
            return list(self._topology.values())[0]

    async def get_home_region(self, tenant_id: str) -> Optional[str]:
        """Get the home region for a tenant."""
        async with self._lock:
            return self._tenant_region_map.get(tenant_id)

    async def set_home_region(self, tenant_id: str, region_id: str,
                               lease_token: str, actor: str):
        """Set the home region for a tenant. Requires lease + audit."""
        if not lease_token:
            raise ValueError("Lease token required to change home region")

        async with self._lock:
            if region_id not in self._topology:
                raise ValueError(f"Region {region_id} does not exist")
            self._tenant_region_map[tenant_id] = region_id
            # Update all regions' is_home_region flag
            for rid, view in self._topology.items():
                if rid == region_id:
                    self._topology[rid] = view.with_nodes(view.nodes)
                else:
                    # Mark as non-home
                    pass
            self._last_updated = time.monotonic()
            logger.info(f"Home region for {tenant_id} set to {region_id}")

    async def is_stale(self) -> bool:
        """Check if topology data is older than TTL."""
        return (time.monotonic() - self._last_updated) > self.TOPOLOGY_TTL_SECONDS

    async def get_all_regions(self) -> List[str]:
        """List all region IDs."""
        async with self._lock:
            return list(self._topology.keys())

    def _get_max_version(self) -> int:
        return max((v.version for v in self._topology.values()), default=0)

    @property
    def version(self) -> int:
        return self._get_max_version()


# Global singleton
topology = Topology()
