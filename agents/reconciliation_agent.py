from typing import Literal
import logging

from services.registry import registry

class ReconciliationAgent:
    def check(self, node_status: dict, expected_commit_hash: str) -> Literal["ok", "stale", "tampered", "ambiguous"]:
        node_id = node_status.get("node_id")
        current_hash = node_status.get("current_hash")
        chain_intact = node_status.get("chain_intact", True)
        version_behind = node_status.get("version_behind", False)
        partial_corruption = node_status.get("partial_corruption", False)

        if current_hash == expected_commit_hash:
            return "ok"
        
        if partial_corruption:
            return "ambiguous"

        if not chain_intact:
            logging.warning(f"Tampered node detected: {node_id}")
            registry.mark_quarantined(node_id, "Chain doesn't verify")
            return "tampered"
            
        if chain_intact and version_behind:
            return "stale"

        # If it doesn't match hash and is not stale or ambiguous, we consider it tampered
        logging.warning(f"Tampered node detected: {node_id}")
        registry.mark_quarantined(node_id, "Hash mismatch with intact chain but not version behind")
        return "tampered"

    def resolve_ambiguous(self, node_status: dict) -> Literal["stale", "tampered"]:
        # Rule-based decision tree for ambiguous cases
        invalid_signatures = node_status.get("invalid_signatures", False)
        missing_blocks = node_status.get("missing_blocks", 0)
        
        if invalid_signatures:
            return "tampered"
        elif missing_blocks > 0:
            return "stale"
        else:
            return "tampered"
