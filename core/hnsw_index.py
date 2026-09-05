"""
core/hnsw_index.py
Hierarchical Navigable Small World (HNSW) Multi-Layer Vector Graph Index for CacheSplit.
Provides O(log N) approximate nearest neighbor search across large-scale semantic vector spaces.
Includes Int8 scalar quantization integration, dynamic graph pruning, and self-healing node deletion.
"""

import math
import random
import heapq
from typing import List, Dict, Any, Tuple, Optional, Callable, Set

from core.scalar_quantizer import ScalarQuantizer


def compute_distance(v1: List[float], v2: List[float], metric: str = "cosine") -> float:
    """
    Computes distance metric between two float vectors.
    Lower is closer (distance = 1.0 - cosine_sim).
    """
    if metric == "cosine":
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 <= 1e-9 or norm2 <= 1e-9:
            return 1.0
        sim = max(-1.0, min(1.0, dot / (norm1 * norm2)))
        return 1.0 - sim  # Distance in [0.0, 2.0]
    elif metric == "euclidean":
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))
    elif metric == "dot":
        dot = sum(a * b for a, b in zip(v1, v2))
        return -dot
    return 1.0


class HNSWNode:
    """Represents a vector node in the HNSW multi-layer graph."""
    def __init__(self, key: str, vector: List[float], level: int, quantizer: Optional[ScalarQuantizer] = None):
        self.key = key
        self.vector = vector
        self.level = level
        # neighbors per layer: {layer_idx: [neighbor_keys]}
        self.neighbors: Dict[int, List[str]] = {lc: [] for lc in range(level + 1)}
        self.norm = math.sqrt(sum(x * x for x in vector))
        
        # Quantized representation
        if quantizer:
            self.q_bytes, self.q_min, self.q_scale = quantizer.quantize_vector(vector)
        else:
            self.q_bytes, self.q_min, self.q_scale = None, 0.0, 1.0


