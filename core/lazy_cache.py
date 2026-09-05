"""
core/lazy_cache.py
Lazy-Loaded Cache Manager for CacheSplit v4.
Separates ultra-lightweight cryptographic hash pointers (stored in fast in-memory / Redis cache)
from heavy JSON data payloads (persisted in SQLite/Postgres DB and hydrated lazily on-demand).
"""
import time
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class HashPointer:
    key: str
    hash: str
    version: int
    node_id: str
    state: str = "FRESH"
    updated_at: float = field(default_factory=time.time)


class LazyCacheStore:
    """
    In-memory / Redis-compatible hash pointer cache.
    Holds pointers (<80 bytes each) and lazily delegates full payload fetching to a DB loader.
    """

    def __init__(self, db_loader_func=None):
        self._pointers: Dict[str, HashPointer] = {}
        self._db_loader = db_loader_func
        self._hydrated_cache: Dict[str, Dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.lazy_loads = 0

    def set_db_loader(self, loader_func):
        self._db_loader = loader_func

    def put_pointer(self, key: str, sha256_hash: str, version: int, node_id: str, state: str = "FRESH"):
        """Store only the lightweight pointer in cache."""
        self._pointers[key] = HashPointer(
            key=key, hash=sha256_hash, version=version, node_id=node_id, state=state
        )
        # Invalidate hydrated payload if present
        self._hydrated_cache.pop(key, None)

    def get_pointer(self, key: str) -> Optional[HashPointer]:
        """Fetch the lightweight hash pointer in O(1) time."""
        return self._pointers.get(key)

    async def get_lazy(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Lazily hydrate the heavy JSON payload from persistent storage
        only if requested and pointer exists.
        """
        pointer = self.get_pointer(key)
        if not pointer:
            self.misses += 1
            return None

        # Check fast in-memory hydrated buffer
        if key in self._hydrated_cache:
            self.hits += 1
            return self._hydrated_cache[key]

        # Lazy hydration from DB
        if self._db_loader:
            self.lazy_loads += 1
            payload = await self._db_loader(key)
            if payload:
                self._hydrated_cache[key] = payload
                return payload

        return {"key": key, "hash": pointer.hash, "version": pointer.version, "node_id": pointer.node_id}

    def stats(self) -> Dict[str, Any]:
        return {
            "pointer_count": len(self._pointers),
            "hydrated_count": len(self._hydrated_cache),
            "hits": self.hits,
            "misses": self.misses,
            "lazy_loads": self.lazy_loads,
        }


lazy_cache = LazyCacheStore()
