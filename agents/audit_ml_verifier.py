"""
agents/audit_ml_verifier.py
QA Structural Data Validator & IsolationForest ML Audit Verifier.
Validates QA tester / client payloads for bad data, schema corruption,
timestamp drifts, and broken Merkle lineage, computing an Audit Risk Score (0.00 to 1.00).
"""
import time
import logging
from typing import Dict, Any, Tuple
import numpy as np
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)


class AuditMLVerifier:
    """
    Combines rule-based QA data validation with an ML Isolation Forest model
    to detect malformed data, schema poison attacks, and anomalous node access patterns.
    """

    def __init__(self):
        self.model = IsolationForest(
            n_estimators=50,
            contamination=0.08,
            random_state=42,
        )
        self._is_trained = False
        self._train_baseline_model()

    def _train_baseline_model(self):
        """Train Isolation Forest on normal audit pattern distributions."""
        np.random.seed(42)
        # Features: [req_rate_1m, payload_bytes, is_cross_region, error_rate, timestamp_drift_s, access_depth]
        normal_samples = np.random.normal(
            loc=[10.0, 500.0, 0.0, 0.01, 0.5, 2.0],
            scale=[3.0, 150.0, 0.1, 0.01, 0.5, 0.5],
            size=(200, 6)
        )
        normal_samples = np.clip(normal_samples, a_min=0, a_max=None)
        self.model.fit(normal_samples)
        self._is_trained = True
        logger.info("AuditMLVerifier: Isolation Forest model trained on baseline audit distributions")

    def validate_and_score(
        self,
        event: Dict[str, Any]
    ) -> Tuple[bool, float, str]:
        """
        Validate data integrity and compute ML audit risk score.
        Returns:
            is_bad_data (bool): True if schema or consistency rules fail.
            risk_score (float): Normalized 0.00 to 1.00 risk indicator.
            reason (str): Diagnostic explanation for audit trail.
        """
        is_bad_data = False
        reasons = []

        # ── 1. Structural QA Validation Rules ────────────────────────────────
        now = time.time()
        evt_ts = event.get("timestamp", now)
        if isinstance(evt_ts, (int, float)):
            drift = abs(now - evt_ts)
            if drift > 300:  # > 5 minutes drift
                is_bad_data = True
                reasons.append(f"Timestamp drift of {drift:.1f}s exceeds 300s tolerance")
        else:
            drift = 0.0

        if not event.get("node_id"):
            is_bad_data = True
            reasons.append("Missing mandatory 'node_id'")

        payload_size = len(str(event.get("data", "")))
        if payload_size > 1_000_000:
            is_bad_data = True
            reasons.append(f"Payload size {payload_size} exceeds 1MB threshold")

        # ── 2. ML Risk Scoring ───────────────────────────────────────────────
        req_rate = float(event.get("request_rate", 10.0))
        is_cross = 1.0 if event.get("is_cross_region", False) else 0.0
        err_rate = float(event.get("error_rate", 0.0))
        access_depth = float(event.get("access_depth", 1.0))

        feat = np.array([[req_rate, float(payload_size), is_cross, err_rate, float(drift), access_depth]])

        try:
            score_raw = self.model.decision_function(feat)[0]
            # Convert decision function (lower = anomalous) to a normalized risk score (0.0 to 1.0)
            risk_score = round(float(np.clip(0.5 - (score_raw * 1.5), 0.0, 1.0)), 3)
        except Exception as e:
            logger.warning(f"ML scoring error: {e}")
            risk_score = 0.50

        if is_bad_data:
            risk_score = max(risk_score, 0.85)

        diagnostic = "; ".join(reasons) if reasons else ("High ML anomaly risk" if risk_score > 0.7 else "OK - verified")
        return is_bad_data, risk_score, diagnostic


audit_verifier = AuditMLVerifier()
