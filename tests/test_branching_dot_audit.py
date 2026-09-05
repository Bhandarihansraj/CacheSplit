"""
tests/test_branching_dot_audit.py
Unit tests for Git-Style Node Branching, Dot-Notation Indexing, Lazy Cache, and Batch Audit Fabric.
"""
import pytest
import asyncio
import time

from core.merkle_dag import MerkleDAG, EntityNode
from core.branch_engine import BranchEngine
from core.dot_indexer import DotIndexer
from core.lazy_cache import LazyCacheStore
from agents.audit_ml_verifier import AuditMLVerifier
from services.audit_batcher import AuditBatcher
from services.audit_trail_service import AuditTrailService
from db.database import init_db, close_db


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db(":memory:")
    yield
    await close_db()


# ── 1. Git-Style Branching Engine ─────────────────────────────────────────────

def test_branch_creation_and_isolation():
    dag = MerkleDAG()
    dag.add_entity(EntityNode(entity_id="pat_1", entity_type="patient", data={"status": "admitted"}))
    engine = BranchEngine(node_id="us-east-1", base_dag=dag)

    b1 = engine.create_branch("dev/feature-1", developer_id="alice")
    assert b1.branch_name == "dev/feature-1"
    assert b1.parent_branch == "main"

    # Commit on branch 1
    engine.commit("dev/feature-1", mutations=[{"entity_id": "pat_1", "data": {"status": "discharged"}}])
    # Main should remain unaffected
    assert engine.get_dag("main").get_entity("pat_1").data["status"] == "admitted"
    # Feature branch has updated status
    assert engine.get_dag("dev/feature-1").get_entity("pat_1").data["status"] == "discharged"


def test_branch_push_and_pull():
    dag = MerkleDAG()
    dag.add_entity(EntityNode(entity_id="pat_1", entity_type="patient", data={"val": 10}))
    engine = BranchEngine(node_id="us-east-1", base_dag=dag)

    engine.create_branch("dev/bob", developer_id="bob")
    engine.commit("dev/bob", mutations=[{"entity_id": "pat_1", "data": {"val": 99}}])

    # Push to main
    res = engine.push(source_branch="dev/bob", target_branch="main")
    assert res["status"] == "pushed"
    assert engine.get_dag("main").get_entity("pat_1").data["val"] == 99


def test_branch_restore_rollback():
    dag = MerkleDAG()
    engine = BranchEngine(node_id="us-east-1", base_dag=dag)

    c1 = engine.commit("main", mutations=[{"entity_id": "rec_1", "data": {"step": 1}}])
    c2 = engine.commit("main", mutations=[{"entity_id": "rec_1", "data": {"step": 2}}])
    assert engine.get_dag("main").get_entity("rec_1").data["step"] == 2

    # Restore to commit 1
    engine.restore("main", c1.commit_id)
    assert engine.get_dag("main").get_entity("rec_1").data["step"] == 1


def test_branch_diff():
    dag = MerkleDAG()
    dag.add_entity(EntityNode(entity_id="common", entity_type="rec", data={"val": 1}))
    engine = BranchEngine(node_id="us-east-1", base_dag=dag)

    engine.create_branch("dev/charlie")
    engine.commit("dev/charlie", mutations=[
        {"entity_id": "common", "data": {"val": 2}},
        {"entity_id": "new_rec", "data": {"val": 100}}
    ])

    diff_res = engine.diff("main", "dev/charlie")
    assert diff_res["is_identical"] is False
    assert "new_rec" in diff_res["added_in_b"]
    assert any(m["entity_id"] == "common" for m in diff_res["modified"])


# ── 2. Dot Indexer ────────────────────────────────────────────────────────────

def test_dot_indexer_resolution():
    indexer = DotIndexer()
    indexer.set_path("nodes.us-east-1.branches.main.merkle_root", "hash_abc_123")
    indexer.set_path("nodes.us-east-1.branches.main.entities.pat_1.condition", "Critical")

    assert indexer.resolve("nodes.us-east-1.branches.main.merkle_root") == "hash_abc_123"
    assert indexer.resolve("nodes.us-east-1.branches.main.entities.pat_1.condition") == "Critical"
    assert indexer.resolve("nodes.non_existent.path") is None


# ── 3. Lazy Cache ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lazy_cache_pointer_and_hydration():
    async def mock_db_loader(key):
        return {"entity_id": key, "heavy_payload": "X" * 1000}

    cache = LazyCacheStore(db_loader_func=mock_db_loader)
    cache.put_pointer("pat_99", sha256_hash="hash99", version=1, node_id="us-east-1")

    # Pointer check (fast, no DB call)
    ptr = cache.get_pointer("pat_99")
    assert ptr is not None
    assert ptr.hash == "hash99"
    assert cache.lazy_loads == 0

    # Lazy hydration
    hydrated = await cache.get_lazy("pat_99")
    assert hydrated["heavy_payload"] == "X" * 1000
    assert cache.lazy_loads == 1


# ── 4. QA Data Validator & ML Audit Verifier ──────────────────────────────────

def test_qa_validator_detects_bad_data():
    verifier = AuditMLVerifier()

    # Normal valid event
    is_bad, risk, diag = verifier.validate_and_score({
        "node_id": "us-east-1",
        "timestamp": time.time(),
        "request_rate": 8.0,
        "is_cross_region": False,
    })
    assert is_bad is False
    assert risk < 0.70

    # Bad data: Missing node_id
    is_bad_2, risk_2, diag_2 = verifier.validate_and_score({
        "timestamp": time.time(),
    })
    assert is_bad_2 is True
    assert "Missing mandatory 'node_id'" in diag_2

    # Bad data: Severe timestamp drift
    is_bad_3, risk_3, diag_3 = verifier.validate_and_score({
        "node_id": "us-east-1",
        "timestamp": time.time() - 3600,  # 1 hour in past
    })
    assert is_bad_3 is True
    assert "Timestamp drift" in diag_3


# ── 5. High-Throughput Batch Audit Buffer ──────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_batcher_and_service():
    batcher = AuditBatcher(batch_size=10, flush_interval_s=0.05)
    batcher.start()

    # Enqueue 15 events
    for i in range(15):
        await batcher.enqueue({
            "node_id": "us-east-1",
            "branch_name": "dev/test",
            "developer_id": f"dev-{i%3}",
            "event_type": "TEST_MUTATION",
            "entity_id": f"entity_{i}",
            "data": {"value": i},
            "timestamp": time.time(),
        })

    # Allow flusher loop to persist
    await asyncio.sleep(0.2)
    batcher.stop()

    assert batcher.total_ingested == 15
    assert batcher.total_flushed == 15

    # Query via service
    service = AuditTrailService()
    res = await service.query_trail(branch_name="dev/test", limit=20)
    assert res["total_returned"] == 15

    stats = await service.get_summary_stats()
    assert stats["total_audit_events"] == 15
