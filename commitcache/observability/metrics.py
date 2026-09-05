"""
Full-spectrum metrics for CacheSplit v4.
Tracks success, reject, timeout, and error counters for every operation.
Every branch gets a metric — no silent paths without counters.
"""
import time
import logging
from typing import Dict, Optional
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MetricCounters:
    success: int = 0
    reject: int = 0
    timeout: int = 0
    error: int = 0
    total_latency_ms: float = 0.0
    count: int = 0


class MetricsCollector:
    """
    Track success, reject, timeout, and error counters for every operation.
    Every branch gets a metric. No silent paths without counters.

    Security requirement:
    - Every except branch increments error counter.
    - Every rejection increments reject counter.
    - Every timeout increments timeout counter.
    - Never swallow exception without incrementing error counter.

    Must not:
    - Only emit success counters.
    - Swallow exceptions without incrementing error counter.
    - Have any function without at least success + error counters.
    """

    def __init__(self):
        self._counters: Dict[str, MetricCounters] = defaultdict(MetricCounters)
        self._histograms: Dict[str, list[float]] = defaultdict(list)

    def record_success(self, metric_name: str, latency_ms: float = 0.0):
        """Record a successful operation."""
        c = self._counters[metric_name]
        c.success += 1
        c.total_latency_ms += latency_ms
        c.count += 1
        logger.debug(f"METRIC {metric_name}.success={c.success}")

    def record_reject(self, metric_name: str):
        """Record a rejected operation."""
        self._counters[metric_name].reject += 1
        self._counters[metric_name].count += 1
        logger.debug(f"METRIC {metric_name}.reject={self._counters[metric_name].reject}")

    def record_timeout(self, metric_name: str):
        """Record a timeout operation."""
        self._counters[metric_name].timeout += 1
        self._counters[metric_name].count += 1
        logger.warning(f"METRIC {metric_name}.timeout={self._counters[metric_name].timeout}")

    def record_error(self, metric_name: str, error: str = ""):
        """Record an error operation. Never silently swallow."""
        self._counters[metric_name].error += 1
        self._counters[metric_name].count += 1
        logger.error(f"METRIC {metric_name}.error={self._counters[metric_name].error}: {error}")

    def record_latency(self, metric_name: str, latency_ms: float):
        """Record operation latency for histogram."""
        self._histograms[metric_name].append(latency_ms)

    def get_counters(self, metric_name: str = None) -> Dict:
        """Get current counter values."""
        if metric_name:
            c = self._counters[metric_name]
            return {
                "success": c.success,
                "reject": c.reject,
                "timeout": c.timeout,
                "error": c.error,
                "count": c.count,
                "avg_latency_ms": c.total_latency_ms / c.count if c.count > 0 else 0,
            }
        return {
            name: {
                "success": c.success,
                "reject": c.reject,
                "timeout": c.timeout,
                "error": c.error,
                "count": c.count,
            }
            for name, c in self._counters.items()
        }

    def get_status_report(self) -> Dict:
        """Full status report for observability dashboard."""
        report = {}
        for name, c in self._counters.items():
            total = c.success + c.reject + c.timeout + c.error
            report[name] = {
                "success": c.success,
                "reject": c.reject,
                "timeout": c.timeout,
                "error": c.error,
                "total": total,
                "success_rate": c.success / total if total > 0 else 0,
                "error_rate": c.error / total if total > 0 else 0,
            }
        return report

    def reset(self, metric_name: str = None):
        """Reset counters for a metric or all."""
        if metric_name:
            self._counters[metric_name] = MetricCounters()
        else:
            self._counters.clear()
        logger.info("Metrics reset")


# Clean up the messy fix at the bottom
# MetricsCollector is correctly defined above
