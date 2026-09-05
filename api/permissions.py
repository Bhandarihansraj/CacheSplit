"""
api/permissions.py
FastAPI router for Cross-Node Permission Governance and Owner Review Workflows.
"""
import logging
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from core.node_permissions import node_permission_manager, AccessLevel, PermissionStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


class CreatePermissionRequest(BaseModel):
    requester_id: str
    requester_node: str
    target_node: str
    target_branch: str = "main"
    access_level: str = "READ"
    reason: str = "Cross-node collaborative operation"


class ReviewPermissionRequest(BaseModel):
    request_id: str
    reviewer_id: str
    decision: str  # "APPROVED" or "REJECTED"
    lease_duration_s: float = 7200.0


@router.post("/request")
async def create_permission_request(req: CreatePermissionRequest):
    """Submit a cross-node access request to a target node owner."""
    try:
        level = AccessLevel(req.access_level.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid access level '{req.access_level}'. Allowed: READ, WRITE, MERGE, ADMIN")

    permission = node_permission_manager.request_access(
        requester_id=req.requester_id,
        requester_node=req.requester_node,
        target_node=req.target_node,
        target_branch=req.target_branch,
        access_level=level,
        reason=req.reason,
    )
    return {
        "status": "success",
        "request": {
            "request_id": permission.request_id,
            "requester_id": permission.requester_id,
            "requester_node": permission.requester_node,
            "target_node": permission.target_node,
            "target_branch": permission.target_branch,
            "access_level": permission.access_level.value,
            "status": permission.status.value,
            "reason": permission.reason,
            "is_active": permission.is_active(),
        }
    }


@router.post("/review")
async def review_permission_request(req: ReviewPermissionRequest):
    """Node owner approves or rejects a pending cross-node access request."""
    try:
        updated = node_permission_manager.review_request(
            request_id=req.request_id,
            reviewer_id=req.reviewer_id,
            decision=req.decision,
            lease_duration_s=req.lease_duration_s,
        )
        return {
            "status": "reviewed",
            "request": {
                "request_id": updated.request_id,
                "status": updated.status.value,
                "reviewer_id": updated.reviewer_id,
                "lease_expires_at": updated.lease_expires_at,
                "is_active": updated.is_active(),
            }
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/list")
async def list_permission_requests(
    target_node: Optional[str] = None,
    status: Optional[str] = None,
):
    """List all cross-node permission requests with optional filters."""
    p_status = None
    if status:
        try:
            p_status = PermissionStatus(status.upper())
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status filter '{status}'")

    requests = node_permission_manager.list_requests(target_node=target_node, status=p_status)
    return {"total": len(requests), "requests": requests}


@router.get("/check")
async def check_access_permission(
    requester_id: str,
    requester_node: str,
    target_node: str,
    target_branch: str = "main",
    required_level: str = "READ",
):
    """Verify if active valid lease allows access to target node/branch."""
    try:
        level = AccessLevel(required_level.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid access level '{required_level}'")

    has_perm = node_permission_manager.check_permission(
        requester_id=requester_id,
        requester_node=requester_node,
        target_node=target_node,
        target_branch=target_branch,
        required_level=level,
    )
    return {
        "allowed": has_perm,
        "requester_id": requester_id,
        "requester_node": requester_node,
        "target_node": target_node,
        "target_branch": target_branch,
        "required_level": level.value,
    }
