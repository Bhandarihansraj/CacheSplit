"""
Priority model for CacheSplit v4.
Replaces raw divergence_magnitude sorting with learned priority score.
Predicts which stale keys are likely to be read next (hot-key prediction).
"""
import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TenantFeatureVector:
    """Historical access features used for priority scoring."""
    access_freq_1h: float = 0.0
    tenant_tier: str = "standard"
    last_repair_age_ms: float = 0.0
    tenant_id: str = ""
    entity_type: str = ""


@dataclass
class PriorityResult:
    """Result of priority scoring with fallback info."""
    priority_score: float
    used_fallback: bool = False
    fallback_reason: str = ""
    raw_divergence: float = 0.0


class PriorityModel:
    """
    Learned priority score for stale keys — predicts which are likely
    to be read next (hot-key prediction) instead of just "biggest gap first."

    Security requirement:
    - Model output is advisory only. It can reorder the queue but
      must still pass through lease.py and audit_log.py like any
      other repair.
    - The model itself must NEVER get direct write access to storage.

    Must not:
    - Use raw per-key access patterns across tenants as shared
      training signal without aggregation — that's a cross-tenant
      data leak through the model.
    - Let a model failure (exception, NaN score) crash the queue.
      Fall back to raw divergence sort on any model error.
    """

    TIER_MULTIPLIER: dict = {
        "enterprise": 1.5,
        "standard": 1.0,
        "basic": 0.5,
    }

    def __init__(self):
        self._model = None
        self._fallback_count = 0
        self._total_score_count = 0
        self._initialized = False

    def _load_model(self):
        """Load or initialize the scoring model."""
        # In production: load from model registry / pickle file
        self._initialized = True
        logger.info("Priority model loaded/initialized")

    def _validate_features(self, features: TenantFeatureVector) -> bool:
        """Validate feature vector — never use raw cross-tenant data."""
        if not features.tenant_id:
            return False
        if features.access_freq_1h < 0:
            return False
        return True

    def _aggregate_features(self, features: TenantFeatureVector) -> dict:
        """
        Aggregate features per-tenant for training signal.
        Never passes raw per-key access patterns across tenants.
        """
        return {
            "tenant_id": features.tenant_id,
            "access_freq_1h": features.access_freq_1h,
            "tier": features.tenant_tier,
            "last_repair_age_ms": features.last_repair_age_ms,
        }

    def score(self, divergence_magnitude: float,
               features: TenantFeatureVector) -> PriorityResult:
        """
        Score a stale key for repair priority.
        Returns PriorityResult with score and fallback info.

        Security: Model never gets storage access. Score is advisory
        — lease and audit gates still apply downstream.
        """
        self._total_score_count += 1

        if not self._initialized:
            self._load_model()

        if not self._validate_features(features):
            logger.warning(f"Invalid features, using fallback")
            return self._fallback(divergence_magnitude, "invalid features")

        try:
            # Learned priority score — bounded 0.0–1.0
            priority_score = self._predict(features, divergence_magnitude)

            # Handle NaN/Inf — model must never produce these
            if math.isnan(priority_score) or math.isinf(priority_score):
                raise ValueError(f"Model produced invalid score: {priority_score}")

            # Clamp to valid range
            priority_score = max(0.0, min(1.0, priority_score))

            logger.debug(f"Priority score: {priority_score:.4f}")
            return PriorityResult(
                priority_score=priority_score,
                used_fallback=False,
                raw_divergence=divergence_magnitude,
            )

        except Exception as e:
            self._fallback_count += 1
            logger.warning(
                f"Priority model error: {e}. Using fallback to divergence sort."
            )
            return self._fallback(divergence_magnitude, str(e))

    def _predict(self, features: TenantFeatureVector,
                  divergence: float) -> float:
        """
        Internal prediction — in production loads a trained model.
        Here uses a bounded heuristic that respects per-tenant aggregation.
        """
        tier_mult = self.TIER_MULTIPLIER.get(features.tenant_tier, 1.0)
        freq_score = min(features.access_freq_1h / 100.0, 1.0)
        age_score = min(features.last_repair_age_ms / 60000.0, 1.0)
        divergence_score = min(divergence / 100.0, 1.0)

        # Weighted combination — all bounded to [0, 1]
        score = (0.3 * freq_score + 0.3 * age_score + 0.4 * divergence_score) * tier_mult
        return max(0.0, min(1.0, score))

    def _fallback(self, divergence: float, reason: str) -> PriorityResult:
        """Safe fallback to raw divergence sort — never raises."""
        logger.warning(f"Model fallback: {reason}")
        return PriorityResult(
            priority_score=min(divergence / 100.0, 1.0),
            used_fallback=True,
            fallback_reason=reason,
            raw_divergence=divergence,
        )

    @property
    def fallback_rate(self) -> float:
        """Rate of model fallbacks (0.0 = no fallbacks, 1.0 = always fallback)."""
        return self._fallback_count / max(self._total_score_count, 1)


# Global singleton
priority_model = PriorityModel()
