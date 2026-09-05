"""
CacheSplit v3 — Dashboard API Router
All endpoints read from / write to real SQLite DB + in-memory DAG.
Zero mock data — explicit "not connected" states on failure.
"""
import json
import time
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from services.registry import registry
from services.cache_store import cache_store
from services.analytics import analytics
from core.compound_commit import CompoundCommit, EntityMutation, RelationshipEdge
from db import node_repo
from db import commit_repo
from db import security_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard")


def _health_label(health: str) -> str:
    return {
        "ok": "All clear",
        "stale": "Needs attention",
        "quarantined": "Critical — Paused for safety",
    }.get(health, "Unknown")


# ───────────────────────── NODE MAP ──────────────────────────────────────────

class CreateNodeRequest(BaseModel):
    node_id: str
    region: str
    tier: str = "main"

class UpdateNodeRequest(BaseModel):
    region: Optional[str] = None
    tier: Optional[str] = None
    health: Optional[str] = None

class BatchCreateNodesRequest(BaseModel):
    nodes: List[CreateNodeRequest]


@router.get("/node-map")
async def get_node_map():
    db_nodes = await node_repo.get_all_nodes()
    nodes_data = []
    for n in db_nodes:
        node_id = n["node_id"]
        in_mem = registry.nodes.get(node_id)
        health = in_mem.health if in_mem else n["health"]
        hb_enabled = in_mem.heartbeat_enabled if in_mem else bool(n["heartbeat_enabled"])
        flags = in_mem.agent_flags if in_mem else n["agent_flags"]
        last_hb = in_mem.last_heartbeat if in_mem else n.get("last_heartbeat", 0)

        entity_count = await cache_store.count_node_entities(node_id)

        nodes_data.append({
            "id": node_id,
            "region": n["region"],
            "tier": n["tier"],
            "health_raw": health,
            "status_label": _health_label(health),
            "is_healthy": health == "ok",
            "heartbeat_enabled": hb_enabled,
            "agent_flags": flags,
            "cached_entity_count": entity_count,
            "version_number": n.get("version_number", 0),
            "last_heartbeat_secs_ago": max(0, int(time.time() - last_hb)) if last_hb else None,
        })
    return {"nodes": nodes_data}


