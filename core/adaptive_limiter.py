"""
core/adaptive_limiter.py
Adaptive Token Bucket Rate Limiter for CacheSplit.
Allows thread-safe, dynamic runtime adjustments to max_rps and burst capacity
driven by the Q-Learning Governor without dropping in-flight requests.
"""

import time
import threading
from typing import Dict, Any


class AdaptiveTokenBucket:
    """
    Token bucket rate limiter supporting live parameter updates from RL Governor.
    """

    def __init__(self, max_rps: float = 6.0, burst: int = 3):
        self.max_rps = float(max_rps)
        self.burst = float(burst)
        self.tokens = float(burst)
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

        # Telemetry stats
        self.total_allowed = 0
        self.total_rejected = 0

    def _replenish(self, now: float) -> None:
        elapsed = now - self.last_update
        self.last_update = now
        added = elapsed * self.max_rps
        self.tokens = min(self.burst, self.tokens + added)

    def allow_request(self, cost: float = 1.0) -> bool:
        """
        Consumes tokens if available.
        Returns True if allowed, False if bucket is exhausted.
        """
        with self._lock:
            now = time.monotonic()
            self._replenish(now)
            if self.tokens >= cost:
                self.tokens -= cost
                self.total_allowed += 1
                return True
            else:
                self.total_rejected += 1
                return False

    def update_limits(self, new_rps: float, new_burst: int) -> None:
        """
        Dynamically adjusts max_rps and burst ceiling while preserving existing tokens.
        """
        with self._lock:
            now = time.monotonic()
            self._replenish(now)
            self.max_rps = max(1.0, float(new_rps))
            self.burst = max(1.0, float(new_burst))
            self.tokens = min(self.burst, self.tokens)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            self._replenish(now)
            return {
                "max_rps": self.max_rps,
                "burst": int(self.burst),
                "available_tokens": round(self.tokens, 2),
                "total_allowed": self.total_allowed,
                "total_rejected": self.total_rejected,
            }
