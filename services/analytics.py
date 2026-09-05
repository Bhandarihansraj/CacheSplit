"""
CacheSplit v3 — Access Analytics Orchestration
Glues the AccessLogger ↔ SecurityAgent ↔ DB together.

On every entity read / write the app calls `analytics.log_access(...)`.
The first N events seed a "normal traffic" baseline and train the
IsolationForest.  Subsequent events are scored in real-time; anomalies
are persisted to the security_events table and surfaced in the feed.
"""
import random
import time
import logging
from typing import Dict, List, Optional

from agents.access_logger import AccessEvent, AccessLogger
from agents.security_agent import SecurityAgent

logger = logging.getLogger(__name__)


class AccessAnalytics:
    def __init__(self, train_interval: int = 100):
        self.logger = AccessLogger()
        self.security_agent = SecurityAgent(logger_instance=self.logger)
        self._events_since_train = 0
        self._train_interval = train_interval
        self._anomaly_count = 0

    # ── public entry-point (called from cache_store) ──────────────────────

    def log_access(self, node_id: str, entity_id: str, entity_type: str,
                   access_type: str = "read", requester_region: str = "",
                   target_region: str = "", **_kw) -> AccessEvent:
        event = AccessEvent(
            node_id=node_id, entity_id=entity_id, entity_type=entity_type,
            access_type=access_type, requester_region=requester_region,
            target_region=target_region,
        )
        self.logger.log(event)

        # Score if model is already trained
        if self.security_agent.is_trained:
            score = self.security_agent.score_event(event)
            if score > 0.7:
                self._anomaly_count += 1
                # Fire-and-forget persistence; the caller is already async
                self._pending_anomalies.append({
                    "node_id": node_id,
                    "event_type": "ML_ANOMALY",
                    "reason": f"ML anomaly score {score:.3f} on {access_type} of {entity_id}",
                    "severity": "HIGH",
                    "target_entity_id": entity_id,
                })

        self._events_since_train += 1
        if self._events_since_train >= self._train_interval and self.logger:
            self._train_model()

        return event

    @property
    def _pending_anomalies(self) -> list:
        if not hasattr(self, "_anomaly_queue"):
            self._anomaly_queue: list = []
        return self._anomaly_queue

    async def flush_anomalies(self):
        """Persist any queued anomalies to the DB."""
        from db import security_repo
        while self._pending_anomalies:
            entry = self._pending_anomalies.pop(0)
            await security_repo.insert_security_event(**entry)

    # ── training ──────────────────────────────────────────────────────────

    def _train_model(self):
        if self.security_agent.train():
            self._events_since_train = 0
            logger.info("SecurityAgent retrained (%d events in buffer)",
                        len(self.logger))

    # ── baseline seeding (called once at startup) ─────────────────────────

    def seed_baseline_traffic(self):
        """
        Generates synthetic *normal* access events so the model has a
        realistic baseline before real traffic arrives.  This is the only
        place synthetic data enters the ML pipeline — it represents the
        expected steady-state: intra-region, patient-heavy, moderate rate.
        """
        regions = [("us-east-1", "US-East"), ("eu-west-1", "EU-West"),
                   ("asia-south-1", "Asia-South")]
        etype_weights = [("patient", 0.70), ("visit", 0.15),
                         ("lab_result", 0.10), ("bed", 0.05)]

        events: List[AccessEvent] = []
        now = time.time()
        for node_id, region in regions:
            safe = region.lower().replace("-", "_")
            for i in range(200):
                etype = random.choices(
                    [e[0] for e in etype_weights],
                    weights=[e[1] for e in etype_weights])[0]
                prefix = {"patient": "pat", "visit": "vis",
                          "lab_result": "lab", "bed": "bed"}.get(etype, "ent")
                eid = f"{prefix}_{safe}_{random.randint(1, 50):03d}"
                events.append(AccessEvent(
                    node_id=node_id, entity_id=eid, entity_type=etype,
                    access_type=random.choice(["read"] * 3 + ["write"]),
                    requester_region=region, target_region=region,
                    timestamp=now - random.uniform(0, 3600),
                ))
        for e in events:
            self.logger.log(e)
        self.security_agent.train(events)
        logger.info("Baseline traffic seeded: %d events, model trained=%s",
                    len(events), self.security_agent.is_trained)

    # ── status ────────────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        return {
            "model_trained": self.security_agent.is_trained,
            "events_logged": len(self.logger),
            "anomalies_detected": self._anomaly_count,
            "events_since_train": self._events_since_train,
            "train_interval": self._train_interval,
            "feature_names": [
                "hour_of_day", "node_rate", "node_frequency",
                "entity_frequency", "entity_type", "is_cross_region",
                "is_write", "unique_entities",
            ],
        }


# Global singleton
analytics = AccessAnalytics()