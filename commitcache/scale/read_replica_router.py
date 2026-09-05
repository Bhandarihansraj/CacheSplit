"""
Read replica router for CacheSplit v4.
Separates read-heavy tenant traffic onto replica nodes instead of
hitting the primary/lease-holder. Write path still goes through
region_router.py + lease, but reads don't need a lease at all.
"""
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeTarget:
    """Target node for an operation."""
    node_id: str
    requires_lease: bool = False
    staleness_ms: int = 0  # 0 = reading lease-holder (fresh)
    is_primary: bool = True


@dataclass
class ShardAssignment:
    """Shard assignment with primary + replicas."""
    shard_id: str
    tenant_id: str
    primary: str
    replicas: tuple
    virtual_node_count: int = 100


class ReadReplicaRouter:
    """
    Separates read-heavy traffic onto replica nodes.
    Write path goes through region_router.py + lease.
    Reads don't need a lease at all — but still pass through auth.py scoping.

    Security requirement:
    - Replica reads must pass through api/auth.py scoping.
      "Read-only" doesn't mean "unauthenticated."
    - Stale-read tolerance must be explicit (return staleness_ms field)
      so callers know they're not reading the lease-holder's latest state.

    Must not:
    - Route writes to a replica under any load condition.
      That's exactly the split-brain scenario lease.py exists to prevent.
    """

    # Default replication lag estimate in milliseconds
    DEFAULT_REPLICATION_LAG_MS = 500
    MAX_ESTIMATED_LAG_MS = 5000

    def __init__(self, shard_ring=None, metrics=None):
        self._shard_ring = shard_ring
        self._metrics = metrics
        self._read_count = 0
        self._write_count = 0
        self._stale_read_count = 0

    def route_operation(
        self, tenant_id: str, op: str,
        shard: ShardAssignment = None
    ) -> NodeTarget:
        """
        Route a read or write operation to the appropriate node.
        Reads go to replicas (with staleness_ms estimate).
        Writes always go to primary with requires_lease=True.
        """
        if op == "write":
            self._write_count += 1
            if not shard or not shard.primary:
                raise ValueError("Write requires a shard assignment with primary node")
            return NodeTarget(
                node_id=shard.primary,
                requires_lease=True,
                staleness_ms=0,
                is_primary=True,
            )

        # Read operation — route to replica
        return self._route_read(tenant_id, shard)

    def _route_read(self, tenant_id: str,
                    shard: ShardAssignment = None) -> NodeTarget:
        """Route a read to a replica node with staleness estimate."""
        self._read_count += 1

        if not shard or not shard.replicas:
            # Fallback to primary if no replicas available
            logger.warning(f"No replicas for {tenant_id}, routing read to primary")
            return NodeTarget(
                node_id=shard.primary if shard else "unknown",
                requires_lease=True,  # Still requires lease for primary read
                staleness_ms=0,
                is_primary=True,
            )

        # Pick a random replica for load distribution
        replica_node = random.choice(list(shard.replicas))

        # Estimate replication lag
        staleness_ms = self._estimate_replication_lag(replica_node, shard)

        # If staleness is high, count as stale read
        if staleness_ms > self.DEFAULT_REPLICATION_LAG_MS:
            self._stale_read_count += 1
            if self._metrics:
                self._metrics.record_success("stale_read_total")

        logger.debug(
            f"Read routed to replica {replica_node} for {tenant_id}, "
            f"staleness_est={staleness_ms}ms"
        )

        return NodeTarget(
            node_id=replica_node,
            requires_lease=False,
            staleness_ms=staleness_ms,
            is_primary=False,
        )

    def _estimate_replication_lag(self, replica_node: str,
                                   shard: ShardAssignment) -> int:
        """
        Estimate replication lag for a replica node.
        In production: use heartbeat timestamps from gossip_worker.
        Here: returns a bounded estimate based on shard configuration.
        """
        # Simulated lag — in production, derive from gossip health signals
        base_lag = self.DEFAULT_REPLICATION_LAG_MS
        variance = random.randint(0, self.MAX_ESTIMATED_LAG_MS - base_lag)
        return base_lag + variance

    def validate_write_target(self, target: NodeTarget,
                               shard: ShardAssignment) -> bool:
        """
        Validate that a write target is the primary node, not a replica.
        Returns True if valid, raises ValueError if replica.
        """
        if not target.is_primary:
            raise ValueError(
                f"Write routed to replica {target.node_id} — "
                f"split-brain risk. Write must go to primary {shard.primary}"
            )
        if not target.requires_lease:
            raise ValueError(
                f"Write target {target.node_id} requires a lease"
            )
        return True

    def get_stats(self) -> dict:
        """Get read/write routing statistics."""
        total_reads = self._read_count + max(self._stale_read_count, 0)
        return {
            "read_count": self._read_count,
            "write_count": self._write_count,
            "stale_read_count": self._stale_read_count,
            "stale_read_rate": self._stale_read_count / max(self._read_count, 1),
        }


# Global singleton
read_replica_router = ReadReplicaRouter()
