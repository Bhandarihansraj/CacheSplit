"""
Independent gossip worker for CacheSplit v4.
Decouples gossip from repair — produces StalenessReport objects
via a bounded queue instead of directly triggering repairs.
"""
import asyncio
import logging
import time
from typing import List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StalenessReport:
    node_id: str
    key: str
    local_version: int
    origin_version: int
    gap: int
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def is_stale(self) -> bool:
        return self.local_version < self.origin_version


class GossipWorker:
    """
    Independent async task that samples every node's version_vector
    and compares with origin.current_versions().

    Security requirement:
    - Gossip worker never calls repair directly.
    - Only produces StalenessReport objects pushed to report_queue.
    - Communication via bounded queue — no direct state modification.

    Must not:
    - Block on repair operations.
    - Directly modify node state — only produce reports.
    """

    def __init__(self, nodes, origin, interval_seconds: float = 2.0):
        self.nodes = nodes
        self.origin = origin
        self.interval_seconds = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.reports_produced = 0
        self._report_queue: Optional[asyncio.Queue] = None

    def set_report_queue(self, queue: asyncio.Queue):
        """Bind the bounded queue that receives StalenessReports."""
        self._report_queue = queue

    async def _gossip_round(self) -> List[StalenessReport]:
        """Compare node version_vectors against origin. Return reports."""
        reports = []
        origin_versions = self.origin.current_versions()

        for node in self.nodes:
            local_vv = node.version_vector()
            for key, origin_v in origin_versions.items():
                local_v = local_vv.get(key, 0)
                gap = origin_v - local_v
                if gap > 0:
                    report = StalenessReport(
                        node_id=node.node_id,
                        key=key,
                        local_version=local_v,
                        origin_version=origin_v,
                        gap=gap,
                    )
                    reports.append(report)

        return reports

    async def _loop(self):
        """Independent gossip loop — produces reports only."""
        logger.info("GossipWorker starting...")
        while self._running:
            try:
                reports = await self._gossip_round()
                for report in reports:
                    if self._report_queue and not self._report_queue.full():
                        await self._report_queue.put(report)
                        self.reports_produced += 1
                        logger.debug(
                            f"Gossip: queued staleness report "
                            f"{report.node_id}/{report.key} gap={report.gap}"
                        )
                    elif self._report_queue:
                        logger.warning(
                            f"Gossip: report queue full, dropping "
                            f"{report.node_id}/{report.key}"
                        )
            except Exception as e:
                logger.error(f"GossipWorker error: {e}")
            await asyncio.sleep(self.interval_seconds)

    def start(self, report_queue: asyncio.Queue):
        """Start the gossip worker with a bounded report queue."""
        self.set_report_queue(report_queue)
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("GossipWorker started.")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("GossipWorker stopped.")


# Standalone factory
def create_gossip_worker(nodes, origin, interval_seconds: float = 2.0) -> GossipWorker:
    return GossipWorker(nodes, origin, interval_seconds)
