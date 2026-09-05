"""
core/rl_stampede_governor.py
AgentDB Reinforcement Learning (Q-Learning) Stampede Governor for CacheSplit.
Optimizes origin recovery token-bucket capacity (max_rps, burst) and coalescing
timeouts dynamically using discrete state-action Q-learning.
"""

import math
import random
import logging
from enum import IntEnum
from typing import Tuple, Dict, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class GovernorAction(IntEnum):
    THROTTLE_DOWN = 0     # Reduce max_rps (-25%) and burst (-1) when overload occurs
    MAINTAIN = 1          # Keep current settings (equilibrium)
    INCREASE_BURST = 2    # Increase burst (+1) for temporary spikes
    BOOST_RPS = 3         # Increase max_rps (+25%) when capacity is healthy
    AGGRESSIVE_BOOST = 4  # Boost both max_rps (+50%) and burst (+2) for large stale backlogs


@dataclass
class EnvironmentTelemetry:
    origin_latency_ms: float = 10.0
    packet_drop_rate: float = 0.0
    stale_key_count: int = 0
    total_keys: int = 10
    origin_rejections: int = 0
    repaired_keys: int = 0
    dedup_savings: int = 0


class QLearningGovernor:
    """
    Q-Learning agent that dynamically learns the optimal rate limiting policy
    to maximize cache convergence speed while avoiding upstream origin overload.
    """

    def __init__(
        self,
        learning_rate: float = 0.15,
        discount_factor: float = 0.90,
        epsilon: float = 0.20,
        epsilon_decay: float = 0.98,
        min_epsilon: float = 0.02,
        min_rps: float = 2.0,
        max_rps_ceiling: float = 50.0,
        min_burst: int = 1,
        max_burst_ceiling: int = 20,
    ):
        self.alpha = learning_rate
        self.gamma = discount_factor
        self.epsilon = epsilon
        self.epsilon_decay = epsilon_decay
        self.min_epsilon = min_epsilon

        # Safety clamps
        self.min_rps = min_rps
        self.max_rps_ceiling = max_rps_ceiling
        self.min_burst = min_burst
        self.max_burst_ceiling = max_burst_ceiling

        # Current controlled state
        self.current_rps: float = 6.0
        self.current_burst: int = 3
        self.auto_pilot: bool = True

        # Q-Table: Dict[StateTuple, Dict[GovernorAction, float]]
        self.q_table: Dict[Tuple[int, int, int, int], Dict[int, float]] = {}

        # Telemetry & Learning History
        self.total_steps: int = 0
        self.cumulative_reward: float = 0.0
        self.recent_rewards: List[float] = []

    def discretize_state(self, telem: EnvironmentTelemetry) -> Tuple[int, int, int, int]:
        """
        Discretizes continuous telemetry into 4-tier state tuple:
        (latency_tier, drop_tier, stale_ratio_tier, overload_tier)
        """
        # 1. Latency tier: 0 = fast (<30ms), 1 = medium (30-100ms), 2 = slow (>100ms)
        if telem.origin_latency_ms < 30.0:
            lat_tier = 0
        elif telem.origin_latency_ms < 100.0:
            lat_tier = 1
        else:
            lat_tier = 2

        # 2. Drop rate tier: 0 = low (<0.15), 1 = medium (0.15-0.40), 2 = high (>0.40)
        if telem.packet_drop_rate < 0.15:
            drop_tier = 0
        elif telem.packet_drop_rate < 0.40:
            drop_tier = 1
        else:
            drop_tier = 2

        # 3. Stale ratio tier: 0 = healthy (<0.20), 1 = drifted (0.20-0.60), 2 = critical (>0.60)
        total = max(telem.total_keys, 1)
        stale_ratio = telem.stale_key_count / total
        if stale_ratio < 0.20:
            stale_tier = 0
        elif stale_ratio < 0.60:
            stale_tier = 1
        else:
            stale_tier = 2

        # 4. Overload tier: 0 = no rejections, 1 = rejected
        overload_tier = 1 if telem.origin_rejections > 0 else 0

        return (lat_tier, drop_tier, stale_tier, overload_tier)

    def _get_q_row(self, state: Tuple[int, int, int, int]) -> Dict[int, float]:
        if state not in self.q_table:
            # Initialize Q-values for all actions
            self.q_table[state] = {a.value: 0.0 for a in GovernorAction}
        return self.q_table[state]

    def select_action(self, state: Tuple[int, int, int, int]) -> GovernorAction:
        """
        Epsilon-greedy action selection.
        """
        q_row = self._get_q_row(state)

        # Explore
        if random.random() < self.epsilon and self.auto_pilot:
            action_val = random.choice(list(GovernorAction)).value
            return GovernorAction(action_val)

        # Exploit: pick best action
        best_action_val = max(q_row.keys(), key=lambda a: q_row[a])
        return GovernorAction(best_action_val)

    def calculate_reward(self, telem: EnvironmentTelemetry) -> float:
        """
        Reward function:
        + 1.5 per repaired key
        + 0.5 per dedup hit avoided
        - 10.0 per origin rejection (heavy penalty for overload)
        - 0.5 * (latency / 50ms)
        """
        reward = (
            (1.5 * telem.repaired_keys)
            + (0.5 * telem.dedup_savings)
            - (10.0 * telem.origin_rejections)
            - (0.5 * (telem.origin_latency_ms / 50.0))
        )
        return round(reward, 3)

    def apply_action(self, action: GovernorAction) -> Tuple[float, int]:
        """
        Applies chosen action to adapt max_rps and burst.
        """
        if action == GovernorAction.THROTTLE_DOWN:
            self.current_rps = max(self.min_rps, round(self.current_rps * 0.75, 1))
            self.current_burst = max(self.min_burst, self.current_burst - 1)
        elif action == GovernorAction.MAINTAIN:
            pass
        elif action == GovernorAction.INCREASE_BURST:
            self.current_burst = min(self.max_burst_ceiling, self.current_burst + 1)
        elif action == GovernorAction.BOOST_RPS:
            self.current_rps = min(self.max_rps_ceiling, round(self.current_rps * 1.25, 1))
        elif action == GovernorAction.AGGRESSIVE_BOOST:
            self.current_rps = min(self.max_rps_ceiling, round(self.current_rps * 1.50, 1))
            self.current_burst = min(self.max_burst_ceiling, self.current_burst + 2)

        return self.current_rps, self.current_burst

    def step(
        self,
        current_telem: EnvironmentTelemetry,
        next_telem: EnvironmentTelemetry,
    ) -> Dict[str, Any]:
        """
        Performs one Q-learning update step and returns decision metadata.
        """
        self.total_steps += 1

        state = self.discretize_state(current_telem)
        action = self.select_action(state)

        if self.auto_pilot:
            self.apply_action(action)

        reward = self.calculate_reward(next_telem)
        self.cumulative_reward += reward
        self.recent_rewards.append(reward)
        if len(self.recent_rewards) > 50:
            self.recent_rewards.pop(0)

        # Bellman Q-Value update
        next_state = self.discretize_state(next_telem)
        current_q = self._get_q_row(state)[action.value]
        max_next_q = max(self._get_q_row(next_state).values())

        new_q = current_q + self.alpha * (reward + (self.gamma * max_next_q) - current_q)
        self._get_q_row(state)[action.value] = round(new_q, 4)

        # Epsilon decay
        if self.epsilon > self.min_epsilon:
            self.epsilon = max(self.min_epsilon, round(self.epsilon * self.epsilon_decay, 4))

        return {
            "step": self.total_steps,
            "state": state,
            "action": action.name,
            "action_id": action.value,
            "reward": reward,
            "new_q_value": round(new_q, 4),
            "current_rps": self.current_rps,
            "current_burst": self.current_burst,
            "epsilon": self.epsilon,
            "cumulative_reward": round(self.cumulative_reward, 3),
            "auto_pilot": self.auto_pilot,
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "total_steps": self.total_steps,
            "current_rps": self.current_rps,
            "current_burst": self.current_burst,
            "epsilon": self.epsilon,
            "q_states_explored": len(self.q_table),
            "cumulative_reward": round(self.cumulative_reward, 3),
            "auto_pilot": self.auto_pilot,
            "safety_bounds": {
                "min_rps": self.min_rps,
                "max_rps_ceiling": self.max_rps_ceiling,
                "min_burst": self.min_burst,
                "max_burst_ceiling": self.max_burst_ceiling,
            },
        }

    def reset(self) -> None:
        self.current_rps = 6.0
        self.current_burst = 3
        self.epsilon = 0.20
        self.total_steps = 0
        self.cumulative_reward = 0.0
        self.recent_rewards.clear()
        self.q_table.clear()


# Global Singleton instance
global_rl_governor = QLearningGovernor()
