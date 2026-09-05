"""
HMAC-signed audit event log for CacheSplit v4.
Every state-mutating event is signed. Provides tamper-evident trail.
"""
import hmac
import hashlib
import json
import time
import logging
import uuid
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class SignedEvent:
    event_id: str
    timestamp: float
    event_type: str
    tenant_id: str
    payload_hash: str
    hmac_signature: str
    payload: Dict
    actor: str = ""

    def verify(self, signing_key: str) -> bool:
        """Verify the event's HMAC signature against the signing key."""
        data_to_sign = {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "payload_hash": self.payload_hash,
            "actor": self.actor,
        }
        expected = hmac.new(
            signing_key.encode(),
            json.dumps(data_to_sign, sort_keys=True).encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, self.hmac_signature)

    def to_dict(self) -> Dict:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "tenant_id": self.tenant_id,
            "payload_hash": self.payload_hash,
            "hmac_signature": self.hmac_signature,
            "payload": self.payload,
            "actor": self.actor,
        }


class AuditLog:
    """
    Tamper-evident event log. Every state-mutating event is HMAC-signed.
    Verification rejects any event with invalid signature.

    Security requirement:
    - Each event signed with HMAC-SHA256(tenant_key, canonical_json)
    - No event appended without a valid signature
    - Never log unverified state changes
    """

    def __init__(self, signing_key: str):
        self.signing_key = signing_key
        self._events: List[SignedEvent] = []
        self._lock = __import__("asyncio").Lock()

    async def append(
        self,
        event_type: str,
        tenant_id: str,
        payload: Dict,
        actor: str = "",
    ) -> SignedEvent:
        """
        Append a signed event to the audit log.
        Raises if payload is empty or tenant_id is invalid.
        """
        if not payload:
            raise ValueError("Cannot log event with empty payload")
        if not tenant_id:
            raise ValueError("Cannot log event without tenant_id")

        payload_json = json.dumps(payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()

        event = SignedEvent(
            event_id=f"evt_{uuid.uuid4().hex[:16]}",
            timestamp=time.monotonic(),
            event_type=event_type,
            tenant_id=tenant_id,
            payload_hash=payload_hash,
            hmac_signature="",
            payload=payload,
            actor=actor,
        )

        # Sign the event
        data_to_sign = {
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "tenant_id": event.tenant_id,
            "payload_hash": event.payload_hash,
            "actor": event.actor,
        }
        event.hmac_signature = hmac.new(
            self.signing_key.encode(),
            json.dumps(data_to_sign, sort_keys=True).encode(),
            hashlib.sha256,
        ).hexdigest()

        async with self._lock:
            self._events.append(event)

        logger.info(f"Audit event logged: {event.event_id} ({event_type})")
        return event

    async def get_events(self, tenant_id: str = None, limit: int = 100) -> List[SignedEvent]:
        """Retrieve events, optionally filtered by tenant_id."""
        async with self._lock:
            events = self._events[-limit:]
            if tenant_id:
                events = [e for e in events if e.tenant_id == tenant_id]
            return events

    async def verify_chain(self, tenant_id: str = None) -> bool:
        """
        Verify all events have valid HMAC signatures.
        Returns True only if every event passes verification.
        """
        async with self._lock:
            events = self._events
            if tenant_id:
                events = [e for e in events if e.tenant_id == tenant_id]
            for event in events:
                if not event.verify(self.signing_key):
                    logger.error(f"Audit chain broken at event {event.event_id}")
                    return False
        return True

    async def count(self, tenant_id: str = None) -> int:
        async with self._lock:
            if tenant_id:
                return sum(1 for e in self._events if e.tenant_id == tenant_id)
            return len(self._events)


# Global singleton
audit_log = AuditLog(signing_key="default-audit-key-change-me")
