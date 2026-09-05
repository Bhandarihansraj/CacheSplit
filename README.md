# CacheSplit v4
**Elite Distributed Merkle-DAG Cache Platform — Planet Scale**

CacheSplit is a production-grade distributed cache fabric with cryptographic Merkle DAG integrity,
Raft consensus, Consistent Hashing, ReBAC access control, tenant isolation,
AI-driven priority scoring, and HMAC-signed audit trails.

## Quick Start

```bash
setup.bat        # First time only — creates venv, installs deps, creates module structure
start.bat        # Launch the cluster
```

- **Operations Console:** http://127.0.0.1:8000/v4_dashboard.html
- **Developer Demo:**   http://127.0.0.1:8000/demo
- **Test Suite:**       http://127.0.0.1:8000/test_cases.html
- **API Docs:**         http://127.0.0.1:8000/docs
- **Interactive CLI:**  `python ops\demo_menu.py`

## Architecture (All 4 Domains)

| Domain | Components |
|--------|-----------|
| **Security** | `tenant.py`, `lease.py`, `audit_log.py`, `auth.py`, `rate_limit.py` |
| **Cloud/Infra** | `topology.py`, `storage_adapter.py`, `network_policy.py`, `region_router.py`, `dr_failover.py` |
| **Scale** | `shard_router.py`, `tenant_queue_pool.py`, `ingress_backpressure.py`, `read_replica_router.py` |
| **AI/ML** | `priority_model.py`, `anomaly_detector.py`, `agent_guardrail.py` |

## Developer API

API Key: `cs_live_55464b6bedb94e77b6444fe49c2e4a2c`

All endpoints require a JWT token with tenant_id. Login at the Operations Console → Auth tab.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/token` | Login, get JWT + tenant_id |
| POST | `/api/auth/refresh` | Rotate tokens |
| GET | `/api/tenant/registry` | List all tenants |
| GET | `/api/topology` | Get cluster topology view |
| POST | `/api/topology/regions` | Add region (lease required) |
| GET | `/api/sharding/ring` | Get shard ring |
| GET | `/api/sharding/shard/{tenant_id}` | Get shard assignment |
| POST | `/api/queue/enqueue` | Enqueue repair task |
| GET | `/api/queue/stats` | Per-tenant queue stats |
| POST | `/api/backpressure/check` | Check ingress backpressure |
| POST | `/api/priority/score` | Score a stale key |
| GET | `/api/anomaly/alerts` | Get anomaly alerts |
| POST | `/api/guardrail/submit` | Submit AI proposal |
| GET | `/api/guardrail/history` | Get proposal history |
| POST | `/api/failover/initiate` | Initiate DR failover |
| POST | `/api/failover/confirm` | Confirm failover |
| POST | `/api/read-replica/route` | Route read/write operation |
| GET | `/api/network/zones` | Get network zones |
| POST | `/api/audit/events` | Get audit events |
| POST | `/api/dev/ops` | Unified compound commit |
| GET | `/api/dashboard/node-map` | Cluster node status |
| GET | `/api/dashboard/commits/recent` | Recent commit log |
| GET | `/api/scan/{entity_id}` | Nmap-style cluster scan |
| GET | `/api/sharding/locate/{entity_id}` | Hash ring lookup |

### Python Example

```python
import httpx

KEY  = 'cs_live_55464b6bedb94e77b6444fe49c2e4a2c'
BASE = 'http://127.0.0.1:8000'

# Login first to get tenant-scoped token
r = httpx.post(f'{BASE}/api/auth/token', json={'identity': 'admin', 'password': 'admin'})
token = r.json()['access_token']

# Now all requests are tenant-scoped
r = httpx.post(f'{BASE}/api/dev/ops',
    headers={'Authorization': f'Bearer {token}'},
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
| 22+   | v4 Evolution — Full architecture across 4 domains (Security, Infra, Scale, AI/ML) | Complete |

## Directory Structure

```
commitcache/           v4 Commit Cache module
├── api/               Auth, rate limiting, routes, guardrail
├── core/              Tenant, lease, audit log
├── coordination/      Gossip worker, repair worker, repair queue
├── infra/             Topology, storage adapter, network policy, region router, DR failover
├── scale/             Shard router, tenant queue pool, ingress backpressure, read replica router
├── ai/                Priority model, anomaly detector, agent guardrail
├── observability/     Metrics collector
├── metering/          Token bucket, per-tenant metering
└── core/              Tenant, lease, audit_log, tenant.py, lease.py, audit_log.py
api/                   FastAPI routes (dashboard, query, scanner, developer, raft)
core/                  Merkle DAG, Compound Commits, ReBAC, Consistent Hash
services/              Registry, Cache Store, Sync Loop, Raft Node, Write-Behind
agents/                ML Security Agent, Reconciliation Agent
db/                    SQLite adapter, migrations
ui/                    Operations Console (v4_dashboard.html), Developer Demo (developer_demo.html), Test Suite (test_cases.html)
ops/                   demo_menu.py interactive CLI
tests/                 Pytest test suite
```

## Security Architecture

- **Tenant Isolation:** Every request carries tenant_id from JWT — never from query params
- **Lease-Based Repairs:** All state changes require time-boxed HMAC-signed leases
- **Audit Trail:** Every mutation is HMAC-signed and tamper-evident
- **Defense in Depth:** Auth → Rate Limit → Authz → Lease → Audit → Storage
- **Network Isolation:** Per-tier network zones enforced at infra level

## Scalability Features

- **Consistent Hashing:** Virtual nodes ensure ~1/N key movement on add/remove
- **Per-Tenant Queues:** One noisy tenant cannot starve others
- **Ingress Backpressure:** Per-tier thresholds, early 503 rejection
- **Read Replicas:** Read traffic offloaded from primary lease-holders

## AI/ML Features

- **Priority Model:** Learned hot-key prediction with safe fallback
- **Anomaly Detector:** HMAC-verified audit stream analysis, alerts only
- **Agent Guardrail:** All AI decisions pass through same authz as human actions

## Audit & Testing

- Run `python audit_checklist.py` for 22-file security/architecture audit
- Run `python audit_checklist.py --json` for structured JSON output
- Open `test_cases.html` in browser for 27 interactive test cases
- Run `pytest tests/` for pytest suite

## Build Status

| Domain | Files | Status |
|--------|-------|--------|
| Handoff (Core) | tenant, lease, audit_log, gossip_worker, repair_worker, repair_queue, auth, rate_limit, routes, metrics | Complete |
| Cloud/Infra | topology, storage_adapter, network_policy, region_router, dr_failover | Complete |
| Scale Depth | shard_router, tenant_queue_pool, ingress_backpressure, read_replica_router | Complete |
| AI/ML Depth | priority_model, anomaly_detector, agent_guardrail | Complete |
| **Total** | **22 files + 2 fixes** | **Complete** |
