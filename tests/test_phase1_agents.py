import pytest
from agents.security_agent import SecurityAgent
from agents.reconciliation_agent import ReconciliationAgent, registry as rec_registry
from agents.access_logger import AccessLogger


def test_security_agent_flags_anomalous_event():
    agent = SecurityAgent(logger_instance=AccessLogger())
    # Mock score_event to return high anomaly score
    agent._is_trained = True
    original_score = agent.score_event
    agent.score_event = lambda ev: 0.9

    event = {"node_id": "node_99", "entity_id": "pat_rogue", "entity_type": "billing",
             "access_type": "read", "requester_region": "EU-West", "target_region": "US-East"}
    is_anomalous = agent.evaluate(event, threshold=0.7)
    assert is_anomalous is True

    # Also test below threshold
    agent.score_event = lambda ev: 0.3
    assert agent.evaluate(event, threshold=0.7) is False

    agent.score_event = original_score


def test_reconciliation_agent_zero_percent_tampered_as_ok(monkeypatch):
    agent = ReconciliationAgent()
    
    quarantined = []
    def mock_mark_quarantined(node_id, reason):
        quarantined.append(node_id)
    monkeypatch.setattr(rec_registry, "mark_quarantined", mock_mark_quarantined)

    # 1. OK
    assert agent.check({
        "node_id": "n1",
        "current_hash": "hashA",
        "chain_intact": True
    }, "hashA") == "ok"
    
    # 2. Tampered (chain not intact) -> Should never be 'ok'
    assert agent.check({
        "node_id": "n2",
        "current_hash": "hashB",
        "chain_intact": False
    }, "hashA") == "tampered"
    assert "n2" in quarantined
    
    # 3. Tampered (hash differs, chain intact but not version behind) -> Should not be 'ok'
    assert agent.check({
        "node_id": "n3",
        "current_hash": "hashC",
        "chain_intact": True,
        "version_behind": False
    }, "hashA") == "tampered"
    
    # 4. Stale
    assert agent.check({
        "node_id": "n4",
        "current_hash": "hashD",
        "chain_intact": True,
        "version_behind": True
    }, "hashA") == "stale"
    
    # 5. Ambiguous
    assert agent.check({
        "node_id": "n5",
        "current_hash": "hashE",
        "partial_corruption": True
    }, "hashA") == "ambiguous"
    
    # Test resolve_ambiguous logic
    assert agent.resolve_ambiguous({"invalid_signatures": True}) == "tampered"
    assert agent.resolve_ambiguous({"missing_blocks": 5, "invalid_signatures": False}) == "stale"
