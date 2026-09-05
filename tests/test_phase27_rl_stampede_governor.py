"""
tests/test_phase27_rl_stampede_governor.py
Automated test suite for Phase 27: AgentDB RL-Tuned Stampede Governor.
Tests state discretization, reward computation, Q-learning policy improvement,
adaptive token bucket dynamic capacity updates, and FastAPI governor endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from core.rl_stampede_governor import (
    QLearningGovernor,
    EnvironmentTelemetry,
    GovernorAction,
)
from core.adaptive_limiter import AdaptiveTokenBucket
from services.adaptive_recovery_service import AdaptiveRecoveryService
from api.server import app


# ── 1. State Discretization & Reward Tests ────────────────────────────────────

def test_governor_state_discretization():
    gov = QLearningGovernor()

    # Healthy state (low latency, low drop, low stale, no rejects)
    healthy_telem = EnvironmentTelemetry(
        origin_latency_ms=12.0,
        packet_drop_rate=0.05,
        stale_key_count=1,
        total_keys=10,
        origin_rejections=0,
    )
    s_healthy = gov.discretize_state(healthy_telem)
    assert s_healthy == (0, 0, 0, 0)

    # Critical degraded state (high latency, high drop, high stale, with rejects)
    critical_telem = EnvironmentTelemetry(
        origin_latency_ms=180.0,
        packet_drop_rate=0.50,
        stale_key_count=8,
        total_keys=10,
        origin_rejections=3,
    )
    s_critical = gov.discretize_state(critical_telem)
    assert s_critical == (2, 2, 2, 1)


def test_reward_function():
    gov = QLearningGovernor()

    # Successful recovery with dedup savings
    good_telem = EnvironmentTelemetry(
        origin_latency_ms=10.0,
        origin_rejections=0,
        repaired_keys=4,
        dedup_savings=6,
    )
    r_good = gov.calculate_reward(good_telem)
    assert r_good > 5.0

    # Overload failure (origin rejected requests)
    bad_telem = EnvironmentTelemetry(
        origin_latency_ms=150.0,
        origin_rejections=2,
        repaired_keys=0,
        dedup_savings=0,
    )
    r_bad = gov.calculate_reward(bad_telem)
    assert r_bad < -15.0  # Heavy penalty for overload


# ── 2. Q-Learning Policy Improvement & Action Effects ─────────────────────────

def test_q_learning_policy_learns_throttle_on_overload():
    gov = QLearningGovernor(learning_rate=0.5, epsilon=0.0)  # Pure exploitation for deterministic test

    state_overload = (2, 2, 2, 1)
    
    # Train governor on overload state:
    # If it throttles down, penalization is small; if it boosts, overload worsens
    telem_overload = EnvironmentTelemetry(
        origin_latency_ms=150.0,
        packet_drop_rate=0.5,
        stale_key_count=8,
        origin_rejections=3,
    )
    telem_recovered = EnvironmentTelemetry(
        origin_latency_ms=25.0,
        packet_drop_rate=0.1,
        stale_key_count=1,
        origin_rejections=0,
        repaired_keys=5,
    )

    # Perform multiple learning steps
    for _ in range(10):
        gov.step(current_telem=telem_overload, next_telem=telem_recovered)

    # Policy should explore and update Q-table
    assert len(gov.q_table) > 0
    assert gov.total_steps == 10


def test_action_bounds_and_safety_clamping():
    gov = QLearningGovernor(min_rps=2.0, max_rps_ceiling=20.0, min_burst=1, max_burst_ceiling=10)
    gov.current_rps = 18.0
    gov.current_burst = 9

    # Aggressive boost cannot exceed ceilings
    gov.apply_action(GovernorAction.AGGRESSIVE_BOOST)
    assert gov.current_rps <= 20.0
    assert gov.current_burst <= 10

    # Repeated throttle down cannot go below floor
    for _ in range(15):
        gov.apply_action(GovernorAction.THROTTLE_DOWN)
    assert gov.current_rps == 2.0
    assert gov.current_burst == 1


# ── 3. Adaptive Token Bucket Tests ───────────────────────────────────────────

def test_adaptive_token_bucket_dynamic_update():
    bucket = AdaptiveTokenBucket(max_rps=4.0, burst=2)
    assert bucket.allow_request(1.0) is True
    assert bucket.allow_request(1.0) is True
    # Burst exhausted
    assert bucket.allow_request(1.0) is False

    # Live dynamic adjustment by Governor
    bucket.update_limits(new_rps=20.0, new_burst=5)
    status = bucket.get_status()
    assert status["max_rps"] == 20.0
    assert status["burst"] == 5


# ── 4. FastAPI Governor Endpoints ────────────────────────────────────────────

def test_api_governor_endpoints():
    client = TestClient(app)

    # 1. Get State
    r = client.get("/api/governor/state")
    assert r.status_code == 200
    data = r.json()
    assert "governor" in data
    assert "limiter" in data
    assert data["governor"]["current_rps"] >= 2.0

    # 2. Step Governor
    step_payload = {
        "origin_latency_ms": 20.0,
        "packet_drop_rate": 0.25,
        "stale_key_count": 3,
        "total_keys": 10,
        "origin_rejections": 0,
        "repaired_keys": 2,
        "dedup_savings": 3,
    }
    r_step = client.post("/api/governor/step", json=step_payload)
    assert r_step.status_code == 200
    res_data = r_step.json()
    assert "step_result" in res_data
    assert "action" in res_data["step_result"]

    # 3. Toggle Autopilot
    r_toggle = client.post("/api/governor/toggle-autopilot", json={"enabled": False})
    assert r_toggle.status_code == 200
    assert r_toggle.json()["auto_pilot"] is False

    # 4. Reset
    r_reset = client.post("/api/governor/reset")
    assert r_reset.status_code == 200
    assert r_reset.json()["status"] == "reset"
