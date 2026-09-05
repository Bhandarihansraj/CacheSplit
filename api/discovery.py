"""
api/discovery.py
FastAPI router for DHCP-style Auto-Discovery, Dynamic Leases, and Master Directory.
"""
import logging
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from core.dhcp_discovery import dhcp_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


class AllocateLeaseRequest(BaseModel):
    raw_id: str
    entity_type: str
    node_id: str
    branch_name: str = "main"
    category: str = "general"
    custom_name: Optional[str] = None
    ttl_s: Optional[float] = 86400.0


@router.post("/allocate")
async def allocate_dhcp_lease(req: AllocateLeaseRequest):
    """Allocate a new DHCP dynamic lease and canonical alias."""
    lease = dhcp_engine.allocate_lease(
        raw_id=req.raw_id,
        entity_type=req.entity_type,
        node_id=req.node_id,
        branch_name=req.branch_name,
        category=req.category,
        custom_name=req.custom_name,
        ttl_s=req.ttl_s,
    )
    return {
        "status": "allocated",
        "lease_id": lease.lease_id,
        "canonical_alias": lease.canonical_alias,
        "assigned_ip": lease.assigned_ip,
        "raw_id": lease.raw_id,
        "node_id": lease.node_id,
        "branch_name": lease.branch_name,
        "expires_at": lease.expires_at,
    }


@router.get("/resolve")
async def resolve_alias(alias: str):
    """Resolve a human-readable canonical alias to connection coordinates."""
    res = dhcp_engine.resolve_alias(alias)
    if not res:
        raise HTTPException(status_code=404, detail=f"Alias '{alias}' not found or expired")
    return res


@router.get("/search")
async def search_directory(q: str, limit: int = 50):
    """Search the global directory by alias, node, branch, or entity ID."""
    return {"query": q, "results": dhcp_engine.search_directory(query=q, limit=limit)}


@router.get("/catalog")
async def get_node_catalog():
    """Retrieve full catalog of connected nodes and allocated aliases."""
    return dhcp_engine.get_node_catalog()
