"""
core/audit_vector_index.py
In-Memory Vector Index with Relational Metadata Filtering for CacheSplit Audit Events.
Combines Cosine similarity search with structured audit query predicates.
"""

import time
import logging
from typing import Optional, Any
from dataclasses import dataclass, field

from core.semantic_cache import _cosine_similarity
from core.audit_embedder import AuditEmbedder

logger = logging.getLogger(__name__)


@dataclass
class AuditVectorRecord:
    event_id: int
    vector: list[float]
    metadata: dict[str, Any]
    indexed_at: float = field(default_factory=time.time)


class AuditVectorIndex:
    """
    Vector index specialized for compliance and security audit trail search.
    """

    def __init__(self):
        self._records: dict[int, AuditVectorRecord] = {}
        self.embedder = AuditEmbedder()

    @property
    def count(self) -> int:
        return len(self._records)

    def upsert(self, event_id: int, vector: list[float], metadata: dict[str, Any]) -> None:
        self._records[event_id] = AuditVectorRecord(
            event_id=event_id,
            vector=vector,
            metadata=metadata,
        )

    def index_event(self, event: dict[str, Any]) -> int:
        event_id = event.get("id") or int(time.time() * 1000)
        vec = self.embedder.embed_event(event)
        self.upsert(event_id=event_id, vector=vec, metadata=dict(event))
        return event_id

    def index_batch(self, events: list[dict[str, Any]]) -> int:
        count = 0
        for e in events:
            self.index_event(e)
            count += 1
        return count

    def search(
        self,
        query_text: str,
        k: int = 25,
        filters: Optional[dict[str, Any]] = None,
        min_similarity: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Executes hybrid semantic search over audit events.
        """
        if not self._records:
            return []

        query_vec = self.embedder.embed_text(query_text)
        filters = filters or {}

        # Filter criteria
        req_node = filters.get("node_id")
        req_branch = filters.get("branch_name")
        req_bad = filters.get("is_bad_data")
        req_min_risk = filters.get("min_risk")
        req_dev = filters.get("developer_id")

        candidates: list[tuple[int, float, dict[str, Any]]] = []

        for event_id, rec in self._records.items():
            meta = rec.metadata

            # Apply structured relational filters
            if req_node and meta.get("node_id") != req_node:
                continue
            if req_branch and meta.get("branch_name") != req_branch:
                continue
            if req_bad is not None and bool(meta.get("is_bad_data")) != bool(req_bad):
                continue
            if req_min_risk is not None and float(meta.get("risk_score") or 0.0) < float(req_min_risk):
                continue
            if req_dev and meta.get("developer_id") != req_dev:
                continue

            sim = _cosine_similarity(query_vec, rec.vector)
            if sim >= min_similarity:
                candidates.append((event_id, sim, meta))

        # Sort by similarity descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        top_k = candidates[:k]

        return [
            {
                "event_id": event_id,
                "similarity": round(sim, 4),
                "event": meta,
            }
            for event_id, sim, meta in top_k
        ]

    def clear(self) -> None:
        self._records.clear()


# Global singleton instance
global_audit_vector_index = AuditVectorIndex()
