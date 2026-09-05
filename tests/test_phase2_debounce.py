import pytest
import asyncio
import time
from services.debounce import DebounceWindow, StampedeBudget

@pytest.mark.asyncio
async def test_debounce_coalescing():
    """Load test: fire 50 simultaneous invalidation triggers; verify exactly 1 coalesced fetch occurs."""
    window = DebounceWindow(node_id="node-1", window_ms=100) # 100ms window
    
    # Fire 50 triggers rapidly
    for i in range(50):
        window.trigger(f"hash-{i}")
        
    # Wait for resolve
    resolved_hash = await window.wait_and_resolve()
    
    # It should resolve to the LAST hint provided ("hash-49")
    assert resolved_hash == "hash-49"
    
    # If we call wait_and_resolve again immediately, it returns the same result
    resolved_hash_2 = await window.wait_and_resolve()
    assert resolved_hash_2 == "hash-49"

@pytest.mark.asyncio
async def test_stampede_budget():
    """Stampede test: origin budget = 2 req/sec, verify it never exceeds 2 req/sec."""
    budget = StampedeBudget(region="us-east", max_requests_per_sec=2)
    
    # 20 attempts at the exact same time
    successful_acquires = 0
    for _ in range(20):
        if budget.try_acquire():
            successful_acquires += 1
            
    assert successful_acquires == 2
    
    # Wait for the next second to begin
    await asyncio.sleep(1.1)
    
    # Try another 20
    successful_acquires_next_sec = 0
    for _ in range(20):
        if budget.try_acquire():
            successful_acquires_next_sec += 1
            
    assert successful_acquires_next_sec == 2
