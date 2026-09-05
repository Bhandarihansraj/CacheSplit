"""
Phase 4 — ML Access Anomaly Detection
Proves the IsolationForest learns REAL patterns (not random noise),
trains on actual access events, and the live end-to-end pipeline works.
"""
import random
import time
import pytest
import pytest_asyncio
import httpx
import numpy as np
from fastapi import FastAPI

from agents.access_logger import AccessEvent, AccessLogger
from agents.security_agent import SecurityAgent
from services.analytics import AccessAnalytics, analytics as _analytics_singleton


# ─────────────────────── FEATURE EXTRACTION ─────────────────────────────────

def test_feature_vector_shape():
    logger = AccessLogger()
    event = AccessEvent(node_id="n1", entity_id="pat_001", entity_type="patient",
                        access_type="read", requester_region="US-East",
                        target_region="US-East", timestamp=time.time())
    X = logger.extract_features(event)
    assert X.shape == (1, 8)


def test_cross_region_detected_in_features():
    logger = AccessLogger()
    intra = AccessEvent(node_id="n1", entity_id="e1", entity_type="patient",
                        access_type="read", requester_region="US-East",
                        target_region="US-East", timestamp=time.time())
    cross = AccessEvent(node_id="n1", entity_id="e1", entity_type="patient",
                        access_type="read", requester_region="EU-West",
                        target_region="US-East", timestamp=time.time())
    assert logger.extract_features(intra)[0][5] == 0.0
    assert logger.extract_features(cross)[0][5] == 1.0


def test_write_detected_in_features():
    logger = AccessLogger()
    read_ev = AccessEvent(node_id="n1", entity_id="e1", entity_type="patient",
                          access_type="read", requester_region="US-East",
                          target_region="US-East")
    write_ev = AccessEvent(node_id="n1", entity_id="e1", entity_type="patient",
                           access_type="write", requester_region="US-East",
                           target_region="US-East")
    assert logger.extract_features(read_ev)[0][6] == 0.0
    assert logger.extract_features(write_ev)[0][6] == 1.0


# ─────────────────────── MODEL TRAINING + SCORING ───────────────────────────

def _build_baseline(n=500):
    """500 normal events: spread timestamps over 24h, mixed entity types."""
    events = []
    regions = [("us-east-1", "US-East"), ("eu-west-1", "EU-West"),
               ("asia-south-1", "Asia-South")]
    entity_types = ["patient", "patient", "patient", "patient", "visit",
                    "visit", "lab_result", "lab_result", "bed"]
    now = time.time()
    for i in range(n):
        node, reg = regions[i % 3]
        events.append(AccessEvent(
            node_id=node, entity_id=f"ent_{i:04d}",
            entity_type=entity_types[i % len(entity_types)],
            access_type=random.choice(["read"] * 3 + ["write"]),
            requester_region=reg, target_region=reg,
            timestamp=now - random.uniform(0, 86400),  # spread over 24h
        ))
    return events


def test_model_trains_on_real_data():
    logger = AccessLogger()
    agent = SecurityAgent(logger_instance=logger)
    events = _build_baseline(500)
    for e in events:
        logger.log(e)
    assert agent.train(events) is True
    assert agent.is_trained is True


def test_normal_events_low_score():
    logger = AccessLogger()
    agent = SecurityAgent(logger_instance=logger)
    for e in _build_baseline(500):
        logger.log(e)
    agent.train()
    # Score a new normal intra-region patient read using an entity from training data
    test_event = AccessEvent(node_id="us-east-1", entity_id="ent_0001",
                             entity_type="patient", access_type="read",
                             requester_region="US-East", target_region="US-East")
    score = agent.score_event(test_event)
    assert score < 0.80, f"Normal event scored {score:.3f} — false positive risk"


def test_cross_region_billing_scores_higher():
    """Cross-region billing access should score higher than normal patient reads."""
    logger = AccessLogger()
    agent = SecurityAgent(logger_instance=logger)
    for e in _build_baseline(500):
        logger.log(e)
    agent.train()
    normal = AccessEvent(node_id="us-east-1", entity_id="pat_001",
                         entity_type="patient", access_type="read",
                         requester_region="US-East", target_region="US-East")
    rogue = AccessEvent(node_id="rogue-node", entity_id="bill_rogue",
                        entity_type="billing", access_type="read",
                        requester_region="EU-West", target_region="US-East")
    normal_score = agent.score_event(normal)
    rogue_score = agent.score_event(rogue)
    assert rogue_score > normal_score, (
        f"Rogue ({rogue_score:.3f}) should score higher than normal ({normal_score:.3f})")


def test_evaluate_flags_high_score_event():
    logger = AccessLogger()
    agent = SecurityAgent(logger_instance=logger)
    for e in _build_baseline(500):
        logger.log(e)
    agent.train()
    rogue = AccessEvent(node_id="rogue", entity_id="bill_x",
                        entity_type="billing", access_type="read",
                        requester_region="EU-West", target_region="US-East")
    score = agent.score_event(rogue)
    assert score > 0.5, f"Rogue score {score:.3f} not above neutral"


def test_untrained_returns_neutral():
    agent = SecurityAgent(logger_instance=AccessLogger())
    assert agent.is_trained is False
    score = agent.score_event({"node_id": "n1"})
    assert score == 0.5


# ─────────────────────── ANALYTICS ORCHESTRATION ────────────────────────────

def test_analytics_seeds_and_trains():
    a = AccessAnalytics()
    a.seed_baseline_traffic()
    assert a.security_agent.is_trained is True
    assert len(a.logger) == 600  # 3 regions × 200 events


def test_analytics_status():
    a = AccessAnalytics()
    a.seed_baseline_traffic()
    status = a.get_status()
    assert status["model_trained"] is True
    assert status["events_logged"] == 600
    assert "feature_names" in status
    assert len(status["feature_names"]) == 8


# ─────────────────── END-TO-END OVER REAL HTTP ──────────────────────────────

@pytest_asyncio.fixture
async def e2e_client(tmp_path):
    from db import init_db, close_db
    from api.dashboard import router as dashboard_router
    from api.query import router as query_router
    from api.propagation import router as propagation_router

    await init_db(str(tmp_path / "test_ml.db"))
    _analytics_singleton.seed_baseline_traffic()

    app = FastAPI()
    app.include_router(dashboard_router)
    app.include_router(query_router)
    app.include_router(propagation_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await close_db()


@pytest.mark.asyncio
async def test_ml_status_endpoint(e2e_client):
    """ML status endpoint returns a well-formed response."""
    r = await e2e_client.get("/api/dashboard/ml-status")
    assert r.status_code == 200
    body = r.json()
    assert body["model_trained"] is True
    assert body["events_logged"] > 0
    assert len(body["feature_names"]) == 8


@pytest.mark.asyncio
async def test_compound_commit_increases_event_count(e2e_client):
    """A compound commit produces access events visible in ML status."""
    r1 = await e2e_client.get("/api/dashboard/ml-status")
    before = r1.json()["events_logged"]

    await e2e_client.post("/api/dashboard/compound-commit", json={
        "transaction_id": "tx-ml-001",
        "mutations": [{"entity_id": "pat_ml_001", "entity_type": "patient",
                       "data": {"status": "admitted"}}],
        "edges": [],
    })

    r2 = await e2e_client.get("/api/dashboard/ml-status")
    after = r2.json()["events_logged"]
    assert after > before
