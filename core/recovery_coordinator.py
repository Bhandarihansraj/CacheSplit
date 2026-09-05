"""
core/recovery_coordinator.py
Gossip-based staleness detection + deduplicated repair queue.
This is the heart of CacheSplit v4's stampede recovery.

Design:
- gossip_round()  → finds which nodes are behind origin
- drain_repair_queue() → fetches each unique stale key ONCE from origin,
                         fans the result out to all waiting nodes
- Deduplication saves origin capacity when many nodes miss the same key
"""
import asyncio
import logging
import time
from collections import defaultdict
from typing import Optional, List, Dict

from core.origin import Origin, OriginOverload
from core.cache_node import CacheNode

try:
    from commitcache.core.lease import LeaseManager
    from commitcache.core.audit_log import AuditLog
except ImportError:
    class LeaseManager:
        def __init__(self, *args, **kwargs): pass
        async def acquire_lease(self, *args, **kwargs):
            class _L:
                def is_valid(self): return True
                @property
                def remaining_ms(self): return 5000.0
            return _L()
        async def release_lease(self, *args, **kwargs): pass

    class AuditLog:
        def __init__(self, *args, **kwargs): pass
        def log(self, *args, **kwargs): pass
        def get_recent(self, *args, **kwargs): return []


logger = logging.getLogger(__name__)


class RecoveryCoordinator:
    """
    Coordinates cache repair without causing a stampede:

    1. gossip_round() samples every node's version_vector and compares
       with origin.current_versions(). Any gap is queued.
    2. drain_repair_queue() groups queued (node, key) pairs by key.
       For each unique key it issues exactly ONE origin.get() regardless
       of how many nodes need it. The result is then applied to all of them.
    """

    def __init__(
        self,
        nodes: List[CacheNode],
        origin: Origin,
        state_manager=None,
        lease_manager: LeaseManager = None,
        audit_log: AuditLog = None,
    ):
        self.nodes = nodes
        self.origin = origin
        self.state_manager = state_manager
        self.lease_manager = lease_manager
        self.audit_log = audit_log

        # Queue: key -> list of CacheNode objects waiting for that key
        self._repair_queue: Dict[str, List[CacheNode]] = defaultdict(list)
        self._event_log: List[dict] = []
        self.origin_hits = 0
        self.origin_rejects = 0
        self.dedup_savings = 0
        self.cycles = 0

    # ── Gossip ───────────────────────────────────────────────────────────────

    def gossip_round(self) -> dict:
        """
        Compare each node's version_vector against the origin.
        Queue repairs for any key where local_version < origin_version.
        Returns a summary of what was queued.
        """
        origin_versions = self.origin.current_versions()
        queued = 0

        for node in self.nodes:
            local_vv = node.version_vector()
            for key, origin_v in origin_versions.items():
                local_v = local_vv.get(key, 0)
                if local_v < origin_v:
                    # Only queue if not already queued for this node+key
                    existing = self._repair_queue.get(key, [])
                    if node not in existing:
                        self._repair_queue[key].append(node)
                        node.start_repair(key)
                        queued += 1
                        evt = {
                            "type": "QUEUED_REPAIR",
                            "node": node.node_id,
                            "key": key,
                            "local_v": local_v,
                            "origin_v": origin_v,
                        }
                        self._event_log.append(evt)
                        logger.debug(f"Gossip: queued repair {node.node_id} key={key} {local_v}->{origin_v}")

        return {"queued": queued, "unique_keys": len(self._repair_queue)}

    # ── Repair ───────────────────────────────────────────────────────────────

    async def drain_repair_queue(self) -> dict:
        """
        Process the repair queue. For each unique key, fetch from origin ONCE
        and fan out to all waiting nodes (deduplication).
        """
        if not self._repair_queue:
            return {"origin_hits": 0, "origin_rejects": 0, "dedup_savings": 0, "repaired_nodes": 0}

        hits, rejects, savings, repaired = 0, 0, 0, 0
        # Snapshot and clear queue atomically
        queue_snapshot = dict(self._repair_queue)
        self._repair_queue.clear()

        for key, waiting_nodes in queue_snapshot.items():
            dedup_count = len(waiting_nodes) - 1  # savings = extra nodes that share 1 fetch
            try:
                record = self.origin.get(key)
                hits += 1
                savings += dedup_count
                if record:
                    for node in waiting_nodes:
                        node.apply_repair(key, record)
                        repaired += 1
                        self._event_log.append({
                            "type": "REPAIRED",
                            "node": node.node_id,
                            "key": key,
                            "version": record.version,
                        })
            except OriginOverload:
                rejects += 1
                # Re-queue for next cycle
                for node in waiting_nodes:
                    self._repair_queue[key].append(node)
                self._event_log.append({"type": "ORIGIN_OVERLOAD", "key": key})
                logger.warning(f"Origin overloaded for key={key}, re-queued {len(waiting_nodes)} nodes")

        self.origin_hits += hits
        self.origin_rejects += rejects
        self.dedup_savings += savings

        # Broadcast to UI via WebSocket
        if self.state_manager and (hits or rejects):
            try:
                await self.state_manager.broadcast({
                    "type": "RECOVERY_CYCLE",
                    "origin_hits": hits,
                    "origin_rejects": rejects,
                    "dedup_savings": savings,
                    "repaired_nodes": repaired,
                })
            except Exception:
                pass

        return {
            "origin_hits": hits,
            "origin_rejects": rejects,
            "dedup_savings": savings,
            "repaired_nodes": repaired,
        }

    # ── Cycle & Convergence ──────────────────────────────────────────────────

    async def run_cycle(self) -> dict:
        """One gossip + repair cycle."""
        self.cycles += 1
        gossip = self.gossip_round()
        repair = await self.drain_repair_queue()
        converged = self.is_converged()
        if converged:
            self._event_log.append({"type": "CONVERGED", "cycle": self.cycles})
            logger.info(f"Cluster CONVERGED after {self.cycles} cycles")
        return {**gossip, **repair, "converged": converged, "cycle": self.cycles}

    def is_converged(self) -> bool:
        """True when every node's FRESH versions match the origin."""
        origin_v = self.origin.current_versions()
        for node in self.nodes:
            local_vv = node.version_vector()
            for key, ov in origin_v.items():
                if local_vv.get(key, 0) < ov:
                    return False
        return True

    @property
    def event_log(self) -> List[dict]:
        return list(self._event_log)

    def snapshot(self) -> dict:
        return {
            "nodes": [n.snapshot() for n in self.nodes],
            "origin_versions": self.origin.current_versions(),
            "bucket_level": self.origin.bucket_level,
            "repair_queue_depth": sum(len(v) for v in self._repair_queue.values()),
            "converged": self.is_converged(),
            "origin_hits": self.origin_hits,
            "origin_rejects": self.origin_rejects,
            "dedup_savings": self.dedup_savings,
            "cycles": self.cycles,
            "event_log": self._event_log[-20:],
        }
