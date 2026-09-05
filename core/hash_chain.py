import hashlib
import json
from typing import Any, List, Dict

def generate_hash(data: Dict[str, Any]) -> str:
    """
    Generates a SHA256 hash for a given dictionary representing commit data.
    """
    data_str = json.dumps(data, sort_keys=True)
    return hashlib.sha256(data_str.encode('utf-8')).hexdigest()

def verify_integrity(commit_data: Dict[str, Any], expected_hash: str) -> bool:
    """
    Verifies if the SHA256 hash of the commit_data matches the expected_hash.
    """
    computed_hash = generate_hash(commit_data)
    return computed_hash == expected_hash

def verify_chain(commits: List[Dict[str, Any]]) -> bool:
    """
    Verifies a chain of commits. Each commit's parent_hash must match the previous commit's hash.
    Assumes commits are ordered from oldest to newest.
    """
    if not commits:
        return True
        
    for i in range(1, len(commits)):
        prev_commit = commits[i-1]
        curr_commit = commits[i]
        
        # Verify current commit's integrity (excluding the hash itself)
        expected_curr_hash = curr_commit.get('commit_hash')
        hashable_data = {k: v for k, v in curr_commit.items() if k != 'commit_hash'}
        if expected_curr_hash and generate_hash(hashable_data) != expected_curr_hash:
            return False
            
        # Verify link to parent
        if curr_commit.get('parent_hash') != prev_commit.get('commit_hash'):
            return False
            
    return True
