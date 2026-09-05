import hashlib
import hmac
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


# ───────────────────────── AUTHENTIC SIGNATURES ─────────────────────────────
# Content hashing above is tamper-EVIDENT: anyone can recompute a valid hash.
# The functions below make chains tamper-PROOF against non-key-holders: a valid
# chain can only be produced by someone holding the origin signing key.

def generate_signature(data: Dict[str, Any], secret: str) -> str:
    """HMAC-SHA256 signature of the canonical JSON representation of `data`."""
    data_str = json.dumps(data, sort_keys=True)
    return hmac.new(secret.encode('utf-8'), data_str.encode('utf-8'), hashlib.sha256).hexdigest()


def verify_signature(data: Dict[str, Any], secret: str, signature: str) -> bool:
    """Constant-time comparison of a signature against the recomputed HMAC."""
    return hmac.compare_digest(generate_signature(data, secret), signature)


def generate_signed_hash(data: Dict[str, Any], secret: str) -> str:
    """Chain a content hash with its keyed signature so the hash is only reproducible by key-holders."""
    sig = generate_signature(data, secret)
    return hashlib.sha256(
        (json.dumps(data, sort_keys=True) + "|" + sig).encode('utf-8')
    ).hexdigest()


def verify_signed_hash(data: Dict[str, Any], expected_hash: str, secret: str) -> bool:
    return hmac.compare_digest(generate_signed_hash(data, secret), expected_hash)


def verify_signed_chain(commits: List[Dict[str, Any]], secret: str) -> bool:
    """
    Verifies a persisted chain where each row carries `commit_hash` and the
    exact `hashable_json` payload that was signed when it was written.
    Returns True only if every signed row recomputes to its stored hash
    under the given secret. Rows without a stored payload are treated as
    unverifiable (cannot be trusted).
    """
    if not commits:
        return False

    for row in commits:
        payload = row.get("hashable_json")
        expected = row.get("commit_hash")
        if not payload or not expected:
            return False
        if not verify_signed_hash(json.loads(payload), expected, secret):
            return False
    return True