@router.post("/nodes")
async def create_node(req: CreateNodeRequest):
    existing = await node_repo.get_node(req.node_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Node '{req.node_id}' already exists")
    await node_repo.upsert_node(node_id=req.node_id, region=req.region, tier=req.tier)
    registry.register_node(req.node_id, req.region, tier=req.tier)
    return {"status": "created", "node_id": req.node_id}


@router.put("/node/{node_id}")
async def update_node(node_id: str, req: UpdateNodeRequest):
    existing = await node_repo.get_node(node_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    await node_repo.update_node(node_id, region=req.region, tier=req.tier, health=req.health)
    if req.region and node_id in registry.nodes:
        registry.nodes[node_id].region = req.region
    return {"status": "updated", "node_id": node_id}


@router.delete("/node/{node_id}")
async def delete_node(node_id: str):
    existing = await node_repo.get_node(node_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    await node_repo.delete_node(node_id)
    if node_id in registry.nodes:
        del registry.nodes[node_id]
    return {"status": "deleted", "node_id": node_id}


@router.post("/nodes/batch")
async def batch_create_nodes(req: BatchCreateNodesRequest):
    created = []
    skipped = []
    for n in req.nodes:
        existing = await node_repo.get_node(n.node_id)
        if existing:
            skipped.append(n.node_id)
            continue
        await node_repo.upsert_node(node_id=n.node_id, region=n.region, tier=n.tier)
        registry.register_node(n.node_id, n.region, tier=n.tier)
        created.append(n.node_id)
    return {"created": len(created), "skipped": len(skipped),
            "created_ids": created, "skipped_ids": skipped}


# ───────────────────────── ENTITY EXPLORER ───────────────────────────────────

@router.get("/node/{node_id}/entities")
async def get_node_entities(node_id: str, limit: int = 50):
    entities = await cache_store.get_node_entities_from_db(node_id, limit=limit)
    total = await cache_store.count_node_entities(node_id)
    return {"node_id": node_id, "entities": entities, "total_cached": total}


@router.get("/entity/{entity_id}/merkle-tree")
async def get_merkle_tree(entity_id: str):
    tree = cache_store.get_entity_dag_tree(entity_id)
    if not tree:
        raise HTTPException(status_code=404, detail="Entity not found in cache DAG")
    return {"merkle_tree": tree}


# ───────────────────────── COMMIT LOG ────────────────────────────────────────

@router.get("/commits/recent")
async def get_recent_commits(limit: int = 20):
    commits = await commit_repo.get_recent_commits(limit=limit)
    return {"commits": commits}


# ───────────────────────── COMPOUND COMMIT ───────────────────────────────────

class CompoundCommitPayload(BaseModel):
    transaction_id: str
    mutations: List[EntityMutation]
    edges: List[RelationshipEdge] = []


@router.post("/compound-commit")
async def execute_compound_commit(payload: CompoundCommitPayload):
    from services.state_manager import state_manager
    commit = CompoundCommit(
        transaction_id=payload.transaction_id,
        mutations=payload.mutations,
        edges=payload.edges,
    )
    try:
        result = await cache_store.execute_compound_commit(commit)
    except ValueError as e:
        if "OCC Conflict" in str(e):
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
        
    # Flush any ML anomalies triggered by the access logging above
    await analytics.flush_anomalies()
    
    # Broadcast to all active UI clients
    await state_manager.broadcast({
        "type": "STATE_MUTATED", 
        "transaction_id": payload.transaction_id,
        "mutated_entities": [m.entity_id for m in payload.mutations]
    })
    
    return {"status": "success", "result": result}


# ───────────────────────── REBAC ─────────────────────────────────────────────

class ReBACTestRequest(BaseModel):
    clinician_id: str
    target_entity_id: str


@router.post("/rebac/test")
async def test_rebac(req: ReBACTestRequest):
    result = await cache_store.authorize_rebac(req.clinician_id, req.target_entity_id)
    return result


# ───────────────────────── GRAPH SECURITY ────────────────────────────────────

class AnomalyTestRequest(BaseModel):
    requesting_node_id: str
    requester_region: str
    target_entity_id: str


@router.post("/security/test-anomaly")
async def test_graph_anomaly(req: AnomalyTestRequest):
    result = await cache_store.evaluate_graph_security(
        requesting_node_id=req.requesting_node_id,
        requester_region=req.requester_region,
        target_entity_id=req.target_entity_id,
    )
    if result.get("flagged"):
        registry.mark_quarantined(req.requesting_node_id, result["reason"])
        flags = registry.nodes[req.requesting_node_id].agent_flags if req.requesting_node_id in registry.nodes else [result["reason"]]
        await node_repo.update_node_health(req.requesting_node_id, "quarantined", flags)
    return result


# ───────────────────────── NODE CONTROL ──────────────────────────────────────

@router.post("/node/{node_id}/toggle-heartbeat")
async def toggle_heartbeat(node_id: str):
    new_state = registry.toggle_heartbeat(node_id)
    await node_repo.toggle_heartbeat(node_id, new_state)
    return {"node_id": node_id, "heartbeat_enabled": new_state}


@router.post("/node/{node_id}/recover")
async def recover_node(node_id: str):
    registry.recover_node(node_id)
    await node_repo.recover_node(node_id)
    return {"status": "recovered", "node_id": node_id}


# ───────────────────────── SECURITY FEED ─────────────────────────────────────

@router.get("/security-feed")
async def get_security_feed(limit: int = 20):
    # Real events from DB
    db_events = await security_repo.get_recent_security_events(limit=limit)
    alerts = []
    for ev in db_events:
        alerts.append({
            "id": ev["id"],
            "node_id": ev["node_id"],
            "event_type": ev["event_type"],
            "description": ev["reason"],
            "severity": ev["severity"],
            "target_entity_id": ev.get("target_entity_id", ""),
            "created_at": ev["created_at"],
            "status_label": _health_label("quarantined"),
        })
    # Also include in-memory node flags for live nodes
    for node_id, status in registry.nodes.items():
        if status.health == "quarantined" and status.agent_flags:
            for flag in status.agent_flags:
                # Avoid duplicates with DB entries
                if not any(a["node_id"] == node_id and flag in a["description"] for a in alerts):
                    alerts.append({
                        "id": None,
                        "node_id": node_id,
                        "event_type": "NODE_FLAG",
                        "description": flag,
                        "severity": "HIGH",
                        "target_entity_id": "",
                        "created_at": time.time(),
                        "status_label": _health_label("quarantined"),
                    })
    return {"alerts": alerts}


# ───────────────────────── ML STATUS ────────────────────────────────────────

@router.get("/ml-status")
async def get_ml_status():
    return analytics.get_status()
