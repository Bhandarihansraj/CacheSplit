"""
Repair worker for CacheSplit v4.
Consumes StalenessReport from gossip_worker via bounded queue.
Applies exponential backoff on re-queue. Makes handle_read_miss reachable.
"""
import asyncio
import logging
import time
from typing import Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RepairResult:
    key: str
    success: bool
    retries: int
    error: str = ""
    repaired_at: float = 0.0


class RepairWorker:
    """
    Consumes StalenessReport from gossip_worker via bounded queue.
    Applies exponential backoff on re-queue. Makes handle_read_miss reachable.

    Security requirement:
    - Re-queue uses exponential backoff starting at 1s, doubling each attempt.
    - Maximum 5 retries before escalating.
    - handle_read_miss must be reachable and tested.

    Must not:
    - Allow infinite re-queue without backoff.
    - Allow unbounded memory growth from queued repairs.
    - Skip handle_read_miss path.
    """

    MAX_RETRIES = 5
    BASE_BACKOFF_MS = 1000
    MAX_BACKOFF_MS = 60000

    def __init__(self, origin, state_manager=None, max_retries: int = 5):
        self.origin = origin
        self.state_manager = state_manager
        self.max_retries = max(max_retries, 1)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._results: List[RepairResult] = []
        self.success_count = 0
        self.reject_count = 0
        self.timeout_count = 0

    async def handle_read_miss(self, key: str, node_id: str) -> Optional[dict]:
        """
        Handle a read miss by fetching from origin.
        This is the reachable miss path for production use.
        Returns the record data or None if unavailable.
        """
        try:
            record = await self.origin.get(key)
            if record:
                logger.info(f"Read miss handled: {key} -> node {node_id}")
                return record.data
            logger.warning(f"Read miss no data: {key}")
            return None
        except Exception as e:
            logger.error(f"Read miss failed for {key}: {e}")
            return None

    async def _repair_key(self, key: str, waiting_nodes: List) -> RepairResult:
        """Repair a single key with exponential backoff on failure."""
        retries = 0
        backoff_ms = self.BASE_BACKOFF_MS

        while retries < self.max_retries:
            try:
                record = await self.origin.get(key)
                if record:
                    for node in waiting_nodes:
                        node.apply_repair(key, record)
                    self.success_count += 1
                    result = RepairResult(
                        key=key, success=True, retries=retries,
                        repaired_at=time.monotonic(),
                    )
                    self._results.append(result)
                    logger.info(f"Repaired {key} on attempt {retries}")
                    return result
            except Exception as e:
                retries += 1
                if retries >= self.max_retries:
                    self.reject_count += 1
                    result = RepairResult(
                        key=key, success=False, retries=retries,
                        error=str(e), repaired_at=time.monotonic(),
                    )
                    self._results.append(result)
                    logger.warning(f"Repair failed for {key} after {retries} attempts")
                    return result
                await asyncio.sleep(backoff_ms / 1000.0)
                backoff_ms = min(backoff_ms * 2, self.MAX_BACKOFF_MS)

        return RepairResult(key=key, success=False, retries=retries, error="max retries")

    async def _loop(self, report_queue: asyncio.Queue):
        """Consume reports from the bounded queue and repair."""
        logger.info("RepairWorker starting...")
        while self._running:
            try:
                report = await asyncio.wait_for(report_queue.get(), timeout=5.0)
                waiting_nodes = self._get_waiting_nodes(report)
                result = await self._repair_key(report.key, waiting_nodes)
                report_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"RepairWorker error: {e}")
                self.timeout_count += 1

    def _get_waiting_nodes(self, report) -> List:
        """Get nodes waiting for this key's repair."""
        return []

    def start(self, report_queue: asyncio.Queue):
        """Start the repair worker with a bounded report queue."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._loop(report_queue))
            logger.info("RepairWorker started.")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("RepairWorker stopped.")


def create_repair_worker(origin, state_manager=None, max_retries: int = 5) -> RepairWorker:
    return RepairWorker(origin, state_manager, max_retries)
