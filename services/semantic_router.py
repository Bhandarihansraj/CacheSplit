"""
services/semantic_router.py
Semantic Router & Query Interceptor for CacheSplit v4.
Provides cache hit/miss evaluation, access metrics, and multi-region index orchestration.
"""

import time
import logging
from typing import Optional, Any
from dataclasses import dataclass, field

from core.semantic_cache import (
    SemanticCacheIndex,
    VectorEntry,
    MetricType,
)
from core.semantic_invalidation import (
    SemanticNeighborhoodInvalidator,
    SemanticInvalidationResult,
)

logger = logging.getLogger(__name__)


@dataclass
class SemanticStats:
    total_queries: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    stale_hits_prevented: int = 0
    total_latency_ms: float = 0.0
    total_entries: int = 0

    @property
    def hit_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return round(self.cache_hits / self.total_queries, 4)

    @property
    def avg_latency_ms(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return round(self.total_latency_ms / self.total_queries, 3)


class SemanticRouter:
    """
    Central router for semantic vector queries and neighborhood invalidation.
    """

    def __init__(self, hit_threshold: float = 0.90):
        self.hit_threshold = hit_threshold
        self.index = SemanticCacheIndex("global_semantic_cache")
        self.invalidator = SemanticNeighborhoodInvalidator(self.index)
        self.stats = SemanticStats()

    def store(
        self,
        key: str,
        vector: list[float],
        data: dict,
        metadata: Optional[dict] = None,
        version: int = 1,
    ) -> VectorEntry:
        entry = VectorEntry(
            key=key,
            vector=vector,
            data=data,
            metadata=metadata or {},
            version=version,
            state="FRESH",
        )
        self.index.upsert(entry)
        self.stats.total_entries = self.index.count
        return entry

    def query(
        self,
        query_vector: list[float],
        k: int = 5,
        metric: MetricType = "cosine",
        filters: Optional[dict[str, Any]] = None,
        use_mmr: bool = False,
        mmr_lambda: float = 0.5,
    ) -> dict[str, Any]:
        start = time.perf_counter()

        matches = self.index.query(
            query_vector=query_vector,
            k=k,
            metric=metric,
            min_similarity=0.0,
            filters=filters,
            only_fresh=True,
            use_mmr=use_mmr,
            mmr_lambda=mmr_lambda,
        )

        latency_ms = (time.perf_counter() - start) * 1000.0

        self.stats.total_queries += 1
        self.stats.total_latency_ms += latency_ms

        is_hit = False
        top_match = matches[0] if matches else None

        if top_match and top_match["similarity"] >= self.hit_threshold:
            is_hit = True
            self.stats.cache_hits += 1
        else:
            self.stats.cache_misses += 1

        # Format output entries (serialize entry to dict)
        formatted_matches = []
        for m in matches:
            e: VectorEntry = m["entry"]
            formatted_matches.append(
                {
                    "key": m["key"],
                    "similarity": m["similarity"],
                    "state": m["state"],
                    "version": m["version"],
                    "data": e.data,
                    "metadata": e.metadata,
                }
            )

        return {
            "status": "CACHE_HIT" if is_hit else "CACHE_MISS",
            "hit_threshold": self.hit_threshold,
            "latency_ms": round(latency_ms, 3),
            "match_count": len(formatted_matches),
            "top_match": formatted_matches[0] if formatted_matches else None,
            "results": formatted_matches,
        }

    def invalidate_neighborhood(
        self,
        pivot_vector: list[float],
        radius_similarity: float = 0.85,
        target_key: Optional[str] = None,
        metric: MetricType = "cosine",
    ) -> SemanticInvalidationResult:
        result = self.invalidator.invalidate_neighborhood(
            pivot_vector=pivot_vector,
            radius_similarity=radius_similarity,
            target_key=target_key,
            metric=metric,
        )
        return result

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_entries": self.index.count,
            "dimension": self.index.dimension,
            "total_queries": self.stats.total_queries,
            "cache_hits": self.stats.cache_hits,
            "cache_misses": self.stats.cache_misses,
            "hit_rate": self.stats.hit_rate,
            "avg_latency_ms": self.stats.avg_latency_ms,
            "hit_threshold": self.hit_threshold,
        }

    def seed_demo_data(self) -> int:
        """Seed sample high-dimensional semantic data for testing and UI demo."""
        demo_items = [
            (
                "doc:rag:auth_jwt",
                [0.92, 0.15, 0.05, 0.22, 0.81, 0.11, 0.04, 0.33],
                {"title": "JWT Authentication Guide", "content": "How to verify and rotate RSA keys"},
                {"domain": "security", "region": "us-east-1", "access_level": 3, "tags": ["auth", "jwt"]},
            ),
            (
                "doc:rag:auth_oauth",
                [0.89, 0.18, 0.06, 0.25, 0.78, 0.14, 0.05, 0.30],
                {"title": "OAuth2 PKCE Flow", "content": "Authorization code exchange for mobile & SPA"},
                {"domain": "security", "region": "us-east-1", "access_level": 2, "tags": ["auth", "oauth"]},
            ),
            (
                "doc:rag:billing_stripe",
                [0.10, 0.88, 0.75, 0.12, 0.15, 0.09, 0.90, 0.08],
                {"title": "Stripe Webhook Processing", "content": "Idempotent payment webhook handler"},
                {"domain": "billing", "region": "eu-west-1", "access_level": 5, "tags": ["payment", "stripe"]},
            ),
            (
                "doc:rag:billing_invoicing",
                [0.12, 0.85, 0.79, 0.15, 0.18, 0.11, 0.88, 0.07],
                {"title": "Automated Tax Invoice Generation", "content": "VAT and GST calculations per region"},
                {"domain": "billing", "region": "eu-west-1", "access_level": 4, "tags": ["invoice", "tax"]},
            ),
            (
                "doc:rag:cache_invalidation",
                [0.35, 0.20, 0.15, 0.94, 0.40, 0.88, 0.12, 0.25],
                {"title": "Stampede Recovery in Distributed Caching", "content": "Token bucket bounding and single-flight coalescing"},
                {"domain": "infra", "region": "asia-south-1", "access_level": 1, "tags": ["cache", "stampede"]},
            ),
        ]

        for key, vec, data, meta in demo_items:
            self.store(key=key, vector=vec, data=data, metadata=meta, version=1)

        return len(demo_items)


# Global singleton router instance
global_semantic_router = SemanticRouter()
global_semantic_router.seed_demo_data()
