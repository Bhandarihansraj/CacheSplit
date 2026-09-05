"""
api/audit.py
FastAPI router for High-Throughput Batch Audit Trail, QA Bad Data Verification, and Stats.
"""
import time
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from services.audit_batcher import audit_batcher
from services.audit_trail_service import audit_trail_service
from agents.audit_ml_verifier import audit_verifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditLogEntry(BaseModel):
    node_id: str
    branch_name: str = "main"
    developer_id: str = "system"
    event_type: str = "CLIENT_MUTATION"
    entity_id: Optional[str] = ""
    data: Optional[Dict[str, Any]] = {}
    request_rate: Optional[float] = 10.0
    is_cross_region: Optional[bool] = False
    error_rate: Optional[float] = 0.0
    access_depth: Optional[float] = 1.0
    timestamp: Optional[float] = None


class BulkAuditLogRequest(BaseModel):
    events: List[AuditLogEntry]


@router.post("/log")
async def ingest_audit_event(req: AuditLogEntry):
    """
    Ingest a single audit event into the asynchronous micro-batch buffer.
    Accepts event in O(1) in memory and flushes in vectorized batch to DB.
    """
    event_dict = req.model_dump()
    if not event_dict.get("timestamp"):
        event_dict["timestamp"] = time.time()

    await audit_batcher.enqueue(event_dict)
    return {
        "status": "enqueued",
        "node_id": req.node_id,
        "branch_name": req.branch_name,
        "buffer_depth": audit_batcher.stats()["queue_depth"],
    }


@router.post("/log/bulk")
async def ingest_bulk_audit_events(req: BulkAuditLogRequest):
    """Ingest an array of audit events (e.g. from high-throughput load or QA test runs)."""
    now = time.time()
    for evt in req.events:
        evt_dict = evt.model_dump()
        if not evt_dict.get("timestamp"):
            evt_dict["timestamp"] = now
        await audit_batcher.enqueue(evt_dict)

    return {
        "status": "enqueued_bulk",
        "count": len(req.events),
        "buffer_depth": audit_batcher.stats()["queue_depth"],
    }


@router.get("/trail")
async def get_audit_trail(
    node_id: Optional[str] = None,
    branch_name: Optional[str] = None,
    developer_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    is_bad_data: Optional[bool] = None,
    min_risk: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    Parameterized audit log query with branch-awareness, QA bad-data filters,
    and ML risk score thresholds.
    """
    return await audit_trail_service.query_trail(
        node_id=node_id,
        branch_name=branch_name,
        developer_id=developer_id,
        entity_id=entity_id,
        is_bad_data=is_bad_data,
        min_risk=min_risk,
        limit=limit,
        offset=offset,
    )


@router.get("/stats")
async def get_audit_stats():
    """Real-time metrics on batch throughput, buffer queue depth, bad data counts, and ML risk stats."""
    batch_stats = audit_batcher.stats()
    summary_stats = await audit_trail_service.get_summary_stats()
    return {
        "batch_buffer": batch_stats,
        "trail_summary": summary_stats,
    }


@router.post("/test-validator")
async def test_qa_validator(req: AuditLogEntry):
    """Test the QA structural data validator and IsolationForest ML risk scorer without persisting."""
    is_bad, risk_score, diagnostic = audit_verifier.validate_and_score(req.model_dump())
    return {
        "is_bad_data": is_bad,
        "risk_score": risk_score,
        "diagnostic": diagnostic,
        "verdict": "BAD_DATA_FLAGGED" if is_bad else ("HIGH_RISK" if risk_score > 0.7 else "VERIFIED_OK"),
    }


class SemanticAuditSearchRequest(BaseModel):
    query: str = Field(..., description="Natural language search query")
    filters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Structured filters (node_id, branch_name, is_bad_data, min_risk)")
    limit: int = Field(25, ge=1, le=100)
    min_similarity: float = Field(0.0, ge=0.0, le=1.0)


@router.post("/semantic-search")
async def semantic_search_audit(req: SemanticAuditSearchRequest):
    """
    Hybrid semantic vector search over the compliance audit trail.
    Accepts natural language queries (e.g. 'cross-region poison injections') with relational filters.
    """
    return await audit_trail_service.search_semantic(
        query_text=req.query,
        filters=req.filters,
        limit=req.limit,
        min_similarity=req.min_similarity,
    )


@router.post("/reindex")
async def reindex_audit_vectors():
    """Populate or refresh the in-memory audit vector index from SQLite history."""
    count = await audit_trail_service.reindex_all_from_db()
    return {"status": "reindexed", "indexed_events": count}
