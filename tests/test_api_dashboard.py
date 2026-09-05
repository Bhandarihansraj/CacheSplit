import sys
import os
import pytest
import pytest_asyncio
import httpx
from fastapi import FastAPI

# Add parent directory to path to allow imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db import init_db, close_db
from api.dashboard import router

app = FastAPI()
app.include_router(router)


@pytest_asyncio.fixture
async def client(tmp_path):
    """Fresh in-memory DB + ASGI client sharing one event loop."""
    db_path = tmp_path / "test_dashboard.db"
    await init_db(str(db_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await close_db()


@pytest.mark.asyncio
async def test_node_map_ok(client):
    """Node map returns a well-formed nodes list (empty on a fresh DB)."""
    r = await client.get("/api/dashboard/node-map")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data
    assert "status_label" in str(data).lower() or isinstance(data["nodes"], list)


@pytest.mark.asyncio
async def test_node_entities_empty(client):
    """Entity explorer returns an empty list on a fresh node."""
    r = await client.get("/api/dashboard/node/us-east-1/entities")
    assert r.status_code == 200
    data = r.json()
    assert data["node_id"] == "us-east-1"
    assert data["entities"] == []
    assert data["total_cached"] == 0


@pytest.mark.asyncio
async def test_compound_commit_persists(client):
    """A compound commit must return a hash and land in the commit log."""
    payload = {
        "transaction_id": "tx-test-001",
        "mutations": [
            {"entity_id": "pat_test_001", "entity_type": "patient",
             "data": {"name": "Test Patient", "status": "admitted"}}
        ],
        "edges": [],
    }
    r = await client.post("/api/dashboard/compound-commit", json=payload)
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["commit_hash"]
    assert result["mutations_applied"] == 1

    r2 = await client.get("/api/dashboard/commits/recent")
    commits = r2.json()["commits"]
    assert any(c["transaction_id"] == "tx-test-001" for c in commits)


@pytest.mark.asyncio
async def test_merkle_tree_after_commit(client):
    """Committed entity is queryable through its Merkle DAG tree."""
    payload = {
        "transaction_id": "tx-tree-001",
        "mutations": [
            {"entity_id": "pat_tree_001", "entity_type": "patient",
             "data": {"name": "Tree", "status": "admitted"}}
        ],
        "edges": [],
    }
    await client.post("/api/dashboard/compound-commit", json=payload)

    r = await client.get("/api/dashboard/entity/pat_tree_001/merkle-tree")
    assert r.status_code == 200
    tree = r.json()["merkle_tree"]
    assert tree["entity_id"] == "pat_tree_001"
    assert tree["merkle_root_hash"]


@pytest.mark.asyncio
async def test_rebac_denied_without_path(client):
    """With no care-team edges, any access is denied."""
    r = await client.post("/api/dashboard/rebac/test", json={
        "clinician_id": "doc_test",
        "target_entity_id": "pat_test_002",
    })
    assert r.status_code == 200
    assert r.json()["authorized"] is False


@pytest.mark.asyncio
async def test_security_feed_ok(client):
    """Security feed returns a well-formed alerts list."""
    r = await client.get("/api/dashboard/security-feed")
    assert r.status_code == 200
    assert "alerts" in r.json()


@pytest.mark.asyncio
async def test_graph_anomaly_unknown_entity(client):
    """Traversal against a nonexistent entity resolves to unknown_entity, not an error."""
    r = await client.post("/api/dashboard/security/test-anomaly", json={
        "requesting_node_id": "eu-west-1",
        "requester_region": "EU-West",
        "target_entity_id": "does_not_exist",
    })
    assert r.status_code == 200
    assert r.json()["verdict"] == "unknown_entity"
    assert r.json()["flagged"] is False