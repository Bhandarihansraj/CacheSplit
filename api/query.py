"""
CacheSplit v3 — Multi-Master Query API
Single endpoint for ops to query one, several, or all master nodes.
Routes via the live NodeRegistry — no mocks.
"""
from typing import List
from fastapi import APIRouter
from pydantic import BaseModel

from services.registry import registry
from db import node_repo, commit_repo

router = APIRouter(prefix="/api/query")


class QueryRequest(BaseModel):
    requester_scope: str
    target: str
    query_type: str


def _resolve_targets(target: str) -> List[str]:
    target = (target or "").strip()
    if not target:
        return []
    if target == "all_masters":
        return [n.node_id for n in registry.list_all_masters()]
    return [t.strip() for t in target.split(",") if t.strip()]


@router.post("")
async def multi_master_query(req: QueryRequest):
    query_type = (req.query_type or "status").lower()
    results = {}

    for node_id in _resolve_targets(req.target):
        status = registry.get_status(node_id)
        db_row = await node_repo.get_node(node_id)

        if not status and not db_row:
            results[node_id] = {"error": "node not registered"}
            continue

        base = {
            "node_id": node_id,
            "region": status.region if status else db_row["region"],
            "tier": status.tier if status else db_row["tier"],
            "health": status.health if status else db_row["health"],
            "version_number": status.version_number if status else db_row.get("version_number", 0),
            "current_commit_hash": (
                status.current_commit_hash if status else db_row.get("current_commit_hash", "")
            ),
        }

        if query_type == "cache_contents":
            from services.cache_store import cache_store
            count = await commit_repo.count_entities_by_node(node_id)
            base["cached_entity_count"] = count
            base["cache_summary"] = status.cache_summary if status else {}
            rows = await commit_repo.get_entities_by_node(node_id, limit=5)
            base["sample_entities"] = [
                {
                    "entity_id": r["entity_id"],
                    "entity_type": r["entity_type"],
                    "merkle_root_hash": r.get("merkle_root_hash", ""),
                }
                for r in rows
            ]
            base["partitions"] = cache_store.node_partitions.get(node_id, [])
            results[node_id] = base

        elif query_type == "commit_history":
            from services.cache_store import cache_store
            commits = await commit_repo.get_recent_commits(limit=50)
            history = []
            for c in commits:
                affected = [cache_store.entity_to_node.get(eid, "") for eid in c.get("entity_ids", [])]
                if node_id in affected:
                    history.append({
                        "transaction_id": c.get("transaction_id"),
                        "commit_hash": c.get("commit_hash"),
                        "entities": c.get("entity_ids", []),
                        "created_at": c.get("created_at"),
                    })
            base["commit_history"] = history[-10:]
            results[node_id] = base

        else:  # "status" is the default
            results[node_id] = base

    return {
        "requester_scope": req.requester_scope,
        "target": req.target,
        "query_type": query_type,
        "results": results,
    }