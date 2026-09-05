"""
tests/test_phase28_quic_transport.py
Automated test suite for Phase 28: AgentDB QUIC Low-Latency Transport Adapter & Mesh Simulator.
Tests binary packet serialization, multiplexed stream isolation, sub-millisecond mesh broadcasts,
and FastAPI QUIC endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from core.quic_transport import (
    QUICPacket,
    QUICPacketType,
    QUICTransportNode,
    QUICStream,
)
from core.quic_mesh import QUICMeshCoordinator
from api.server import app


# ── 1. Packet Framing & Serialization ────────────────────────────────────────

def test_quic_packet_serialization_roundtrip():
    pkt = QUICPacket(
        stream_id=7,
        packet_type=QUICPacketType.INVALIDATION,
        sender_id="us-east-1",
        payload={"key": "patient:101", "version": 4},
        sequence_num=42,
    )
    raw = pkt.serialize()
    assert isinstance(raw, bytes)

    deserialized = QUICPacket.deserialize(raw)
    assert deserialized.stream_id == 7
    assert deserialized.packet_type == QUICPacketType.INVALIDATION
    assert deserialized.sender_id == "us-east-1"
    assert deserialized.payload["key"] == "patient:101"
    assert deserialized.payload["version"] == 4
    assert deserialized.sequence_num == 42


# ── 2. Stream Multiplexing & Transport Node ──────────────────────────────────

def test_quic_transport_node_stream_multiplexing():
    node_a = QUICTransportNode("us-east-1", port=4433, region="US-East")
    node_b = QUICTransportNode("eu-west-1", port=4434, region="EU-West")

    received = []
    node_b.register_handler(lambda p: received.append(p))

    # Open 2 independent streams
    s1 = node_a.open_stream()
    s2 = node_a.open_stream()
    assert s1.stream_id != s2.stream_id

    p1 = s1.create_packet(QUICPacketType.INVALIDATION, {"key": "entity:0", "v": 2})
    p2 = s2.create_packet(QUICPacketType.INVALIDATION, {"key": "entity:1", "v": 2})

    lat1 = node_a.send_packet(node_b, p1)
    lat2 = node_a.send_packet(node_b, p2)

    assert lat1 is not None and lat1 < 2.0  # Sub-millisecond / near-zero latency
    assert lat2 is not None and lat2 < 2.0
    assert len(received) == 2
    assert len(node_b.streams) == 2


# ── 3. Mesh Coordinator & Stream Isolation Benchmark ─────────────────────────

def test_quic_mesh_broadcast():
    mesh = QUICMeshCoordinator()
    mesh.init_default_cluster()

    broadcast = mesh.broadcast_invalidation(key="doc:rag:security", version=3, sender_id="us-east-1")
    assert broadcast["key"] == "doc:rag:security"
    assert broadcast["version"] == 3
    assert "eu-west-1" in broadcast["deliveries"]
    assert "asia-south-1" in broadcast["deliveries"]
    assert broadcast["deliveries"]["eu-west-1"]["status"] == "DELIVERED"
    assert broadcast["deliveries"]["asia-south-1"]["status"] == "DELIVERED"
    assert broadcast["avg_latency_ms"] < 2.0


def test_quic_stream_isolation_eliminates_hol_blocking():
    mesh = QUICMeshCoordinator()
    mesh.init_default_cluster()

    result = mesh.benchmark_stream_isolation()
    assert result["head_of_line_blocking"] == "ELIMINATED"
    # Clean stream 2 must have 100% delivery rate
    assert result["stream_2_clean"]["packets_delivered"] == 10
    assert result["stream_2_clean"]["packets_sent"] == 10


# ── 4. FastAPI QUIC Endpoints ────────────────────────────────────────────────

def test_fastapi_quic_endpoints():
    client = TestClient(app)

    # 1. Mesh status
    r_status = client.get("/api/quic/mesh-status")
    assert r_status.status_code == 200
    data = r_status.json()
    assert data["mesh_nodes_count"] >= 3
    assert "us-east-1" in data["nodes"]

    # 2. Broadcast endpoint
    b_payload = {
        "key": "user:test:99",
        "version": 5,
        "sender_id": "us-east-1",
        "loss_rate": 0.0,
    }
    r_broadcast = client.post("/api/quic/broadcast", json=b_payload)
    assert r_broadcast.status_code == 200
    b_data = r_broadcast.json()
    assert b_data["key"] == "user:test:99"
    assert b_data["deliveries"]["eu-west-1"]["status"] == "DELIVERED"

    # 3. Benchmark isolation endpoint
    r_bench = client.post("/api/quic/benchmark-isolation")
    assert r_bench.status_code == 200
    bench_data = r_bench.json()
    assert bench_data["head_of_line_blocking"] == "ELIMINATED"
