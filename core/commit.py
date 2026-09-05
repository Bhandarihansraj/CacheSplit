from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any
import time
import json

import os
from core.hash_chain import generate_signed_hash, verify_signed_hash

# Loaded from environment. Set CACHESPLIT_SIGNING_KEY in production.
# Falls back to a local dev default — never deploy the default to production.
ORIGIN_SIGNING_KEY = os.getenv("CACHESPLIT_SIGNING_KEY", "cachesplit-dev-key")


class Commit(BaseModel):
    commit_hash: str = ""
    parent_hash: Optional[str] = None
    version_number: int
    json_manifest: str  # Kept as string for hashing simplicity
    affected_entity_id: str
    timestamp: float = Field(default_factory=time.time)
    test_gate_result: Optional[bool] = None

    @field_validator("version_number")
    @classmethod
    def check_version(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Version number must be >= 1")
        return v

    @field_validator("json_manifest")
    @classmethod
    def check_manifest_size(cls, v: str) -> str:
        if len(v) > 1_000_000:  # 1MB limit
            raise ValueError("Manifest exceeds 1MB limit")
        return v

    def run_auto_test_gate(self) -> bool:
        """
        Runs the auto-test gate logic.
        Returns True if passed, False otherwise.
        """
        if not self.json_manifest:
            self.test_gate_result = False
            return False
            
        self.test_gate_result = True
        return True

    def sign(self, secret: str = ORIGIN_SIGNING_KEY) -> str:
        """Signs this commit so its hash is only reproducible by a key-holder."""
        hashable = self.model_dump(exclude={"commit_hash"})
        self.commit_hash = generate_signed_hash(hashable, secret)
        return self.commit_hash

    def verify_signature(self, secret: str = ORIGIN_SIGNING_KEY) -> bool:
        """True only if this commit's hash is authentic under the given key."""
        if not self.commit_hash:
            return False
        hashable = self.model_dump(exclude={"commit_hash"})
        return generate_signed_hash(hashable, secret) == self.commit_hash
