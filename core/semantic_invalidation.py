"""
core/semantic_invalidation.py
Semantic Neighborhood Invalidation for CacheSplit.
Calculates vector similarity neighborhoods and broadcasts batch invalidation
events to mark related cached fragments as STALE.
"""

import logging
from typing import Optional
from dataclasses import dataclass, field

from core.semantic_cache import SemanticCacheIndex, compute_similarity, MetricType

logger = logging.getLogger(__name__)


@dataclass
class SemanticInvalidationResult:
    target_key: Optional[str]
    invalidated_keys: list[str]
    similarity_scores: dict[str, float]
    radius_threshold: float
    total_evaluated: int


class SemanticNeighborhoodInvalidator:
    """
    Scans a SemanticCacheIndex and identifies all records falling within a
    semantic distance radius from a pivot vector, invalidating them in batch.
    """

    def __init__(self, index: SemanticCacheIndex):
        self.index = index

    def invalidate_neighborhood(
        self,
        pivot_vector: list[float],
        radius_similarity: float = 0.85,
        target_key: Optional[str] = None,
        metric: MetricType = "cosine",
    ) -> SemanticInvalidationResult:
        """
        Marks all entries with similarity >= radius_similarity as STALE.
        """
        invalidated: list[str] = []
        scores: dict[str, float] = {}
        total = 0

        for key, entry in list(self.index._entries.items()):
            total += 1
            sim = compute_similarity(pivot_vector, entry.vector, metric=metric)
            if sim >= radius_similarity:
                entry.state = "STALE"
                invalidated.append(key)
                scores[key] = round(sim, 4)
                logger.info(
                    f"SemanticInvalidator: marked STALE key={key} sim={sim:.4f} (>= {radius_similarity})"
                )

        return SemanticInvalidationResult(
            target_key=target_key,
            invalidated_keys=invalidated,
            similarity_scores=scores,
            radius_threshold=radius_similarity,
            total_evaluated=total,
        )
