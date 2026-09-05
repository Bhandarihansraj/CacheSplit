import asyncio
import time
from typing import Optional

class DebounceWindow:
    def __init__(self, node_id: str, window_ms: int = 1000):
        self.node_id = node_id
        self.window_seconds = window_ms / 1000.0
        self._current_hint: Optional[str] = None
        self._resolve_task: Optional[asyncio.Task] = None
        self._resolve_event = asyncio.Event()
        self._latest_resolved_hint: Optional[str] = None

    def trigger(self, new_version_hint: str) -> None:
        """Called every time an invalidation event arrives."""
        self._current_hint = new_version_hint
        
        if self._resolve_task is None or self._resolve_task.done():
            self._resolve_event.clear()
            self._resolve_task = asyncio.create_task(self._wait_and_resolve_internal())

    async def _wait_and_resolve_internal(self):
        await asyncio.sleep(self.window_seconds)
        self._latest_resolved_hint = self._current_hint
        self._resolve_event.set()

    async def wait_and_resolve(self) -> str:
        """Resolves ONCE per window, returns latest known commit_hash to fetch."""
        if self._resolve_task:
            await self._resolve_event.wait()
            return self._latest_resolved_hint
        return ""

class StampedeBudget:
    def __init__(self, region: str, max_requests_per_sec: int):
        self.region = region
        self.max_requests_per_sec = max_requests_per_sec
        self._requests_this_second = 0
        self._last_second = int(time.time())

    def try_acquire(self) -> bool:
        """Non-blocking; returns False if budget exhausted this second."""
        current_second = int(time.time())
        if current_second != self._last_second:
            self._last_second = current_second
            self._requests_this_second = 0
            
        if self._requests_this_second < self.max_requests_per_sec:
            self._requests_this_second += 1
            return True
        return False
