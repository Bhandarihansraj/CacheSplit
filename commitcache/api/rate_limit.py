"""
Per-identity rate limiting for CacheSplit v4.
Rate limit keyed on (tenant_id, identity) tuple, not IP.
Authenticated abuse from a single account gets throttled.
"""
import time
import logging
from typing import Dict, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class RateLimitExceeded(Exception):
    pass


class RateLimiter:
    """
    Per-identity rate limiter keyed on (tenant_id, identity).
    Unauthenticated requests fall back to IP-based limiting.

    Security requirement:
    - Rate limit per (tenant_id, identity) tuple for authenticated requests.
    - Unauthenticated requests rate-limited on IP only as fallback.

    Must not:
    - Rate limit based on IP alone for authenticated requests.
    - Allow unlimited requests from a single identity.
    """

    def __init__(self, default_limit: int = 100, default_window: float = 60.0):
        self.default_limit = default_limit
        self.default_window = default_window
        self._limits: Dict[Tuple[str, str], list[float]] = defaultdict(list)
        self._ip_limits: Dict[str, list[float]] = defaultdict(list)
        self._lock = __import__("asyncio").Lock()

    async def is_allowed(
        self,
        identity: str,
        tenant_id: str = None,
        ip: str = None,
        limit: int = None,
        window: float = None,
    ) -> bool:
        """
        Check if a request is allowed.
        Returns True if allowed, raises RateLimitExceeded if not.
        """
        limit = limit or self.default_limit
        window = window or self.default_window
        now = time.monotonic()
        key = (tenant_id, identity) if tenant_id else ("unauthenticated", identity)

        async with self._lock:
            if tenant_id and identity:
                # Authenticated: per (tenant_id, identity)
                timestamps = self._limits[key]
                # Remove old timestamps
                cutoff = now - window
                self._limits[key] = [t for t in timestamps if t > cutoff]

                if len(self._limits[key]) >= limit:
                    logger.warning(
                        f"Rate limit exceeded: {key} ({len(self._limits[key])}/{limit})"
                    )
                    raise RateLimitExceeded(
                        f"Rate limit exceeded for {identity} tenant={tenant_id}"
                    )
                self._limits[key].append(now)
                return True
            else:
                # Fallback: IP-based for unauthenticated
                ip = ip or "unknown"
                cutoff = now - window
                self._ip_limits[ip] = [t for t in self._ip_limits[ip] if t > cutoff]

                if len(self._ip_limits[ip]) >= limit:
                    logger.warning(f"IP rate limit exceeded: {ip}")
                    raise RateLimitExceeded(f"Rate limit exceeded for IP {ip}")
                self._ip_limits[ip].append(now)
                return True

    async def get_usage(self, identity: str, tenant_id: str = None) -> Dict:
        """Get current rate limit usage for an identity."""
        key = (tenant_id, identity) if tenant_id else ("unauthenticated", identity)
        async with self._lock:
            if tenant_id:
                count = len(self._limits[key])
                return {"identity": identity, "tenant_id": tenant_id, "current": count, "limit": self.default_limit}
            else:
                count = len(self._ip_limits[key])
                return {"identity": identity, "current": count, "limit": self.default_limit}

    async def reset(self, identity: str, tenant_id: str = None):
        """Reset rate limit counters for an identity."""
        key = (tenant_id, identity) if tenant_id else ("unauthenticated", identity)
        async with self._lock:
            if key in self._limits:
                del self._limits[key]
            else:
                self._ip_limits.pop(key[1], None)
            logger.info(f"Rate limit reset for {key}")


# Global singleton
rate_limiter = RateLimiter(default_limit=100, default_window=60.0)
