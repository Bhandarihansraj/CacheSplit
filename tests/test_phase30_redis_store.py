"""
tests/test_phase30_redis_store.py
Comprehensive test suite for Phase 30: Redis Data Types & In-Memory Storage Engine.
Verifies Strings, Hashes, Lists, Sets, ZSets, WRONGTYPE enforcement, and FastAPI endpoints.
"""
import pytest
from fastapi.testclient import TestClient

from core.redis_store import RedisStore, RedisType, WrongTypeError, RedisError
from api.server import app


@pytest.fixture
def store():
    """Returns a fresh RedisStore instance for each test."""
    return RedisStore()


@pytest.fixture
def client():
    """Returns FastAPI TestClient."""
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 1. STRING OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────
def test_string_basic_set_get(store: RedisStore):
    assert store.set("k1", "hello") is True
    assert store.get("k1") == "hello"
    assert store.type("k1") == RedisType.STRING
    assert store.get("nonexistent") is None


def test_string_set_nx_xx(store: RedisStore):
    assert store.set("lock", "1", nx=True) is True
    assert store.set("lock", "2", nx=True) is False
    assert store.get("lock") == "1"

    assert store.set("newkey", "val", xx=True) is False
    assert store.set("lock", "updated", xx=True) is True
    assert store.get("lock") == "updated"


def test_string_incr_decr(store: RedisStore):
    assert store.set("counter", "10") is True
    assert store.incr("counter") == 11
    assert store.incr("counter", 5) == 16
    assert store.decr("counter") == 15
    assert store.decr("counter", 10) == 5
    # Auto-initialize non-existent key
    assert store.incr("views") == 1


def test_string_mset_mget(store: RedisStore):
    store.mset({"a": "alpha", "b": "beta", "c": "gamma"})
    res = store.mget("a", "b", "c", "missing")
    assert res == ["alpha", "beta", "gamma", None]


def test_string_append_and_strlen(store: RedisStore):
    store.set("greeting", "Hello")
    assert store.append("greeting", " World") == 11
    assert store.get("greeting") == "Hello World"
    assert store.strlen("greeting") == 11
    assert store.strlen("empty_key") == 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. HASH OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────
def test_hash_hset_hget_hgetall(store: RedisStore):
    assert store.hset("user:101", "name", "Hansraj") == 1
    assert store.hset("user:101", "role", "Lead") == 1
    assert store.hset("user:101", "name", "Hansraj B.") == 0  # Update returns 0

    assert store.hget("user:101", "name") == "Hansraj B."
    assert store.hget("user:101", "role") == "Lead"
    assert store.hget("user:101", "missing") is None

    all_fields = store.hgetall("user:101")
    assert all_fields == {"name": "Hansraj B.", "role": "Lead"}
    assert store.hlen("user:101") == 2


def test_hash_hmset_hkeys_hvals_hexists(store: RedisStore):
    store.hmset("profile:1", {"bio": "Dev", "city": "Delhi", "age": "28"})
    assert store.hexists("profile:1", "city") is True
    assert store.hexists("profile:1", "salary") is False
    assert set(store.hkeys("profile:1")) == {"bio", "city", "age"}
    assert set(store.hvals("profile:1")) == {"Dev", "Delhi", "28"}


def test_hash_hincrby_and_hdel(store: RedisStore):
    store.hset("stats:page", "views", 100)
    assert store.hincrby("stats:page", "views", 25) == 125
    assert store.hdel("stats:page", "views", "nonexistent") == 1
    assert store.hget("stats:page", "views") is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. LIST OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────
def test_list_lpush_rpush_lrange(store: RedisStore):
    assert store.rpush("queue", "task1", "task2") == 2
    assert store.lpush("queue", "task0") == 3
    assert store.lrange("queue", 0, -1) == ["task0", "task1", "task2"]
    assert store.lrange("queue", 1, 2) == ["task1", "task2"]
    assert store.llen("queue") == 3
    assert store.lindex("queue", 0) == "task0"
    assert store.lindex("queue", 2) == "task2"


def test_list_pop_operations(store: RedisStore):
    store.rpush("items", "a", "b", "c", "d")
    assert store.lpop("items") == "a"
    assert store.rpop("items") == "d"
    assert store.lrange("items", 0, -1) == ["b", "c"]
    assert store.lpop("items", count=2) == ["b", "c"]
    assert store.lpop("items") is None


