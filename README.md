# CacheSplit v3
**Elite Distributed Merkle-DAG Cache Platform — Planet Scale**

CacheSplit is a production-grade distributed cache fabric with cryptographic Merkle DAG integrity, Raft consensus, Consistent Hashing, ReBAC access control, and ML-driven anomaly detection.

## Quick Start

```bash
# 1. Setup (first time only)
setup.bat

# 2. Run the cluster
start.bat

# 3. Open Operations Console
http://127.0.0.1:8000/

# 4. Open Developer Demo
http://127.0.0.1:8000/demo

# 5. Interactive CLI
python ops\demo_menu.py
```

## Developer API

Connect your own application to CacheSplit using a simple API key.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/dev/keys` | Generate a new API key |
| POST | `/api/dev/ops` | Unified compound commit (no DAG knowledge needed) |
| GET  | `/api/scan/{entity_id}` | Nmap-style cluster propagation scan |
| GET  | `/api/sharding/locate/{entity_id}` | Find which node owns the data |
| GET  | `/api/dashboard/node-map` | Cluster node status |
| GET  | `/api/dashboard/commits/recent` | Recent commit log |

### Example (Python)

```python
import httpx

KEY = "cs_live_55464b6bedb94e77b6444fe49c2e4a2c"
BASE = "http://127.0.0.1:8000"

r = httpx.post(f"{BASE}/api/dev/ops",
    headers={"Authorization": f"Bearer {KEY}"},
    json={
        "mutations": [{
            "entity_id": "patient_001",
            "entity_type": "patient",
            "data": {"condition": "Stable", "status": "Admitted"}
        }],
        "edges": []
    })
print(r.json())
```

### Example (cURL)

```bash
curl -X POST http://127.0.0.1:8000/api/dev/ops \
  -H "Authorization: Bearer cs_live_55464b6bedb94e77b6444fe49c2e4a2c" \
  -H "Content-Type: application/json" \
  -d '{"mutations":[{"entity_id":"pat_01","entity_type":"patient","data":{"status":"ok"}}],"edges":[]}'
```

## Architecture & Completed Phases

| Phase | Description | Status |
|-------|-------------|--------|
| 0-2 | Core Engine, Hash Chain, Node Registry, Debounce | ? |
| 3-8 | Relational Merkle DAG, Compound Commits, ReBAC | ? |
| 9-10 | CI/CD, Ops Routines, Tenant Config | ? |
| 11 | OCC State Management, WebSocket Real-Time Sync | ? |
| 12-14 | Device Handshake, User/Payment Domains, Commit Lab UI | ? |
| 15-17 | Sync Loop, Nmap Scanner, Menu-Driven CLI | ? |
| 18-21 | Raft Consensus, Consistent Hashing, Write-Behind Sync, Developer API | ? |

## Directory Structure

```
api/          FastAPI routes (dashboard, query, scanner, developer, raft)
core/         Merkle DAG, Compound Commits, ReBAC, Consistent Hash
services/     Registry, Cache Store, Sync Loop, Raft Node, Write-Behind
agents/       ML Security Agent, Reconciliation Agent
db/           SQLite adapter, migrations
ui/           Operations Console + Developer Demo (dashboard.html, developer_demo.html)
ops/          demo_menu.py (interactive CLI)
tests/        Pytest test suite
```
