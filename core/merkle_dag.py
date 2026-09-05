import hashlib
import json
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

class EntityNode(BaseModel):
    entity_id: str
    entity_type: str  # "patient", "visit", "lab_result", "bed", "billing"
    data: Dict[str, Any]
    parent_id: Optional[str] = None
    children_ids: List[str] = Field(default_factory=list)
    local_hash: str = ""
    merkle_root_hash: str = ""
    region: str = "US-East"
    anchor_root_id: Optional[str] = None  # Colocation affinity partition key
    version: int = 1  # For Optimistic Concurrency Control (OCC)

    def compute_local_hash(self) -> str:
        payload = {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "data": self.data
        }
        serialized = json.dumps(payload, sort_keys=True)
        self.local_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return self.local_hash

class MerkleDAG:
    """
    Merkle Directed Acyclic Graph:
    Parent Root Hash = SHA256(Parent Data || sum(Child Entity Hashes))
    Guarantees child mutation ripples deterministically up to the root.
    """
    def __init__(self):
        self.entities: Dict[str, EntityNode] = {}
        # Adjacency list: source_id -> list of (relation, target_id)
        self.edges: Dict[str, List[tuple[str, str]]] = {}
        # Reverse edges: target_id -> list of (relation, source_id)
        self.reverse_edges: Dict[str, List[tuple[str, str]]] = {}

    def add_entity(self, entity: EntityNode):
        entity.compute_local_hash()
        self.entities[entity.entity_id] = entity
        if entity.entity_id not in self.edges:
            self.edges[entity.entity_id] = []
        if entity.entity_id not in self.reverse_edges:
            self.reverse_edges[entity.entity_id] = []

    def add_edge(self, source_id: str, relation: str, target_id: str):
        if source_id not in self.edges:
            self.edges[source_id] = []
        if target_id not in self.reverse_edges:
            self.reverse_edges[target_id] = []
            
        self.edges[source_id].append((relation, target_id))
        self.reverse_edges[target_id].append((relation, source_id))
        
        # Link child to parent in entity hierarchy
        if source_id in self.entities and target_id in self.entities:
            if target_id not in self.entities[source_id].children_ids:
                self.entities[source_id].children_ids.append(target_id)
            self.entities[target_id].parent_id = source_id
            
            # Set anchor root ID for colocation affinity
            root_anchor = self.entities[source_id].anchor_root_id or source_id
            self.entities[target_id].anchor_root_id = root_anchor

    def compute_merkle_root(self, entity_id: str) -> str:
        """
        Recursively calculates Merkle Root Hash:
        Parent Root Hash = SHA256(Parent Local Hash || sorted concatenation of child Merkle Root Hashes)
        """
        if entity_id not in self.entities:
            return ""

        node = self.entities[entity_id]
        if not node.local_hash:
            node.compute_local_hash()

        if not node.children_ids:
            node.merkle_root_hash = node.local_hash
            return node.merkle_root_hash

        # Recursively compute children hashes
        child_hashes = []
        for child_id in sorted(node.children_ids):
            if child_id in self.entities:
                ch_hash = self.compute_merkle_root(child_id)
                child_hashes.append(ch_hash)

        # Ripple hash combination: SHA256(local_hash + sum(child_hashes))
        combined = node.local_hash + "".join(child_hashes)
        node.merkle_root_hash = hashlib.sha256(combined.encode("utf-8")).hexdigest()
        return node.merkle_root_hash

    def update_entity_data(self, entity_id: str, new_data: Dict[str, Any]) -> str:
        """
        Updates an entity's data and triggers a deterministic upward Merkle ripple.
        Returns the updated top-level Merkle root hash.
        """
        if entity_id not in self.entities:
            raise KeyError(f"Entity {entity_id} does not exist.")

        node = self.entities[entity_id]
        node.data.update(new_data)
        node.compute_local_hash()

        # Ripple up to root
        curr = node
        while curr.parent_id and curr.parent_id in self.entities:
            curr = self.entities[curr.parent_id]

        # Recompute from the top root
        return self.compute_merkle_root(curr.entity_id)

    def get_relational_tree(self, root_id: str) -> Dict[str, Any]:
        """
        Returns full nested JSON tree of entity and children for UI visualization.
        """
        if root_id not in self.entities:
            return {}

        node = self.entities[root_id]
        tree = {
            "entity_id": node.entity_id,
            "entity_type": node.entity_type,
            "data": node.data,
            "region": node.region,
            "local_hash": node.local_hash[:12] + "...",
            "merkle_root_hash": (node.merkle_root_hash or node.local_hash)[:16] + "...",
            "full_merkle_hash": node.merkle_root_hash or node.local_hash,
            "children": [self.get_relational_tree(ch) for ch in node.children_ids if ch in self.entities]
        }
        return tree