def test_list_ltrim(store: RedisStore):
    store.rpush("log", "1", "2", "3", "4", "5")
    assert store.ltrim("log", 1, 3) is True
    assert store.lrange("log", 0, -1) == ["2", "3", "4"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. SET OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────
def test_set_sadd_smembers_srem(store: RedisStore):
    assert store.sadd("tags", "python", "fastapi", "redis") == 3
    assert store.sadd("tags", "python") == 0  # Duplicate
    assert store.scard("tags") == 3
    assert store.sismember("tags", "fastapi") is True
    assert store.sismember("tags", "rust") is False
    assert store.smembers("tags") == {"python", "fastapi", "redis"}

    assert store.srem("tags", "fastapi", "rust") == 1
    assert store.scard("tags") == 2


def test_set_algebra_sinter_sunion_sdiff(store: RedisStore):
    store.sadd("setA", "1", "2", "3")
    store.sadd("setB", "2", "3", "4")
    store.sadd("setC", "3", "4", "5")

    assert store.sinter("setA", "setB") == {"2", "3"}
    assert store.sinter("setA", "setB", "setC") == {"3"}
    assert store.sunion("setA", "setB") == {"1", "2", "3", "4"}
    assert store.sdiff("setA", "setB") == {"1"}


# ─────────────────────────────────────────────────────────────────────────────
# 5. SORTED SET (ZSET) OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────
def test_zset_zadd_zrange_zscore(store: RedisStore):
    assert store.zadd("leaderboard", {"alice": 100.0, "bob": 250.0, "charlie": 180.0}) == 3
    assert store.zcard("leaderboard") == 3
    assert store.zscore("leaderboard", "bob") == 250.0

    # Score ASC
    assert store.zrange("leaderboard", 0, -1) == ["alice", "charlie", "bob"]
    # Score DESC
    assert store.zrevrange("leaderboard", 0, -1) == ["bob", "charlie", "alice"]

    # Withscores
    with_scores = store.zrange("leaderboard", 0, 1, withscores=True)
    assert with_scores == [("alice", 100.0), ("charlie", 180.0)]


def test_zset_rank_and_score_filtering(store: RedisStore):
    store.zadd("scores", {"p1": 10.0, "p2": 20.0, "p3": 30.0, "p4": 40.0})
    assert store.zrank("scores", "p1") == 0
    assert store.zrank("scores", "p4") == 3
    assert store.zrevrank("scores", "p4") == 0

    assert store.zrangebyscore("scores", 15.0, 35.0) == ["p2", "p3"]
    assert store.zcount("scores", 15.0, 35.0) == 2

    assert store.zrem("scores", "p1", "p2") == 2
    assert store.zcard("scores") == 2


# ─────────────────────────────────────────────────────────────────────────────
# 6. WRONGTYPE ERROR ENFORCEMENT & KEY DELETION
# ─────────────────────────────────────────────────────────────────────────────
def test_wrongtype_enforcement(store: RedisStore):
    store.set("str_key", "simple_value")

    with pytest.raises(WrongTypeError):
        store.hset("str_key", "field", "val")

    with pytest.raises(WrongTypeError):
        store.lpush("str_key", "item")

    with pytest.raises(WrongTypeError):
        store.sadd("str_key", "item")

    with pytest.raises(WrongTypeError):
        store.zadd("str_key", {"item": 1.0})


def test_generic_keys_exists_del_flush(store: RedisStore):
    store.set("k1", "v1")
    store.hset("h1", "f", "v")
    store.rpush("l1", "item")

    assert store.exists("k1", "h1", "l1", "missing") == 3
    assert set(store.keys("*1")) == {"k1", "h1", "l1"}
    assert store.delete("k1", "h1") == 2
    assert store.dbsize() == 1

    assert store.flushdb() is True
    assert store.dbsize() == 0


def test_store_stats_and_metrics(store: RedisStore):
    store.set("s1", "v")
    store.hset("h1", "f", "v")
    store.get("s1")  # Hit
    store.get("nonexistent")  # Miss

    stats = store.stats()
    assert stats["total_keys"] == 2
    assert stats["type_breakdown"]["string"] == 1
    assert stats["type_breakdown"]["hash"] == 1
    assert stats["hits"] >= 1
    assert stats["misses"] >= 1
    assert stats["hit_rate_pct"] == 50.0


# ─────────────────────────────────────────────────────────────────────────────
# 7. FASTAPI REDIS ENDPOINTS INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────
def test_api_redis_command_flow(client: TestClient):
    # 1. SET
    res = client.post("/api/redis/command", json={"cmd": "SET", "args": ["api:msg", "Hello FastApi"]})
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # 2. GET
    res = client.post("/api/redis/command", json={"cmd": "GET", "args": ["api:msg"]})
    assert res.status_code == 200
    assert res.json()["result"] == "Hello FastApi"

    # 3. HSET & HGETALL
    client.post("/api/redis/command", json={"cmd": "HSET", "args": ["api:user:1", "name", "Hansraj", "role", "Architect"]})
    res = client.post("/api/redis/command", json={"cmd": "HGETALL", "args": ["api:user:1"]})
    assert res.status_code == 200
    assert res.json()["result"] == {"name": "Hansraj", "role": "Architect"}

    # 4. ZADD & ZRANGE
    client.post("/api/redis/command", json={"cmd": "ZADD", "args": ["api:ranks", 100, "dev1", 200, "dev2"]})
    res = client.post("/api/redis/command", json={"cmd": "ZRANGE", "args": ["api:ranks", 0, -1, "WITHSCORES"]})
    assert res.status_code == 200
    assert len(res.json()["result"]) == 2

    # 5. WRONGTYPE Error response
    res = client.post("/api/redis/command", json={"cmd": "LPUSH", "args": ["api:msg", "fail"]})
    assert res.status_code == 200
    assert res.json()["ok"] is False
    assert res.json()["error_type"] == "WRONGTYPE"

    # 6. Key listing & Inspect
    res = client.get("/api/redis/keys?pattern=api:*")
    assert res.status_code == 200
    assert res.json()["count"] >= 3

    res = client.get("/api/redis/get/api:user:1")
    assert res.status_code == 200
    assert res.json()["type"] == "hash"
    assert res.json()["value"]["name"] == "Hansraj"

    # 7. Stats
    res = client.get("/api/redis/stats")
    assert res.status_code == 200
    assert res.json()["total_keys"] >= 3
