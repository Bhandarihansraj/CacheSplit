"""
Short-lived JWT authentication and scope enforcement for CacheSplit v4.
Every route validates token and extracts tenant_id from JWT.
"""
import time
import logging
import hashlib
import hmac
import json
import uuid
from typing import Optional, Dict, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TokenPayload:
    identity: str
    tenant_id: str
    permissions: List[str]
    exp: float
    iat: float
    scope: str


class AuthError(Exception):
    pass


class TokenExpired(AuthError):
    pass


class TokenInvalid(AuthError):
    pass


class AuthManager:
    """
    Issue short-lived JWT tokens scoped to tenant + permissions.
    Every route validates token and extracts tenant_id from JWT.

    Security requirement:
    - JWT expiry <= 300 seconds.
    - Refresh tokens rotate.
    - Token scope includes tenant_id + explicit permissions.
    - Validate signature on every request.

    Must not:
    - Issue tokens with expiry > 300s.
    - Allow token reuse after refresh.
    - Accept tenant_id from query param — always from JWT.
    """

    TOKEN_TTL_SECONDS = 300
    REFRESH_TTL_SECONDS = 86400

    def __init__(self, signing_key: str):
        self.signing_key = signing_key
        self._issued_tokens: Dict[str, TokenPayload] = {}
        self._refreshed_tokens: Dict[str, str] = {}

    def _create_token(self, payload: TokenPayload) -> str:
        """Create a signed JWT-like token."""
        header = {"alg": "HS256", "typ": "JWT", "jti": uuid.uuid4().hex}
        header_b64 = self._b64(json.dumps(header, sort_keys=True))
        payload_b64 = self._b64(json.dumps(payload.__dict__, sort_keys=True))
        signing_input = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            self.signing_key.encode(), signing_input.encode(), hashlib.sha256
        ).hexdigest()
        return f"{signing_input}.{signature}"

    def _b64(self, data: str) -> str:
        import base64
        return base64.urlsafe_b64encode(data.encode()).rstrip(b"=").decode()

    def issue(self, identity: str, tenant_id: str,
              permissions: List[str] = None) -> tuple[str, str]:
        """
        Issue access and refresh tokens.
        Returns (access_token, refresh_token).
        Access token expires in 300 seconds.
        """
        now = time.monotonic()
        access_payload = TokenPayload(
            identity=identity,
            tenant_id=tenant_id,
            permissions=permissions or ["read"],
            exp=now + self.TOKEN_TTL_SECONDS,
            iat=now,
            scope=f"tenant:{tenant_id}",
        )
        refresh_payload = TokenPayload(
            identity=identity,
            tenant_id=tenant_id,
            permissions=permissions or ["read"],
            exp=now + self.REFRESH_TTL_SECONDS,
            iat=now,
            scope=f"refresh:tenant:{tenant_id}",
        )

        access_token = self._create_token(access_payload)
        refresh_token = self._create_token(refresh_payload)

        self._issued_tokens[access_token] = access_payload
        self._issued_tokens[refresh_token] = refresh_payload

        logger.info(f"Tokens issued for {identity} tenant={tenant_id}")
        return access_token, refresh_token

    def validate(self, token: str) -> TokenPayload:
        """
        Validate a token. Returns TokenPayload if valid.
        Raises TokenExpired or TokenInvalid on failure.
        Must be called on every request.
        """
        if token not in self._issued_tokens:
            raise TokenInvalid("Token not found in issued tokens")

        payload = self._issued_tokens[token]

        if time.monotonic() > payload.exp:
            del self._issued_tokens[token]
            raise TokenExpired(f"Token expired for {payload.identity}")

        return payload

    def refresh(self, refresh_token: str) -> tuple[str, str]:
        """
        Rotate refresh token. Old access token invalidated.
        Returns (new_access_token, new_refresh_token).

        Must not:
        - Allow token reuse after refresh.
        """
        try:
            payload = self.validate(refresh_token)
        except TokenExpired:
            raise TokenInvalid("Refresh token expired")

        # Invalidate old tokens for this identity+tenant
        old_tokens = [
            t for t, p in self._issued_tokens.items()
            if p.identity == payload.identity and p.tenant_id == payload.tenant_id
        ]
        for t in old_tokens:
            del self._issued_tokens[t]

        new_access, new_refresh = self.issue(
            payload.identity, payload.tenant_id, payload.permissions
        )
        logger.info(f"Tokens refreshed for {payload.identity}")
        return new_access, new_refresh

    async def extract_tenant_id(self, token: str) -> str:
        """Extract tenant_id from a validated token. Used by routes."""
        payload = self.validate(token)
        return payload.tenant_id

    async def check_permission(self, token: str, permission: str) -> bool:
        """Check if the token's identity has the required permission."""
        payload = self.validate(token)
        return permission in payload.permissions or "*" in payload.permissions


# Global singleton
auth_manager = AuthManager(signing_key="default-auth-key-change-me")
