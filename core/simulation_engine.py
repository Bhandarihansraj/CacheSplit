"""
core/simulation_engine.py
Orchestrates the full PRD demo scenario end-to-end:
  1. Seed cluster
  2. Invalidate with dropped messages
  3. Overlap: second update before first recovery completes
  4. Recover within token budget
  5. Report convergence
"""
import asyncio
import time
import logging
from typing import Any

from core.origin import Origin
from core.cache_node import CacheNode
from core.invalidation_bus import InvalidationBus
from core.recovery_coordinator import RecoveryCoordinator

logger = logging.getLogger(__name__)


async def run_full_scenario(config: dict) -> dict[str, Any]:
    """
    Run the complete stampede recovery scenario.

    Config keys:
        node_count   (int, default 4)
        key_count    (int, default 5)
        drop_prob    (float, default 0.4)  — probability an invalidation is dropped
        max_rps      (float, default 6)    — origin token-bucket rate
        burst        (int, default 3)      — max burst tokens
        max_cycles   (int, default 10)     — give up after this many recovery cycles
    """
    node_count = config.get("node_count", 4)
    key_count  = config.get("key_count", 5)
    drop_prob  = config.get("drop_prob", 0.4)
    max_rps    = config.get("max_rps", 6.0)
    burst      = config.get("burst", 3)
    max_cycles = config.get("max_cycles", 10)

    event_log: list[dict] = []

    def log(evt_type: str, detail: str, **kw):
        evt = {"type": evt_type, "detail": detail, "ts": time.monotonic(), **kw}
        event_log.append(evt)
        logger.info(f"[{evt_type}] {detail}")

    # ── 1. Build cluster ─────────────────────────────────────────────────────
    origin = Origin(capacity_rps=max_rps, burst=burst)
    bus = InvalidationBus(delivery_prob=1.0 - drop_prob, max_delay_ms=50)
    nodes = [CacheNode(node_id=f"node-{i}", region=f"region-{i % 3}") for i in range(node_count)]
    coordinator = RecoveryCoordinator(nodes=nodes, origin=origin)
    for node in nodes:
        bus.subscribe(node)

    keys = [f"entity:{i}" for i in range(key_count)]

    # ── 2. Seed all nodes ───────────────────────────────────────────────────
    for key in keys:
        record = origin.seed(key, {"value": 100, "gen": 0})
        for node in nodes:
            node.seed(key, record)
    log("SEED", f"All {node_count} nodes seeded with {key_count} keys at v1")

    # ── 3. First origin update — some invalidations dropped ─────────────────
    updated_keys = keys[:2]
    for key in updated_keys:
        record = origin.update(key, {"value": 200, "gen": 1})
        result = await bus.broadcast(key, record.version)
        log(
            "INVALIDATION",
            f"key={key} v{record.version} → delivered={result['delivered']} dropped={result['dropped']}",
            key=key, version=record.version,
        )

    # Give delayed invalidations a moment to land
    await asyncio.sleep(0.1)

    # ── 4. Check for inconsistent reads before recovery ─────────────────────
    for node in nodes:
        stale = node.stale_keys()
        if stale:
            log("INCONSISTENT_READ", f"{node.node_id} has {len(stale)} stale keys: {stale}", node=node.node_id)

    # ── 5. Overlap: second update while recovery is still pending ───────────
    overlap_key = keys[0]
    record2 = origin.update(overlap_key, {"value": 300, "gen": 2})
    await bus.broadcast(overlap_key, record2.version)
    log("OVERLAP", f"Second update for key={overlap_key} v{record2.version} — recovery in flight")

    # ── 6. Recovery cycles ───────────────────────────────────────────────────
    for cycle in range(max_cycles):
        result = await coordinator.run_cycle()
        log(
            "RECOVERY_CYCLE",
            f"cycle={result['cycle']} hits={result['origin_hits']} "
            f"rejects={result['origin_rejects']} dedup_saved={result['dedup_savings']}",
        )
        if result["converged"]:
            log("CONVERGED", f"All nodes converged after {result['cycle']} cycle(s)")
            break
        await asyncio.sleep(0.05)  # allow any late invalidation deliveries

    # ── 7. Final bus drops ──────────────────────────────────────────────────
    for evt in bus.event_log:
        event_log.append(evt)

    return {
        "event_log": event_log,
        "origin_version": origin.current_versions(),
        "node_snapshots": {n.node_id: n.snapshot() for n in nodes},
        "converged": coordinator.is_converged(),
        "cycles_taken": coordinator.cycles,
        "origin_hits": coordinator.origin_hits,
        "origin_rejects": coordinator.origin_rejects,
        "dedup_savings": coordinator.dedup_savings,
    }
