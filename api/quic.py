"""
api/quic.py
FastAPI router for QUIC Transport and Cross-Node Mesh Invalidation.
"""

from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter

from services.quic_mesh_service import quic_mesh_service

router = APIRouter(prefix="/api/quic", tags=["QUIC Transport"])


class QUICBroadcastRequest(BaseModel):
    key: str = Field("patient:101", description="Cache entity key to invalidate")
    version: int = Field(2, description="Target version")
    sender_id: str = Field("us-east-1", description="Sender node ID")
    loss_rate: float = Field(0.0, ge=0.0, le=1.0, description="Simulated UDP packet drop rate")


@router.get("/mesh-status")
def get_mesh_status():
    """Returns QUIC mesh topology, active peer sockets, and transmission latency."""
    return quic_mesh_service.get_mesh_status()


@router.post("/broadcast")
def broadcast_invalidation(req: QUICBroadcastRequest):
    """Broadcasts cache invalidation across all regional QUIC peers on multiplexed parallel streams."""
    return quic_mesh_service.broadcast_invalidation(
        key=req.key,
        version=req.version,
        sender_id=req.sender_id,
        loss_rate=req.loss_rate,
    )


@router.post("/benchmark-isolation")
def benchmark_stream_isolation():
    """Runs head-of-line blocking benchmark comparing lossy and clean multiplexed streams."""
    return quic_mesh_service.run_stream_isolation_benchmark()
