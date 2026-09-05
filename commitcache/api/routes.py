"""
Route enforcement for CacheSplit v4.
Every route requires tenant_id extracted from auth JWT — never from query param.
Wires together auth.py, rate_limit.py, tenant.py, and audit_log.py.
"""
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class RouteGuard:
    """
    Middleware that enforces tenant scoping on every API route.
    Extracts tenant_id from JWT (never query param).
    Validates lease for repair operations.
    Logs all mutations to audit_log.

    Security requirement:
    - All routes must go through auth.py for tenant_id extraction.
    - All repairs must go through lease.py.
    - All state changes must go through audit_log.py.
    """

    def __init__(self, auth_manager, rate_limiter, tenant_registry, lease_manager, audit_log):
        self.auth = auth_manager
        self.rate_limiter = rate_limiter
        self.tenant_registry = tenant_registry
        self.lease_manager = lease_manager
        self.audit = audit_log

    async def enforce(self, token: str, operation: str, tenant_id: str = None) -> Dict[str, Any]:
        """
        Enforce all security gates on a request.
        Returns validated context dict with tenant_id, identity, permissions.
        Raises AuthError, RateLimitExceeded, or LeaseError on failure.
        """
        # Gate 1: Validate JWT and extract tenant_id
        payload = self.auth.validate(token)
        resolved_tenant_id = tenant_id or payload.tenant_id

        # Verify tenant_id matches JWT
        if resolved_tenant_id != payload.tenant_id:
            raise ValueError("tenant_id mismatch: JWT and request differ")

        # Gate 2: Check tenant exists
        tenant = await self.tenant_registry.get(resolved_tenant_id)
        if not tenant:
            raise ValueError(f"Unknown tenant: {resolved_tenant_id}")

        # Gate 3: Rate limit per identity
        await self.rate_limiter.is_allowed(
            identity=payload.identity,
            tenant_id=resolved_tenant_id,
        )

        return {
            "tenant_id": resolved_tenant_id,
            "identity": payload.identity,
            "permissions": payload.permissions,
            "token_valid": True,
        }

    async def enforce_repair(self, token: str, lease_token: str,
                              key: str) -> Dict[str, Any]:
        """
        Enforce all gates for a repair operation.
        Validates JWT, lease, and tenant before proceeding.
        """
        context = await self.enforce(token, "repair")

        # Gate 4: Validate lease
        lease = await self.lease_manager.validate(lease_token)
        if not lease:
            raise ValueError("Invalid or expired lease_token — repair blocked")

        if lease.tenant_id != context["tenant_id"]:
            raise ValueError("Lease tenant_id does not match request tenant_id")

        # Gate 5: Log to audit
        await self.audit.append(
            event_type="REPAIR_INITIATED",
            tenant_id=context["tenant_id"],
            payload={"key": key, "lease_token": lease_token[:8] + "..."},
            actor=context["identity"],
        )

        context["lease_valid"] = True
        context["lease_key"] = key
        return context

    async def enforce_write(self, token: str, operation: str,
                            tenant_id: str = None) -> Dict[str, Any]:
        """
        Enforce gates for write/mutation operations.
        Validates JWT, rate limit, and logs to audit.
        """
        context = await self.enforce(token, operation, tenant_id)

        # Log state change to audit
        await self.audit.append(
            event_type=operation.upper(),
            tenant_id=context["tenant_id"],
            payload={"operation": operation},
            actor=context["identity"],
        )

        return context


def create_route_guard(auth, rate_limiter, tenant_registry, lease_manager, audit_log) -> RouteGuard:
    return RouteGuard(auth, rate_limiter, tenant_registry, lease_manager, audit_log)
