import asyncio
import httpx
import sys

async def inject():
    target_url = "http://127.0.0.1:8000"
    print("Connecting to CacheSplit backend at http://127.0.0.1:8000...")
    
    async with httpx.AsyncClient(base_url=target_url, timeout=5.0) as client:
        try:
            # Check health
            check = await client.get("/api/dashboard/node-map")
            if check.status_code != 200:
                print("Server returned non-200 status code.")
                sys.exit(1)
        except (httpx.ConnectError, httpx.RequestError) as e:
            print(f"\n[!] Connection Failed: Could not connect to {target_url}")
            print("    Please ensure CacheSplit server is running first using: start.bat")
            sys.exit(1)

        print("Injecting anomaly into node: asia-south-1...")
        reason = "Security Agent Flag: Anomalous payload size & scope mismatch"
        res = await client.post(f"/api/debug/quarantine?node_id=asia-south-1&reason={reason}")
        
        if res.status_code == 200:
            print("\n[✓] SUCCESS: Anomaly injected and node quarantined!")
            print(f"    Target Node: asia-south-1")
            print(f"    Flag: {reason}")
            print("\n>>> Open your browser at http://127.0.0.1:8000")
            print("    Observe:")
            print("    1. Node 'asia-south-1' status changes to 'Critical failure (Paused for safety)'")
            print("    2. 'Security Feed & Activity' timeline displays the security event flag.")
        else:
            print(f"Failed to inject anomaly: {res.text}")

if __name__ == "__main__":
    asyncio.run(inject())
