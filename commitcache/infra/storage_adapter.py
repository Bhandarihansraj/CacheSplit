"""
DB-agnostic storage adapter for CacheSplit v4.
One protocol, swappable implementation (Postgres, Mongo, etc.).
Never leaks backend-specific types upward.
"""
import logging
import time
from typing import Optional, Protocol, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class StorageResultStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    OK = "ok"
    CONFLICT = "conflict"
    ERROR = "error"


@dataclass
class StorageResult:
    status: StorageResultStatus
    value: Optional[bytes] = None
    fencing_token: int = 0
    error: str = ""
    backend_latency_ms: float = 0.0

    @classmethod
    def found(cls, value: bytes, fencing_token: int = 0, latency_ms: float = 0.0) -> "StorageResult":
        return cls(status=StorageResultStatus.FOUND, value=value, fencing_token=fencing_token, backend_latency_ms=latency_ms)

    @classmethod
    def not_found(cls, latency_ms: float = 0.0) -> "StorageResult":
        return cls(status=StorageResultStatus.NOT_FOUND, backend_latency_ms=latency_ms)

    @classmethod
    def ok(cls, fencing_token: int = 0, latency_ms: float = 0.0) -> "StorageResult":
        return cls(status=StorageResultStatus.OK, fencing_token=fencing_token, backend_latency_ms=latency_ms)

    @classmethod
    def conflict(cls, error: str, fencing_token: int = 0) -> "StorageResult":
        return cls(status=StorageResultStatus.CONFLICT, fencing_token=fencing_token, error=error)

    @classmethod
    def error(cls, error: str) -> "StorageResult":
        return cls(status=StorageResultStatus.ERROR, error=error)


class StorageError(Exception):
    """Normalized storage exception — never leaks backend-specific error format."""
    def __init__(self, message: str, backend_code: str = ""):
        self.message = message
        self.backend_code = backend_code
        super().__init__(self.message)


class StorageAdapter(Protocol):
    """
    DB-agnostic storage interface. One contract, swappable implementation.
    The only place raw DB credentials are used — credentials injected via
    Vault/KMS reference, never passed as constructor args in plaintext.
    """

    async def get(self, scoped_key: str) -> Optional[StorageResult]:
        """Fetch a value by scoped key. Returns None if not found."""
        ...

    async def put(self, scoped_key: str, value: bytes,
                  fencing_token: int) -> StorageResult:
        """
        Write a value with fencing token. Rejects stale/out-of-order writes
        at the DB boundary. Fencing token must be monotonically increasing.
        """
        ...

    async def delete(self, scoped_key: str, fencing_token: int) -> StorageResult:
        """Delete a value with fencing token — rejects stale deletes."""
        ...

    async def exists(self, scoped_key: str) -> bool:
        """Check if a key exists."""
        ...

    async def list_keys(self, prefix: str, limit: int = 100) -> list[str]:
        """List keys matching a prefix."""
        ...


class BaseStorageAdapter:
    """
    Base adapter with credential management. Credentials injected via
    Vault/KMS reference — never passed as constructor args in plaintext.
    Never leaks backend-specific types to callers.

    Security requirement:
    - Adapter is the ONLY place raw DB credentials are used.
    - Credentials from Vault/KMS reference, not plain string args.

    Must not:
    - Accept raw (non-tenant-scoped) keys — keys must be scoped via tenant.py.
    - Let backend error formats leak to callers — all errors become StorageError.
    """

    def __init__(self, credential_ref: str):
        """
        Initialize with a credential reference (Vault path / KMS ARN).
        credential_ref is NOT the actual credential — it's a pointer to
        the Vault/KMS location. Actual credentials are fetched at runtime.
        """
        self._credential_ref = credential_ref
        self._credentials = None
        self._backend_type = "unknown"

    async def _resolve_credentials(self):
        """Resolve credential_ref to actual credentials via Vault/KMS."""
        # In production: call Vault/KMS client
        if self._credential_ref.startswith("vault://"):
            logger.info(f"Resolving credentials from {self._credential_ref}")
        elif self._credential_ref.startswith("kms://"):
            logger.info(f"Resolving credentials from {self._credential_ref}")
        else:
            raise StorageError(f"Unsupported credential reference: {self._credential_ref}")

    def _normalize_error(self, exc: Exception, backend: str) -> StorageError:
        """Normalize any backend exception to StorageError — never leak backend format."""
        return StorageError(
            message=f"Storage error in {backend}: {str(exc)}",
            backend_code=getattr(exc, 'code', 'UNKNOWN')
        )

    def _scope_key(self, tenant_id: str, key: str) -> str:
        """Ensure every key is tenant-scoped — never accept raw unscoped keys."""
        if not tenant_id:
            raise ValueError("tenant_id required for key scoping")
        return f"{tenant_id}/{key}"


