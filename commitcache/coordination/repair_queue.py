"""
Deterministic repair queue for CacheSplit v4.
Priority queue where priority = biggest version gap first.
Ties broken by deterministic seeded RNG. All entries comparable.
"""
import heapq
import random
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(order=True)
class RepairEntry:
    """Priority queue entry. Priority = biggest gap first, ties deterministic."""
    priority: int  # negative gap so biggest gap = lowest number = highest priority
    seed_sort: int  # deterministic tiebreaker from seeded RNG
    key: str = field(compare=False)
    gap: int = field(compare=False)
    node_id: str = field(compare=False)
    retry_count: int = field(compare=False, default=0)
    timestamp: float = field(compare=False, default=0.0)

    @classmethod
    def create(cls, key: str, gap: int, node_id: str, seed: int = 42) -> "RepairEntry":
        """Create a repair entry with deterministic ordering."""
        rng = random.Random(seed)
        seed_sort = rng.randint(0, 2**31)
        return cls(
            priority=-gap,  # negate so bigger gap = higher priority
            seed_sort=seed_sort,
            key=key,
            gap=gap,
            node_id=node_id,
            timestamp=0.0,
        )


class RepairQueue:
    """
    Priority queue where priority = biggest version gap first.
    Ties broken by deterministic seeded RNG.

    Security requirement:
    - RNG is seeded and deterministic. Same inputs always produce same ordering.
    - No hidden randomness.

    Must not:
    - Use random.random() without a seed.
    - Allow arbitrary ordering — every tie resolved deterministically.
    """

    def __init__(self, seed: int = 42):
        self._heap: list[RepairEntry] = []
        self._seed = seed
        self._counter = 0

    def push(self, key: str, gap: int, node_id: str, retry_count: int = 0):
        """Push a repair entry with deterministic priority ordering."""
        entry = RepairEntry.create(
            key=key, gap=gap, node_id=node_id, seed=self._seed
        )
        entry.retry_count = retry_count
        entry.timestamp = self._counter
        self._counter += 1
        heapq.heappush(self._heap, entry)
        logger.debug(f"RepairQueue: pushed {key} gap={gap}")

    def pop(self) -> Optional[RepairEntry]:
        """Pop the highest-priority repair entry. Returns None if empty."""
        if not self._heap:
            return None
        entry = heapq.heappop(self._heap)
        logger.debug(f"RepairQueue: popped {entry.key} gap={entry.gap}")
        return entry

    def peek(self) -> Optional[RepairEntry]:
        """View the highest-priority entry without removing."""
        return self._heap[0] if self._heap else None

    def remove(self, key: str) -> bool:
        """Remove all entries for a given key. Returns True if found."""
        initial_len = len(self._heap)
        self._heap = [e for e in self._heap if e.key != key]
        heapq.heapify(self._heap)
        removed = initial_len - len(self._heap)
        if removed:
            logger.info(f"RepairQueue: removed {removed} entries for {key}")
        return removed > 0

    @property
    def size(self) -> int:
        return len(self._heap)

    @property
    def is_empty(self) -> bool:
        return len(self._heap) == 0

    def clear(self):
        self._heap.clear()
        self._counter = 0
        logger.info("RepairQueue cleared")

    def get_stale_keys(self, max_keys: int = 10) -> list[str]:
        """Return list of keys with highest gaps without popping."""
        sorted_entries = sorted(self._heap, key=lambda e: e.priority)
        return [e.key for e in sorted_entries[:max_keys]]
