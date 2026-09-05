"""
services/quic_mesh_service.py
Service managing QUIC transport lifecycle and cross-node mesh operations.
"""

from typing import Dict, Any, Optional

from core.quic_mesh import global_quic_mesh, QUICMeshCoordinator


class QUICMeshService:
    """
    Coordinates QUIC transport and high-frequency invalidation broadcasts.
    """

    def __init__(self, coordinator: Optional[QUICMeshCoordinator] = None):
        self.coordinator = coordinator or global_quic_mesh

    def get_mesh_status(self) -> Dict[str, Any]:
        return self.coordinator.get_topology_status()

    def broadcast_invalidation(
        self,
        key: str,
        version: int,
        sender_id: str = "us-east-1",
        loss_rate: float = 0.0,
    ) -> Dict[str, Any]:
        return self.coordinator.broadcast_invalidation(
            key=key,
            version=version,
            sender_id=sender_id,
            loss_rate=loss_rate,
        )

    def run_stream_isolation_benchmark(self) -> Dict[str, Any]:
        return self.coordinator.benchmark_stream_isolation()


quic_mesh_service = QUICMeshService()
