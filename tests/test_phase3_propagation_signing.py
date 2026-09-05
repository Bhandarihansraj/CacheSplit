"""
Phase 3 — Authentic commit signing + wired propagation.
Tests that commit chains are only reproducible by key-holders (forgery =
failed verification), and that the debounce/stampede machinery now runs in a
real fetch workflow over the live API.
"""
import json
import pytest
import pytest_asyncio
import httpx
from fastapi import FastAPI

from core.commit import Commit
from core.compound_commit import CompoundCommit, EntityMutation
from core.hash_chain import generate_signed_hash, verify_signed_hash, verify_signed_chain
from services.propagation import PropagationService

KEY_A = "origin-key-A"
KEY_B = "origin-key-B"


# ─────────────────────────── COMMIT SIGNING ────────────────────────────────

def test_commit_sign_and_verify():
    c = Commit(parent_hash=None, version_number=1,
               json_manifest='{"status": "active"}', affected_entity_id="e1")
    c.sign(KEY_A)
    assert c.commit_hash
    assert c.verify_signature(KEY_A) is True


def test_commit_tampering_breaks_signature():
    c = Commit(parent_hash=None, version_number=1,
               json_manifest='{"status": "active"}', affected_entity_id="e1")
    c.sign(KEY_A)
    c.json_manifest = '{"status": "deleted"}'
    assert c.verify_signature(KEY_A) is False


def test_wrong_key_rejected():
    c = Commit(parent_hash=None, version_number=1,
               json_manifest='{"status": "active"}', affected_entity_id="e1")
    c.sign(KEY_A)
    assert c.verify_signature(KEY_B) is False


def test_compound_commit_signed_hash_roundtrip():
    cc = CompoundCommit(
        transaction_id="tx-signed-1",
        mutations=[EntityMutation(entity_type="patient", entity_id="p1", data={"name": "X"})],
    )
    h = cc.compute_commit_hash(secret=KEY_A)
    payload = json.loads(cc.signed_payload())
    assert verify_signed_hash(payload, h, KEY_A) is True
    assert verify_signed_hash(payload, h, KEY_B) is False


# ─────────────────────── SIGNED CHAIN VERIFICATION ─────────────────────────

def _chain_rows(n: int, secret: str):
    rows = []
    for i in range(n):
        cc = CompoundCommit(
            transaction_id=f"tx-chain-{i}",
            timestamp=float(i),
            mutations=[EntityMutation(entity_type="visit", entity_id=f"v{i}", data={"room": f"{i}"})],
        )
        h = cc.compute_commit_hash(secret=secret)
        rows.append({"transaction_id": cc.transaction_id, "commit_hash": h,
                     "hashable_json": cc.signed_payload()})
    return rows


def test_signed_chain_accepts_valid():
    rows = _chain_rows(3, KEY_A)
    assert verify_signed_chain(rows, KEY_A) is True


def test_signed_chain_rejects_wrong_key():
    rows = _chain_rows(3, KEY_A)
    assert verify_signed_chain(rows, KEY_B) is False


def test_signed_chain_rejects_forged_payload():
    rows = _chain_rows(2, KEY_A)
    forged = json.loads(rows[1]["hashable_json"])
    forged["mutations"][0]["data"] = {"room": "RANSOMED"}
    rows[1]["hashable_json"] = json.dumps(forged)  # hash left untouched
    assert verify_signed_chain(rows, KEY_A) is False


def test_signed_chain_rejects_unverifiable_rows():
    rows = _chain_rows(2, KEY_A)
    rows.append({"transaction_id": "tx-legacy", "commit_hash": "oldhash", "hashable_json": ""})
    assert verify_signed_chain(rows, KEY_A) is False


# ─────────────────────────── PROPAGATION SERVICE ───────────────────────────

@pytest.mark.asyncio
async def test_coalescing_50_triggers_to_1_fetch():
    p = PropagationService(window_ms=30, fetch_budget_per_second=100)
    async def fetch_fn(hint):
        return []

    for i in range(50):
        p.on_invalidation("node-coalesce", f"hash-{i}")

    res = await p.run_fetch_workflow("node-coalesce", fetch_fn)

    assert res["status"] == "fetched"
    assert res["invalidations"] == 50
    assert res["fetches"] == 1
    metrics = p.metrics("node-coalesce")
    assert metrics["coalescing_ratio"] == 0.02


@pytest.mark.asyncio
async def test_stampede_budget_gates_fetches():
    p = PropagationService(window_ms=20, fetch_budget_per_second=2)
    async def fetch_fn(hint):
        return []

    p.on_invalidation("node-budget", "v1")
    r1 = await p.run_fetch_workflow("node-budget", fetch_fn)
    r2 = await p.run_fetch_workflow("node-budget", fetch_fn)
    assert r1["status"] == "fetched"
    assert r2["status"] == "fetched"

    for _ in range(10):
        denied = await p.run_fetch_workflow("node-budget", fetch_fn)
        assert denied["status"] == "budget_exhausted"

    assert p.metrics("node-budget")["fetches"] == 2
    assert p.metrics("node-budget")["budget_denials"] == 10


# ─────────────────────── END-TO-END OVER REAL HTTP ─────────────────────────

@pytest_asyncio.fixture
async def e2e_client(tmp_path):
    from db import init_db, close_db
    from api.dashboard import router as dashboard_router
    from api.propagation import router as propagation_router

    await init_db(str(tmp_path / "test_prop.db"))
    app = FastAPI()
    app.include_router(dashboard_router)
    app.include_router(propagation_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await close_db()


@pytest.mark.asyncio
async def test_propagation_end_to_end(e2e_client):
    # 1. Origin signs + persists a real compound commit
    r = await e2e_client.post("/api/dashboard/compound-commit", json={
        "transaction_id": "tx-e2e-001",
        "mutations": [{"entity_id": "pat_e2e_001", "entity_type": "patient",
                       "data": {"name": "E2E", "status": "admitted"}}],
        "edges": [],
    })
    assert r.status_code == 200
    assert r.json()["result"]["commit_hash"]

    # 2. An invalidation hint arrives for a cache node
    r = await e2e_client.post("/api/propagation/invalidate", json={
        "node_id": "cache-eu-1", "version_hint": "tx-e2e-001",
    })
    assert r.status_code == 200
    assert r.json()["invalidations_total"] == 1

    # 3. The node performs its (debounced) fetch; the fetched chain must verify
    r = await e2e_client.post("/api/propagation/fetch", json={
        "node_id": "cache-eu-1", "limit": 20,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "fetched"
    assert body["commits_fetched"] == 1
    assert body["chain_verified"] is True

    # 4. Metrics confirm 1 trigger → 1 coalesced fetch
    r = await e2e_client.get("/api/propagation/metrics?node_id=cache-eu-1")
    assert r.json()["metrics"]["invalidations"] == 1
    assert r.json()["metrics"]["fetches"] == 1
    assert r.json()["metrics"]["chains_verified"] == 1