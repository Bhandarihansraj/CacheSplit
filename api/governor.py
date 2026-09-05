"""
api/governor.py
FastAPI router for AgentDB Reinforcement Learning Stampede Governor.
"""

from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter

from services.adaptive_recovery_service import adaptive_recovery_service

router = APIRouter(prefix="/api/governor", tags=["RL Stampede Governor"])


class GovernorStepRequest(BaseModel):
    origin_latency_ms: float = Field(15.0, description="Origin response latency in ms")
    packet_drop_rate: float = Field(0.20, ge=0.0, le=1.0, description="Network invalidation drop rate")
    stale_key_count: int = Field(4, ge=0, description="Number of stale drifted keys across nodes")
    total_keys: int = Field(10, ge=1, description="Total keys tracked")
    origin_rejections: int = Field(0, ge=0, description="Number of 429/Overload rejections from origin")
    repaired_keys: int = Field(2, ge=0, description="Keys repaired in this cycle")
    dedup_savings: int = Field(3, ge=0, description="Redundant origin calls avoided via coalescing")


class AutoPilotToggleRequest(BaseModel):
    enabled: bool = Field(True, description="Enable or disable autonomous RL adaptation")


@router.get("/state")
def get_governor_state():
    """Returns real-time RL state, current policy parameters, Q-table size, and token bucket status."""
    return adaptive_recovery_service.get_status()


@router.post("/step")
def step_governor(req: GovernorStepRequest):
    """Executes one simulated RL environment step and adapts rate limiting parameters."""
    return adaptive_recovery_service.step_simulation(
        origin_latency_ms=req.origin_latency_ms,
        packet_drop_rate=req.packet_drop_rate,
        stale_key_count=req.stale_key_count,
        total_keys=req.total_keys,
        origin_rejections=req.origin_rejections,
        repaired_keys=req.repaired_keys,
        dedup_savings=req.dedup_savings,
    )


@router.post("/toggle-autopilot")
def toggle_autopilot(req: AutoPilotToggleRequest):
    """Enables or disables autonomous RL rate tuning."""
    status = adaptive_recovery_service.set_autopilot(req.enabled)
    return {"status": "updated", "auto_pilot": status}


@router.post("/reset")
def reset_governor():
    """Resets the Q-table and re-initializes baseline token bucket parameters."""
    adaptive_recovery_service.reset()
    return {"status": "reset", "state": adaptive_recovery_service.get_status()}
