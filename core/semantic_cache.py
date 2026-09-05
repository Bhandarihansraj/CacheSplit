"""
core/semantic_cache.py
AgentDB-inspired Semantic Vector Cache Engine for CacheSplit.
Provides in-memory vector storage, similarity metrics (Cosine, Euclidean, Dot Product),
hybrid metadata filtering ($eq, $gte, $lte, $in, $contains), and Maximal Marginal Relevance (MMR).
"""

import math
import time
import logging
from typing import Literal, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MetricType = Literal["cosine", "euclidean", "dot"]
CacheState = Literal["FRESH", "STALE", "REPAIRING"]


@dataclass
class VectorEntry:
    key: str
    vector: list[float]
    data: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    version: int = 1
    state: CacheState = "FRESH"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def _dot_product(v1: list[float], v2: list[float]) -> float:
    return sum(a * b for a, b in zip(v1, v2))


def _magnitude(v: list[float]) -> float:
    return math.sqrt(sum(a * a for a in v))


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    mag1 = _magnitude(v1)
    mag2 = _magnitude(v2)
    if mag1 == 0.0 or mag2 == 0.0:
        return 0.0
    return _dot_product(v1, v2) / (mag1 * mag2)


def _euclidean_distance(v1: list[float], v2: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


def compute_similarity(v1: list[float], v2: list[float], metric: MetricType = "cosine") -> float:
    """
    Computes similarity score where higher is more similar.
    - cosine: [-1.0, 1.0]
    - dot: [-inf, inf]
    - euclidean: converted to similarity via 1 / (1 + distance) in [0, 1]
    """
    if len(v1) != len(v2):
        raise ValueError(f"Vector dimension mismatch: {len(v1)} vs {len(v2)}")

    if metric == "cosine":
        return _cosine_similarity(v1, v2)
    elif metric == "dot":
        return _dot_product(v1, v2)
    elif metric == "euclidean":
        dist = _euclidean_distance(v1, v2)
        return 1.0 / (1.0 + dist)
    else:
        raise ValueError(f"Unsupported metric: {metric}")


def matches_filter(metadata: dict, filters: Optional[dict[str, Any]]) -> bool:
    """
    Evaluates metadata against a filter query.
    Supports exact match or operators: $eq, $gte, $lte, $in, $contains.
    """
    if not filters:
        return True

    for field, rule in filters.items():
        val = metadata.get(field)
        if isinstance(rule, dict):
            for op, target in rule.items():
                if op == "$eq" and val != target:
                    return False
                elif op == "$ne" and val == target:
                    return False
                elif op == "$gte" and (val is None or val < target):
                    return False
                elif op == "$lte" and (val is None or val > target):
                    return False
                elif op == "$gt" and (val is None or val <= target):
                    return False
                elif op == "$lt" and (val is None or val >= target):
                    return False
                elif op == "$in" and val not in target:
                    return False
                elif op == "$contains":
                    if isinstance(val, list):
                        if target not in val:
                            return False
                    elif isinstance(val, str):
                        if str(target) not in val:
                            return False
                    else:
                        return False
        else:
            if val != rule:
                return False
    return True


class SemanticCacheIndex:
    """
    In-memory Semantic Vector Index with hybrid metadata filtering and MMR diversification.
    """

    def __init__(self, name: str = "default"):
        self.name = name
        self._entries: dict[str, VectorEntry] = {}
        self._dimension: Optional[int] = None

    @property
    def count(self) -> int:
        return len(self._entries)

    @property
    def dimension(self) -> Optional[int]:
        return self._dimension

    def upsert(self, entry: VectorEntry) -> None:
        if self._dimension is None:
            self._dimension = len(entry.vector)
        elif len(entry.vector) != self._dimension:
            raise ValueError(
                f"Dimension mismatch: expected {self._dimension}, got {len(entry.vector)}"
            )

        entry.updated_at = time.time()
        self._entries[entry.key] = entry

    def get(self, key: str) -> Optional[VectorEntry]:
        return self._entries.get(key)

    def delete(self, key: str) -> bool:
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    def query(
        self,
        query_vector: list[float],
        k: int = 5,
        metric: MetricType = "cosine",
        min_similarity: float = 0.0,
        filters: Optional[dict[str, Any]] = None,
        only_fresh: bool = True,
        use_mmr: bool = False,
        mmr_lambda: float = 0.5,
    ) -> list[dict[str, Any]]:
        """
        Executes hybrid semantic search over indexed entries.
        Returns a list of dicts with: key, similarity, entry, and state.
        """
        if not self._entries:
            return []

        if len(query_vector) != self._dimension:
            raise ValueError(
                f"Query vector dimension {len(query_vector)} does not match index {self._dimension}"
            )

        # 1. Candidate selection & metadata filtering
        candidates: list[tuple[str, VectorEntry, float]] = []
        for key, entry in self._entries.items():
            if only_fresh and entry.state != "FRESH":
                continue

            if not matches_filter(entry.metadata, filters):
                continue

            sim = compute_similarity(query_vector, entry.vector, metric=metric)
            if sim >= min_similarity:
                candidates.append((key, entry, sim))

        if not candidates:
            return []

        # 2. Standard Top-K Ranking
        if not use_mmr:
            candidates.sort(key=lambda x: x[2], reverse=True)
            top_k = candidates[:k]
            return [
                {
                    "key": key,
                    "similarity": round(sim, 4),
                    "entry": entry,
                    "state": entry.state,
                    "version": entry.version,
                }
                for key, entry, sim in top_k
            ]

        # 3. Maximal Marginal Relevance (MMR) Diversification
        selected: list[tuple[str, VectorEntry, float]] = []
        unselected = list(candidates)

        while len(selected) < min(k, len(candidates)) and unselected:
            if not selected:
                best_idx = max(range(len(unselected)), key=lambda i: unselected[i][2])
                selected.append(unselected.pop(best_idx))
            else:
                best_idx = -1
                best_mmr = -float("inf")

                for i, (u_key, u_entry, u_sim) in enumerate(unselected):
                    max_sim_to_selected = max(
                        compute_similarity(u_entry.vector, s_entry.vector, metric=metric)
                        for _, s_entry, _ in selected
                    )
                    mmr_score = (mmr_lambda * u_sim) - ((1.0 - mmr_lambda) * max_sim_to_selected)

                    if mmr_score > best_mmr:
                        best_mmr = mmr_score
                        best_idx = i

                if best_idx >= 0:
                    selected.append(unselected.pop(best_idx))
                else:
                    break

        return [
            {
                "key": key,
                "similarity": round(sim, 4),
                "entry": entry,
                "state": entry.state,
                "version": entry.version,
            }
            for key, entry, sim in selected
        ]

    def clear(self) -> None:
        self._entries.clear()
        self._dimension = None
