"""
tests/test_phase31_ttl_eviction.py
Comprehensive test suite for Phase 31: TTL Key Expiration & LRU/LFU Memory Eviction Engine.
"""
import time
import pytest
from fastapi.testclient import TestClient

from core.redis_store import (
    EvictionPolicy,
    OOMError,
    RedisStore,
    RedisType,
    redis_store,
)
from api.server import app


@pytest.fixture
def store():
    """Returns a fresh RedisStore instance."""
    return RedisStore()


@pytest.fixture
def client():
    """Returns FastAPI TestClient."""
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 1. TTL & KEY EXPIRATION BASICS
# ─────────────────────────────────────────────────────────────────────────────
def test_ttl_expire_and_pttl(store: RedisStore):
    store.set("temp_key", "value")
    assert store.ttl("temp_key") == -1  # No TTL set
    assert store.pttl("temp_key") == -1

    # Expire in 10 seconds
    assert store.expire("temp_key", 10) is True
    ttl_sec = store.ttl("temp_key")
    assert 1 <= ttl_sec <= 10
    assert store.pttl("temp_key") > 0

    # Non-existent key returns -2
    assert store.ttl("missing_key") == -2
    assert store.expire("missing_key", 10) is False


def test_set_with_ex_and_px(store: RedisStore):
    # SET key val EX 5
    store.set("ex_key", "hello", ex=5)
    assert 1 <= store.ttl("ex_key") <= 5

    # SET key val PX 2000 (2 seconds)
    store.set("px_key", "world", px=2000)
    assert 1 <= store.ttl("px_key") <= 2


def test_persist_removes_ttl(store: RedisStore):
    store.set("persist_key", "important", ex=60)
    assert store.ttl("persist_key") > 0
    assert store.persist("persist_key") is True
    assert store.ttl("persist_key") == -1
    assert store.get("persist_key") == "important"

    # Persisting a persistent key returns False
    assert store.persist("persist_key") is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. PASSIVE ON-ACCESS EXPIRATION
# ─────────────────────────────────────────────────────────────────────────────
def test_passive_expiration_on_strings(store: RedisStore):
    # Set short TTL (0.05 seconds = 50ms)
    store.set("short_str", "transient", ex=0.05)
    assert store.get("short_str") == "transient"

    time.sleep(0.08)

    # After 80ms, key must be passively evicted on GET
    assert store.get("short_str") is None
    assert store.exists("short_str") == 0
    assert store.ttl("short_str") == -2
    assert store.type("short_str") == RedisType.NONE


def test_passive_expiration_on_hashes(store: RedisStore):
    store.hset("short_hash", "f1", "v1")
    store.expire("short_hash", 0.05)
    assert store.hget("short_hash", "f1") == "v1"

    time.sleep(0.08)

    assert store.hget("short_hash", "f1") is None
    assert store.hgetall("short_hash") == {}
    assert store.hlen("short_hash") == 0


def test_passive_expiration_on_lists_and_sets(store: RedisStore):
    store.rpush("short_list", "item1", "item2")
    store.sadd("short_set", "m1", "m2")
    store.expire("short_list", 0.05)
    store.expire("short_set", 0.05)

    time.sleep(0.08)

    assert store.lrange("short_list", 0, -1) == []
    assert store.smembers("short_set") == set()
    assert store.sismember("short_set", "m1") is False


def test_passive_expiration_on_zsets(store: RedisStore):
    store.zadd("short_zset", {"alice": 100.0})
    store.expire("short_zset", 0.05)

    time.sleep(0.08)

    assert store.zrange("short_zset", 0, -1) == []
    assert store.zscore("short_zset", "alice") is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. ACTIVE BACKGROUND EXPIRATION SWEEP
# ─────────────────────────────────────────────────────────────────────────────
def test_active_expiration_sweep(store: RedisStore):
    for i in range(10):
        store.set(f"exp:{i}", f"val_{i}", ex=0.05)
    for i in range(5):
        store.set(f"perm:{i}", f"val_{i}")

    assert store.dbsize() == 15

    time.sleep(0.08)

    # Run active expire cycle
    purged = store.active_expire_cycle(sample_size=20)
    assert purged == 10
    assert store.dbsize() == 5
    assert len(store.keys()) == 5


