from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
import time

class Commit(BaseModel):
    commit_hash: str
    parent_hash: Optional[str]
    version_number: int
    json_manifest: dict[str, Any]
    affected_entity_id: str
    timestamp: float = Field(default_factory=time.time)
    test_gate_result: Optional[bool] = None

    def run_auto_test_gate(self) -> bool:
        """
        Runs the auto-test gate logic.
        Returns True if passed, False otherwise.
        """
        # Auto-test gate checks
        if not self.json_manifest:
            self.test_gate_result = False
            return False
            
        # Add basic sanity checks for the manifest content
        # Mark as true if passed
        self.test_gate_result = True
        return True
