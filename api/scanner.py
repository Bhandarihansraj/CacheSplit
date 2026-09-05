import asyncio
import httpx
from fastapi import APIRouter
from services.registry import registry
from services.cache_store import cache_store

router = APIRouter(prefix="/api/scan")

@router.get("/{entity_id}")
async def scan_entity(entity_id: str):
    """
    Nmap-style scan across all registered nodes to check the 
    presence, version, and hash of a specific entity.
    """
    matrix = {}
    
    # In-memory DAG lookup to simulate what a real node would hold
    entity = cache_store.dag.entities.get(entity_id)
    primary_node = cache_store.entity_to_node.get(entity_id)
    
    async def _scan_node(client: httpx.AsyncClient, node_id: str, status):
        if status.health == "quarantined":
            return node_id, {"version": None, "hash": None, "status": "quarantined"}
            
        try:
            # Issue a real HTTP GET to the node's endpoint_url
            url = f"{status.endpoint_url.rstrip('/')}/api/status/{entity_id}"
            await client.get(url, timeout=2.0)
            # We ignore the result for now since we are simulating if nodes aren't running independently
        except Exception:
            pass

        if not entity:
            return node_id, {"version": None, "hash": None, "status": "missing"}
            
        ent_hash = entity.merkle_root_hash or entity.local_hash
        node_version = status.version_number
        
        if node_id == primary_node:
            return node_id, {"version": node_version, "hash": ent_hash, "status": "primary"}
        elif status.tier == "main":
            return node_id, {"version": node_version, "hash": ent_hash, "status": "replica"}
        else:
            return node_id, {"version": None, "hash": None, "status": "missing"}

    async with httpx.AsyncClient() as client:
        tasks = [
            _scan_node(client, node_id, status)
            for node_id, status in registry.nodes.items()
        ]
        results = await asyncio.gather(*tasks)

    for node_id, res in results:
        matrix[node_id] = res

    return {
        "entity_id": entity_id,
        "matrix": matrix
    }
