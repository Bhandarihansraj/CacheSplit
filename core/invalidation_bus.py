"""
core/invalidation_bus.py
Simulates real network unreliability: drops messages and adds random delays.
This is the key realism component — without it, all nodes would always be FRESH.
"""
import asyncio
import random
import logging

logger = logging.getLogger(__name__)


class InvalidationBus:
    """
    Broadcast invalidation messages to subscribed cache nodes.
    Each message has a configurable probability of being dropped entirely,
    and surviving messages are delayed by a random amount.
    """

    def __init__(self, delivery_prob: float = 0.7, max_delay_ms: int = 200):
        if not 0.0 <= delivery_prob <= 1.0:
            raise ValueError("delivery_prob must be between 0.0 and 1.0")
        self.delivery_prob = delivery_prob
        self.max_delay_ms = max_delay_ms
        self._subscribers: list = []
        self._event_log: list[dict] = []

    def subscribe(self, node):
        self._subscribers.append(node)

    async def broadcast(self, key: str, new_version: int) -> dict:
        """
        Broadcast a cache invalidation to all subscribed nodes.
        Returns counts of delivered vs. dropped messages.
        """
        delivered, dropped = 0, 0
        loop = asyncio.get_event_loop()

        for node in self._subscribers:
            if random.random() <= self.delivery_prob:
                delay_s = random.randint(0, self.max_delay_ms) / 1000.0
                loop.call_later(delay_s, node.invalidate, key, new_version)
                delivered += 1
            else:
                dropped += 1
                evt = {
                    "type": "INVALIDATION_DROPPED",
                    "key": key,
                    "version": new_version,
                    "node": node.node_id,
                }
                self._event_log.append(evt)
                logger.info(f"Bus: DROPPED key={key} v={new_version} → {node.node_id}")

        return {"delivered": delivered, "dropped": dropped, "total": len(self._subscribers)}

    @property
    def event_log(self) -> list[dict]:
        return list(self._event_log)

    def clear_log(self):
        self._event_log.clear()
