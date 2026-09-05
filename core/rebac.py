from typing import List, Dict, Optional, Set, Any
from core.merkle_dag import MerkleDAG

class ReBACPolicy:
    """
    Relationship-Based Access Control (ReBAC)
    Enforces contextual graph authorization.
    Example: Access Granted <=> Path(Clinician -> ASSIGNED_TO -> Visit -> CONTAINS -> LabResult) exists.
    """
    def __init__(self, dag: MerkleDAG):
        self.dag = dag

    def has_access_path(self, subject_id: str, target_id: str, max_depth: int = 4) -> bool:
        """
        Performs bidirectional Breadth-First Search (BFS) along relationship edges
        to confirm subject is connected to target entity via care-team relationships.
        """
        if subject_id == target_id:
            return True

        if subject_id not in self.dag.edges and subject_id not in self.dag.reverse_edges:
            return False

        visited: Set[str] = set([subject_id])
        queue: List[tuple[str, int]] = [(subject_id, 0)]

        while queue:
            curr_node, depth = queue.pop(0)
            if curr_node == target_id:
                return True
            if depth >= max_depth:
                continue

            # Check outbound edges
            for _, neighbor in self.dag.edges.get(curr_node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

            # Check inbound edges (relational reciprocity)
            for _, neighbor in self.dag.reverse_edges.get(curr_node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

        return False

    def authorize_read(self, clinician_id: str, target_entity_id: str) -> Dict[str, Any]:
        """
        Validates whether clinician is legally assigned to the patient or records.
        """
        if not self.has_access_path(clinician_id, target_entity_id):
            return {
                "authorized": False,
                "reason": f"ReBAC Violation: No care-relationship path exists between {clinician_id} and {target_entity_id}.",
                "clinician_id": clinician_id,
                "target_id": target_entity_id
            }

        target_node = self.dag.entities.get(target_entity_id)
        return {
            "authorized": True,
            "clinician_id": clinician_id,
            "target_id": target_entity_id,
            "entity_type": target_node.entity_type if target_node else "unknown",
            "data": target_node.data if target_node else {}
        }
