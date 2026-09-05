"""
CacheSplit v3 — Access Event Logger + Feature Extraction
Captures real app activity (entity reads, writes, queries) in a ring buffer
and extracts feature vectors for the IsolationForest anomaly detector.
"""
import math
import time
import uuid
from collections import Counter, deque
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
from pydantic import BaseModel, Field


ENTITY_TYPE_MAP = {"patient": 0, "visit": 1, "lab_result": 2, "bed": 3,
                   "billing": 4, "clinician": 5}


class AccessEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    node_id: str
    entity_id: str = ""
    entity_type: str = ""
    access_type: str = "read"         # read | write | query
    requester_region: str = ""
    target_region: str = ""
    timestamp: float = Field(default_factory=time.time)
    fields_accessed: int = 1


class AccessLogger:
    """Ring-buffer of recent access events with per-node rate tracking."""

    def __init__(self, max_buffer: int = 5000):
        self._buffer: deque[AccessEvent] = deque(maxlen=max_buffer)
        self._node_timestamps: Dict[str, deque[float]] = {}
        self._entity_counts: Counter = Counter()
        self._node_counts: Counter = Counter()
        self._node_entity_sets: Dict[str, set] = {}

    def log(self, event: AccessEvent) -> AccessEvent:
        self._buffer.append(event)
        if event.node_id not in self._node_timestamps:
            self._node_timestamps[event.node_id] = deque(maxlen=500)
        self._node_timestamps[event.node_id].append(event.timestamp)
        self._entity_counts[event.entity_id] += 1
        self._node_counts[event.node_id] += 1
        if event.node_id not in self._node_entity_sets:
            self._node_entity_sets[event.node_id] = set()
        self._node_entity_sets[event.node_id].add(event.entity_id)
        return event

    def _rate_around_timestamp(self, node_id: str, ref_ts: float,
                                window: int = 60) -> float:
        """Events for this node within ±window seconds of ref_ts."""
        if node_id not in self._node_timestamps:
            return 0.0
        count = sum(1 for t in self._node_timestamps[node_id]
                    if abs(ref_ts - t) <= window)
        return float(count)

    def extract_features(self, event: AccessEvent) -> np.ndarray:
        """
        8-dim feature vector for a single access event:
          [hour_of_day,        cyclical hour normalised 0-1
           node_rate,          burst score around event's own timestamp
           node_frequency,     fraction of total events from this node
           entity_frequency,   fraction of total events for this entity
           entity_type,        ordinal 0-5 / 5
           is_cross_region,    0 or 1
           is_write,           0 or 1
           unique_entities,    diversity of entities per node (normalised)]
        """
        total = max(len(self._buffer), 1)

        hour = datetime.fromtimestamp(event.timestamp).hour + \
               datetime.fromtimestamp(event.timestamp).minute / 60.0
        hour_norm = (hour % 24) / 24.0

        node_rate = min(self._rate_around_timestamp(event.node_id,
                                                     event.timestamp) / 20.0, 1.0)
        node_freq = self._node_counts.get(event.node_id, 0) / total
        entity_freq = self._entity_counts.get(event.entity_id, 0) / total
        etype = ENTITY_TYPE_MAP.get(event.entity_type, 0) / 5.0
        cross = 1.0 if (event.requester_region and event.target_region
                        and event.requester_region != event.target_region) else 0.0
        write = 1.0 if event.access_type == "write" else 0.0
        node_entities = self._node_entity_sets.get(event.node_id, set())
        unique_ent = min(len(node_entities) / 50.0, 1.0)

        return np.array([[hour_norm, node_rate, node_freq, entity_freq,
                          etype, cross, write, unique_ent]])

    def get_feature_matrix(self, node_id: Optional[str] = None) -> np.ndarray:
        """Feature matrix for all buffered events (optionally filtered by node)."""
        events = list(self._buffer)
        if node_id:
            events = [e for e in events if e.node_id == node_id]
        if not events:
            return np.zeros((0, 8))
        return np.vstack([self.extract_features(e) for e in events])

    # ── queries ───────────────────────────────────────────────────────────

    def get_recent(self, node_id: Optional[str] = None, limit: int = 100) -> List[AccessEvent]:
        events = list(self._buffer)
        if node_id:
            events = [e for e in events if e.node_id == node_id]
        return events[-limit:]

    def __len__(self) -> int:
        return len(self._buffer)