# ─────────────────────────────────────────────────────────────────────────────
# 4. MEMORY EVICTION POLICIES
# ─────────────────────────────────────────────────────────────────────────────
def test_eviction_noeviction_raises_oom():
    bounded_store = RedisStore(max_keys=3, eviction_policy=EvictionPolicy.NOEVICTION)
    bounded_store.set("k1", "v1")
    bounded_store.set("k2", "v2")
    bounded_store.set("k3", "v3")

    with pytest.raises(OOMError):
        bounded_store.set("k4", "v4")


def test_eviction_allkeys_lru():
    bounded_store = RedisStore(max_keys=3, eviction_policy=EvictionPolicy.ALLKEYS_LRU)
    bounded_store.set("k1", "v1")
    time.sleep(0.01)
    bounded_store.set("k2", "v2")
    time.sleep(0.01)
    bounded_store.set("k3", "v3")

    # Access k1 to make it recently used (k2 becomes oldest accessed)
    time.sleep(0.01)
    bounded_store.get("k1")

    # Adding k4 should evict k2
    bounded_store.set("k4", "v4")

    assert bounded_store.exists("k2") == 0
    assert bounded_store.exists("k1") == 1
    assert bounded_store.exists("k3") == 1
    assert bounded_store.exists("k4") == 1


def test_eviction_allkeys_lfu():
    bounded_store = RedisStore(max_keys=3, eviction_policy=EvictionPolicy.ALLKEYS_LFU)
    bounded_store.set("k1", "v1")
    bounded_store.set("k2", "v2")
    bounded_store.set("k3", "v3")

    # Touch k1 multiple times, k3 multiple times
    bounded_store.get("k1")
    bounded_store.get("k1")
    bounded_store.get("k3")
    bounded_store.get("k3")

    # k2 has lowest access count -> k2 should be evicted on inserting k4
    bounded_store.set("k4", "v4")

    assert bounded_store.exists("k2") == 0
    assert bounded_store.exists("k1") == 1
    assert bounded_store.exists("k3") == 1
    assert bounded_store.exists("k4") == 1


def test_eviction_volatile_ttl():
    bounded_store = RedisStore(max_keys=3, eviction_policy=EvictionPolicy.VOLATILE_TTL)
    bounded_store.set("perm1", "v1")
    bounded_store.set("ttl_long", "v2", ex=300)  # 5 min
    bounded_store.set("ttl_short", "v3", ex=10)  # 10 sec

    # Inserting 4th key should evict 'ttl_short' (shortest TTL)
    bounded_store.set("k4", "v4")

    assert bounded_store.exists("ttl_short") == 0
    assert bounded_store.exists("perm1") == 1
    assert bounded_store.exists("ttl_long") == 1
    assert bounded_store.exists("k4") == 1


# ─────────────────────────────────────────────────────────────────────────────
# 5. FASTAPI TTL & EVICTION ENDPOINTS INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────
def test_api_ttl_and_expire_endpoints(client: TestClient):
    # 1. SET and EXPIRE
    client.post("/api/redis/command", json={"cmd": "SET", "args": ["api:session", "token_1234"]})
    res = client.post("/api/redis/expire", json={"key": "api:session", "seconds": 120})
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 2. Check TTL
    res = client.get("/api/redis/ttl/api:session")
    assert res.status_code == 200
    data = res.json()
    assert data["has_ttl"] is True
    assert 1 <= data["ttl_seconds"] <= 120

    # 3. PERSIST
    res = client.post("/api/redis/persist/api:session")
    assert res.status_code == 200
    assert res.json()["persisted"] is True

    res = client.get("/api/redis/ttl/api:session")
    assert res.json()["is_persistent"] is True


def test_api_eviction_config_endpoint(client: TestClient):
    res = client.post("/api/redis/config/eviction", json={"max_keys": 500, "policy": "allkeys-lru"})
    assert res.status_code == 200
    assert res.json()["max_keys"] == 500
    assert res.json()["eviction_policy"] == "allkeys-lru"

    stats_res = client.get("/api/redis/stats")
    assert stats_res.status_code == 200
    assert stats_res.json()["eviction_policy"] == "allkeys-lru"
    assert stats_res.json()["max_keys_limit"] == 500
