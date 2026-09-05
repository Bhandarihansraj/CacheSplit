import time
import uuid
import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from core.compound_commit import CompoundCommit, EntityMutation, RelationshipEdge
from services.cache_store import cache_store
from services.analytics import analytics
from services.state_manager import state_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dev", tags=["developer"])

# In-memory store for MVP API Keys
API_KEYS = set()

class APIKeyResponse(BaseModel):
    api_key: str

@router.post("/keys", response_model=APIKeyResponse)
async def generate_api_key():
    new_key = f"cs_live_{uuid.uuid4().hex}"
    API_KEYS.add(new_key)
    return {"api_key": new_key}

# Dependency to verify API Key
api_key_header = APIKeyHeader(name="Authorization", auto_error=False)

async def get_api_key(api_key: str = Security(api_key_header)):
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = api_key.replace("Bearer ", "")
    if token not in API_KEYS:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return token

class DevOpPayload(BaseModel):
    mutations: List[Dict[str, Any]]
    edges: Optional[List[Dict[str, Any]]] = []

@router.post("/ops")
async def dev_ops(payload: DevOpPayload, key: str = Depends(get_api_key)):
    """
    Unified endpoint for developers to push JSON payloads to trigger compound commits
    without knowing internal DAG mechanics.
    """
    transaction_id = f"dev-tx-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}"
    
    parsed_mutations = []
    for m in payload.mutations:
        if "entity_id" not in m or "entity_type" not in m or "data" not in m:
            raise HTTPException(status_code=400, detail="Mutation must include entity_id, entity_type, and data")
        
        parsed_mutations.append(EntityMutation(
            entity_id=m["entity_id"],
            entity_type=m["entity_type"],
            data=m["data"],
            expected_version=m.get("expected_version")
        ))
    
    parsed_edges = []
    for edge in payload.edges:
        if "from_entity_id" in edge and "to_entity_id" in edge and "relationship_type" in edge:
            parsed_edges.append(RelationshipEdge(
                from_entity_id=edge["from_entity_id"],
                to_entity_id=edge["to_entity_id"],
                relationship_type=edge["relationship_type"]
            ))

    if not parsed_mutations:
        raise HTTPException(status_code=400, detail="No valid mutations provided")

    commit = CompoundCommit(
        transaction_id=transaction_id,
        mutations=parsed_mutations,
        edges=parsed_edges,
    )
    
    try:
        result = await cache_store.execute_compound_commit(commit)
    except ValueError as e:
        if "OCC Conflict" in str(e):
            raise HTTPException(status_code=409, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
        
    await analytics.flush_anomalies()
    
    await state_manager.broadcast({
        "type": "STATE_MUTATED", 
        "transaction_id": transaction_id,
        "mutated_entities": [m.entity_id for m in parsed_mutations]
    })
    
    return {"status": "success", "transaction_id": transaction_id, "result": result}
