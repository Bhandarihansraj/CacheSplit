"""
core/redlock.py
Distributed Redlock Mutex Engine for CacheSplit.
Provides cluster-wide atomic mutual exclusion, safe token-based lock release,
auto-lease expiration safety, and lock renewal mechanisms.
"""
from __future__ import annotations
import threading
import time
import uuid
from typing import Any, Dict, List, Optional


class LockInfo:
    def __init__(self, resource: str, owner_token: str, ttl_ms: int):
        self.resource = resource
        self.owner_token = owner_token
        self.ttl_ms = ttl_ms
        self.acquired_at = time.time()
        self.expires_at = self.acquired_at + (ttl_ms / 1000.0)

    def is_expired(self, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.time()
        return now >= self.expires_at

    def remaining_ttl_ms(self, now: Optional[float] = None) -> int:
        if now is None:
            now = time.time()
        rem = (self.expires_at - now) * 1000.0
        return max(0, int(rem))

    def extend(self, extension_ms: int) -> None:
        self.expires_at = time.time() + (extension_ms / 1000.0)
        self.ttl_ms = extension_ms

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource": self.resource,
            "owner_token": self.owner_token,
            "ttl_ms": self.ttl_ms,
            "remaining_ttl_ms": self.remaining_ttl_ms(),
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "is_expired": self.is_expired(),
        }


class RedlockManager:
    """
    Thread-safe Distributed Redlock Mutex Coordinator.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._locks: Dict[str, LockInfo] = {}
        self._total_acquired: int = 0
        self._total_released: int = 0
        self._total_expired: int = 0
        self._total_conflicts: int = 0

    def _purge_if_expired(self, resource: str) -> bool:
        """Removes lock if lease time expired."""
        if resource in self._locks:
            if self._locks[resource].is_expired():
                del self._locks[resource]
                self._total_expired += 1
                return True
        return False

    def acquire(
        self,
        resource: str,
        ttl_ms: int = 5000,
        owner_token: Optional[str] = None,
        retry_times: int = 0,
        retry_delay_ms: int = 50,
    ) -> Optional[str]:
        """
        Acquire a distributed lock on `resource` with lease `ttl_ms`.
        Returns owner_token on success, or None if lock could not be acquired.
        """
        if not owner_token:
            owner_token = str(uuid.uuid4())

        attempts = 0
        while attempts <= retry_times:
            with self._lock:
                self._purge_if_expired(resource)
                if resource not in self._locks:
                    self._locks[resource] = LockInfo(resource, owner_token, ttl_ms)
                    self._total_acquired += 1
                    return owner_token
                else:
                    self._total_conflicts += 1

            if attempts < retry_times:
                time.sleep(retry_delay_ms / 1000.0)
            attempts += 1

        return None

    def release(self, resource: str, owner_token: str) -> bool:
        """
        Atomically release a distributed lock if and only if owner_token matches.
        Prevents clients from accidentally releasing an expired lock that was re-acquired by another client.
        """
        with self._lock:
            self._purge_if_expired(resource)
            if resource not in self._locks:
                return False

            lock_info = self._locks[resource]
            if lock_info.owner_token == owner_token:
                del self._locks[resource]
                self._total_released += 1
                return True
            return False

    def renew(self, resource: str, owner_token: str, extension_ms: int = 5000) -> bool:
        """
        Extend lock lease by extension_ms if owner_token is the valid holder.
        """
        with self._lock:
            self._purge_if_expired(resource)
            if resource not in self._locks:
                return False

            lock_info = self._locks[resource]
            if lock_info.owner_token == owner_token:
                lock_info.extend(extension_ms)
                return True
            return False

    def is_locked(self, resource: str) -> bool:
        """Returns True if resource is currently locked and not expired."""
        with self._lock:
            self._purge_if_expired(resource)
            return resource in self._locks

    def get_lock_info(self, resource: str) -> Optional[Dict[str, Any]]:
        """Returns detailed lock info or None."""
        with self._lock:
            self._purge_if_expired(resource)
            if resource in self._locks:
                return self._locks[resource].to_dict()
            return None

    def list_active_locks(self) -> List[Dict[str, Any]]:
        """Returns all active, non-expired locks."""
        with self._lock:
            active = []
            for res in list(self._locks.keys()):
                if not self._purge_if_expired(res):
                    active.append(self._locks[res].to_dict())
            return active

    def stats(self) -> Dict[str, Any]:
        """Returns lock manager metrics."""
        with self._lock:
            return {
                "active_locks": len(self.list_active_locks()),
                "total_acquired": self._total_acquired,
                "total_released": self._total_released,
                "total_expired": self._total_expired,
                "total_conflicts": self._total_conflicts,
            }


# Global singleton instance
redlock_manager = RedlockManager()
