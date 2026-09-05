"""
tests/test_phase32_pubsub_redlock.py
Comprehensive test suite for Phase 32: Pub/Sub Messaging Engine & Distributed Redlock Locks.
"""
import time
import pytest
from fastapi.testclient import TestClient

from core.redis_pubsub import PubSubManager
from core.redlock import RedlockManager
from api.server import app


@pytest.fixture
def pubsub():
    """Returns fresh PubSubManager instance."""
    return PubSubManager()


@pytest.fixture
def redlock():
    """Returns fresh RedlockManager instance."""
    return RedlockManager()


@pytest.fixture
def client():
    """Returns FastAPI TestClient."""
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 1. PUB/SUB CHANNEL & PATTERN MESSAGING
# ─────────────────────────────────────────────────────────────────────────────
def test_pubsub_exact_channel_delivery(pubsub: PubSubManager):
    # Subscribe sub1 and sub2 to 'news'
    pubsub.subscribe("sub1", "news")
    pubsub.subscribe("sub2", "news")

    # Publish message to 'news'
    receivers = pubsub.publish("news", "Breaking: CacheSplit Phase 32 live")
    assert receivers == 2

    # Poll messages for sub1
    msgs1 = pubsub.poll("sub1")
    assert len(msgs1) == 1
    assert msgs1[0]["channel"] == "news"
    assert msgs1[0]["data"] == "Breaking: CacheSplit Phase 32 live"

    # Poll messages for sub2
    msgs2 = pubsub.poll("sub2")
    assert len(msgs2) == 1
    assert msgs2[0]["data"] == "Breaking: CacheSplit Phase 32 live"

    # Queue should now be empty
    assert len(pubsub.poll("sub1")) == 0


def test_pubsub_pattern_matching(pubsub: PubSubManager):
    # Subscribe to patterns
    pubsub.psubscribe("logger_all", "events.*")
    pubsub.psubscribe("orders_watcher", "events.order.*")

    # Publish to events.order.created -> matches both
    count = pubsub.publish("events.order.created", "Order #1001 created")
    assert count == 2

    msgs_logger = pubsub.poll("logger_all")
    assert len(msgs_logger) == 1
    assert msgs_logger[0]["type"] == "pmessage"
    assert msgs_logger[0]["pattern"] == "events.*"

    msgs_orders = pubsub.poll("orders_watcher")
    assert len(msgs_orders) == 1
    assert msgs_orders[0]["pattern"] == "events.order.*"

    # Publish to events.user.login -> matches only logger_all
    count2 = pubsub.publish("events.user.login", "User login")
    assert count2 == 1
    assert len(pubsub.poll("orders_watcher")) == 0


def test_pubsub_unsubscribe_and_punsubscribe(pubsub: PubSubManager):
    pubsub.subscribe("clientA", "ch1", "ch2")
    pubsub.psubscribe("clientA", "pat.*")

    assert pubsub.publish("ch1", "msg1") == 1
    pubsub.poll("clientA")  # drain

    # Unsubscribe from ch1
    pubsub.unsubscribe("clientA", "ch1")
    assert pubsub.publish("ch1", "msg2") == 0  # No delivery

    # ch2 and pat.* still active
    assert pubsub.publish("ch2", "msg3") == 1
    assert pubsub.publish("pat.test", "msg4") == 1
    assert len(pubsub.poll("clientA")) == 2

    # Punsubscribe
    pubsub.punsubscribe("clientA", "pat.*")
    assert pubsub.publish("pat.test", "msg5") == 0


