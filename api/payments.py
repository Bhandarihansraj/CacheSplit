import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.compound_commit import CompoundCommit, EntityMutation, RelationshipEdge
from services.cache_store import cache_store

router = APIRouter(prefix="/api/payments")

class PaymentCreateRequest(BaseModel):
    payment_id: Optional[str] = None
    user_id: str
    amount: float
    status: str = "pending"

@router.post("")
async def create_payment(req: PaymentCreateRequest):
    payment_id = req.payment_id or f"pay_{uuid.uuid4().hex[:8]}"
    billing_id = f"bill_{req.user_id}" 
    
    mutation_payment = EntityMutation(
        entity_type="payment",
        entity_id=payment_id,
        data={"amount": req.amount, "status": req.status, "user_id": req.user_id}
    )
    mutation_billing = EntityMutation(
        entity_type="billing",
        entity_id=billing_id,
        data={"user_id": req.user_id}
    )
    
    edge1 = RelationshipEdge(source=req.user_id, relation="HAS_PAYMENT", target=payment_id)
    edge2 = RelationshipEdge(source=payment_id, relation="LINKED_TO_BILLING", target=billing_id)
    
    commit = CompoundCommit(
        transaction_id=f"tx_pay_{uuid.uuid4().hex[:8]}",
        mutations=[mutation_payment, mutation_billing],
        edges=[edge1, edge2]
    )
    result = await cache_store.execute_compound_commit(commit)
    return {"status": "success", "payment_id": payment_id, "result": result}

@router.get("/{payment_id}")
async def get_payment(payment_id: str):
    entity = cache_store.dag.entities.get(payment_id)
    if not entity or entity.entity_type != "payment":
        raise HTTPException(status_code=404, detail="Payment not found")
    return {"payment_id": entity.entity_id, "data": entity.data}
