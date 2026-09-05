import pytest
from datetime import datetime
from core.commit import Commit
from core.hash_chain import generate_hash, verify_integrity, verify_chain

def test_hash_chain_tampering():
    """Unit: tampered json_manifest must break commit_hash verification."""
    commit = Commit(
        parent_hash="0000",
        version_number=1,
        json_manifest='{"status": "active"}',
        affected_entity_id="entity-123"
    )
    # The hashable data excludes commit_hash
    hashable_data = commit.model_dump(exclude={'commit_hash'})
    commit.commit_hash = generate_hash(hashable_data)
    
    # Verify valid
    assert verify_integrity(hashable_data, commit.commit_hash) == True
    
    # Tamper
    commit.json_manifest = '{"status": "deleted"}'
    tampered_data = commit.model_dump(exclude={'commit_hash'})
    assert verify_integrity(tampered_data, commit.commit_hash) == False

def test_business_rule_validator():
    """Unit: reject negative version, reject oversized manifest."""
    # Negative version
    with pytest.raises(ValueError):
        Commit(
            parent_hash="0000",
            version_number=-1,
            json_manifest='{"data": "x"}',
            affected_entity_id="e1"
        )
    
    # Oversized manifest
    large_manifest = '{"data": "' + "x" * 1_000_001 + '"}'
    with pytest.raises(ValueError):
        Commit(
            parent_hash="0000",
            version_number=2,
            json_manifest=large_manifest,
            affected_entity_id="e1"
        )

def test_adversarial_forge_stale_parent():
    """Adversarial: forge a valid-looking commit with a stale parent_hash."""
    commit1 = Commit(parent_hash=None, version_number=1, json_manifest='{}', affected_entity_id="e1")
    commit1.commit_hash = generate_hash(commit1.model_dump(exclude={'commit_hash'}))

    commit2 = Commit(parent_hash=commit1.commit_hash, version_number=2, json_manifest='{}', affected_entity_id="e1")
    commit2.commit_hash = generate_hash(commit2.model_dump(exclude={'commit_hash'}))

    # Forge a commit 3 that points back to commit 1, but claims version 3
    forged = Commit(parent_hash=commit1.commit_hash, version_number=3, json_manifest='{"fake": "data"}', affected_entity_id="e1")
    forged.commit_hash = generate_hash(forged.model_dump(exclude={'commit_hash'}))

    # The chain verifier should reject it if we pass it as a sequence
    commits = [commit1.model_dump(), commit2.model_dump(), forged.model_dump()]
    assert verify_chain(commits) == False
