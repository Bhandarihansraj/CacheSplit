"""
CacheSplit v3 — Propagation API
Live endpoints for the debounced, budgeted, verified fetch workflow.
These are wired to the real registry + commit store — the propagation service
classes are exercised through real HTTP calls, not just unit tests.
"""
from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

from services.propagation import propagation
from db import commit_repo

router = APIRouter(prefix="/api/propagation")


class InvalidateRequest(BaseModel):
    node_id: str
    version_hint: str


class FetchRequest(BaseModel):
    node_id: str
    limit: int = 20


@router.post("/invalidate")
async def invalidate(req: InvalidateRequest):
    count = propagation.on_invalidation(req.node_id, req.version_hint)
    return {"node_id": req.node_id, "version_hint": req.version_hint, "invalidations_total": count}


@router.post("/fetch")
async def fetch(req: FetchRequest):
    async def fetch_fn(hint: str):
        # Simulates fetching the latest signed commit chain from origin/master.
        return await commit_repo.get_signed_commits(limit=req.limit)

    return await propagation.run_fetch_workflow(req.node_id, fetch_fn)


@router.get("/metrics")
async def metrics(node_id: Optional[str] = Query(default=None)):
    if node_id:
        return {"node_id": node_id, "metrics": propagation.metrics(node_id)}
    return {"nodes": {nid: propagation.metrics(nid) for nid in propagation._metrics}}