"""
Ingress backpressure for CacheSplit v4.
Rejects requests at the API gateway BEFORE they hit the queue, using
current queue depth as the signal. Turns "queue fills up then everything
degrades" into "clean 503 early."
"""
import logging
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BackpressureDecision:
    allow: bool
    retry_after_seconds: int = 0
    reason: str = ""
    current_depth: int = 0
    threshold: int = 0


class IngressBackpressure:
    """
    Rejects requests at the API gateway before they hit the queue,
    using current queue depth as the signal.

    Security requirement:
    - Backpressure thresholds must be per-tier (enterprise tenants get
      higher headroom). But the check itself must key on the
      authenticated tenant_id from TenantContext, same rule as the queue pool.

    Must not:
    - Apply backpressure based on global queue depth alone.
      A single hot tenant's queue filling up must not trip backpressure
      for everyone. Ties to tenant_queue_pool.py — per-tenant isolation.
    """

    # Per-tier thresholds (queue depth at which to start rejecting)
    TIER_THRESHOLDS: dict = {
        "enterprise": 5000,
        "standard": 1000,
        "basic": 500,
    }

    # Default retry-after header value when rejecting
    DEFAULT_RETRY_AFTER = 30  # seconds

    def __init__(self, queue_pool=None, metrics_collector=None):
        self._queue_pool = queue_pool
        self._metrics = metrics_collector
        self._reject_count = 0
        self._total_checks = 0

    async def check(
        self,
        tenant_id: str,
        tier: str = "standard",
        current_depth: int = None,
    ) -> BackpressureDecision:
        """
        Check if a request should be allowed or rejected due to backpressure.
        Returns BackpressureDecision — allow or reject with Retry-After.

        tenant_id MUST come from TenantContext (authenticated), never client input.
        """
        self._total_checks += 1

        # Get queue depth for this specific tenant only
        if current_depth is None and self._queue_pool:
            current_depth = await self._queue_pool.get_queue_depth(tenant_id)
        elif current_depth is None:
            current_depth = 0

        # Per-tier threshold — enterprise gets higher headroom
        threshold = self.TIER_THRESHOLDS.get(tier, self.TIER_THRESHOLDS["standard"])

        if current_depth >= threshold:
            self._reject_count += 1
            retry_after = self._calculate_retry_after(current_depth, threshold)
            logger.warning(
                f"Backpressure REJECT for tenant {tenant_id} "
                f"(tier={tier}, depth={current_depth}/{threshold})"
            )

            if self._metrics:
                self._metrics.record_reject("backpressure_rejected_total")

            return BackpressureDecision(
                allow=False,
                retry_after_seconds=retry_after,
                reason=f"Queue depth {current_depth} >= threshold {threshold}",
                current_depth=current_depth,
                threshold=threshold,
            )

        logger.debug(
            f"Backpressure ALLOW for tenant {tenant_id} "
            f"(depth={current_depth}/{threshold})"
        )
        return BackpressureDecision(
            allow=True,
            current_depth=current_depth,
            threshold=threshold,
            reason="within threshold",
        )

    def _calculate_retry_after(self, depth: int, threshold: int) -> int:
        """Calculate Retry-After seconds based on how overloaded we are."""
        ratio = depth / max(threshold, 1)
        if ratio > 2.0:
            return 60  # Severely overloaded
        elif ratio > 1.5:
            return 30
        else:
            return 15

    async def record_allowed(self, tenant_id: str, tier: str = "standard"):
        """Record an allowed request for metrics."""
        if self._metrics:
            self._metrics.record_success("backpressure_allowed_total")

    def get_stats(self) -> dict:
        """Get backpressure statistics."""
        return {
            "total_checks": self._total_checks,
            "reject_count": self._reject_count,
            "reject_rate": self._reject_count / max(self._total_checks, 1),
        }

    def get_tier_threshold(self, tier: str) -> int:
        """Get the queue depth threshold for a given tier."""
        return self.TIER_THRESHOLDS.get(tier, self.TIER_THRESHOLDS["standard"])


# Global singleton
ingress_backpressure = IngressBackpressure()
