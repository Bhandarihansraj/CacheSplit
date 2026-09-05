# CacheSplit v3
**Elite Distributed Merkle-DAG Cache Platform -- Planet Scale**

CacheSplit is a production-grade distributed cache fabric with cryptographic Merkle DAG integrity,
Raft consensus, Consistent Hashing, ReBAC access control, and ML-driven anomaly detection.

## Quick Start

```bash
setup.bat        # First time only -- creates venv and installs deps
start.bat        # Launch the cluster
```

- Operations Console: http://127.0.0.1:8000/
- Developer Demo:     http://127.0.0.1:8000/demo
- Interactive CLI:    python ops/demo_menu.py

## Developer API

API Key: `cs_live_55464b6bedb94e77b6444fe49c2e4a2c`

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/dev/keys | Generate a new API key |
| POST | /api/dev/ops  | Unified compound commit (no DAG knowledge needed) |
| GET  | /api/scan/{entity_id} | Nmap-style cluster propagation scan |
| GET  | /api/sharding/locate/{entity_id} | Hash ring node lookup |
| GET  | /api/dashboard/node-map | Cluster node status |
| GET  | /api/dashboard/commits/recent | Recent commit log |

### Python Example

```python
import httpx
KEY  = 'cs_live_55464b6bedb94e77b6444fe49c2e4a2c'
BASE = 'http://127.0.0.1:8000'
r = httpx.post(f'{BASE}/api/dev/ops',
    headers={'Authorization': f'Bearer {KEY}'},
    json={'mutations': [{'entity_id': 'patient_001', 'entity_type': 'patient',
           'data': {'condition': 'Stable', 'status': 'Admitted'}}], 'edges': []})
print(r.json())
```

## Architecture and Completed Phases

| Phase | Description | Status |
|-------|-------------|--------|
| 0-2   | Core Engine, Hash Chain, Node Registry, Debounce | Complete |
| 3-8   | Relational Merkle DAG, Compound Commits, ReBAC | Complete |
| 9-10  | CI/CD, Ops Routines, Tenant Config | Complete |
| 11    | OCC State Management, WebSocket Real-Time Sync | Complete |
| 12-14 | Device Handshake, User/Payment Domains, Commit Lab UI | Complete |
| 15-17 | Sync Loop, Nmap Scanner, Menu-Driven CLI | Complete |
| 18-21 | Raft Consensus, Consistent Hashing, Write-Behind Sync, Developer API | Complete |

## Directory Structure

```
api/       FastAPI routes (dashboard, query, scanner, developer, raft)
core/      Merkle DAG, Compound Commits, ReBAC, Consistent Hash
services/  Registry, Cache Store, Sync Loop, Raft Node, Write-Behind
agents/    ML Security Agent, Reconciliation Agent
db/        SQLite adapter, migrations
ui/        Operations Console (dashboard.html) + Developer Demo (developer_demo.html)
ops/       demo_menu.py interactive CLI
tests/     Pytest test suite
```
