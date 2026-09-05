"""
core/scalar_quantizer.py
Dynamic Int8 Scalar Quantization (SQ8) Engine for CacheSplit.
Compresses float32 vector embeddings to 8-bit integers (4x memory reduction)
with per-vector dynamic scaling, zero copy calibration, and fast asymmetric dot product estimation.
"""

import math
from typing import List, Tuple, Dict, Any


class ScalarQuantizer:
    """
    Int8 Uniform Scalar Quantizer with asymmetric reconstruction and direct distance computation.
    Compresses 32-D or N-D float32 vectors to int8 arrays + scale/min offset coefficients.
    """

    def __init__(self, dim: int, num_bits: int = 8):
        self.dim = dim
        self.num_bits = num_bits
        self.qmax = (1 << num_bits) - 1  # 255 for 8-bit
        self.qmin = 0

    def quantize_vector(self, vec: List[float]) -> Tuple[bytes, float, float]:
        """
        Quantizes a single float vector into 8-bit unsigned byte representation with scale and offset.
        Returns: (quantized_bytes, min_val, scale)
        """
        if len(vec) != self.dim:
            raise ValueError(f"Vector dimension mismatch: expected {self.dim}, got {len(vec)}")

        min_val = min(vec)
        max_val = max(vec)
        val_range = max_val - min_val

        if val_range <= 1e-9:
            # Constant vector
            scale = 1.0
            q_bytes = bytes([0] * self.dim)
            return q_bytes, min_val, scale

        scale = val_range / self.qmax
        # Quantize: q = round((x - min_val) / scale)
        q_list = []
        for x in vec:
            q = int(round((x - min_val) / scale))
            q = max(0, min(self.qmax, q))
            q_list.append(q)

        return bytes(q_list), float(min_val), float(scale)

    def dequantize_vector(self, q_bytes: bytes, min_val: float, scale: float) -> List[float]:
        """
        Reconstructs float vector from quantized bytes.
        """
        return [float(min_val + b * scale) for b in q_bytes]

    def asymmetric_dot_product(
        self,
        query_vec: List[float],
        target_q_bytes: bytes,
        target_min: float,
        target_scale: float,
    ) -> float:
        """
        Computes fast dot product directly between a float query vector and quantized target bytes
        without full float vector decompression.
        Formula: sum(q_i * (min_val + t_i * scale)) = min_val * sum(q_i) + scale * sum(q_i * t_i)
        """
        query_sum = 0.0
        weighted_dot = 0.0
        for q, t in zip(query_vec, target_q_bytes):
            query_sum += q
            weighted_dot += q * t

        return target_min * query_sum + target_scale * weighted_dot

    def asymmetric_cosine_similarity(
        self,
        query_vec: List[float],
        target_q_bytes: bytes,
        target_min: float,
        target_scale: float,
        target_norm: float,
    ) -> float:
        """
        Computes fast cosine similarity against quantized representation.
        """
        dot = self.asymmetric_dot_product(query_vec, target_q_bytes, target_min, target_scale)
        q_norm = math.sqrt(sum(x * x for x in query_vec))
        if q_norm <= 1e-9 or target_norm <= 1e-9:
            return 0.0
        return max(-1.0, min(1.0, dot / (q_norm * target_norm)))

    def compute_compression_stats(self, raw_vector_count: int) -> Dict[str, Any]:
        """
        Calculates exact memory savings for given vector volume.
        """
        raw_bytes = raw_vector_count * self.dim * 4  # 4 bytes per float32
        # Quantized: 1 byte per dimension + 8 bytes (2 floats for min and scale) + 4 bytes for norm
        quantized_bytes = raw_vector_count * (self.dim + 12)
        ratio = raw_bytes / max(1, quantized_bytes)
        savings_pct = (1.0 - (quantized_bytes / max(1, raw_bytes))) * 100.0

        return {
            "dimension": self.dim,
            "vector_count": raw_vector_count,
            "raw_memory_bytes": raw_bytes,
            "quantized_memory_bytes": quantized_bytes,
            "compression_ratio": round(ratio, 2),
            "memory_reduction_pct": round(savings_pct, 1),
        }
