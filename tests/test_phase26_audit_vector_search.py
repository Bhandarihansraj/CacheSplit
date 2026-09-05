"""
tests/test_phase26_audit_vector_search.py
Automated test suite for Phase 26: Hybrid Vector + Metadata Audit Trail Search.
Tests dense feature-text embeddings, hybrid vector search with relational filters,
and FastAPI semantic-search endpoints.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from core.audit_embedder import AuditEmbedder
from core.audit_vector_index import AuditVectorIndex, global_audit_vector_index
from services.audit_trail_service import audit_trail_service
from services.audit_batcher import audit_batcher
from api.server import app
from db.database import init_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_db()
    yield


# ── 1. Embedder Tests ────────────────────────────────────────────────────────

def test_audit_embedder_normalization_and_concept_alignment():
    embedder = AuditEmbedder()

    # Poison / corruption concept
    vec_poison = embedder.embed_text("qa poison injection malformed corrupted data")
    vec_billing = embedder.embed_text("stripe billing invoice payment webhook")
    vec_telemetry = embedder.embed_text("cardiology patient telemetry sensor stream")

    # Vectors must be unit normalized (magnitude == 1.0)
    import math
    assert pytest.approx(math.sqrt(sum(x * x for x in vec_poison)), 0.001) == 1.0
    assert pytest.approx(math.sqrt(sum(x * x for x in vec_billing)), 0.001) == 1.0

    # Event embeddings
    poison_event = {
        "event_type": "QA_POISON_INJECTION",
        "node_id": "eu-west-1",
        "branch_name": "qa/adversarial",
        "is_bad_data": True,
        "risk_score": 0.95,
        "diagnostic": "Timestamp drift > 3600s",
    }
    vec_event = embedder.embed_event(poison_event)

    # Cosine similarity between poison text query and poison event must be high (> 0.65)
    from core.semantic_cache import _cosine_similarity
    sim = _cosine_similarity(vec_poison, vec_event)
    assert sim > 0.65

    # Similarity to unrelated billing text must be lower
    sim_unrelated = _cosine_similarity(vec_billing, vec_event)
    assert sim > sim_unrelated


# ── 2. Vector Index & Hybrid Relational Filters ───────────────────────────────

def test_audit_vector_index_hybrid_search():
    index = AuditVectorIndex()

    events = [
        {
            "id": 101,
            "node_id": "us-east-1",
            "branch_name": "main",
            "event_type": "PAYMENT_CAPTURE",
            "developer_id": "billing-bot",
            "is_bad_data": False,
            "risk_score": 0.15,
            "diagnostic": "Clean Stripe transaction",
        },
        {
            "id": 102,
            "node_id": "eu-west-1",
            "branch_name": "qa/tests",
            "event_type": "QA_POISON_INJECTION",
            "developer_id": "qa-tester",
            "is_bad_data": True,
            "risk_score": 0.92,
            "diagnostic": "Corrupted payload",
        },
        {
            "id": 103,
            "node_id": "us-east-1",
            "branch_name": "feature/payments",
            "event_type": "CROSS_REGION_BILLING_MUTATION",
            "developer_id": "dev-01",
            "is_bad_data": False,
            "risk_score": 0.78,
            "diagnostic": "Unusual cross-region access",
        },
    ]

    index.index_batch(events)
    assert index.count == 3

    # 1. Search for poison events
    res_poison = index.search("poison injection corrupted payload", k=1)
    assert len(res_poison) == 1
    assert res_poison[0]["event_id"] == 102
    assert res_poison[0]["similarity"] > 0.65

    # 2. Search with relational filter (is_bad_data = True)
    res_bad = index.search("payment", filters={"is_bad_data": True})
    assert len(res_bad) == 1
    assert res_bad[0]["event_id"] == 102  # Only bad data event returned

    # 3. Search with min_risk filter (>= 0.70)
    res_high_risk = index.search("all events", filters={"min_risk": 0.70})
    returned_ids = [r["event_id"] for r in res_high_risk]
    assert 101 not in returned_ids
    assert 102 in returned_ids
    assert 103 in returned_ids


# ── 3. FastAPI Semantic Search Endpoint ──────────────────────────────────────

def test_api_semantic_audit_search_and_reindex():
    client = TestClient(app)

    # 1. Enqueue audit event
    payload = {
        "node_id": "asia-south-1",
        "branch_name": "main",
        "developer_id": "telemetry-agent",
        "event_type": "PATIENT_CARDIOLOGY_TELEMETRY_SYNC",
        "entity_id": "pat_007",
        "data": {"heart_rate": 72, "bpm_drift": 0.02},
        "request_rate": 12.0,
        "is_cross_region": False,
        "error_rate": 0.0,
    }
    r = client.post("/api/audit/log", json=payload)
    assert r.status_code == 200

    # 2. Execute semantic search (instantly finds the vector in memory)
    search_payload = {
        "query": "cardiology patient telemetry sync",
        "filters": {"node_id": "asia-south-1"},
        "limit": 10,
        "min_similarity": 0.0,
    }
    r_search = client.post("/api/audit/semantic-search", json=search_payload)
    assert r_search.status_code == 200
    data = r_search.json()
    assert "results" in data
    assert data["total_matches"] >= 1
    assert data["results"][0]["event"]["node_id"] == "asia-south-1"
