"""
api/semantic.py
FastAPI Router for AgentDB Semantic Vector Cache Engine.
Exposes endpoints for hybrid vector query, entry storage, neighborhood invalidation, and statistics.
"""

from typing import Optional, Any, Literal
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from services.semantic_router import global_semantic_router

router = APIRouter(prefix="/semantic", tags=["Semantic Vector Cache"])


class SemanticQueryRequest(BaseModel):
    query_vector: list[float] = Field(..., description="Query vector embedding")
    k: int = Field(5, ge=1, le=50, description="Top-k candidates")
    metric: Literal["cosine", "euclidean", "dot"] = "cosine"
    filters: Optional[dict[str, Any]] = Field(None, description="Metadata filters ($eq, $gte, $in, $contains)")
    use_mmr: bool = Field(False, description="Enable Maximal Marginal Relevance diversity")
    mmr_lambda: float = Field(0.5, ge=0.0, le=1.0, description="MMR Lambda (1.0 = pure relevance, 0.0 = pure diversity)")


class SemanticStoreRequest(BaseModel):
    key: str = Field(..., description="Unique cache key")
    vector: list[float] = Field(..., description="Vector embedding")
    data: dict = Field(default_factory=dict, description="Payload data")
    metadata: Optional[dict] = Field(default_factory=dict, description="Metadata for hybrid filtering")
    version: int = Field(1, description="Entity version")


class SemanticInvalidateRequest(BaseModel):
    pivot_vector: list[float] = Field(..., description="Vector pivot for neighborhood search")
    radius_similarity: float = Field(0.85, ge=0.0, le=1.0, description="Similarity radius threshold")
    target_key: Optional[str] = Field(None, description="Optional target key identifier")
    metric: Literal["cosine", "euclidean", "dot"] = "cosine"


@router.post("/query")
def query_semantic_cache(req: SemanticQueryRequest):
    try:
        res = global_semantic_router.query(
            query_vector=req.query_vector,
            k=req.k,
            metric=req.metric,
            filters=req.filters,
            use_mmr=req.use_mmr,
            mmr_lambda=req.mmr_lambda,
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/store")
def store_semantic_entry(req: SemanticStoreRequest):
    try:
        entry = global_semantic_router.store(
            key=req.key,
            vector=req.vector,
            data=req.data,
            metadata=req.metadata,
            version=req.version,
        )
        return {
            "status": "STORED",
            "key": entry.key,
            "version": entry.version,
            "state": entry.state,
            "vector_dimension": len(entry.vector),
            "updated_at": entry.updated_at,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/invalidate-neighborhood")
def invalidate_neighborhood(req: SemanticInvalidateRequest):
    try:
        result = global_semantic_router.invalidate_neighborhood(
            pivot_vector=req.pivot_vector,
            radius_similarity=req.radius_similarity,
            target_key=req.target_key,
            metric=req.metric,
        )
        return {
            "status": "NEIGHBORHOOD_INVALIDATED",
            "target_key": result.target_key,
            "invalidated_count": len(result.invalidated_keys),
            "invalidated_keys": result.invalidated_keys,
            "similarity_scores": result.similarity_scores,
            "radius_threshold": result.radius_threshold,
            "total_evaluated": result.total_evaluated,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stats")
def get_semantic_stats():
    return global_semantic_router.get_stats()


@router.post("/seed")
def seed_semantic_data():
    count = global_semantic_router.seed_demo_data()
    return {"status": "SEEDED", "entries_added": count, "stats": global_semantic_router.get_stats()}
