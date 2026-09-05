import time
import hashlib
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from core.merkle_dag import MerkleDAG, EntityNode
from core.commit import ORIGIN_SIGNING_KEY
from core.hash_chain import generate_signed_hash

class EntityMutation(BaseModel):
    entity_type: str
    entity_id: str
    data: Dict[str, Any]  # renamed from 'diff' for API/UI alignment
    expected_version: Optional[int] = None  # OCC guard

class RelationshipEdge(BaseModel):
    source: str
    relation: str
    target: str

class CompoundCommit(BaseModel):
    transaction_id: str
    timestamp: float = Field(default_factory=time.time)
    mutations: List[EntityMutation]
    edges: List[RelationshipEdge] = Field(default_factory=list)
    commit_hash: str = ""

    def signed_payload(self) -> str:
        """Exact JSON payload that was (or will be) signed — persisted for later verification."""
        return self.model_dump_json(exclude={"commit_hash"})

    def compute_commit_hash(self, secret: str = ORIGIN_SIGNING_KEY) -> str:
        """Signs the commit with the origin key; hash is only reproducible by key-holders."""
        self.commit_hash = generate_signed_hash(json.loads(self.signed_payload()), secret)
        return self.commit_hash

    def apply_to_dag(self, dag: MerkleDAG) -> Dict[str, str]:
        """
        Atomically applies all mutations and edges to the Merkle DAG in a single memory operation.
        Returns dict of updated root entity IDs to their new Merkle Root Hashes.
        """
        # 1. Apply or upsert entities
        updated_roots = set()
        
        # Phase 1a: Pre-flight OCC checks
        for mut in self.mutations:
            if mut.entity_id in dag.entities and mut.expected_version is not None:
                current_version = dag.entities[mut.entity_id].version
                if current_version != mut.expected_version:
                    raise ValueError(f"OCC Conflict: Entity {mut.entity_id} version mismatch (expected {mut.expected_version}, got {current_version})")

        # Phase 1b: Apply mutations
        for mut in self.mutations:
            if mut.entity_id in dag.entities:
                dag.entities[mut.entity_id].data.update(mut.data)
                dag.entities[mut.entity_id].version += 1  # Increment version on edit
                dag.entities[mut.entity_id].compute_local_hash()
            else:
                new_entity = EntityNode(
                    entity_id=mut.entity_id,
                    entity_type=mut.entity_type,
                    data=mut.data
                )
                dag.add_entity(new_entity)

        # 2. Add edges
        for edge in self.edges:
            dag.add_edge(edge.source, edge.relation, edge.target)

        # 3. Recompute affected Merkle Roots
        results = {}
        for mut in self.mutations:
            curr = dag.entities[mut.entity_id]
            while curr.parent_id and curr.parent_id in dag.entities:
                curr = dag.entities[curr.parent_id]
            root_hash = dag.compute_merkle_root(curr.entity_id)
            results[curr.entity_id] = root_hash

        return results
