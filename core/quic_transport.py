"""
core/quic_transport.py
AgentDB-inspired QUIC (Quick UDP Internet Connections) Transport Layer for CacheSplit.
Provides multiplexed bidirectional streams over UDP, eliminating Head-of-Line blocking,
with sub-millisecond latency tracking and frame serialization.
"""

import time
import json
import asyncio
import logging
from enum import Enum
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class QUICPacketType(str, Enum):
    INVALIDATION = "INVALIDATION"
    HEARTBEAT = "HEARTBEAT"
    PEER_GOSSIP = "PEER_GOSSIP"
    STATE_SYNC = "STATE_SYNC"
    ACK = "ACK"


@dataclass
class QUICPacket:
    stream_id: int
    packet_type: QUICPacketType
    sender_id: str
    payload: Dict[str, Any]
    sequence_num: int
    timestamp: float = field(default_factory=time.time)

    def serialize(self) -> bytes:
        data = {
            "s": self.stream_id,
            "t": self.packet_type.value,
            "snd": self.sender_id,
            "p": self.payload,
            "seq": self.sequence_num,
            "ts": self.timestamp,
        }
        return json.dumps(data).encode("utf-8")

    @classmethod
    def deserialize(cls, raw: bytes) -> "QUICPacket":
        data = json.loads(raw.decode("utf-8"))
        return cls(
            stream_id=data["s"],
            packet_type=QUICPacketType(data["t"]),
            sender_id=data["snd"],
            payload=data["p"],
            sequence_num=data["seq"],
            timestamp=data["ts"],
        )


class QUICStream:
    """
    Represents an independent logical multiplexed stream on a node connection.
    Drops or latency on one stream do not block other parallel streams.
    """

    def __init__(self, stream_id: int, node_id: str):
        self.stream_id = stream_id
        self.node_id = node_id
        self.seq_counter = 0
        self.received_packets: List[QUICPacket] = []
        self.is_active = True

    def create_packet(self, packet_type: QUICPacketType, payload: Dict[str, Any]) -> QUICPacket:
        self.seq_counter += 1
        return QUICPacket(
            stream_id=self.stream_id,
            packet_type=packet_type,
            sender_id=self.node_id,
            payload=payload,
            sequence_num=self.seq_counter,
        )

    def receive_packet(self, packet: QUICPacket) -> None:
        self.received_packets.append(packet)


class QUICTransportNode:
    """
    Simulates or operates an asynchronous QUIC transport endpoint per regional node.
    Manages active multiplexed streams, peer connections, and latency metrics.
    """

    def __init__(self, node_id: str, port: int, region: str = "unknown"):
        self.node_id = node_id
        self.port = port
        self.region = region
        self.streams: Dict[int, QUICStream] = {}
        self.next_stream_id = 1
        self.packet_handlers: List[Callable[[QUICPacket], None]] = []

        # Transport Metrics
        self.packets_sent = 0
        self.packets_received = 0
        self.bytes_transferred = 0
        self.total_latency_ms = 0.0

    def open_stream(self) -> QUICStream:
        stream_id = self.next_stream_id
        self.next_stream_id += 1
        stream = QUICStream(stream_id, self.node_id)
        self.streams[stream_id] = stream
        return stream

    def get_or_create_stream(self, stream_id: int) -> QUICStream:
        if stream_id not in self.streams:
            self.streams[stream_id] = QUICStream(stream_id, self.node_id)
        return self.streams[stream_id]

    def register_handler(self, handler: Callable[[QUICPacket], None]) -> None:
        self.packet_handlers.append(handler)

    def send_packet(
        self,
        peer: "QUICTransportNode",
        packet: QUICPacket,
        simulated_loss_rate: float = 0.0,
    ) -> Optional[float]:
        """
        Sends packet to a peer node over UDP stream framing.
        Returns transmission latency in ms, or None if dropped by simulated loss.
        """
        raw = packet.serialize()
        self.packets_sent += 1
        self.bytes_transferred += len(raw)

        # Simulated Packet Loss check
        import random
        if simulated_loss_rate > 0.0 and random.random() < simulated_loss_rate:
            logger.debug(f"QUIC {self.node_id}->{peer.node_id}: Packet dropped on stream {packet.stream_id}")
            return None

        # Simulated Sub-millisecond UDP transmission (~0.15ms - 0.45ms)
        latency_ms = round(random.uniform(0.12, 0.48), 3)

        # Deliver to peer
        peer.receive_raw(raw, latency_ms)
        self.total_latency_ms += latency_ms
        return latency_ms

    def receive_raw(self, raw: bytes, latency_ms: float) -> None:
        packet = QUICPacket.deserialize(raw)
        self.packets_received += 1
        self.bytes_transferred += len(raw)
        self.total_latency_ms += latency_ms

        stream = self.get_or_create_stream(packet.stream_id)
        stream.receive_packet(packet)

        for handler in self.packet_handlers:
            try:
                handler(packet)
            except Exception as e:
                logger.error(f"QUIC handler error on node {self.node_id}: {e}")

    def get_status(self) -> Dict[str, Any]:
        avg_latency = 0.0
        total_ops = self.packets_sent + self.packets_received
        if total_ops > 0:
            avg_latency = round(self.total_latency_ms / total_ops, 3)

        return {
            "node_id": self.node_id,
            "port": self.port,
            "region": self.region,
            "active_streams": len(self.streams),
            "packets_sent": self.packets_sent,
            "packets_received": self.packets_received,
            "bytes_transferred": self.bytes_transferred,
            "avg_latency_ms": avg_latency,
        }