def test_pubsub_discovery_and_stats(pubsub: PubSubManager):
    pubsub.subscribe("s1", "alpha", "beta")
    pubsub.subscribe("s2", "alpha")
    pubsub.psubscribe("s3", "test.*")

    assert set(pubsub.list_channels()) == {"alpha", "beta"}
    assert pubsub.numsub("alpha", "beta") == {"alpha": 2, "beta": 1}
    assert pubsub.numpat() == 1

    stats = pubsub.stats()
    assert stats["active_channels"] == 2
    assert stats["active_patterns"] == 1
    assert stats["active_subscribers"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# 2. DISTRIBUTED REDLOCK MUTEX LOCKS
# ─────────────────────────────────────────────────────────────────────────────
def test_redlock_mutual_exclusion(redlock: RedlockManager):
    # Client 1 acquires lock
    token1 = redlock.acquire("order:999", ttl_ms=10000, owner_token="client-1")
    assert token1 == "client-1"
    assert redlock.is_locked("order:999") is True

    # Client 2 attempts to acquire same resource -> must fail (return None)
    token2 = redlock.acquire("order:999", ttl_ms=10000, owner_token="client-2")
    assert token2 is None

    # Client 1 releases lock
    assert redlock.release("order:999", "client-1") is True
    assert redlock.is_locked("order:999") is False

    # Now Client 2 can acquire
    token2_retry = redlock.acquire("order:999", ttl_ms=10000, owner_token="client-2")
    assert token2_retry == "client-2"


def test_redlock_owner_token_safety(redlock: RedlockManager):
    # Client 1 acquires lock
    redlock.acquire("inventory:item:42", ttl_ms=10000, owner_token="owner-alice")

    # Client 2 attempts to release Alice's lock with wrong token -> must be rejected
    assert redlock.release("inventory:item:42", "attacker-bob") is False
    assert redlock.is_locked("inventory:item:42") is True

    # Alice releases with correct token -> succeeds
    assert redlock.release("inventory:item:42", "owner-alice") is True
    assert redlock.is_locked("inventory:item:42") is False


def test_redlock_auto_lease_expiration(redlock: RedlockManager):
    # Short TTL lease: 50ms
    redlock.acquire("resource:temp", ttl_ms=50, owner_token="client-temp")
    assert redlock.is_locked("resource:temp") is True

    # Wait for lease to expire
    time.sleep(0.08)

    # Lock must be automatically reclaimed
    assert redlock.is_locked("resource:temp") is False

    # Another client can acquire immediately
    token_new = redlock.acquire("resource:temp", ttl_ms=5000, owner_token="client-next")
    assert token_new == "client-next"


def test_redlock_renew(redlock: RedlockManager):
    redlock.acquire("job:crawler", ttl_ms=100, owner_token="worker-1")

    # Wrong token cannot renew
    assert redlock.renew("job:crawler", "wrong-worker", extension_ms=5000) is False

    # Correct token renews lease
    assert redlock.renew("job:crawler", "worker-1", extension_ms=5000) is True
    info = redlock.get_lock_info("job:crawler")
    assert info is not None
    assert info["remaining_ttl_ms"] > 3000


# ─────────────────────────────────────────────────────────────────────────────
# 3. FASTAPI REST & COMMAND ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────
def test_api_pubsub_endpoints(client: TestClient):
    # 1. Subscribe
    res = client.post("/api/redis/subscribe", json={"subscriber_id": "api-sub-1", "channels": ["alerts"]})
    assert res.status_code == 200

    # 2. Publish
    res = client.post("/api/redis/publish", json={"channel": "alerts", "message": "High Latency Warning"})
    assert res.status_code == 200
    assert res.json()["receivers"] >= 1

    # 3. Poll messages
    res = client.get("/api/redis/messages/api-sub-1")
    assert res.status_code == 200
    assert res.json()["count"] >= 1
    assert res.json()["messages"][0]["data"] == "High Latency Warning"


def test_api_redlock_endpoints(client: TestClient):
    # 1. Acquire Lock
    res = client.post("/api/redis/lock/acquire", json={"resource": "db:migration", "ttl_ms": 10000, "owner_token": "dev-token-1"})
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert res.json()["owner_token"] == "dev-token-1"

    # 2. Conflicting Acquire fails
    res = client.post("/api/redis/lock/acquire", json={"resource": "db:migration", "ttl_ms": 10000, "owner_token": "dev-token-2"})
    assert res.status_code == 200
    assert res.json()["ok"] is False

    # 3. Lock info
    res = client.get("/api/redis/lock/info/db:migration")
    assert res.status_code == 200
    assert res.json()["locked"] is True

    # 4. Release with wrong token fails
    res = client.post("/api/redis/lock/release", json={"resource": "db:migration", "owner_token": "wrong-token"})
    assert res.status_code == 200
    assert res.json()["ok"] is False

    # 5. Release with correct token succeeds
    res = client.post("/api/redis/lock/release", json={"resource": "db:migration", "owner_token": "dev-token-1"})
    assert res.status_code == 200
    assert res.json()["ok"] is True

    # 6. Verify unlocked
    res = client.get("/api/redis/lock/info/db:migration")
    assert res.json()["locked"] is False
