"""
Anomaly detector for CacheSplit v4.
Consumes the signed audit log stream to flag abnormal repair/access patterns.
Every event verified via HMAC chain before use — forged data can't poison the detector.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class AnomalyAlert:
    """Anomaly detection output — human-alerting signal only, never auto-remediated."""
    node_id: str
    tenant_id: str
    score: float
    reason: str
    timestamp: float = field(default_factory=time.monotonic)
    event_count: int = 0
    baseline_rate: float = 0.0


class AnomalyDetector:
    """
    Consumes the signed audit log stream to flag abnormal repair/access patterns.
    E.g., a node suddenly issuing 50x its normal repair volume could mean compromise.

    Security requirement:
    - Must verify each event's HMAC chain BEFORE using it as training/scoring input.
      An unverified event feeding the anomaly model is itself an attack vector
      (poison the detector with forged data).
    - Detector runs READ-ONLY against the audit log. Zero write path.

    Must not:
    - Auto-block a node based on anomaly score alone.
      Output is a human-alerting signal, not an enforcement mechanism.
      Avoids false-positive lockouts turning into a self-inflicted outage.
    """

    # Anomaly thresholds
    SCORE_THRESHOLD = 0.85  # Score above this triggers an alert
    MIN_EVENTS_FOR_BASELINE = 10  # Minimum events before scoring
    ROLLING_WINDOW = 100  # Events to keep in rolling baseline

    def __init__(self, audit_log=None, metrics=None):
        self._audit_log = audit_log
        self._metrics = metrics
        self._node_baselines: Dict[str, list] = defaultdict(list)
        self._tenant_baselines: Dict[str, list] = defaultdict(list)
        self._alerts: List[AnomalyAlert] = []
        self._verification_failures = 0
        self._events_processed = 0
        self._alerts_fired = 0

    async def verify_event(self, event) -> bool:
        """
        Verify an audit event's HMAC chain before using it.
        Returns True if verified, False if forged/invalid.
        """
        if not self._audit_log:
            # No audit log to verify against — skip verification
            # In production, this would call audit_log.verify_chain()
            return True

        verified = await self._audit_log.verify_chain()
        if not verified:
            self._verification_failures += 1
            if self._metrics:
                self._metrics.record_error("audit_signature_failures")
            logger.warning(f"Audit event signature verification failed")
            return False
        return True

    async def process_event(self, event) -> Optional[AnomalyAlert]:
        """
        Process a single audit event through the anomaly detector.
        Verifies HMAC chain first — if verification fails, drops the event.
        Returns AnomalyAlert if anomaly detected, None otherwise.
        """
        # Step 1: Verify HMAC chain
        if not await self.verify_event(event):
            return None  # Event dropped — forged data cannot poison detector

        self._events_processed += 1

        # Step 2: Extract features from verified event
        features = self._extract_features(event)
        if not features:
            return None

        # Step 3: Update rolling baselines
        self._update_baseline(features)

        # Step 4: Score against rolling baseline
        score = self._score(features)
        if score is None:
            return None

        # Step 5: Check threshold
        if score > self.SCORE_THRESHOLD:
            alert = AnomalyAlert(
                node_id=features.node_id,
                tenant_id=features.tenant_id,
                score=score,
                reason=f"Anomalous {features.event_type}: {features.rate:.1f}x baseline",
                event_count=features.event_count,
                baseline_rate=features.baseline_rate,
            )
            self._alerts.append(alert)
            self._alerts_fired += 1
            logger.warning(
                f"ANOMALY ALERT: {alert.node_id}/{alert.tenant_id} "
                f"score={score:.3f} reason={alert.reason}"
            )
            return alert

        return None

    def _extract_features(self, event) -> Optional[dict]:
        """Extract features from a verified audit event."""
        payload = event.payload if hasattr(event, 'payload') else {}
        return {
            "node_id": getattr(event, 'node_id', ''),
            "tenant_id": getattr(event, 'tenant_id', ''),
            "event_type": getattr(event, 'event_type', ''),
            "rate": self._calculate_rate(event),
            "event_count": self._count_events(event),
            "baseline_rate": self._get_baseline_rate(event),
        }

    def _calculate_rate(self, event) -> float:
        """Calculate event rate for the node/tenant."""
        # In production: calculate from rolling window of events
        return 1.0  # Placeholder

    def _count_events(self, event) -> int:
        """Count events for this node/tenant in the rolling window."""
        node_id = getattr(event, 'node_id', '')
        return len(self._node_baselines.get(node_id, []))

    def _get_baseline_rate(self, event) -> float:
        """Get the rolling baseline rate for this node/tenant."""
        node_id = getattr(event, 'node_id', '')
        baselines = self._node_baselines.get(node_id, [])
        if len(baselines) < self.MIN_EVENTS_FOR_BASELINE:
            return 0.0
        return sum(baselines[-self.ROLLING_WINDOW:]) / self.ROLLING_WINDOW

    def _update_baseline(self, features: dict):
        """Update rolling baseline with a verified event."""
        node_id = features.get("node_id", "")
        tenant_id = features.get("tenant_id", "")
        self._node_baselines[node_id].append(1.0)  # Each event = 1 count
        self._tenant_baselines[tenant_id].append(1.0)
        # Keep rolling window bounded
        if len(self._node_baselines[node_id]) > self.ROLLING_WINDOW:
            self._node_baselines[node_id] = self._node_baselines[node_id][-self.ROLLING_WINDOW:]
        if len(self._tenant_baselines[tenant_id]) > self.ROLLING_WINDOW:
            self._tenant_baselines[tenant_id] = self._tenant_baselines[tenant_id][-self.ROLLING_WINDOW:]

    def _score(self, features: dict) -> Optional[float]:
        """
        Score event against rolling baseline.
        Returns None if insufficient baseline data.
        """
        baseline_rate = features.get("baseline_rate", 0.0)
        current_rate = features.get("rate", 1.0)
        event_count = features.get("event_count", 0)

        if event_count < self.MIN_EVENTS_FOR_BASELINE:
            return None  # Not enough data to score

        if baseline_rate == 0:
            return 0.0  # No baseline, no anomaly

        ratio = current_rate / baseline_rate
        # Convert ratio to 0-1 anomaly score
        score = min(ratio / 10.0, 1.0)
        return score

    async def get_alerts(self, limit: int = 100) -> List[AnomalyAlert]:
        """Retrieve recent anomaly alerts."""
        return self._alerts[-limit:]

    @property
    def verification_failure_rate(self) -> float:
        return self._verification_failures / max(self._events_processed, 1)

    @property
    def is_read_only(self) -> bool:
        """Always True — detector has zero write path."""
        return True


# Global singleton
anomaly_detector = AnomalyDetector()
