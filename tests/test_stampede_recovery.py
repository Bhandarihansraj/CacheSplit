"""
tests/test_stampede_recovery.py
CacheSplit v4 — Stampede Recovery test suite.
"""
import asyncio
import pytest

from core.stampede_limiter import TokenBucket
from core.origin import Origin, OriginOverload
from core.cache_node import CacheNode
from core.invalidation_bus import InvalidationBus
from core.recovery_coordinator import RecoveryCoordinator
from core.simulation_engine import run_full_scenario


# ── Token Bucket ─────────────────────────────────────────────────────────────

def test_token_bucket_allows_within_burst():
    bucket = TokenBucket(rate_rps=5, burst=3)
    results = [bucket.consume() for _ in range(3)]
    assert all(results), "Should allow up to burst count"


def test_token_bucket_blocks_over_burst():
    bucket = TokenBucket(rate_rps=5, burst=3)
    for _ in range(3):
        bucket.consume()
    assert bucket.consume() is False, "Should reject when empty"


def test_token_bucket_level():
    bucket = TokenBucket(rate_rps=10, burst=10)
    assert bucket.level == 1.0
    bucket.consume()
    assert bucket.level < 1.0


# ── Origin ───────────────────────────────────────────────────────────────────

def test_origin_update_increments_version():
    origin = Origin(capacity_rps=100)
    origin.seed("key1", {"v": 1})
    r1 = origin.update("key1", {"v": 2})
    r2 = origin.update("key1", {"v": 3})
    assert r1.version == 2
    assert r2.version == 3


def test_origin_overload_raised():
    origin = Origin(capacity_rps=100, burst=1)
    origin.seed("key1", {"v": 1})
    origin.get("key1")  # consumes the 1 burst token
    with pytest.raises(OriginOverload):
        origin.get("key1")


# ── InvalidationBus ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bus_drops_all_at_zero_prob():
    node = CacheNode("n0")
    node.seed("k", type("R", (), {"version": 1, "data": {}})())
    bus = InvalidationBus(delivery_prob=0.0)
    bus.subscribe(node)
    result = await bus.broadcast("k", 2)
    assert result["dropped"] == 1
    assert result["delivered"] == 0


@pytest.mark.asyncio
async def test_bus_delivers_all_at_full_prob():
    from core.origin import OriginRecord
    node = CacheNode("n0")
    node.seed("k", OriginRecord(key="k", version=1, data={}))
    bus = InvalidationBus(delivery_prob=1.0, max_delay_ms=0)
    bus.subscribe(node)
    result = await bus.broadcast("k", 2)
    assert result["delivered"] == 1
    assert result["dropped"] == 0


# ── CacheNode ─────────────────────────────────────────────────────────────────

def test_cache_node_invalidate_marks_stale():
    from core.origin import OriginRecord
    node = CacheNode("n0")
    node.seed("k", OriginRecord(key="k", version=1, data={"x": 1}))
    node.invalidate("k", new_version=2)
    assert node.get("k").state == "STALE"


def test_cache_node_fresh_not_stale_on_same_version():
    from core.origin import OriginRecord
    node = CacheNode("n0")
    node.seed("k", OriginRecord(key="k", version=3, data={}))
    node.invalidate("k", new_version=3)  # same version — should not mark stale
    assert node.get("k").state == "FRESH"


# ── RecoveryCoordinator ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_coordinator_skips_fresh_nodes():
    from core.origin import OriginRecord
    origin = Origin(capacity_rps=100)
    origin.seed("k", {"v": 1})
    node = CacheNode("n0")
    node.seed("k", OriginRecord(key="k", version=1, data={}))
    coord = RecoveryCoordinator(nodes=[node], origin=origin)
    result = coord.gossip_round()
    assert result["queued"] == 0, "Fresh node should not be queued"


@pytest.mark.asyncio
async def test_coordinator_dedup_saves_origin_hits():
    """3 stale nodes on same key → only 1 origin hit."""
    origin = Origin(capacity_rps=100, burst=10)
    origin.seed("k", {"v": 1})
    origin.update("k", {"v": 2})  # advance to v2

    nodes = [CacheNode(f"n{i}") for i in range(3)]
    from core.origin import OriginRecord
    for n in nodes:
        n.seed("k", OriginRecord(key="k", version=1, data={}))
        n.invalidate("k", 2)

    coord = RecoveryCoordinator(nodes=nodes, origin=origin)
    coord.gossip_round()
    result = await coord.drain_repair_queue()
    assert result["origin_hits"] == 1, "Should fetch key only once"
    assert result["dedup_savings"] == 2, "Should save 2 extra origin hits"
    assert result["repaired_nodes"] == 3


# ── End-to-End ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_scenario_converges():
    result = await run_full_scenario({
        "node_count": 3,
        "key_count": 3,
        "drop_prob": 0.5,
        "max_rps": 20,
        "burst": 10,
        "max_cycles": 15,
    })
    assert result["converged"] is True
    assert result["origin_hits"] > 0


@pytest.mark.asyncio
async def test_overlap_scenario_reaches_latest_version():
    """Nodes that miss two invalidations should still reach the final version."""
    result = await run_full_scenario({
        "node_count": 4,
        "key_count": 2,
        "drop_prob": 0.9,  # very lossy — forces gossip-based repair
        "max_rps": 50,
        "burst": 20,
        "max_cycles": 20,
    })
    # All nodes should have the latest version after recovery
    origin_v = result["origin_version"]
    for node_id, snap in result["node_snapshots"].items():
        for key, entry in snap["entries"].items():
            assert entry["version"] >= origin_v.get(key, 0), \
                f"{node_id} key={key} still behind after convergence"
