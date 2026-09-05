import pytest
from core.merkle_dag import MerkleDAG, EntityNode
from core.compound_commit import CompoundCommit, EntityMutation, RelationshipEdge
from core.rebac import ReBACPolicy
from agents.graph_security_agent import GraphSecurityAgent

def test_merkle_dag_deterministic_ripple():
    """
    Test Merkle Dependency DAG:
    Parent Root Hash = SHA256(Parent Data || sum(Child Entity Hashes))
    Mutating child lab result must deterministically change parent root hash.
    """
    dag = MerkleDAG()
    p_node = EntityNode(
        entity_id="pat_001",
        entity_type="patient",
        data={"name": "Alice", "status": "admitted"}
    )
    v_node = EntityNode(
        entity_id="vis_001",
        entity_type="visit",
        data={"room": "ICU-1"}
    )
    l_node = EntityNode(
        entity_id="lab_001",
        entity_type="lab_result",
        data={"panel": "Glucose", "value": 98.5}
    )
    dag.add_entity(p_node)
    dag.add_entity(v_node)
    dag.add_entity(l_node)

    dag.add_edge("pat_001", "HAS_CURRENT_VISIT", "vis_001")
    dag.add_edge("vis_001", "CONTAINS_LAB", "lab_001")

    initial_root = dag.compute_merkle_root("pat_001")
    assert initial_root != ""

    # Mutate child lab result
    updated_root = dag.update_entity_data("lab_001", {"value": 142.0})

    # Assert deterministic ripple
    assert updated_root != initial_root, "Child mutation failed to ripple to parent root hash!"

def test_compound_commit_atomic_swap():
    """
    Test multi-entity atomic transactions:
    Admitting patient creates Visit, Bed, and Patient mutations atomically in one commit.
    """
    dag = MerkleDAG()
    commit = CompoundCommit(
        transaction_id="tx_test_101",
        mutations=[
            EntityMutation(entity_type="patient", entity_id="p_99", data={"name": "Bob", "status": "admitted"}),
            EntityMutation(entity_type="visit", entity_id="v_99", data={"type": "inpatient"}),
            EntityMutation(entity_type="bed", entity_id="b_99", data={"bed_code": "B-12", "status": "occupied"})
        ],
        edges=[
            RelationshipEdge(source="p_99", relation="HAS_CURRENT_VISIT", target="v_99"),
            RelationshipEdge(source="v_99", relation="ALLOCATED_BED", target="b_99")
        ]
    )
    updated_roots = commit.apply_to_dag(dag)
    assert "p_99" in updated_roots
    assert dag.entities["p_99"].data["status"] == "admitted"
    assert dag.entities["b_99"].data["status"] == "occupied"
    assert len(dag.entities["p_99"].children_ids) == 1

def test_rebac_contextual_authorization():
    """
    Test ReBAC:
    Access Granted <=> Path(Clinician -> ASSIGNED_TO -> Visit -> CONTAINS -> LabResult) exists.
    """
    dag = MerkleDAG()
    dag.add_entity(EntityNode(entity_id="doc_sarah", entity_type="clinician", data={"name": "Dr. Sarah"}))
    dag.add_entity(EntityNode(entity_id="doc_unassigned", entity_type="clinician", data={"name": "Dr. Stranger"}))
    dag.add_entity(EntityNode(entity_id="pat_50", entity_type="patient", data={}))
    dag.add_entity(EntityNode(entity_id="vis_50", entity_type="visit", data={}))
    dag.add_entity(EntityNode(entity_id="lab_50", entity_type="lab_result", data={"result": "sensitive"}))

    dag.add_edge("pat_50", "HAS_CURRENT_VISIT", "vis_50")
    dag.add_edge("vis_50", "CONTAINS_LAB", "lab_50")
    dag.add_edge("doc_sarah", "ASSIGNED_TO", "vis_50")

    rebac = ReBACPolicy(dag)

    # Authorized: Dr. Sarah is assigned
    res_sarah = rebac.authorize_read("doc_sarah", "lab_50")
    assert res_sarah["authorized"] is True

    # Denied: Dr. Stranger has no assignment path
    res_stranger = rebac.authorize_read("doc_unassigned", "lab_50")
    assert res_stranger["authorized"] is False

def test_graph_security_orphan_and_cross_region():
    """
    Test Graph-Level Anomaly Detection:
    1. Direct billing scraping without patient context -> Flagged & quarantined.
    2. EU node accessing US clinical trial -> Flagged & quarantined.
    """
    dag = MerkleDAG()
    dag.add_entity(EntityNode(entity_id="pat_us_trial", entity_type="patient", region="US-East", data={}))
    dag.add_entity(EntityNode(entity_id="bill_rogue", entity_type="billing", region="US-East", data={"amt": 500}))

    sec_agent = GraphSecurityAgent(dag)

    # Orphan scraping
    res_orphan = sec_agent.evaluate_traversal("node-1", "US-East", "bill_rogue")
    assert res_orphan["flagged"] is True

    # Cross-region breach
    res_cross = sec_agent.evaluate_traversal("eu-node", "EU-West", "pat_us_trial")
    assert res_cross["flagged"] is True
