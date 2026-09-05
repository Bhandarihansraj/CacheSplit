"""
api/simulation.py
FastAPI router for CacheSplit v4 Stampede Recovery Simulation.
Endpoints allow starting simulations, polling real-time snapshots,
triggering origin writes/invalidations, and manually stepping recovery cycles.
"""
import asyncio
import logging
import uuid
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, BackgroundTasks, HTTPException

from core.origin import Origin
from core.cache_node import CacheNode
from core.invalidation_bus import InvalidationBus
from core.recovery_coordinator import RecoveryCoordinator
from services.state_manager import state_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sim", tags=["simulation"])


class SimConfig(BaseModel):
    node_count: int = Field(default=4, ge=1, le=10)
    key_count: int = Field(default=5, ge=1, le=50)
    drop_prob: float = Field(default=0.4, ge=0.0, le=1.0)
    max_rps: float = Field(default=6.0, gt=0.0, le=100.0)
    burst: int = Field(default=3, ge=1, le=50)
    max_cycles: int = Field(default=12, ge=1, le=100)


class SimUpdateRequest(BaseModel):
    key: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


# Module-level simulation state
class SimulationState:
    def __init__(self):
        self.sim_id: Optional[str] = None
        self.config: SimConfig = SimConfig()
        self.origin: Optional[Origin] = None
        self.bus: Optional[InvalidationBus] = None
        self.nodes: list[CacheNode] = []
        self.coordinator: Optional[RecoveryCoordinator] = None
        self.is_running: bool = False
        self.event_log: list[dict] = []
        self.keys: list[str] = []

    def reset(self, config: SimConfig):
        self.sim_id = str(uuid.uuid4())[:8]
        self.config = config
        self.origin = Origin(capacity_rps=config.max_rps, burst=config.burst)
        self.bus = InvalidationBus(delivery_prob=1.0 - config.drop_prob, max_delay_ms=80)
        self.nodes = [
            CacheNode(node_id=f"node-{i}", region=f"region-{(i % 3) + 1}")
            for i in range(config.node_count)
        ]
        for node in self.nodes:
            self.bus.subscribe(node)

        self.coordinator = RecoveryCoordinator(
            nodes=self.nodes, origin=self.origin, state_manager=state_manager
        )
        self.keys = [f"entity:{i}" for i in range(config.key_count)]
        self.event_log = []

        # Seed keys across origin and nodes at v1
        for key in self.keys:
            record = self.origin.seed(key, {"value": 100, "status": "initial"})
            for node in self.nodes:
                node.seed(key, record)

        self.event_log.append({
            "type": "SEED",
            "detail": f"Initialized {config.node_count} nodes with {config.key_count} keys at v1 (Capacity: {config.max_rps} RPS)",
        })
        self.is_running = True

    def snapshot(self) -> dict:
        if not self.coordinator or not self.origin:
            return {
                "active": False,
                "sim_id": None,
                "config": self.config.model_dump(),
                "nodes": [],
                "origin_versions": {},
                "bucket_level": 1.0,
                "repair_queue_depth": 0,
                "converged": True,
                "origin_hits": 0,
                "origin_rejects": 0,
                "dedup_savings": 0,
                "cycles": 0,
                "event_log": [],
            }

        coord_snap = self.coordinator.snapshot()
        all_events = self.event_log + coord_snap.get("event_log", []) + self.bus.event_log
        return {
            "active": True,
            "sim_id": self.sim_id,
            "config": self.config.model_dump(),
            "nodes": coord_snap.get("nodes", []),
            "origin_versions": coord_snap.get("origin_versions", {}),
            "bucket_level": coord_snap.get("bucket_level", 1.0),
            "repair_queue_depth": coord_snap.get("repair_queue_depth", 0),
            "converged": coord_snap.get("converged", True),
            "origin_hits": coord_snap.get("origin_hits", 0),
            "origin_rejects": coord_snap.get("origin_rejects", 0),
            "dedup_savings": coord_snap.get("dedup_savings", 0),
            "cycles": coord_snap.get("cycles", 0),
            "event_log": all_events[-30:],
        }


sim_state = SimulationState()
# Auto-seed a default simulation on load
sim_state.reset(SimConfig())


@router.get("/config")
async def get_config():
    """Return default and active simulation parameters."""
    return {
        "active_sim_id": sim_state.sim_id,
        "config": sim_state.config.model_dump(),
        "is_active": sim_state.is_running,
    }


@router.post("/start")
async def start_simulation(config: Optional[SimConfig] = None):
    """Start or reset the simulation cluster with given parameters."""
    active_config = config or SimConfig()
    sim_state.reset(active_config)
    return {
        "status": "started",
        "sim_id": sim_state.sim_id,
        "config": active_config.model_dump(),
    }


@router.get("/snapshot")
async def get_snapshot():
    """Poll real-time simulation state: node versions, states, bucket level, event log."""
    return sim_state.snapshot()


@router.post("/update")
async def trigger_update(req: Optional[SimUpdateRequest] = None):
    """
    Trigger an origin update on a key.
    Increments origin version and broadcasts lossy/delayed invalidations across the cluster.
    """
    if not sim_state.is_running or not sim_state.origin or not sim_state.bus:
        sim_state.reset(SimConfig())

    key = (req.key if req and req.key else None) or (
        sim_state.keys[0] if sim_state.keys else "entity:0"
    )
    data = (req.data if req and req.data else None) or {
        "value": 200,
        "updated": True,
    }

    record = sim_state.origin.update(key, data)
    broadcast_res = await sim_state.bus.broadcast(key, record.version)

    sim_state.event_log.append({
        "type": "INVALIDATION",
        "detail": f"Origin updated {key} -> v{record.version} (Delivered: {broadcast_res['delivered']}, Dropped: {broadcast_res['dropped']})",
        "key": key,
        "version": record.version,
    })

    return {
        "status": "updated",
        "key": key,
        "new_version": record.version,
        "broadcast": broadcast_res,
    }


@router.post("/step")
async def step_cycle():
    """Manually advance one recovery cycle (gossip detection + deduplicated repair)."""
    if not sim_state.coordinator:
        raise HTTPException(status_code=400, detail="Simulation not started")

    result = await sim_state.coordinator.run_cycle()
    return {
        "status": "stepped",
        "cycle": result.get("cycle", 0),
        "converged": result.get("converged", False),
        "origin_hits": result.get("origin_hits", 0),
        "origin_rejects": result.get("origin_rejects", 0),
        "dedup_savings": result.get("dedup_savings", 0),
        "repaired_nodes": result.get("repaired_nodes", 0),
    }
