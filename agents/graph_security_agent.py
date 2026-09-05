from typing import Dict, Any, List
from core.merkle_dag import MerkleDAG

class GraphSecurityAgent:
    """
    Graph-Level Anomaly Detection:
    1. Detects orphaned queries (scraping billing/lab records without active patient context).
    2. Detects geographic jurisdiction violations (EU node accessing US-restricted clinical data).
    3. Triggers node quarantine and security alerts.
    """
    def __init__(self, dag: MerkleDAG):
        self.dag = dag
        self.audit_log: List[Dict[str, Any]] = []

    def evaluate_traversal(self, requesting_node_id: str, requester_region: str, target_entity_id: str) -> Dict[str, Any]:
        entity = self.dag.entities.get(target_entity_id)
        if not entity:
            return {"verdict": "unknown_entity", "flagged": False}

        # 1. Geographic Compliance & Data Residency Check
        if entity.region and requester_region and entity.region != requester_region:
            flag_reason = f"Cross-Jurisdiction Breach: Node in {requester_region} attempted to access {entity.region}-restricted data ({target_entity_id})."
            self.audit_log.append({
                "type": "RESIDENCY_VIOLATION",
                "node_id": requesting_node_id,
                "target": target_entity_id,
                "reason": flag_reason,
                "severity": "CRITICAL"
            })
            return {"verdict": "quarantine", "flagged": True, "reason": flag_reason, "severity": "CRITICAL"}

        # 2. Orphan Scraping Check
        # Billing records must be traversed via Patient/Visit, never isolated direct access
        if entity.entity_type == "billing" and not entity.parent_id:
            flag_reason = f"Structural Anomaly: Direct scraping of orphan billing record '{target_entity_id}' without parent visit context."
            self.audit_log.append({
                "type": "ORPHAN_SCRAPE",
                "node_id": requesting_node_id,
                "target": target_entity_id,
                "reason": flag_reason,
                "severity": "HIGH"
            })
            return {"verdict": "quarantine", "flagged": True, "reason": flag_reason, "severity": "HIGH"}

        return {"verdict": "clear", "flagged": False, "severity": "INFO"}
