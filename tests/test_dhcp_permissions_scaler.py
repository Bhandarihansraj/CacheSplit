"""
tests/test_dhcp_permissions_scaler.py
Unit tests for DHCP Discovery Protocol, Cross-Node Permission Governance,
and Cluster Scaling.
"""
import pytest
import time
from core.dhcp_discovery import DHCPDiscoveryEngine, DHCPLease
from core.node_permissions import NodePermissionManager, AccessLevel, PermissionStatus
from seed_10k_cluster import generate_node_entities


def test_dhcp_allocation_and_resolution():
    engine = DHCPDiscoveryEngine(default_lease_ttl_s=3600.0)

    lease = engine.allocate_lease(
        raw_id="pat_us_east_00042",
        entity_type="patient",
        node_id="us-east-1",
        branch_name="main",
        category="healthcare",
        custom_name="patient-42",
    )

    assert lease.canonical_alias == "cluster.us.east.healthcare.patient-42"
    assert lease.assigned_ip.startswith("10.100.")
    assert lease.is_valid() is True

    # Resolve alias
    resolved = engine.resolve_alias("cluster.us.east.healthcare.patient-42")
    assert resolved is not None
    assert resolved["raw_id"] == "pat_us_east_00042"
    assert resolved["node_id"] == "us-east-1"
    assert resolved["branch_name"] == "main"
    assert resolved["assigned_ip"] == lease.assigned_ip

    # Resolve raw id
    assert engine.resolve_raw_id("pat_us_east_00042") == "cluster.us.east.healthcare.patient-42"


def test_dhcp_directory_search():
    engine = DHCPDiscoveryEngine()
    engine.allocate_lease("pat_001", "patient", "us-east-1", category="cardiology", custom_name="p1")
    engine.allocate_lease("inv_999", "invoice", "eu-west-1", category="billing", custom_name="i999")
    engine.allocate_lease("sens_55", "telemetry", "asia-south-1", category="sensors", custom_name="s55")

    results = engine.search_directory("cardiology")
    assert len(results) == 1
    assert results[0]["canonical_alias"] == "cluster.us.east.cardiology.p1"

    results_node = engine.search_directory("eu-west-1")
    assert len(results_node) == 1
    assert results_node[0]["raw_id"] == "inv_999"


def test_cross_node_permission_workflow():
    manager = NodePermissionManager()
    manager.set_node_owner("eu-west-1", "alice-lead")

    # Developer on us-east-1 requests WRITE on eu-west-1:dev/billing
    req = manager.request_access(
        requester_id="bob-dev",
        requester_node="us-east-1",
        target_node="eu-west-1",
        target_branch="dev/billing",
        access_level=AccessLevel.WRITE,
        reason="Syncing regional billing records",
    )

    assert req.status == PermissionStatus.PENDING
    assert req.is_active() is False

    # Check permission fails before approval
    assert manager.check_permission("bob-dev", "us-east-1", "eu-west-1", "dev/billing", AccessLevel.WRITE) is False

    # Owner approves request
    reviewed = manager.review_request(
        request_id=req.request_id,
        reviewer_id="alice-lead",
        decision="APPROVED",
        lease_duration_s=3600.0,
    )
    assert reviewed.status == PermissionStatus.APPROVED
    assert reviewed.is_active() is True

    # Permission now allowed
    assert manager.check_permission("bob-dev", "us-east-1", "eu-west-1", "dev/billing", AccessLevel.WRITE) is True

    # Auto-approval for same-node access
    same_node_req = manager.request_access(
        requester_id="charlie-dev",
        requester_node="us-east-1",
        target_node="us-east-1",
        target_branch="main",
        access_level=AccessLevel.READ,
    )
    assert same_node_req.status == PermissionStatus.APPROVED
    assert manager.check_permission("charlie-dev", "us-east-1", "us-east-1", "main", AccessLevel.READ) is True


def test_permission_rejection_and_expiration():
    manager = NodePermissionManager()
    manager.set_node_owner("asia-south-1", "ravi-lead")

    req = manager.request_access(
        requester_id="mallory-dev",
        requester_node="us-east-1",
        target_node="asia-south-1",
        target_branch="main",
        access_level=AccessLevel.ADMIN,
    )

    manager.review_request(req.request_id, "ravi-lead", "REJECTED")
    assert req.status == PermissionStatus.REJECTED
    assert manager.check_permission("mallory-dev", "us-east-1", "asia-south-1", "main", AccessLevel.ADMIN) is False

    # Expired lease
    req_expired = manager.request_access(
        requester_id="dan-dev",
        requester_node="us-east-1",
        target_node="asia-south-1",
        target_branch="main",
    )
    manager.review_request(req_expired.request_id, "ravi-lead", "APPROVED", lease_duration_s=-10.0)
    assert req_expired.is_active() is False
    assert manager.check_permission("dan-dev", "us-east-1", "asia-south-1", "main", AccessLevel.READ) is False


def test_entity_generator():
    entities = generate_node_entities("us-east-1", "US-East", count=100)
    assert len(entities) == 100
    assert entities[0]["entity_id"].startswith("pat_us_east_")
    assert len(entities[0]["local_hash"]) == 64
    assert entities[0]["category"] in ["healthcare", "billing", "telemetry"]
