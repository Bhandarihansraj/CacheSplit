"""
core/node_permissions.py
Cross-Origin & Cross-Node Permission Governance for CacheSplit v4.
Enforces Node Owner Access Control: when a developer on Node A requests access
to branches/entities on Node B, a permission request is generated and reviewed by the Node Owner.
"""
import time
import uuid
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class PermissionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class AccessLevel(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    MERGE = "MERGE"
    ADMIN = "ADMIN"


@dataclass
class PermissionRequest:
    request_id: str
    requester_id: str
    requester_node: str
    target_node: str
    target_branch: str
    access_level: AccessLevel
    reason: str
    status: PermissionStatus = PermissionStatus.PENDING
    reviewer_id: Optional[str] = None
    lease_expires_at: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    reviewed_at: Optional[float] = None

    def is_active(self) -> bool:
        if self.status != PermissionStatus.APPROVED:
            return False
        if self.lease_expires_at and time.time() > self.lease_expires_at:
            return False
        return True


class NodePermissionManager:
    """
    Manages node-level and branch-level permissions across clusters.
    Enforces that node owners approve cross-node operations.
    """

    def __init__(self):
        # request_id -> PermissionRequest
        self._requests: Dict[str, PermissionRequest] = {}
        # Node ID -> Node Owner ID
        self._node_owners: Dict[str, str] = {
            "us-east-1": "owner-us-east",
            "eu-west-1": "owner-eu-west",
            "asia-south-1": "owner-asia-south",
        }

    def set_node_owner(self, node_id: str, owner_id: str):
        self._node_owners[node_id] = owner_id

    def get_node_owner(self, node_id: str) -> str:
        return self._node_owners.get(node_id, "admin-system")

    def request_access(
        self,
        requester_id: str,
        requester_node: str,
        target_node: str,
        target_branch: str = "main",
        access_level: AccessLevel = AccessLevel.READ,
        reason: str = "Cross-node collaborative operation",
    ) -> PermissionRequest:
        """Create a new cross-node permission request."""
        # Auto-approve if requester is the node owner or same node
        is_auto = (requester_node == target_node) or (requester_id == self.get_node_owner(target_node))
        status = PermissionStatus.APPROVED if is_auto else PermissionStatus.PENDING

        req_id = f"perm-req-{uuid.uuid4().hex[:8]}"
        expires = (time.time() + 7200.0) if is_auto else None  # 2h default lease if auto

        req = PermissionRequest(
            request_id=req_id,
            requester_id=requester_id,
            requester_node=requester_node,
            target_node=target_node,
            target_branch=target_branch,
            access_level=access_level,
            reason=reason,
            status=status,
            reviewer_id="system" if is_auto else None,
            lease_expires_at=expires,
            reviewed_at=time.time() if is_auto else None,
        )

        self._requests[req_id] = req
        logger.info(f"PermissionRequest [{req_id}]: {requester_id}@{requester_node} -> {target_node}:{target_branch} [{access_level}] ({status})")
        return req

    def review_request(
        self,
        request_id: str,
        reviewer_id: str,
        decision: str,  # "APPROVED" or "REJECTED"
        lease_duration_s: float = 7200.0,
    ) -> PermissionRequest:
        """Node owner review of a pending permission request."""
        if request_id not in self._requests:
            raise KeyError(f"Permission request '{request_id}' not found")

        req = self._requests[request_id]
        if decision.upper() == "APPROVED":
            req.status = PermissionStatus.APPROVED
            req.reviewer_id = reviewer_id
            req.lease_expires_at = time.time() + lease_duration_s
            req.reviewed_at = time.time()
        else:
            req.status = PermissionStatus.REJECTED
            req.reviewer_id = reviewer_id
            req.reviewed_at = time.time()

        logger.info(f"PermissionRequest [{request_id}] reviewed by {reviewer_id}: {req.status}")
        return req

    def check_permission(
        self,
        requester_id: str,
        requester_node: str,
        target_node: str,
        target_branch: str = "main",
        required_level: AccessLevel = AccessLevel.READ,
    ) -> bool:
        """Check if an active approved lease exists for this cross-node action."""
        if requester_node == target_node or requester_id == self.get_node_owner(target_node):
            return True

        for req in self._requests.values():
            if (
                req.requester_id == requester_id
                and req.target_node == target_node
                and (req.target_branch == target_branch or req.target_branch == "*")
                and req.is_active()
            ):
                return True

        return False

    def list_requests(
        self,
        target_node: Optional[str] = None,
        status: Optional[PermissionStatus] = None,
    ) -> List[Dict[str, Any]]:
        """List permission requests with optional filtering."""
        results = []
        for req in self._requests.values():
            if target_node and req.target_node != target_node:
                continue
            if status and req.status != status:
                continue
            results.append({
                "request_id": req.request_id,
                "requester_id": req.requester_id,
                "requester_node": req.requester_node,
                "target_node": req.target_node,
                "target_branch": req.target_branch,
                "access_level": req.access_level.value,
                "reason": req.reason,
                "status": req.status.value,
                "reviewer_id": req.reviewer_id,
                "is_active": req.is_active(),
                "expires_in_s": round(max(0, (req.lease_expires_at or 0) - time.time()), 1) if req.lease_expires_at else None,
                "created_at": req.created_at,
            })
        return results


node_permission_manager = NodePermissionManager()
