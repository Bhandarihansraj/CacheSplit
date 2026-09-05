"""
Core tenant model and scoping enforcement.
Every operation must carry a valid tenant_id.
"""
from pydantic import BaseModel, Field, validator
from typing import List, Dict, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TenantRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class Tenant(BaseModel):
    tenant_id: str
    identity: str
    region: str
    role: TenantRole = TenantRole.VIEWER
    permissions: List[str] = Field(default_factory=list)

    @validator("tenant_id")
    def tenant_id_must_not_be_empty(cls, v):
        if not v or len(v) < 3:
            raise ValueError("tenant_id must be at least 3 characters")
        return v

    @validator("identity")
    def identity_must_not_be_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("identity must not be empty")
        return v.strip()


class TenantRegistry:
    """
    Registry of all known tenants. All API operations resolve
    tenant_id from this registry. Never accepts tenant_id from
    query params or URL paths.
    """

    def __init__(self):
        self._tenants: Dict[str, Tenant] = {}
        self._lock = __import__("asyncio").Lock()

    async def register(self, tenant_id: str, identity: str, region: str,
                       role: TenantRole = TenantRole.OPERATOR,
                       permissions: List[str] = None) -> Tenant:
        tenant = Tenant(
            tenant_id=tenant_id, identity=identity,
            region=region, role=role,
            permissions=permissions or ["read", "write"],
        )
        self._tenants[tenant_id] = tenant
        logger.info(f"Tenant registered: {tenant_id} ({identity})")
        return tenant

    async def get(self, tenant_id: str) -> Optional[Tenant]:
        return self._tenants.get(tenant_id)

    async def get_all(self) -> List[Tenant]:
        return list(self._tenants.values())

    async def has_permission(self, tenant_id: str, permission: str) -> bool:
        tenant = await self.get(tenant_id)
        if not tenant:
            return False
        return permission in tenant.permissions or "*" in tenant.permissions

    async def is_valid(self, tenant_id: str) -> bool:
        return tenant_id in self._tenants


# Global singleton
tenant_registry = TenantRegistry()
