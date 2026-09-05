import asyncio
from typing import Callable, Any, Dict

class RequestDebouncer:
    def __init__(self, wait_time: float = 0.1):
        self.wait_time = wait_time
        self._pending_tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, Any] = {}
        self._events: Dict[str, asyncio.Event] = {}

    async def execute(self, key: str, func: Callable, *args, **kwargs) -> Any:
        if key in self._pending_tasks:
            await self._events[key].wait()
            return self._results[key]

        event = asyncio.Event()
        self._events[key] = event

        async def _wrapper():
            await asyncio.sleep(self.wait_time)
            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                self._results[key] = result
            except Exception as e:
                self._results[key] = e
            finally:
                self._events[key].set()
                self._cleanup(key)

        task = asyncio.create_task(_wrapper())
        self._pending_tasks[key] = task
        
        await event.wait()
        result = self._results.pop(key, None)
        if isinstance(result, Exception):
            raise result
        return result

    def _cleanup(self, key: str):
        self._pending_tasks.pop(key, None)
        self._events.pop(key, None)

debouncer = RequestDebouncer()
