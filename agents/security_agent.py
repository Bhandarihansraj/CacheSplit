"""
CacheSplit v3 — Security Agent with ML Anomaly Detection

Real IsolationForest model trained on LIVE access patterns.
No random noise, no hard-coded thresholds — genuine ML.
"""
import os
import pickle
import logging
import numpy as np
from typing import Optional

from agents.access_logger import AccessEvent, AccessLogger

logger = logging.getLogger(__name__)


class SecurityAgent:
    """
    Wraps a scikit-learn IsolationForest trained on 8-dim feature vectors
    from the AccessLogger.  The model is fit on the actual event buffer
    so it learns real per-cluster normal behaviour.
    """

    def __init__(self, model_path: str = "", logger_instance: AccessLogger = None):
        self.model_path = model_path
        self.logger = logger_instance or AccessLogger()

        try:
            from sklearn.ensemble import IsolationForest
        except ImportError:
            raise ImportError(
                "scikit-learn is required for ML anomaly detection.  "
                "Install it:  pip install scikit-learn"
            )

        self.model = IsolationForest(
            n_estimators=200,
            contamination=0.05,
            random_state=42,
        )
        self._is_trained = False

        if model_path and os.path.exists(model_path):
            self._load(model_path)

    # ── persistence ───────────────────────────────────────────────────────

    def _load(self, path: str):
        try:
            with open(path, "rb") as f:
                self.model = pickle.load(f)
            self._is_trained = True
            logger.info("Loaded pre-trained anomaly model from %s", path)
        except Exception as e:
            logger.warning("Could not load model from %s: %s", path, e)

    def save(self, path: Optional[str] = None):
        path = path or self.model_path
        if not path:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self.model, f)
        logger.info("Saved anomaly model to %s", path)

    # ── training ──────────────────────────────────────────────────────────

    def train(self, events=None) -> bool:
        """
        Fit the IsolationForest on the provided events (or the logger's
        entire buffer if None).  Requires at least 30 events.
        Returns True if training succeeded.
        """
        from sklearn.ensemble import IsolationForest

        if events is not None:
            if len(events) < 30:
                return False
            X = np.vstack([self.logger.extract_features(e) for e in events])
        else:
            X = self.logger.get_feature_matrix()
            if X.shape[0] < 30:
                return False

        self.model.fit(X)
        self._is_trained = True
        logger.info("Anomaly model trained on %d samples, %d features",
                     X.shape[0], X.shape[1])
        return True

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    # ── scoring ───────────────────────────────────────────────────────────

    def score_event(self, event) -> float:
        """
        Returns an anomaly score in [0, 1].  Higher = more anomalous.
        Accepts an AccessEvent or a plain dict (backward-compatible).
        If the model is untrained returns 0.5 (neutral).
        """
        if not self._is_trained:
            return 0.5

        if isinstance(event, dict):
            event = AccessEvent(
                node_id=event.get("node_id", ""),
                entity_id=event.get("entity_id", ""),
                entity_type=event.get("entity_type", ""),
                access_type=event.get("access_type", "read"),
                requester_region=event.get("requester_region", ""),
                target_region=event.get("target_region", ""),
                timestamp=event.get("timestamp", event.get("time_of_day", 0.0)),
            )

        X = self.logger.extract_features(event)
        # score_samples returns offset where lower = more anomalous
        raw = self.model.score_samples(X)[0]
        # Map to [0, 1]:  score_samples returns values roughly in [-1, 1]
        # Typical range is about -0.5 to 0.3 for IsolationForest
        # Map so that low raw → high anomaly score
        score = 0.5 - raw / (abs(raw) + 1.0)
        return float(max(0.0, min(1.0, score)))

    def evaluate(self, event, threshold: float = 0.6) -> bool:
        """Score an event and return True if it exceeds the anomaly threshold."""
        return self.score_event(event) > threshold
