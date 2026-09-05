import asyncio
import httpx
import sys
import time

async def wait_for_server(url: str = "http://127.0.0.1:8000", max_retries: int = 15):
    """Wait for server to start accepting connections."""
    async with httpx.AsyncClient(timeout=2.0) as client:
        for i in range(max_retries):
            try:
                res = await client.get(f"{url}/api/dashboard/node-map")
                if res.status_code == 200:
                    print("Server is up and accepting connections.")
                    return True
            except (httpx.ConnectError, httpx.ReadError):
                pass
            print(f"Waiting for server on {url} (attempt {i+1}/{max_retries})...")
            await asyncio.sleep(1.0)
    return False

async def seed_data():
    server_ready = await wait_for_server()
    if not server_ready:
        print("ERROR: Server did not respond within timeout period.")
        print("Please check the 'CacheSplit API Server' terminal window for startup errors.")
        sys.exit(1)

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", timeout=5.0) as client:
        print("Registering nodes...")
        await client.post("/api/register?node_id=us-east-1&region=US-East&tier=main")
        await client.post("/api/register?node_id=eu-west-1&region=EU-West&tier=main")
        await client.post("/api/register?node_id=asia-south-1&region=Asia-South&tier=main")
        
        print("Sending initial heartbeats...")
        await client.post("/api/heartbeat", json={
            "node_id": "us-east-1",
            "current_commit_hash": "hash-genesis-us",
            "version_number": 1,
            "cache_summary": {"patient_records": "h_a91f"}
        })
        
        await client.post("/api/heartbeat", json={
            "node_id": "eu-west-1",
            "current_commit_hash": "hash-genesis-eu",
            "version_number": 1,
            "cache_summary": {"patient_records": "h_b82e"}
        })
        
        await client.post("/api/heartbeat", json={
            "node_id": "asia-south-1",
            "current_commit_hash": "hash-genesis-as",
            "version_number": 1,
            "cache_summary": {"patient_records": "h_c73d"}
        })
        print("Initial nodes seeded successfully: us-east-1, eu-west-1, asia-south-1.")

if __name__ == "__main__":
    asyncio.run(seed_data())
