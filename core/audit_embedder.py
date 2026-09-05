"""
core/audit_embedder.py
Deterministic Dense Feature & Text Embedder for CacheSplit Audit Trail.
Converts structured audit events and natural language audit queries into
normalized dense embedding vectors for fast cosine similarity search.
"""

import re
import math
import hashlib
from typing import Optional, Any

# Vocabulary dimension for text projection
EMBEDDING_DIM = 32

# Key domain keywords for semantic concept projection
CONCEPT_BUCKETS = {
    # Security & Anomalies
    "poison": 0, "injection": 0, "corrupt": 0, "tamper": 0, "malformed": 0,
    "unauthorized": 1, "anomaly": 1, "flag": 1, "quarantine": 1, "risk": 1,
    "cross_region": 2, "cross": 2, "region": 2, "drift": 2, "leak": 2,
    # High Traffic & Stampede
    "stampede": 3, "burst": 3, "rate": 3, "overload": 3, "traffic": 3, "velocity": 3,
    # Rollback & Branch ops
    "rollback": 4, "restore": 4, "merge": 4, "conflict": 4, "diff": 4, "branch": 4,
    # Domains
    "payment": 5, "billing": 5, "stripe": 5, "invoice": 5, "tax": 5,
    "auth": 6, "jwt": 6, "oauth": 6, "token": 6, "session": 6,
    "telemetry": 7, "cardiology": 7, "patient": 7, "health": 7, "trial": 7,
    "cache": 8, "invalidation": 8, "stale": 8, "repair": 8, "coalesce": 8,
}


def _normalize(vector: list[float]) -> list[float]:
    mag = math.sqrt(sum(x * x for x in vector))
    if mag == 0.0:
        return [0.0] * len(vector)
    return [round(x / mag, 5) for x in vector]


class AuditEmbedder:
    """
    Encodes audit events and natural language queries into 32-dimensional normalized vectors.
    """

    def __init__(self, dim: int = EMBEDDING_DIM):
        self.dim = dim

    def embed_text(self, text: str) -> list[float]:
        """
        Embeds a natural language query string into a dense vector.
        """
        vec = [0.0] * self.dim
        if not text:
            return vec

        tokens = re.findall(r"\w+", text.lower())
        if not tokens:
            return vec

        for token in tokens:
            # 1. Check concept buckets (indices 0..8)
            if token in CONCEPT_BUCKETS:
                bucket = CONCEPT_BUCKETS[token]
                vec[bucket] += 2.0

            # 2. Hash-based semantic distributed projection for arbitrary words (indices 9..31)
            h = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16)
            slot = 9 + (h % (self.dim - 9))
            sign = 1.0 if (h % 2 == 0) else -1.0
            vec[slot] += sign * 1.0

        return _normalize(vec)

    def embed_event(self, event: dict[str, Any]) -> list[float]:
        """
        Embeds a structured audit log event into a dense vector.
        """
        vec = [0.0] * self.dim

        # 1. Structural features
        event_type = str(event.get("event_type", "")).lower()
        node_id = str(event.get("node_id", "")).lower()
        branch = str(event.get("branch_name", "")).lower()
        dev_id = str(event.get("developer_id", "")).lower()
        diag = str(event.get("diagnostic", "")).lower()
        is_bad = bool(event.get("is_bad_data", False))
        is_cross = bool(event.get("is_cross_region", False))
        risk_score = float(event.get("risk_score", 0.0) or 0.0)
        req_rate = float(event.get("request_rate", 0.0) or 0.0)

        # Map concept weights
        combined_text = f"{event_type} {node_id} {branch} {dev_id} {diag}"
        text_vec = self.embed_text(combined_text)

        for i in range(self.dim):
            vec[i] += text_vec[i] * 1.5

        # Feature overrides for precise clustering
        if is_bad or "poison" in event_type or "corrupt" in diag:
            vec[0] += 3.0  # Poison / Bad data bucket

        if risk_score > 0.6 or "unauthorized" in event_type:
            vec[1] += 2.5 * risk_score  # Anomaly / Risk bucket

        if is_cross or "cross" in event_type:
            vec[2] += 2.5  # Cross-region bucket

        if req_rate > 50.0 or "stampede" in event_type:
            vec[3] += min(req_rate / 20.0, 3.0)  # High traffic bucket

        if "rollback" in event_type or "restore" in event_type or "branch" in event_type:
            vec[4] += 2.5  # Branch / Rollback bucket

        return _normalize(vec)
