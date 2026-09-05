"""
CacheSplit v3 — Propagation Service
Wires the previously-standalone Debounce + StampedeBudget into a real fetch
workflow: invalidation events coalesce into ONE origin fetch per window, every
origin fetch is gated by a per-region stampede budget, and the fetched commit
chain is cryptographically verified against the origin signing key.
"""
import time
from typing import Callable, Dict, Optional

from core.commit import ORIGIN_SIGNING_KEY
from core.hash_chain import verify_signed_chain
from services.debounce import DebounceWindow, StampedeBudget

FetchFn = Callable[[str], object]


class PropagationService:
    def __init__(self, window_ms: int = 1000, fetch_budget_per_second: int = 2):
        self.window_ms = window_ms
        self.fetch_budget_per_second = fetch_budget_per_second
        self.windows: Dict[str, DebounceWindow] = {}
        self.budgets: Dict[str, StampedeBudget] = {}
        self._metrics: Dict[str, Dict[str, int]] = {}

    # ── internal plumbing ──────────────────────────────────────────────────

    def _window(self, node_id: str) -> DebounceWindow:
        if node_id not in self.windows:
            self.windows[node_id] = DebounceWindow(node_id, window_ms=self.window_ms)
        return self.windows[node_id]

    def _budget(self, node_id: str) -> StampedeBudget:
        if node_id not in self.budgets:
            self.budgets[node_id] = StampedeBudget(node_id, self.fetch_budget_per_second)
        return self.budgets[node_id]

    def _stats(self, node_id: str) -> Dict[str, int]:
        if node_id not in self._metrics:
            self._metrics[node_id] = {
                "invalidations": 0,
                "fetches": 0,
                "budget_denials": 0,
                "chains_verified": 0,
                "chain_failures": 0,
                "last_fetch_ts": 0,
            }
        return self._metrics[node_id]

    # ── public API ─────────────────────────────────────────────────────────

    def on_invalidation(self, node_id: str, version_hint: str) -> int:
        """Called whenever an invalidation/drift event arrives for a node."""
        self._stats(node_id)["invalidations"] += 1
        self._window(node_id).trigger(version_hint)
        return self._stats(node_id)["invalidations"]

    async def run_fetch_workflow(self, node_id: str, fetch_fn: FetchFn) -> Dict:
        """
        One fetch cycle:
          1. Coalesce — wait for the current debounce window to resolve.
          2. Budget — refuse the fetch if the stampede budget is exhausted.
          3. Verify — cryptographic check of the fetched commit chain.
        Returns per-call status plus cumulative node metrics.
        """
        stats = self._stats(node_id)
        hint = await self._window(node_id).wait_and_resolve()
        if not hint:
            return {"node_id": node_id, "status": "idle",
                    "reason": "no invalidations pending in window", **stats}

        if not self._budget(node_id).try_acquire():
            stats["budget_denials"] += 1
            return {"node_id": node_id, "status": "budget_exhausted",
                    "reason": "stampede budget exhausted for this second", **stats}

        commits = await fetch_fn(hint)
        stats["fetches"] += 1
        stats["last_fetch_ts"] = int(time.time())

        if verify_signed_chain(commits, ORIGIN_SIGNING_KEY):
            stats["chains_verified"] += 1
            verified = True
        else:
            stats["chain_failures"] += 1
            verified = False

        return {
            "node_id": node_id,
            "status": "fetched",
            "commits_fetched": len(commits),
            "chain_verified": verified,
            "hint": hint,
            **stats,
        }

    def metrics(self, node_id: str) -> Dict:
        stats = self._stats(node_id).copy()
        if stats["invalidations"]:
            stats["coalescing_ratio"] = round(stats["fetches"] / stats["invalidations"], 3)
        else:
            stats["coalescing_ratio"] = 0.0
        return stats


# Global singleton
propagation = PropagationService()