import pytest
import asyncio
from services.registry import NodeRegistry

@pytest.mark.asyncio
async def test_hierarchy_heartbeat():
    """Integration: spin up 1 region, 1 main node, 3 sub-nodes; verify heartbeats register correctly."""
    registry = NodeRegistry(timeout_seconds=2)
    registry.start_sweep()
    
    # Register hierarchy
    registry.register_node("us-east-main", "us-east", "main")
    for i in range(1, 4):
        registry.register_node(f"us-east-sub-{i}", "us-east", "sub", "us-east-main")
        
    # Send heartbeats
    registry.heartbeat("us-east-main", "hash1", 1, {})
    for i in range(1, 4):
        registry.heartbeat(f"us-east-sub-{i}", "hash1", 1, {})
        
    active = [n for n in registry.nodes.values() if n.health == "ok"]
    assert len(active) == 4
    
    masters = registry.list_all_masters()
    assert len(masters) == 1
    assert masters[0].node_id == "us-east-main"
    
    registry.stop_sweep()

@pytest.mark.asyncio
async def test_failure_injection_stale_node():
    """Failure injection: kill a sub-node heartbeat; registry must mark it stale within one heartbeat interval."""
    registry = NodeRegistry(timeout_seconds=1) # 1 second timeout
    registry.start_sweep()
    
    registry.register_node("eu-main", "eu-west", "main")
    registry.register_node("eu-sub-1", "eu-west", "sub", "eu-main")
    
    registry.heartbeat("eu-main", "hash1", 1, {})
    registry.heartbeat("eu-sub-1", "hash1", 1, {})
    
    assert registry.get_status("eu-sub-1").health == "ok"
    
    # Simulate time passing (kill sub-node heartbeat) - wait slightly more than timeout
    await asyncio.sleep(1.2)
    
    # Main node still heartbeats
    registry.heartbeat("eu-main", "hash1", 1, {})
    
    # Sub node should be marked stale by the background task
    assert registry.get_status("eu-sub-1").health == "stale"
    assert registry.get_status("eu-main").health == "ok"
    
    registry.stop_sweep()
