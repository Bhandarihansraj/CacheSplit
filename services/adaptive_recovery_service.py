"""
services/adaptive_recovery_service.py
Service coordinating the Q-Learning Governor with live Cache Recovery workflows.
"""

import time
import logging
from typing import Dict, Any, Optional

from core.rl_stampede_governor import (
    global_rl_governor,
    QLearningGovernor,
    EnvironmentTelemetry,
    GovernorAction,
)
from core.adaptive_limiter import AdaptiveTokenBucket

logger = logging.getLogger(__name__)


class AdaptiveRecoveryService:
    """
    Manages RL-governed recovery cycles and live rate-limit adaptation.
    """

    def __init__(self, governor: Optional[QLearningGovernor] = None):
        self.governor = governor or global_rl_governor
        self.limiter = AdaptiveTokenBucket(
            max_rps=self.governor.current_rps,
            burst=self.governor.current_burst,
        )
        self.last_telemetry = EnvironmentTelemetry()

    def step_simulation(
        self,
        origin_latency_ms: float = 15.0,
        packet_drop_rate: float = 0.20,
        stale_key_count: int = 4,
        total_keys: int = 10,
        origin_rejections: int = 0,
        repaired_keys: int = 2,
        dedup_savings: int = 3,
    ) -> Dict[str, Any]:
        """
        Feeds simulated telemetry into the Q-learning governor and applies the policy.
        """
        next_telem = EnvironmentTelemetry(
            origin_latency_ms=origin_latency_ms,
            packet_drop_rate=packet_drop_rate,
            stale_key_count=stale_key_count,
            total_keys=total_keys,
            origin_rejections=origin_rejections,
            repaired_keys=repaired_keys,
            dedup_savings=dedup_savings,
        )

        step_result = self.governor.step(
            current_telem=self.last_telemetry,
            next_telem=next_telem,
        )

        # Apply newly tuned limits to the token bucket
        if self.governor.auto_pilot:
            self.limiter.update_limits(
                new_rps=self.governor.current_rps,
                new_burst=self.governor.current_burst,
            )

        self.last_telemetry = next_telem

        return {
            "step_result": step_result,
            "limiter_status": self.limiter.get_status(),
            "telemetry": {
                "origin_latency_ms": origin_latency_ms,
                "packet_drop_rate": packet_drop_rate,
                "stale_keys": stale_key_count,
                "origin_rejections": origin_rejections,
            },
        }

    def set_autopilot(self, enabled: bool) -> bool:
        self.governor.auto_pilot = enabled
        return self.governor.auto_pilot

    def get_status(self) -> Dict[str, Any]:
        return {
            "governor": self.governor.get_status(),
            "limiter": self.limiter.get_status(),
        }

    def reset(self) -> None:
        self.governor.reset()
        self.limiter.update_limits(6.0, 3)
        self.last_telemetry = EnvironmentTelemetry()


adaptive_recovery_service = AdaptiveRecoveryService()
