from fastapi import APIRouter, HTTPException
from services.registry import registry
from services.debounce import debouncer
import httpx

router = APIRouter()

async def fetch_from_node(node_id: str, hash_val: str):
    # Simulated fetch from another node
    # In a real app, this would make an HTTP request to the node
    async with httpx.AsyncClient() as client:
        # Dummy URL
        try:
            # response = await client.get(f"http://{node_id}/data/{hash_val}")
            # return response.json()
            return {"data": f"content_of_{hash_val}", "source": node_id}
        except Exception:
            raise HTTPException(status_code=502, detail="Failed to fetch from node")

@router.get("/{hash_val}")
async def query_hash(hash_val: str):
    nodes = registry.find_nodes_for_hash(hash_val)
    if not nodes:
        raise HTTPException(status_code=404, detail="Hash not found in any active node")
    
    # Try the first available node using debouncer to avoid stampeding
    target_node = nodes[0]
    
    try:
        # Debounce requests for the same hash
        result = await debouncer.execute(
            f"fetch_{hash_val}",
            fetch_from_node,
            target_node,
            hash_val
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
