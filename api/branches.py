"""
api/branches.py
FastAPI router for Git-style Node Branching & Dot-Notation Indexing.
Endpoints for branch creation, commits, push, pull, restore/rollback, diffs, and dot path resolution.
"""
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from core.branch_engine import BranchEngine, NodeBranch
from core.dot_indexer import dot_indexer
from services.cache_store import cache_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/branch", tags=["branches"])

# In-memory registry of BranchEngine instances per node_id
_node_engines: Dict[str, BranchEngine] = {}


def get_or_create_engine(node_id: str) -> BranchEngine:
    if node_id not in _node_engines:
        # Initialize branch engine with current node DAG snapshot
        base_dag = cache_store.dag
        _node_engines[node_id] = BranchEngine(node_id=node_id, base_dag=base_dag)
    return _node_engines[node_id]


# ── Request Models ────────────────────────────────────────────────────────────

class CreateBranchRequest(BaseModel):
    node_id: str
    branch_name: str
    developer_id: str = "dev-user"
    from_branch: str = "main"


class CommitBranchRequest(BaseModel):
    node_id: str
    branch_name: str
    developer_id: str = "dev-user"
    message: str = "Feature mutation"
    mutations: List[Dict[str, Any]]
    edges: Optional[List[Dict[str, Any]]] = []


class PushBranchRequest(BaseModel):
    node_id: str
    source_branch: str
    target_branch: str = "main"


class PullBranchRequest(BaseModel):
    node_id: str
    branch_name: str
    from_branch: str = "main"


class RestoreBranchRequest(BaseModel):
    node_id: str
    branch_name: str
    commit_id: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/create")
async def create_branch(req: CreateBranchRequest):
    """Create an isolated developer branch on a node."""
    engine = get_or_create_engine(req.node_id)
    try:
        branch = engine.create_branch(
            branch_name=req.branch_name,
            developer_id=req.developer_id,
            from_branch=req.from_branch,
        )
        return {
            "status": "created",
            "branch": {
                "branch_name": branch.branch_name,
                "node_id": branch.node_id,
                "merkle_root": branch.merkle_root,
                "developer_id": branch.developer_id,
                "parent_branch": branch.parent_branch,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/list/{node_id}")
async def list_branches(node_id: str):
    """List all active branches on a given node."""
    engine = get_or_create_engine(node_id)
    return {"node_id": node_id, "branches": engine.list_branches()}


@router.post("/commit")
async def commit_to_branch(req: CommitBranchRequest):
    """Submit a compound commit isolated to a specific developer branch."""
    engine = get_or_create_engine(req.node_id)
    try:
        commit_obj = engine.commit(
            branch_name=req.branch_name,
            mutations=req.mutations,
            edges=req.edges,
            developer_id=req.developer_id,
            message=req.message,
        )
        # Update dot indexer context
        dot_indexer.set_path(
            f"nodes.{req.node_id}.branches.{req.branch_name}.head",
            commit_obj.commit_id,
        )
        dot_indexer.set_path(
            f"nodes.{req.node_id}.branches.{req.branch_name}.merkle_root",
            commit_obj.merkle_root,
        )
        return {
            "status": "committed",
            "commit_id": commit_obj.commit_id,
            "branch_name": commit_obj.branch_name,
            "merkle_root": commit_obj.merkle_root,
            "timestamp": commit_obj.timestamp,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/push")
async def push_branch(req: PushBranchRequest):
    """Push updates from a developer branch into target branch (e.g. main)."""
    engine = get_or_create_engine(req.node_id)
    try:
        res = engine.push(source_branch=req.source_branch, target_branch=req.target_branch)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pull")
async def pull_branch(req: PullBranchRequest):
    """Pull changes from source branch (e.g. main) into developer branch."""
    engine = get_or_create_engine(req.node_id)
    try:
        res = engine.pull(branch_name=req.branch_name, from_branch=req.from_branch)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/restore")
async def restore_branch(req: RestoreBranchRequest):
    """Restore branch state to a specific historical commit hash."""
    engine = get_or_create_engine(req.node_id)
    try:
        res = engine.restore(branch_name=req.branch_name, commit_id=req.commit_id)
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/diff")
async def diff_branches(node_id: str, branch_a: str, branch_b: str):
    """Compare entity versions and Merkle roots between two branches."""
    engine = get_or_create_engine(node_id)
    try:
        return engine.diff(branch_a=branch_a, branch_b=branch_b)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/log/{node_id}/{branch_name}")
async def branch_log(node_id: str, branch_name: str, limit: int = 20):
    """Get commit history for a branch."""
    engine = get_or_create_engine(node_id)
    return {"node_id": node_id, "branch_name": branch_name, "log": engine.log(branch_name, limit=limit)}


# ── Hierarchical Dot-Notation Resolver ────────────────────────────────────────

dot_router = APIRouter(prefix="/api/dot", tags=["dot-indexer"])


@dot_router.get("/resolve")
async def resolve_dot_path(path: str):
    """
    Resolve hierarchical dot-notation path in O(1) in-memory lookup.
    e.g. /api/dot/resolve?path=nodes.us-east-1.branches.main.merkle_root
    """
    # Synchronize current live state into dot indexer
    for nid, engine in _node_engines.items():
        for b_info in engine.list_branches():
            bname = b_info["branch_name"]
            dot_indexer.set_path(f"nodes.{nid}.branches.{bname}.merkle_root", b_info["merkle_root"])
            dot_indexer.set_path(f"nodes.{nid}.branches.{bname}.head_commit", b_info["head_commit_id"])
            dot_indexer.set_path(f"nodes.{nid}.branches.{bname}.developer_id", b_info["developer_id"])

    val = dot_indexer.resolve(path)
    if val is None:
        return {"path": path, "found": False, "value": None}
    return {"path": path, "found": True, "value": val}
