"""
api/hnsw.py
FastAPI Router for AgentDB HNSW Multi-Layer Vector Graph & Int8 Quantization Engine.
Provides graph telemetry, real-time Flat vs HNSW performance benchmarks, and quantization inspection.
"""

import time
import random
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from services.semantic_router import global_semantic_router
from core.hnsw_index import HNSWIndex
from core.scalar_quantizer import ScalarQuantizer

router = APIRouter(prefix="/api/hnsw", tags=["AgentDB HNSW & Quantization"])


class BenchmarkRequest(BaseModel):
    num_vectors: int = Field(500, ge=50, le=5000, description="Number of synthetic vectors to index for benchmark")
    num_queries: int = Field(20, ge=1, le=200, description="Number of test queries to run")
    dim: int = Field(32, ge=8, le=128, description="Vector dimension")
    k: int = Field(5, ge=1, le=20, description="Top-k nearest neighbors")


class QuantizeInspectRequest(BaseModel):
    vector: list[float] = Field(..., description="Float vector to inspect quantization on")


@router.get("/stats")
def get_hnsw_stats():
    """Returns live graph index statistics and scalar quantization compression metrics."""
    hnsw = global_semantic_router.index.hnsw
    if not hnsw:
        # Fallback default stats if index empty
        dim = global_semantic_router.index.dimension or 32
        sq = ScalarQuantizer(dim)
        return {
            "status": "UNINITIALIZED",
            "total_nodes": global_semantic_router.index.count,
            "dimension": dim,
            "max_level": 0,
            "compression_stats": sq.compute_compression_stats(global_semantic_router.index.count),
            "layer_distribution": {0: global_semantic_router.index.count},
            "average_degrees": {"layer_0": 0.0},
        }

    return {
        "status": "INITIALIZED",
        **hnsw.get_stats(),
    }


@router.post("/benchmark")
def run_hnsw_benchmark(req: BenchmarkRequest):
    """
    Executes a head-to-head benchmark comparing Brute-Force Flat Search vs HNSW Graph Search.
    Measures search latency (microseconds), speedup multiplier, recall accuracy, and memory savings.
    """
    try:
        # 1. Generate synthetic dataset
        random.seed(42)
        dataset = []
        for i in range(req.num_vectors):
            vec = [round(random.uniform(-1.0, 1.0), 4) for _ in range(req.dim)]
            dataset.append((f"vec_{i}", vec))

        # 2. Build HNSW graph
        hnsw = HNSWIndex(dim=req.dim, M=16, ef_construction=64, ef_search=32, metric="cosine", enable_quantization=True)
        t_build_start = time.perf_counter()
        for k_id, v in dataset:
            hnsw.insert(k_id, v)
        t_build_ms = (time.perf_counter() - t_build_start) * 1000.0

        # 3. Generate test queries
        queries = []
        for _ in range(req.num_queries):
            q_vec = [round(random.uniform(-1.0, 1.0), 4) for _ in range(req.dim)]
            queries.append(q_vec)

        # 4. Run Brute-Force Flat Search
        flat_times = []
        flat_results = []
        for q in queries:
            t0 = time.perf_counter()
            # Brute-force cosine
            scored = []
            q_norm = (sum(x * x for x in q)) ** 0.5 or 1.0
            for k_id, v in dataset:
                v_norm = (sum(x * x for x in v)) ** 0.5 or 1.0
                dot = sum(a * b for a, b in zip(q, v))
                sim = dot / (q_norm * v_norm)
                scored.append((k_id, sim))
            scored.sort(key=lambda x: x[1], reverse=True)
            flat_times.append(time.perf_counter() - t0)
            flat_results.append(set(k for k, _ in scored[:req.k]))

        # 5. Run HNSW Graph Search
        hnsw_times = []
        hnsw_results = []
        for q in queries:
            t0 = time.perf_counter()
            res = hnsw.search(q, k=req.k)
            hnsw_times.append(time.perf_counter() - t0)
            hnsw_results.append(set(k for k, _ in res))

        # 6. Compute metrics
        avg_flat_us = (sum(flat_times) / len(flat_times)) * 1_000_000.0
        avg_hnsw_us = (sum(hnsw_times) / len(hnsw_times)) * 1_000_000.0
        speedup = avg_flat_us / max(0.001, avg_hnsw_us)

        # Recall@K calculation
        total_overlap = 0
        for f_set, h_set in zip(flat_results, hnsw_results):
            overlap = len(f_set.intersection(h_set))
            total_overlap += overlap / max(1, req.k)
        recall_pct = (total_overlap / len(queries)) * 100.0

        sq = ScalarQuantizer(req.dim)
        compression = sq.compute_compression_stats(req.num_vectors)

        return {
            "status": "COMPLETED",
            "dataset_size": req.num_vectors,
            "vector_dimension": req.dim,
            "top_k": req.k,
            "queries_executed": req.num_queries,
            "hnsw_build_time_ms": round(t_build_ms, 2),
            "flat_search_avg_us": round(avg_flat_us, 1),
            "hnsw_search_avg_us": round(avg_hnsw_us, 1),
            "speedup_multiplier": round(speedup, 2),
            "recall_accuracy_pct": round(recall_pct, 1),
            "graph_stats": hnsw.get_stats(),
            "compression_stats": compression,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Benchmark error: {str(e)}")


@router.post("/quantize")
def inspect_quantization(req: QuantizeInspectRequest):
    """Inspects Int8 scalar quantization byte conversion and decompression delta."""
    dim = len(req.vector)
    sq = ScalarQuantizer(dim)
    q_bytes, min_val, scale = sq.quantize_vector(req.vector)
    reconstructed = sq.dequantize_vector(q_bytes, min_val, scale)

    # Compute max absolute error and mean squared error
    max_err = max(abs(a - b) for a, b in zip(req.vector, reconstructed))
    mse = sum((a - b) ** 2 for a, b in zip(req.vector, reconstructed)) / dim

    return {
        "dimension": dim,
        "original_vector": req.vector[:8],
        "quantized_int8_bytes": list(q_bytes[:8]),
        "reconstructed_vector": [round(x, 4) for x in reconstructed[:8]],
        "min_offset": round(min_val, 4),
        "scale_step": round(scale, 6),
        "max_absolute_error": round(max_err, 6),
        "mean_squared_error": round(mse, 8),
        "byte_reduction": f"{dim * 4} bytes (Float32) -> {dim + 12} bytes (Int8 SQ8)",
    }
