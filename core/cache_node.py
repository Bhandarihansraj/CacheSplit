"""
core/cache_node.py
Per-node versioned KV store for CacheSplit v4.
Each entry tracks its state: FRESH | STALE | REPAIRING.
"""
import time
import logging
from typing import Literal, Optional
from dataclasses import dataclass, field

from core.origin import OriginRecord

logger = logging.getLogger(__name__)

CacheState = Literal["FRESH", "STALE", "REPAIRING"]


@dataclass
class CacheEntry:
    key: str
    version: int
    data: dict
    state: CacheState = "FRESH"
    updated_at: float = field(default_factory=time.monotonic)


class CacheNode:
    """
    Simulates one regional cache node.
    Tracks versioned entries and state transitions per key.
    """

    def __init__(self, node_id: str, region: str = "unknown"):
        self.node_id = node_id
        self.region = region
        self._store: dict[str, CacheEntry] = {}

    # ── Write operations ─────────────────────────────────────────────────────

    def seed(self, key: str, record: OriginRecord):
        """Populate from origin at startup — always FRESH."""
        self._store[key] = CacheEntry(
            key=key, version=record.version, data=dict(record.data), state="FRESH"
        )

    def invalidate(self, key: str, new_version: int):
        """
        Called by the InvalidationBus (may arrive late or be dropped entirely).
        Only marks STALE if our version is behind the announced new version.
        """
        entry = self._store.get(key)
        if entry is None:
            # We never had this key — create a placeholder so we know to fetch it
            self._store[key] = CacheEntry(key=key, version=0, data={}, state="STALE")
            logger.info(f"{self.node_id}: STALE (new key) key={key} announced_v={new_version}")
        elif entry.version < new_version:
            entry.state = "STALE"
            logger.info(f"{self.node_id}: STALE key={key} local_v={entry.version} announced_v={new_version}")

    def start_repair(self, key: str):
        entry = self._store.get(key)
        if entry:
            entry.state = "REPAIRING"

    def apply_repair(self, key: str, record: OriginRecord):
        """Apply a fetched record from origin → FRESH."""
        self._store[key] = CacheEntry(
            key=key, version=record.version, data=dict(record.data), state="FRESH"
        )
        logger.info(f"{self.node_id}: REPAIRED key={key} → v{record.version}")

    # ── Read operations ───────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[CacheEntry]:
        return self._store.get(key)

    def stale_keys(self) -> list[str]:
        return [k for k, e in self._store.items() if e.state == "STALE"]

    def version_vector(self) -> dict[str, int]:
        """Only FRESH entries count as authoritative."""
        return {k: e.version for k, e in self._store.items() if e.state == "FRESH"}

    def snapshot(self) -> dict:
        return {
            "node_id": self.node_id,
            "region": self.region,
            "entries": {
                k: {"version": e.version, "state": e.state}
                for k, e in self._store.items()
            },
        }

    def __repr__(self):
        fresh = sum(1 for e in self._store.values() if e.state == "FRESH")
        stale = sum(1 for e in self._store.values() if e.state == "STALE")
        return f"CacheNode({self.node_id}, fresh={fresh}, stale={stale})"
