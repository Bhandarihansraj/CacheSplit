import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.compound_commit import CompoundCommit, EntityMutation
from services.cache_store import cache_store

router = APIRouter(prefix="/api/users")

class UserCreateRequest(BaseModel):
    user_id: Optional[str] = None
    name: str
    email: str

@router.post("")
async def create_user(req: UserCreateRequest):
    user_id = req.user_id or f"user_{uuid.uuid4().hex[:8]}"
    mutation = EntityMutation(
        entity_type="user",
        entity_id=user_id,
        data={"name": req.name, "email": req.email}
    )
    commit = CompoundCommit(
        transaction_id=f"tx_user_{uuid.uuid4().hex[:8]}",
        mutations=[mutation]
    )
    result = await cache_store.execute_compound_commit(commit)
    return {"status": "success", "user_id": user_id, "result": result}

@router.get("/{user_id}")
async def get_user(user_id: str):
    entity = cache_store.dag.entities.get(user_id)
    if not entity or entity.entity_type != "user":
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": entity.entity_id, "data": entity.data, "region": entity.region}
