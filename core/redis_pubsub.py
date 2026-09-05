"""
core/redis_pubsub.py
High-throughput in-memory Pub/Sub Messaging Engine for CacheSplit.
Supports:
  - Exact channel subscriptions (SUBSCRIBE / UNSUBSCRIBE)
  - Pattern-based wildcard subscriptions (PSUBSCRIBE / PUNSUBSCRIBE)
  - Message broadcasting (PUBLISH)
  - Per-subscriber message queue polling
  - Channel discovery and subscriber metrics
"""
from __future__ import annotations
import fnmatch
import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple


class PubSubManager:
    """
    Thread-safe in-memory Publish/Subscribe messaging coordinator.
    """
    def __init__(self, max_queue_size: int = 1000):
        self._lock = threading.RLock()
        self._max_queue_size = max_queue_size

        # channel -> set of subscriber_ids
        self._channels: Dict[str, Set[str]] = {}

        # pattern -> set of subscriber_ids
        self._patterns: Dict[str, Set[str]] = {}

        # subscriber_id -> deque of messages
        self._subscriber_queues: Dict[str, deque] = {}

        # subscriber_id -> set of subscribed channels
        self._sub_channels: Dict[str, Set[str]] = {}

        # subscriber_id -> set of subscribed patterns
        self._sub_patterns: Dict[str, Set[str]] = {}

        # Metrics
        self._total_published: int = 0
        self._total_delivered: int = 0

    def subscribe(self, subscriber_id: str, *channels: str) -> List[Tuple[str, int]]:
        """
        Subscribes a client to one or more channels.
        Returns a list of tuples: (channel, total_subscriptions_for_client)
        """
        with self._lock:
            if subscriber_id not in self._subscriber_queues:
                self._subscriber_queues[subscriber_id] = deque(maxlen=self._max_queue_size)
                self._sub_channels[subscriber_id] = set()
                self._sub_patterns[subscriber_id] = set()

            results = []
            for ch in channels:
                ch_name = str(ch)
                if ch_name not in self._channels:
                    self._channels[ch_name] = set()
                self._channels[ch_name].add(subscriber_id)
                self._sub_channels[subscriber_id].add(ch_name)

                total_subs = len(self._sub_channels[subscriber_id]) + len(self._sub_patterns[subscriber_id])
                results.append((ch_name, total_subs))

            return results

    def unsubscribe(self, subscriber_id: str, *channels: str) -> List[Tuple[str, int]]:
        """
        Unsubscribes a client from specified channels (or all channels if none given).
        """
        with self._lock:
            if subscriber_id not in self._sub_channels:
                return []

            target_channels = list(channels) if channels else list(self._sub_channels[subscriber_id])
            results = []

            for ch in target_channels:
                ch_name = str(ch)
                if ch_name in self._channels:
                    self._channels[ch_name].discard(subscriber_id)
                    if len(self._channels[ch_name]) == 0:
                        del self._channels[ch_name]

                self._sub_channels[subscriber_id].discard(ch_name)
                total_subs = len(self._sub_channels[subscriber_id]) + len(self._sub_patterns[subscriber_id])
                results.append((ch_name, total_subs))

            return results

    def psubscribe(self, subscriber_id: str, *patterns: str) -> List[Tuple[str, int]]:
        """
        Subscribes a client to one or more glob patterns (e.g. 'news.*', 'orders.*.created').
        """
        with self._lock:
            if subscriber_id not in self._subscriber_queues:
                self._subscriber_queues[subscriber_id] = deque(maxlen=self._max_queue_size)
                self._sub_channels[subscriber_id] = set()
                self._sub_patterns[subscriber_id] = set()

            results = []
            for pat in patterns:
                pat_str = str(pat)
                if pat_str not in self._patterns:
                    self._patterns[pat_str] = set()
                self._patterns[pat_str].add(subscriber_id)
                self._sub_patterns[subscriber_id].add(pat_str)

                total_subs = len(self._sub_channels[subscriber_id]) + len(self._sub_patterns[subscriber_id])
                results.append((pat_str, total_subs))

            return results

    def punsubscribe(self, subscriber_id: str, *patterns: str) -> List[Tuple[str, int]]:
        """
        Unsubscribes a client from specified patterns (or all patterns if none given).
        """
        with self._lock:
            if subscriber_id not in self._sub_patterns:
                return []

            target_patterns = list(patterns) if patterns else list(self._sub_patterns[subscriber_id])
            results = []

            for pat in target_patterns:
                pat_str = str(pat)
                if pat_str in self._patterns:
                    self._patterns[pat_str].discard(subscriber_id)
                    if len(self._patterns[pat_str]) == 0:
                        del self._patterns[pat_str]

                self._sub_patterns[subscriber_id].discard(pat_str)
                total_subs = len(self._sub_channels[subscriber_id]) + len(self._sub_patterns[subscriber_id])
                results.append((pat_str, total_subs))

            return results

    def publish(self, channel: str, message: Any) -> int:
        """
        Publishes a message to a channel. Delivers to direct channel subscribers
        as well as matching pattern subscribers.
        Returns the total number of receivers that received the message.
        """
        with self._lock:
            self._total_published += 1
            receivers: Set[str] = set()
            now = time.time()
            msg_str = str(message)

            # 1. Direct channel subscribers
            if channel in self._channels:
                for sub_id in self._channels[channel]:
                    if sub_id in self._subscriber_queues:
                        self._subscriber_queues[sub_id].append({
                            "type": "message",
                            "channel": channel,
                            "pattern": None,
                            "data": msg_str,
                            "ts": now,
                        })
                        receivers.add(sub_id)

            # 2. Pattern subscribers
            for pat, sub_ids in self._patterns.items():
                if fnmatch.fnmatch(channel, pat):
                    for sub_id in sub_ids:
                        if sub_id in self._subscriber_queues:
                            self._subscriber_queues[sub_id].append({
                                "type": "pmessage",
                                "channel": channel,
                                "pattern": pat,
                                "data": msg_str,
                                "ts": now,
                            })
                            receivers.add(sub_id)

            count = len(receivers)
            self._total_delivered += count
            return count

    def poll(self, subscriber_id: str, count: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieves and clears pending messages for a subscriber.
        """
        with self._lock:
            if subscriber_id not in self._subscriber_queues:
                return []

            q = self._subscriber_queues[subscriber_id]
            messages = []
            for _ in range(min(count, len(q))):
                messages.append(q.popleft())

            return messages

    def list_channels(self, pattern: str = "*") -> List[str]:
        """PUBSUB CHANNELS [pattern] -> returns active channels matching pattern."""
        with self._lock:
            if pattern == "*":
                return list(self._channels.keys())
            return [ch for ch in self._channels.keys() if fnmatch.fnmatch(ch, pattern)]

    def numsub(self, *channels: str) -> Dict[str, int]:
        """PUBSUB NUMSUB [channel ...] -> returns dict of channel -> subscriber count."""
        with self._lock:
            return {ch: len(self._channels.get(ch, set())) for ch in channels}

    def numpat(self) -> int:
        """PUBSUB NUMPAT -> returns total number of active pattern subscriptions."""
        with self._lock:
            return len(self._patterns)

    def stats(self) -> Dict[str, Any]:
        """Returns Pub/Sub coordinator stats."""
        with self._lock:
            return {
                "active_channels": len(self._channels),
                "active_patterns": len(self._patterns),
                "active_subscribers": len(self._subscriber_queues),
                "total_published": self._total_published,
                "total_delivered": self._total_delivered,
            }


# Global singleton instance
pubsub_manager = PubSubManager()
