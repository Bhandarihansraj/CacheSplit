from fastapi import APIRouter
from services.registry import registry
from services.cache_store import cache_store

router = APIRouter(prefix="/api/scan")

@router.get("/{entity_id}")
async def scan_entity(entity_id: str):
    """
    Simulates an Nmap-style scan across all registered nodes to check the 
    presence, version, and hash of a specific entity.
    """
    matrix = {}
    
    # In-memory DAG lookup to simulate what a real node would hold
    entity = cache_store.dag.entities.get(entity_id)
    primary_node = cache_store.entity_to_node.get(entity_id)
    
    for node_id, status in registry.nodes.items():
        if status.health == "quarantined":
            matrix[node_id] = {"version": None, "hash": None, "status": "quarantined"}
            continue
            
        if not entity:
            matrix[node_id] = {"version": None, "hash": None, "status": "missing"}
            continue
            
        ent_hash = entity.merkle_root_hash or entity.local_hash
        node_version = status.version_number
        
        if node_id == primary_node:
            matrix[node_id] = {"version": node_version, "hash": ent_hash, "status": "primary"}
        elif status.tier == "main":
            matrix[node_id] = {"version": node_version, "hash": ent_hash, "status": "replica"}
        else:
            matrix[node_id] = {"version": None, "hash": None, "status": "missing"}

    return {
        "entity_id": entity_id,
        "matrix": matrix
    }
