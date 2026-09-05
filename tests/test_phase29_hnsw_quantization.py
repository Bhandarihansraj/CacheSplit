"""
tests/test_phase29_hnsw_quantization.py
Automated test suite for Phase 29: AgentDB HNSW Multi-Layer Vector Graph & Int8 Quantization Engine.
"""

import math
import random
import pytest
from starlette.testclient import TestClient

from core.scalar_quantizer import ScalarQuantizer
from core.hnsw_index import HNSWIndex, compute_distance
from core.semantic_cache import SemanticCacheIndex, VectorEntry
from api.server import app

client = TestClient(app)


def test_scalar_quantizer_roundtrip_and_compression():
    dim = 32
    sq = ScalarQuantizer(dim=dim, num_bits=8)

    random.seed(123)
    orig_vec = [random.uniform(-2.5, 3.5) for _ in range(dim)]
    q_bytes, min_val, scale = sq.quantize_vector(orig_vec)

    assert len(q_bytes) == dim
    assert isinstance(min_val, float)
    assert scale > 0.0

    reconstructed = sq.dequantize_vector(q_bytes, min_val, scale)
    assert len(reconstructed) == dim

    # Check maximum quantization error is within 1 scale unit
    max_err = max(abs(a - b) for a, b in zip(orig_vec, reconstructed))
    assert max_err <= scale + 1e-4

    # Check asymmetric dot product
    q_vec2 = [random.uniform(-1.0, 1.0) for _ in range(dim)]
    true_dot = sum(a * b for a, b in zip(q_vec2, orig_vec))
    asym_dot = sq.asymmetric_dot_product(q_vec2, q_bytes, min_val, scale)
    assert abs(true_dot - asym_dot) < 0.25

    # Check memory compression stats
    stats = sq.compute_compression_stats(1000)
    assert stats["compression_ratio"] >= 2.5
    assert stats["memory_reduction_pct"] >= 65.0


def test_hnsw_multi_layer_construction():
    dim = 16
    hnsw = HNSWIndex(dim=dim, M=8, ef_construction=32, ef_search=16, metric="cosine", enable_quantization=True)

    random.seed(42)
    keys = [f"k_{i}" for i in range(100)]
    for k in keys:
        v = [random.uniform(-1.0, 1.0) for _ in range(dim)]
        hnsw.insert(k, v)

    stats = hnsw.get_stats()
    assert stats["total_nodes"] == 100
    assert stats["entry_point"] is not None
    assert stats["max_level"] >= 0
    assert 0 in stats["layer_distribution"]
    assert stats["layer_distribution"][0] == 100
    assert stats["quantization_enabled"] is True


def test_hnsw_nearest_neighbor_recall():
    dim = 16
    hnsw = HNSWIndex(dim=dim, M=16, ef_construction=64, ef_search=32, metric="cosine", enable_quantization=False)

    random.seed(99)
    dataset = []
    for i in range(200):
        vec = [random.uniform(-1.0, 1.0) for _ in range(dim)]
        dataset.append((f"doc_{i}", vec))
        hnsw.insert(f"doc_{i}", vec)

    # Test top-k recall across multiple queries
    recalls = []
    for _ in range(15):
        query = [random.uniform(-1.0, 1.0) for _ in range(dim)]
        q_norm = math.sqrt(sum(x * x for x in query))

        # True brute-force cosine top-5
        scored = []
        for k_id, v in dataset:
            v_norm = math.sqrt(sum(x * x for x in v))
            sim = sum(a * b for a, b in zip(query, v)) / (q_norm * v_norm)
            scored.append((k_id, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        ground_truth = set(k for k, _ in scored[:5])

        # HNSW top-5
        hnsw_results = set(k for k, _ in hnsw.search(query, k=5))

        overlap = len(ground_truth.intersection(hnsw_results))
        recalls.append(overlap / 5.0)

    avg_recall = sum(recalls) / len(recalls)
    assert avg_recall >= 0.85, f"Expected average recall >= 85%, got {avg_recall*100}%"


def test_hnsw_self_healing_deletion():
    dim = 8
    hnsw = HNSWIndex(dim=dim, M=4, ef_construction=16, ef_search=8, metric="cosine")

    for i in range(20):
        v = [float(i + j) for j in range(dim)]
        hnsw.insert(f"node_{i}", v)

    initial_ep = hnsw.entry_point
    assert initial_ep in hnsw.nodes

    # Delete entry point node
    assert hnsw.delete(initial_ep) is True
    assert initial_ep not in hnsw.nodes
    assert hnsw.entry_point != initial_ep
    assert hnsw.entry_point in hnsw.nodes

    # Verify search still works cleanly after deletion
    q = [1.0] * dim
    results = hnsw.search(q, k=3)
    assert len(results) == 3
    assert not any(k == initial_ep for k, _ in results)


def test_semantic_cache_hnsw_integration():
    index = SemanticCacheIndex(name="hnsw_test", enable_hnsw=True)

    v1 = [1.0, 0.0, 0.0, 0.0]
    v2 = [0.9, 0.1, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0, 0.0]

    index.upsert(VectorEntry(key="cardio_1", vector=v1, data={"type": "cardio"}, metadata={"dept": "cardio"}))
    index.upsert(VectorEntry(key="cardio_2", vector=v2, data={"type": "cardio"}, metadata={"dept": "cardio"}))
    index.upsert(VectorEntry(key="billing_1", vector=v3, data={"type": "billing"}, metadata={"dept": "billing"}))

    assert index.hnsw is not None
    assert index.hnsw.get_stats()["total_nodes"] == 3

    # HNSW accelerated search query
    results = index.query(query_vector=[0.95, 0.05, 0.0, 0.0], k=2, use_hnsw=True)
    assert len(results) == 2
    assert results[0]["key"] == "cardio_1" or results[0]["key"] == "cardio_2"
    assert results[0]["similarity"] > 0.9

    # Filtered HNSW query
    filtered = index.query(
        query_vector=[0.5, 0.5, 0.0, 0.0],
        k=2,
        filters={"dept": "billing"},
        use_hnsw=True,
    )
    assert len(filtered) == 1
    assert filtered[0]["key"] == "billing_1"


def test_api_hnsw_endpoints():
    # 1. GET /api/hnsw/stats
    res_stats = client.get("/api/hnsw/stats")
    assert res_stats.status_code == 200
    data_stats = res_stats.json()
    assert "total_nodes" in data_stats
    assert "compression_stats" in data_stats

    # 2. POST /api/hnsw/benchmark
    bench_payload = {
        "num_vectors": 100,
        "num_queries": 10,
        "dim": 16,
        "k": 5
    }
    res_bench = client.post("/api/hnsw/benchmark", json=bench_payload)
    assert res_bench.status_code == 200
    data_bench = res_bench.json()
    assert data_bench["status"] == "COMPLETED"
    assert data_bench["dataset_size"] == 100
    assert "speedup_multiplier" in data_bench
    assert "recall_accuracy_pct" in data_bench

    # 3. POST /api/hnsw/quantize
    quant_payload = {
        "vector": [0.12, -0.45, 0.88, 0.34, -0.91, 0.05, 0.67, -0.22]
    }
    res_quant = client.post("/api/hnsw/quantize", json=quant_payload)
    assert res_quant.status_code == 200
    data_quant = res_quant.json()
    assert data_quant["dimension"] == 8
    assert "quantized_int8_bytes" in data_quant
    assert data_quant["max_absolute_error"] >= 0.0