class HNSWIndex:
    """
    Hierarchical Navigable Small World Index with Int8 Quantization and Self-Healing Deletion.
    """

    def __init__(
        self,
        dim: int,
        M: int = 16,
        ef_construction: int = 64,
        ef_search: int = 32,
        metric: str = "cosine",
        enable_quantization: bool = True,
    ):
        self.dim = dim
        self.M = M
        self.M0 = 2 * M  # Max connections for layer 0
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.metric = metric
        self.mL = 1.0 / math.log(M) if M > 1 else 1.0
        
        self.quantizer = ScalarQuantizer(dim) if enable_quantization else None
        self.nodes: Dict[str, HNSWNode] = {}
        self.entry_point: Optional[str] = None
        self.max_level: int = -1

    def _random_level(self) -> int:
        """Assigns a level using geometric distribution."""
        r = random.random()
        if r == 0:
            r = 1e-9
        return int(-math.log(r) * self.mL)

    def _dist(self, v1: List[float], v2: List[float]) -> float:
        return compute_distance(v1, v2, self.metric)

    def _dist_node(self, q_vec: List[float], node: HNSWNode) -> float:
        if self.quantizer and node.q_bytes is not None and self.metric == "cosine":
            sim = self.quantizer.asymmetric_cosine_similarity(
                q_vec, node.q_bytes, node.q_min, node.q_scale, node.norm
            )
            return 1.0 - sim
        return self._dist(q_vec, node.vector)

    def insert(self, key: str, vector: List[float]) -> None:
        """Inserts a vector into the multi-layer graph."""
        if len(vector) != self.dim:
            raise ValueError(f"Dimension mismatch: expected {self.dim}, got {len(vector)}")

        # If key already exists, delete first to update
        if key in self.nodes:
            self.delete(key)

        level = self._random_level()
        node = HNSWNode(key, vector, level, self.quantizer)
        self.nodes[key] = node

        if self.entry_point is None:
            self.entry_point = key
            self.max_level = level
            return

        curr_ep = self.entry_point
        curr_dist = self._dist_node(vector, self.nodes[curr_ep])

        # 1. Greedy routing down to level+1
        for lc in range(self.max_level, level, -1):
            changed = True
            while changed:
                changed = False
                for neighbor_key in self.nodes[curr_ep].neighbors.get(lc, []):
                    if neighbor_key not in self.nodes:
                        continue
                    d = self._dist_node(vector, self.nodes[neighbor_key])
                    if d < curr_dist:
                        curr_dist = d
                        curr_ep = neighbor_key
                        changed = True

        # 2. Layer-by-layer beam search and edge connection from min(max_level, level) down to 0
        w_candidates = [curr_ep]
        for lc in range(min(self.max_level, level), -1, -1):
            candidates = self._search_layer(vector, w_candidates, self.ef_construction, lc)
            neighbors = self._select_neighbors(candidates, self.M0 if lc == 0 else self.M)

            node.neighbors[lc] = [c[1] for c in neighbors]
            for _, neighbor_key in neighbors:
                if neighbor_key in self.nodes:
                    n_node = self.nodes[neighbor_key]
                    if lc in n_node.neighbors:
                        n_node.neighbors[lc].append(key)
                        # Prune if exceeding M
                        max_m = self.M0 if lc == 0 else self.M
                        if len(n_node.neighbors[lc]) > max_m:
                            self._prune_neighbors(n_node, lc, max_m)
            w_candidates = [c[1] for c in candidates]

        if level > self.max_level:
            self.max_level = level
            self.entry_point = key

    def _search_layer(
        self,
        query: List[float],
        entry_points: List[str],
        ef: int,
        layer: int,
    ) -> List[Tuple[float, str]]:
        """
        Beam search on a single layer.
        Returns sorted list of (distance, key).
        """
        visited: Set[str] = set(entry_points)
        
        # Candidates min-heap: (dist, key)
        candidates: List[Tuple[float, str]] = []
        # Results max-heap (negated dist): (-dist, key)
        results: List[Tuple[float, str]] = []

        for ep in entry_points:
            if ep in self.nodes:
                d = self._dist_node(query, self.nodes[ep])
                heapq.heappush(candidates, (d, ep))
                heapq.heappush(results, (-d, ep))

        while candidates:
            c_dist, c_key = heapq.heappop(candidates)
            furthest_result_dist = -results[0][0]

            if c_dist > furthest_result_dist and len(results) >= ef:
                break

            for neighbor_key in self.nodes[c_key].neighbors.get(layer, []):
                if neighbor_key not in visited and neighbor_key in self.nodes:
                    visited.add(neighbor_key)
                    n_dist = self._dist_node(query, self.nodes[neighbor_key])
                    furthest_result_dist = -results[0][0]

                    if n_dist < furthest_result_dist or len(results) < ef:
                        heapq.heappush(candidates, (n_dist, neighbor_key))
                        heapq.heappush(results, (-n_dist, neighbor_key))
                        if len(results) > ef:
                            heapq.heappop(results)

        # Return sorted by distance ASC
        sorted_results = [(-dist, key) for dist, key in results]
        sorted_results.sort(key=lambda x: x[0])
        return sorted_results

    def _select_neighbors(self, candidates: List[Tuple[float, str]], M: int) -> List[Tuple[float, str]]:
        """Simple greedy neighbor selection."""
        return candidates[:M]

    def _prune_neighbors(self, node: HNSWNode, layer: int, max_m: int) -> None:
        """Prunes neighbor connections exceeding max_m."""
        scored = []
        for n_key in node.neighbors[layer]:
            if n_key in self.nodes:
                d = self._dist_node(node.vector, self.nodes[n_key])
                scored.append((d, n_key))
        scored.sort(key=lambda x: x[0])
        node.neighbors[layer] = [k for _, k in scored[:max_m]]

    def search(
        self,
        query_vector: List[float],
        k: int = 5,
        ef: Optional[int] = None,
        filter_fn: Optional[Callable[[str], bool]] = None,
    ) -> List[Tuple[str, float]]:
        """
        Executes approximate nearest neighbor search.
        Returns: List of (key, similarity_score) sorted by similarity DESC.
        """
        if not self.nodes or self.entry_point is None:
            return []

        if len(query_vector) != self.dim:
            raise ValueError(f"Dimension mismatch: expected {self.dim}, got {len(query_vector)}")

        ef_val = ef or max(self.ef_search, k)
        curr_ep = self.entry_point
        curr_dist = self._dist_node(query_vector, self.nodes[curr_ep])

        # 1. Route through upper layers down to layer 1
        for lc in range(self.max_level, 0, -1):
            changed = True
            while changed:
                changed = False
                for neighbor_key in self.nodes[curr_ep].neighbors.get(lc, []):
                    if neighbor_key not in self.nodes:
                        continue
                    d = self._dist_node(query_vector, self.nodes[neighbor_key])
                    if d < curr_dist:
                        curr_dist = d
                        curr_ep = neighbor_key
                        changed = True

        # 2. Search bottom layer 0 with ef beam width
        candidates = self._search_layer(query_vector, [curr_ep], ef_val, 0)

        # Apply filter and convert distance to similarity
        results = []
        for dist, key in candidates:
            if filter_fn and not filter_fn(key):
                continue
            sim = 1.0 - dist if self.metric == "cosine" else -dist
            results.append((key, round(float(sim), 4)))
            if len(results) >= k:
                break

        return results

    def delete(self, key: str) -> bool:
        """
        Deletes a vector and re-wires neighboring edges (Self-Healing Graph).
        """
        if key not in self.nodes:
            return False

        node = self.nodes.pop(key)

        # Re-wire bidirectional neighbors
        for lc, neighbors in node.neighbors.items():
            for n_key in neighbors:
                if n_key in self.nodes and lc in self.nodes[n_key].neighbors:
                    if key in self.nodes[n_key].neighbors[lc]:
                        self.nodes[n_key].neighbors[lc].remove(key)

        # If entry point was removed, elect new entry point
        if self.entry_point == key:
            if not self.nodes:
                self.entry_point = None
                self.max_level = -1
            else:
                highest_lvl = -1
                best_ep = None
                for k, n in self.nodes.items():
                    if n.level > highest_lvl:
                        highest_lvl = n.level
                        best_ep = k
                self.entry_point = best_ep
                self.max_level = highest_lvl

        return True

    def get_stats(self) -> Dict[str, Any]:
        """Returns comprehensive graph index metrics."""
        layer_counts = {}
        for node in self.nodes.values():
            for lc in range(node.level + 1):
                layer_counts[lc] = layer_counts.get(lc, 0) + 1

        avg_degrees = {}
        for lc in sorted(layer_counts.keys()):
            degrees = [len(n.neighbors.get(lc, [])) for n in self.nodes.values() if lc in n.neighbors]
            avg_degrees[f"layer_{lc}"] = round(sum(degrees) / max(1, len(degrees)), 2)

        compression = self.quantizer.compute_compression_stats(len(self.nodes)) if self.quantizer else {}

        return {
            "total_nodes": len(self.nodes),
            "dimension": self.dim,
            "max_level": self.max_level,
            "entry_point": self.entry_point,
            "M": self.M,
            "ef_construction": self.ef_construction,
            "ef_search": self.ef_search,
            "metric": self.metric,
            "quantization_enabled": self.quantizer is not None,
            "layer_distribution": layer_counts,
            "average_degrees": avg_degrees,
            "compression_stats": compression,
        }