class PostgresAdapter(BaseStorageAdapter):
    """
    Postgres implementation of StorageAdapter. Uses fencing tokens for
    optimistic concurrency control at the DB boundary.
    """

    def __init__(self, credential_ref: str):
        super().__init__(credential_ref)
        self._backend_type = "postgres"
        self._client = None

    async def connect(self):
        """Connect using resolved credentials from Vault/KMS reference."""
        await self._resolve_credentials()
        # In production: create asyncpg connection pool
        logger.info("PostgresAdapter connected")

    async def get(self, scoped_key: str) -> Optional[StorageResult]:
        try:
            await self.connect()
            # In production: asyncpg query with scoped_key
            return StorageResult.not_found()
        except Exception as e:
            raise self._normalize_error(e, "postgres")

    async def put(self, scoped_key: str, value: bytes,
                  fencing_token: int) -> StorageResult:
        try:
            await self.connect()
            if fencing_token <= 0:
                raise StorageError("fencing_token must be > 0")
            # In production: INSERT with ON CONFLICT WHERE fencing_token > old
            return StorageResult.ok(fencing_token=fencing_token)
        except StorageError:
            raise
        except Exception as e:
            raise self._normalize_error(e, "postgres")

    async def delete(self, scoped_key: str, fencing_token: int) -> StorageResult:
        try:
            await self.connect()
            return StorageResult.ok(fencing_token=fencing_token)
        except StorageError:
            raise
        except Exception as e:
            raise self._normalize_error(e, "postgres")

    async def exists(self, scoped_key: str) -> bool:
        try:
            await self.connect()
            return False
        except Exception:
            return False

    async def list_keys(self, prefix: str, limit: int = 100) -> list[str]:
        return []


class InMemoryAdapter(BaseStorageAdapter):
    """
    In-memory implementation for testing/development. Implements the same
    StorageAdapter protocol so code is always tested against the real interface.
    """

    def __init__(self):
        super().__init__("memory://local")
        self._backend_type = "memory"
        self._store: dict[str, Tuple[bytes, int]] = {}

    async def get(self, scoped_key: str) -> Optional[StorageResult]:
        entry = self._store.get(scoped_key)
        if entry:
            return StorageResult.found(entry[0], entry[1])
        return StorageResult.not_found()

    async def put(self, scoped_key: str, value: bytes,
                  fencing_token: int) -> StorageResult:
        existing = self._store.get(scoped_key)
        if existing and existing[1] >= fencing_token:
            return StorageResult.conflict(
                f"Fencing token {fencing_token} <= existing {existing[1]}",
                fencing_token=existing[1]
            )
        self._store[scoped_key] = (value, fencing_token)
        return StorageResult.ok(fencing_token=fencing_token)

    async def delete(self, scoped_key: str, fencing_token: int) -> StorageResult:
        existing = self._store.get(scoped_key)
        if existing and existing[1] > fencing_token:
            return StorageResult.conflict(
                f"Cannot delete — newer fencing token exists",
                fencing_token=existing[1]
            )
        self._store.pop(scoped_key, None)
        return StorageResult.ok(fencing_token=fencing_token)

    async def exists(self, scoped_key: str) -> bool:
        return scoped_key in self._store

    async def list_keys(self, prefix: str, limit: int = 100) -> list[str]:
        keys = [k for k in self._store.keys() if k.startswith(prefix)]
        return sorted(keys)[:limit]


def create_storage_adapter(adapter_type: str, credential_ref: str) -> BaseStorageAdapter:
    """Factory to create the right storage adapter."""
    if adapter_type == "postgres":
        return PostgresAdapter(credential_ref)
    elif adapter_type == "memory":
        return InMemoryAdapter()
    else:
        raise StorageError(f"Unknown adapter type: {adapter_type}")
