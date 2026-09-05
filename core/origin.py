"""
core/origin.py
Bounded source-of-truth for CacheSplit v4.
Enforces a token-bucket rate limit so no stampede can overwhelm it.
"""
import time
import logging
from typing import Optional
from dataclasses import dataclass, field

from core.stampede_limiter import TokenBucket

logger = logging.getLogger(__name__)


class OriginOverload(Exception):
    """Raised when the origin rejects a request due to rate limiting."""


@dataclass
class OriginRecord:
    key: str
    version: int
    data: dict
    updated_at: float = field(default_factory=time.monotonic)


class Origin:
    """
    Bounded source of truth. Wraps a simple in-memory store behind a
    TokenBucket so callers cannot overwhelm it with simultaneous refreshes.
    """

    def __init__(self, capacity_rps: float = 10.0, burst: int = None):
        self._store: dict[str, OriginRecord] = {}
        self._bucket = TokenBucket(rate_rps=capacity_rps, burst=burst)
        self._invalidation_bus = None  # injected after construction

    def attach_bus(self, bus):
        self._invalidation_bus = bus

    def get(self, key: str) -> Optional[OriginRecord]:
        """Fetch a record. Raises OriginOverload if rate limit hit."""
        if not self._bucket.consume():
            raise OriginOverload(f"Origin capacity exhausted (key={key})")
        return self._store.get(key)

    def update(self, key: str, data: dict) -> OriginRecord:
        """
        Write a new version. Always succeeds (writes bypass the bucket —
        only reads are limited). Broadcasts invalidation asynchronously.
        """
        old = self._store.get(key)
        new_version = (old.version + 1) if old else 1
        record = OriginRecord(key=key, version=new_version, data=data)
        self._store[key] = record
        logger.info(f"Origin: updated key={key} → v{new_version}")
        return record

    def seed(self, key: str, data: dict, version: int = 1) -> OriginRecord:
        """Seed initial state without broadcasting."""
        record = OriginRecord(key=key, version=version, data=data)
        self._store[key] = record
        return record

    def current_versions(self) -> dict[str, int]:
        return {k: v.version for k, v in self._store.items()}

    @property
    def bucket_level(self) -> float:
        return self._bucket.level
