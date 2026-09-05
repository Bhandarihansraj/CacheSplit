import hashlib
import bisect
from typing import List, Optional

class HashRing:
    def __init__(self, nodes: Optional[List[str]] = None, replicas: int = 3):
        self.replicas = replicas
        self.ring = {}
        self.sorted_keys = []
        
        if nodes:
            for node in nodes:
                self.add_node(node)

    def _hash(self, key: str) -> int:
        """Hash a key to a degree on a 360-degree ring."""
        return int(hashlib.md5(key.encode('utf-8')).hexdigest(), 16) % 360

    def add_node(self, node: str):
        """Add a node and its virtual replicas to the hash ring."""
        for i in range(self.replicas):
            virtual_node = f"{node}:{i}"
            key = self._hash(virtual_node)
            # Handle collisions by moving to the next degree
            while key in self.ring and self.ring[key] != node:
                key = (key + 1) % 360
            
            if key not in self.ring:
                self.ring[key] = node
                bisect.insort(self.sorted_keys, key)

    def remove_node(self, node: str):
        """Remove a node and all its virtual replicas from the hash ring."""
        keys_to_remove = [k for k, v in self.ring.items() if v == node]
        for k in keys_to_remove:
            del self.ring[k]
            self.sorted_keys.remove(k)

    def get_node(self, entity_id: str) -> Optional[str]:
        """Locate the node that owns the given entity_id."""
        if not self.ring:
            return None
        
        key = self._hash(entity_id)
        idx = bisect.bisect_right(self.sorted_keys, key)
        if idx == len(self.sorted_keys):
            idx = 0
            
        return self.ring[self.sorted_keys[idx]]
