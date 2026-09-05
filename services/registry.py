import time
from typing import Dict, List, Set

class NodeRegistry:
    def __init__(self, timeout_seconds: int = 30):
        self.nodes: Dict[str, float] = {}
        self.node_hashes: Dict[str, Set[str]] = {}
        self.timeout_seconds = timeout_seconds

    def heartbeat(self, node_id: str, hashes: List[str] = None):
        self.nodes[node_id] = time.time()
        if hashes is not None:
            self.node_hashes[node_id] = set(hashes)
            
    def get_active_nodes(self) -> List[str]:
        current_time = time.time()
        active = []
        to_remove = []
        for node_id, last_seen in self.nodes.items():
            if current_time - last_seen <= self.timeout_seconds:
                active.append(node_id)
            else:
                to_remove.append(node_id)
                
        for node_id in to_remove:
            self.remove_node(node_id)
            
        return active

    def remove_node(self, node_id: str):
        if node_id in self.nodes:
            del self.nodes[node_id]
        if node_id in self.node_hashes:
            del self.node_hashes[node_id]

    def find_nodes_for_hash(self, hash_val: str) -> List[str]:
        active_nodes = self.get_active_nodes()
        found_in = []
        for node_id in active_nodes:
            if hash_val in self.node_hashes.get(node_id, set()):
                found_in.append(node_id)
        return found_in
        
registry = NodeRegistry()
