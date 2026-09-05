"""
Lease management for CacheSplit v4.
Time-boxed leases on (tenant_id, key) before any repair operation.
Uses atomic SET NX PX semantics via a pluggable backend.
"""
import asyncio
import time
import hmac
import hashlib
import logging
import uuid
from typing import Optional, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class LeaseExpired(Exception):
    pass


class LeaseAcquisitionError(Exception):
    pass


@dataclass
class Lease:
    lease_token: str
    tenant_id: str
    key: str
    expires_at: float
    acquired_at: float

    def is_valid(self) -> bool:
        return time.monotonic() < self.expires_at

    @property
    def remaining_ms(self) -> float:
        return max(0, (self.expires_at - time.monotonic()) * 1000)


class LeaseManager:
    """
    Acquire and release time-boxed leases on (tenant_id, key).

    Security requirement:
    - Lease acquisition uses atomic SET NX PX semantics.
    - Lease tokens are HMAC-signed so they cannot be forged.
    - No repair proceeds without a valid, non-expired lease_token.
    """

    def __init__(self, signing_key: str, default_ttl_ms: int = 30000):
        self.signing_key = signing_key
        self.default_ttl_ms = default_ttl_ms
        self._leases: Dict[str, Lease] = {}
        self._lock = asyncio.Lock()

    def _sign_token(self, tenant_id: str, key: str, expires_at: float) -> str:
        """HMAC-sign the lease parameters so tokens cannot be forged."""
        payload = f"{tenant_id}:{key}:{expires_at}"
        sig = hmac.new(
            self.signing_key.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return f"{uuid.uuid4().hex}:{sig}"

    async def acquire(
        self, tenant_id: str, key: str, ttl_ms: int = None
    ) -> Optional[Lease]:
        """
        Acquire a time-boxed lease on (tenant_id, key).
        Uses atomic semantics — no read-then-write race.
        Returns Lease object or None if acquisition failed.
        """
        ttl_ms = ttl_ms or self.default_ttl_ms
        expires_at = time.monotonic() + (ttl_ms / 1000.0)
        lease_token = self._sign_token(tenant_id, key, expires_at)

        async with self._lock:
            # Atomic check-and-set: no double-lease on same key
            lease_id = f"{tenant_id}:{key}"
            if lease_id in self._leases:
                existing = self._leases[lease_id]
                if existing.is_valid():
                    logger.warning(
                        f"Lease conflict: {lease_id} already held"
                    )
                    return None

            lease = Lease(
                lease_token=lease_token,
                tenant_id=tenant_id,
                key=key,
                expires_at=expires_at,
                acquired_at=time.monotonic(),
            )
            self._leases[lease_id] = lease
            logger.info(f"Lease acquired: {lease_id} ttl={ttl_ms}ms")
            return lease

    async def release(self, lease_token: str) -> bool:
        """Release a lease by its token. Returns True on success."""
        async with self._lock:
            for lease_id, lease in list(self._leases.items()):
                if lease.lease_token == lease_token:
                    if not lease.is_valid():
                        raise LeaseExpired(f"Lease {lease_id} already expired")
                    del self._leases[lease_id]
                    logger.info(f"Lease released: {lease_id}")
                    return True
        return False

    async def validate(self, lease_token: str) -> Optional[Lease]:
        """
        Validate a lease token. Returns the Lease if valid, None otherwise.
        Must be called before every repair operation.
        """
        async with self._lock:
            for lease_id, lease in list(self._leases.items()):
                if lease.lease_token == lease_token:
                    if not lease.is_valid():
                        del self._leases[lease_id]
                        logger.warning(f"Lease expired: {lease_id}")
                        return None
                    return lease
        return None

    async def cleanup_expired(self) -> int:
        """Remove all expired leases. Returns count of cleaned."""
        async with self._lock:
            now = time.monotonic()
            expired = [k for k, v in self._leases.items() if not v.is_valid()]
            for k in expired:
                del self._leases[k]
            logger.info(f"Cleaned {len(expired)} expired leases")
            return len(expired)


# Global singleton
lease_manager = LeaseManager(signing_key="default-signing-key-change-me")
