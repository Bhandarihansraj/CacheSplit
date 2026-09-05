"""
Per-tenant queue pool for CacheSplit v4.
Replaces single global repair_queue with per-tenant bounded queues.
One noisy tenant's repair volume cannot starve others.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, List

logger = logging.getLogger(__name__)


@dataclass
class RepairTask:
    """A repair task carrying tenant_id for queue routing."""
    tenant_id: str
    key: str
    priority: int = 0
    timestamp: float = field(default_factory=lambda: __import__("time").monotonic())
    retry_count: int = 0


@dataclass
class TenantQueueStats:
    """Per-tenant queue statistics."""
    tenant_id: str
    queue_depth: int
    max_size: int
    processed: int = 0
    rejected: int = 0
    tier: str = "standard"


class TenantQueuePool:
    """
    Per-tenant (or per-tier) bounded queues. One noisy tenant's repair
    volume cannot starve others.

    Security requirement:
    - Queue keying must use the *authenticated* tenant_id from TenantContext.
    - Never use a client-supplied field — a tenant could spoof another
      tenant's queue key to starve them or dodge their own limits.

    Must not:
    - Let one tenant's full queue block queue_pool.put() for a different
      tenant (each queue's backpressure is isolated).
    - Accept client-supplied tenant_id for queue keying.
    """

    def __init__(self, max_per_tenant: int = 1000,
                 tier_weights: Dict[str, int] = None):
        self._max_per_tenant = max_per_tenant
        self._tier_weights = tier_weights or {
            "enterprise": 5000,
            "standard": 1000,
            "basic": 500,
        }
        self._queues: Dict[str, asyncio.Queue] = {}
        self._stats: Dict[str, TenantQueueStats] = {}
        self._lock = __import__("asyncio").Lock()

    async def get_or_create(self, tenant_id: str,
                            tier: str = "standard",
                            max_size: int = None) -> asyncio.Queue:
        """
        Get existing queue or lazily create one for this tenant.
        tenant_id MUST come from TenantContext (authenticated), never from client input.
        Returns the bounded asyncio.Queue for this tenant.
        """
        async with self._lock:
            if tenant_id not in self._queues:
                effective_max = max_size or self._tier_weights.get(tier, self._max_per_tenant)
                self._queues[tenant_id] = asyncio.Queue(maxsize=effective_max)
                self._stats[tenant_id] = TenantQueueStats(
                    tenant_id=tenant_id,
                    queue_depth=0,
                    max_size=effective_max,
                    tier=tier,
                )
                logger.info(f"Queue created for tenant {tenant_id} (tier={tier}, max={effective_max})")

            return self._queues[tenant_id]

    async def put(self, tenant_id: str, task: RepairTask,
                  tier: str = "standard") -> bool:
        """
        Route a repair task to the tenant's queue. Returns True if enqueued, False if rejected.
        tenant_id MUST be from TenantContext (authenticated), never client-supplied.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required — must come from TenantContext")

        queue = await self.get_or_create(tenant_id, tier=tier)

        if queue.full():
            self._stats[tenant_id].rejected += 1
            logger.warning(f"Queue full for tenant {tenant_id}")
            return False

        await queue.put(task)
        self._stats[tenant_id].queue_depth = queue.qsize()
        self._stats[tenant_id].processed += 1
        return True

    async def get(self, tenant_id: str) -> Optional[RepairTask]:
        """Get next repair task for a tenant's queue."""
        queue = self._queues.get(tenant_id)
        if not queue or queue.empty():
            return None
        task = await queue.get()
        self._stats[tenant_id].queue_depth = queue.qsize()
        return task

    def get_stats(self, tenant_id: str = None) -> Dict:
        """Get queue stats for a tenant or all tenants."""
        if tenant_id:
            return self._stats.get(tenant_id, TenantQueueStats(tenant_id, 0, 0)).__dict__
        return {tid: stats.__dict__ for tid, stats in self._stats.items()}

    async def reject_if_overloaded(self, tenant_id: str,
                                     tier: str = "standard") -> bool:
        """
        Check if a tenant's queue is overloaded.
        Returns True if rejected (backpressure applied).
        """
        stats = self._stats.get(tenant_id)
        if not stats:
            return False

        max_size = self._tier_weights.get(tier, self._max_per_tenant)
        if stats.queue_depth >= max_size:
            logger.warning(f"Overloaded queue for tenant {tenant_id}: {stats.queue_depth}/{max_size}")
            return True
        return False

    async def get_queue_depth(self, tenant_id: str) -> int:
        """Get current queue depth for a tenant."""
        stats = self._stats.get(tenant_id)
        return stats.queue_depth if stats else 0

    @property
    def tenant_count(self) -> int:
        return len(self._queues)


# Global singleton
tenant_queue_pool = TenantQueuePool()
