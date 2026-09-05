import time
import asyncio
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel

class NodeStatus(BaseModel):
    node_id: str
    region: str
    tier: Literal["main", "sub"]
    parent_node_id: Optional[str] = None
    current_commit_hash: str = ""
    version_number: int = 0
    cache_summary: dict[str, str] = {}
    last_heartbeat: float = 0.0
    health: Literal["ok", "stale", "quarantined"] = "ok"
    agent_flags: list[str] = []
    heartbeat_enabled: bool = True
    handshake_status: Literal["pending", "approved", "rejected"] = "pending"
    join_token: str = ""
    endpoint_url: str = "http://127.0.0.1:8000"

class NodeRegistry:
    MINIMUM_NODE_VERSION = 3

    def __init__(self, timeout_seconds: int = 20):
        self.nodes: Dict[str, NodeStatus] = {}
        self.timeout_seconds = timeout_seconds
        self._sweep_task: Optional[asyncio.Task] = None
        self._emitter_task: Optional[asyncio.Task] = None
        self._running = False

    def start_sweep(self, enable_auto_heartbeat: bool = False):
        """Starts background sweep and optional heartbeat emitter tasks."""
        if not self._running:
            self._running = True
            self._sweep_task = asyncio.create_task(self._sweep_loop())
            if enable_auto_heartbeat:
                self._emitter_task = asyncio.create_task(self._auto_heartbeat_emitter())

    def stop_sweep(self):
        self._running = False
        if self._sweep_task:
            self._sweep_task.cancel()
        if self._emitter_task:
            self._emitter_task.cancel()

    async def _auto_heartbeat_emitter(self):
        """Automatically emits regular heartbeats for nodes where heartbeat_enabled is True."""
        while self._running:
            now = time.time()
            for node_id, status in list(self.nodes.items()):
                if status.heartbeat_enabled and status.health != "quarantined":
                    status.last_heartbeat = now
                    # If it was stale due to timeout, recover it
                    if status.health == "stale" and "timeout" in status.agent_flags:
                        status.health = "ok"
                        status.agent_flags.remove("timeout")
            await asyncio.sleep(4.0)

    async def _sweep_loop(self):
        while self._running:
            self._check_staleness()
            sleep_duration = min(1.0, max(0.2, self.timeout_seconds / 2.0))
            await asyncio.sleep(sleep_duration)

    def _check_staleness(self):
        current_time = time.time()
        for node_id, status in self.nodes.items():
            if status.health == "quarantined":
                continue
            if current_time - status.last_heartbeat > self.timeout_seconds:
                self.mark_stale(node_id, "timeout")

    def register_node(self, node_id: str, region: str, tier: Literal["main", "sub"], parent_node_id: Optional[str] = None, join_token: str = "") -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = NodeStatus(
                node_id=node_id,
                region=region,
                tier=tier,
                parent_node_id=parent_node_id,
                last_heartbeat=time.time(),
                heartbeat_enabled=True,
                join_token=join_token,
                handshake_status="pending"
            )

    def heartbeat(self, node_id: str, current_commit_hash: str, version_number: int, cache_summary: dict[str, str]) -> None:
        if node_id in self.nodes:
            node = self.nodes[node_id]
            node.current_commit_hash = current_commit_hash
            node.version_number = version_number
            node.cache_summary = cache_summary
            node.last_heartbeat = time.time()
            if node.health == "stale" and "timeout" in node.agent_flags:
                node.health = "ok"
                node.agent_flags.remove("timeout")

    def handshake(self, node_id: str, version_number: int, join_token: str) -> bool:
        if node_id in self.nodes:
            node = self.nodes[node_id]
            if version_number < self.MINIMUM_NODE_VERSION:
                node.handshake_status = "rejected"
                return False
            if node.join_token and node.join_token != join_token:
                node.handshake_status = "rejected"
                return False
            
            node.handshake_status = "approved"
            node.version_number = version_number
            return True
        return False

    def toggle_heartbeat(self, node_id: str, enabled: Optional[bool] = None) -> bool:
        if node_id in self.nodes:
            if enabled is None:
                self.nodes[node_id].heartbeat_enabled = not self.nodes[node_id].heartbeat_enabled
            else:
                self.nodes[node_id].heartbeat_enabled = enabled
            return self.nodes[node_id].heartbeat_enabled
        return False

    def recover_node(self, node_id: str) -> None:
        if node_id in self.nodes:
            node = self.nodes[node_id]
            node.health = "ok"
            node.heartbeat_enabled = True
            node.last_heartbeat = time.time()
            node.agent_flags = []

    def get_status(self, node_id: str) -> Optional[NodeStatus]:
        return self.nodes.get(node_id)

    def list_by_region(self, region: str) -> List[NodeStatus]:
        return [n for n in self.nodes.values() if n.region == region]

    def list_all_masters(self) -> List[NodeStatus]:
        return [n for n in self.nodes.values() if n.tier == "main"]

    def mark_stale(self, node_id: str, reason: str) -> None:
        if node_id in self.nodes and self.nodes[node_id].health != "quarantined":
            self.nodes[node_id].health = "stale"
            if reason not in self.nodes[node_id].agent_flags:
                self.nodes[node_id].agent_flags.append(reason)

    def mark_quarantined(self, node_id: str, reason: str) -> None:
        if node_id in self.nodes:
            self.nodes[node_id].health = "quarantined"
            self.nodes[node_id].heartbeat_enabled = False
            if reason not in self.nodes[node_id].agent_flags:
                self.nodes[node_id].agent_flags.append(reason)

# Global singleton
registry = NodeRegistry()
