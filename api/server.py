from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
from services.registry import registry
from api.query import router as query_router

app = FastAPI(title="CacheSplit v2", version="2.0.0")

app.include_router(query_router, prefix="/query", tags=["query"])

class HeartbeatRequest(BaseModel):
    node_id: str
    hashes: Optional[List[str]] = None

@app.post("/heartbeat")
async def receive_heartbeat(req: HeartbeatRequest):
    registry.heartbeat(req.node_id, req.hashes)
    return {"status": "ok", "message": f"Heartbeat received for {req.node_id}"}

@app.post("/commit")
async def receive_commit(node_id: str = Body(...), hash_val: str = Body(...)):
    # Basic commit receiver
    active = registry.get_active_nodes()
    if node_id not in active:
        raise HTTPException(status_code=400, detail="Unknown node")
    # Add hash to node
    if node_id in registry.node_hashes:
        registry.node_hashes[node_id].add(hash_val)
    else:
        registry.node_hashes[node_id] = {hash_val}
    return {"status": "ok"}

@app.get("/nodes")
async def list_nodes():
    return {"active_nodes": registry.get_active_nodes()}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
