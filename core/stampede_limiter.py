"""
core/stampede_limiter.py
Token-bucket rate limiter for CacheSplit v4.
Hard wall on origin reads — no blocking, just reject when empty.
"""
import time
import threading
import logging

logger = logging.getLogger(__name__)


class TokenBucket:
    """
    Token bucket rate limiter.
    Tokens refill at `rate_rps` per second up to `burst` capacity.
    `consume()` is non-blocking: returns True if a token was taken, False if empty.
    """

    def __init__(self, rate_rps: float, burst: int = None):
        self.rate = rate_rps
        self.burst = burst if burst is not None else max(1, int(rate_rps * 2))
        self._tokens = float(self.burst)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def consume(self) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(float(self.burst), self._tokens + elapsed * self.rate)
            self._last = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            logger.debug("TokenBucket: budget exhausted — request rejected")
            return False

    @property
    def level(self) -> float:
        """Fraction of bucket remaining (0.0 = empty, 1.0 = full)."""
        with self._lock:
            return round(self._tokens / self.burst, 4)

    def __repr__(self):
        return f"TokenBucket(rate={self.rate}rps, burst={self.burst}, level={self.level:.2f})"
