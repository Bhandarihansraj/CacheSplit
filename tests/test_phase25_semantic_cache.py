"""
tests/test_phase25_semantic_cache.py
Comprehensive test suite for Phase 25: AgentDB Semantic Vector Cache Engine.
Tests similarity metrics, hybrid metadata filters, MMR diversification,
semantic neighborhood invalidation, and FastAPI endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from core.semantic_cache import (
    SemanticCacheIndex,
    VectorEntry,
    compute_similarity,
    matches_filter,
)
from core.semantic_invalidation import SemanticNeighborhoodInvalidator
from services.semantic_router import SemanticRouter
from api.server import app


# ── 1. Vector Metrics & Similarity ──────────────────────────────────────────

def test_vector_similarity_metrics():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]

    # Cosine: identical = 1.0, orthogonal = 0.0
    assert pytest.approx(compute_similarity(v1, v2, "cosine"), 0.001) == 1.0
    assert pytest.approx(compute_similarity(v1, v3, "cosine"), 0.001) == 0.0

    # Dot product: identical = 1.0, orthogonal = 0.0
    assert pytest.approx(compute_similarity(v1, v2, "dot"), 0.001) == 1.0
    assert pytest.approx(compute_similarity(v1, v3, "dot"), 0.001) == 0.0

    # Euclidean similarity = 1 / (1 + dist)
    assert pytest.approx(compute_similarity(v1, v2, "euclidean"), 0.001) == 1.0
    assert compute_similarity(v1, v3, "euclidean") < 1.0


def test_vector_dimension_mismatch_raises():
    v1 = [1.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    with pytest.raises(ValueError, match="dimension mismatch"):
        compute_similarity(v1, v2, "cosine")


# ── 2. Hybrid Filtering ──────────────────────────────────────────────────────

def test_hybrid_metadata_filters():
    meta = {
        "region": "us-east-1",
        "access_level": 3,
        "tags": ["auth", "security", "jwt"],
        "price": 49.99,
    }

    # Exact match
    assert matches_filter(meta, {"region": "us-east-1"}) is True
    assert matches_filter(meta, {"region": "eu-west-1"}) is False

    # Comparison operators
    assert matches_filter(meta, {"access_level": {"$gte": 3}}) is True
    assert matches_filter(meta, {"access_level": {"$gt": 3}}) is False
    assert matches_filter(meta, {"price": {"$lte": 50.0}}) is True

    # In and Contains operators
    assert matches_filter(meta, {"region": {"$in": ["us-east-1", "eu-central-1"]}}) is True
    assert matches_filter(meta, {"region": {"$in": ["asia-south-1"]}}) is False
    assert matches_filter(meta, {"tags": {"$contains": "jwt"}}) is True
    assert matches_filter(meta, {"tags": {"$contains": "billing"}}) is False


# ── 3. Index & MMR Diversification ───────────────────────────────────────────

def test_semantic_index_and_mmr_diversification():
    index = SemanticCacheIndex("test_index")

    # Document A and B are very similar (Auth guides)
    index.upsert(VectorEntry(key="doc:a", vector=[0.9, 0.1, 0.0], data={"title": "Auth A"}, metadata={"cat": "auth"}))
    index.upsert(VectorEntry(key="doc:b", vector=[0.88, 0.12, 0.0], data={"title": "Auth B"}, metadata={"cat": "auth"}))
    # Document C is moderately similar
    index.upsert(VectorEntry(key="doc:c", vector=[0.7, 0.3, 0.0], data={"title": "Security C"}, metadata={"cat": "auth"}))
    # Document D is different (Billing)
    index.upsert(VectorEntry(key="doc:d", vector=[0.1, 0.9, 0.0], data={"title": "Billing D"}, metadata={"cat": "billing"}))

    query_vec = [0.95, 0.05, 0.0]

    # Standard query without MMR returns doc:a then doc:b (both near identical)
    std_results = index.query(query_vec, k=2, use_mmr=False)
    assert len(std_results) == 2
    assert std_results[0]["key"] == "doc:a"
    assert std_results[1]["key"] == "doc:b"

    # Query with MMR (lambda = 0.2 -> strong diversity)
    mmr_results = index.query(query_vec, k=2, use_mmr=True, mmr_lambda=0.2)
    assert len(mmr_results) == 2
    assert mmr_results[0]["key"] == "doc:a"
    # MMR should choose a more diverse candidate (doc:c or doc:d) over redundant doc:b
    assert mmr_results[1]["key"] in ["doc:c", "doc:d"]


# ── 4. Semantic Neighborhood Invalidation ────────────────────────────────────

def test_semantic_neighborhood_invalidation():
    index = SemanticCacheIndex("inval_index")

    # Cluster 1: Payment keys
    index.upsert(VectorEntry(key="pay:1", vector=[0.05, 0.95, 0.1], data={"val": 100}))
    index.upsert(VectorEntry(key="pay:2", vector=[0.08, 0.92, 0.1], data={"val": 200}))
    # Cluster 2: Security keys
    index.upsert(VectorEntry(key="sec:1", vector=[0.95, 0.05, 0.1], data={"val": 300}))

    invalidator = SemanticNeighborhoodInvalidator(index)

    # Invalidate neighborhood around payment pivot
    pivot = [0.06, 0.94, 0.1]
    res = invalidator.invalidate_neighborhood(pivot_vector=pivot, radius_similarity=0.85)

    assert "pay:1" in res.invalidated_keys
    assert "pay:2" in res.invalidated_keys
    assert "sec:1" not in res.invalidated_keys

    # Verifying states
    assert index.get("pay:1").state == "STALE"
    assert index.get("pay:2").state == "STALE"
    assert index.get("sec:1").state == "FRESH"


# ── 5. Semantic Router Hit/Miss & Stats ──────────────────────────────────────

def test_semantic_router_workflow():
    router = SemanticRouter(hit_threshold=0.90)

    router.store("profile:alice", [0.8, 0.2, 0.1], {"name": "Alice"})
    router.store("profile:bob", [0.1, 0.9, 0.1], {"name": "Bob"})

    # Query with near-identical vector -> CACHE_HIT
    hit_res = router.query([0.81, 0.19, 0.1], k=1)
    assert hit_res["status"] == "CACHE_HIT"
    assert hit_res["top_match"]["key"] == "profile:alice"

    # Query with distant vector -> CACHE_MISS
    miss_res = router.query([0.5, 0.5, 0.5], k=1)
    assert miss_res["status"] == "CACHE_MISS"

    stats = router.get_stats()
    assert stats["total_queries"] == 2
    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 1
    assert stats["hit_rate"] == 0.5


# ── 6. FastAPI Semantic Endpoints ────────────────────────────────────────────

def test_fastapi_semantic_endpoints():
    client = TestClient(app)

    # 1. Store
    store_payload = {
        "key": "test:api:1",
        "vector": [0.92, 0.15, 0.05, 0.22, 0.81, 0.11, 0.04, 0.33],
        "data": {"title": "API Test Item"},
        "metadata": {"region": "us-east-1", "tier": "gold"},
        "version": 1,
    }
    r = client.post("/semantic/store", json=store_payload)
    assert r.status_code == 200
    assert r.json()["status"] == "STORED"

    # 2. Query
    query_payload = {
        "query_vector": [0.92, 0.15, 0.05, 0.22, 0.81, 0.11, 0.04, 0.33],
        "k": 3,
        "metric": "cosine",
        "filters": {"tier": "gold"},
        "use_mmr": False,
    }
    r = client.post("/semantic/query", json=query_payload)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "CACHE_HIT"
    assert len(data["results"]) >= 1

    # 3. Invalidate Neighborhood
    inval_payload = {
        "pivot_vector": [0.92, 0.15, 0.05, 0.22, 0.81, 0.11, 0.04, 0.33],
        "radius_similarity": 0.80,
    }
    r = client.post("/semantic/invalidate-neighborhood", json=inval_payload)
    assert r.status_code == 200
    assert r.json()["status"] == "NEIGHBORHOOD_INVALIDATED"
    assert "test:api:1" in r.json()["invalidated_keys"]

    # 4. Stats
    r = client.get("/semantic/stats")
    assert r.status_code == 200
    assert "hit_rate" in r.json()
    assert "total_entries" in r.json()
