# PROJECT INDEX: CacheSplit v4
> This document is the Single Source of Truth (SSoT) for the CacheSplit project. Read this before touching any code.

## 1. Project Identity
- **Name:** CacheSplit
- **Type:** Secure Distributed Commit-Cache Platform (v4)
- **Stack:** Python, FastAPI, asyncio, Pydantic, uv, TailwindCSS/HTML (UI)
- **Status:** All phases 0-21 complete. Phase 22 v4 fully implemented across all 4 domains.

## 2. Architecture & Design Rules
- **Core Principle:** Provable deterministic verification for commits (Phase 0).
- **Relational Merkle DAG:** Entities form a Merkle Directed Acyclic Graph (Patient -> Visit -> LabResult / BedAllocation). Parent Root Hash = SHA256(Parent Data || sum(Child Hashes)). Child mutations deterministically ripple to parent root.
- **Compound Commits:** Multi-entity atomic transactions (`core/compound_commit.py`) across foreign keys in a single atomic memory swap.
- **ReBAC:** Relationship-Based Access Control (`core/rebac.py`) enforcing contextual graph path authorization (Clinician -> ASSIGNED_TO -> Visit -> CONTAINS -> LabResult).
- **Colocation Affinity:** Partitioning by Anchor Root Key (`patient_id`) ensuring relational subtrees reside on the same cache pod for sub-millisecond graph joins with zero cross-pod network hops.
- **Hierarchy & Debounce:** Global nodes route via `NodeRegistry`. Stampede budget and SingleFlight request coalescing.
- **ML Agents:** Isolation Forest anomaly detection & graph anomaly agent (detecting orphan scraping and cross-jurisdiction boundary breaches).
- **UI:** Anthropic Design System (Newsreader serif + Inter), v4 Operations Console, Developer Demo, Test Suite.

## 3. Directory Structure
- `commitcache/`: v4 Commit Cache module — 22 files across 4 domains:
  - `commitcache/api/`: `auth.py` (JWT + tenant scoping), `rate_limit.py` (per-identity), `routes.py` (RouteGuard), `agent_guardrail.py` (AI choke point)
  - `commitcache/core/`: `tenant.py` (Tenant model + registry), `lease.py` (time-boxed HMAC-signed leases), `audit_log.py` (HMAC-signed event log)
  - `commitcache/coordination/`: `gossip_worker.py` (independent gossip task), `repair_worker.py` (bounded queue + backoff), `repair_queue.py` (deterministic priority queue)
  - `commitcache/infra/`: `topology.py` (region/node hierarchy), `storage_adapter.py` (DB-agnostic), `network_policy.py` (per-tier isolation), `region_router.py` (home-region routing), `dr_failover.py` (quorum-based failover)
  - `commitcache/scale/`: `shard_router.py` (consistent hashing), `tenant_queue_pool.py` (per-tenant bounded queues), `ingress_backpressure.py` (per-tier 503), `read_replica_router.py` (reads to replicas)
  - `commitcache/ai/`: `priority_model.py` (hot-key prediction), `anomaly_detector.py` (HMAC-verified audit analysis), `agent_guardrail.py` (AI propose/dispose)
  - `commitcache/observability/`: `metrics.py` (success/reject/timeout/error counters)
  - `commitcache/metering/`: Token bucket, per-tenant metering
- `core/`: Immutable core logic, Commit schema, Hash verification, Access Control, `merkle_dag.py`, `compound_commit.py`, `rebac.py`, `tenant_config.py`.
- `services/`: Node Registry, Debounce / SingleFlight, `cache_store.py` (high-volume regional cache fabric).
- `agents/`: Security Agent (Isolation Forest), Reconciliation Agent, `graph_security_agent.py`.
- `api/`: FastAPI server, query, and comprehensive dashboard APIs (`dashboard.py`).
- `adapters/`: Database interfaces (`interface.py`, `postgres_adapter.py`, `sqlite_mock.py`).
- `ui/`: v4 Operations Console (`v4_dashboard.html`), Developer Demo (`developer_demo.html`), Test Suite (`test_cases.html`), Model Layer (`services_v4.js`), Controller (`app_v4.js`).
- `tests/`: Pytest test suite (16 test gates covering core, registry, agents, debounce, postgres, and ER Merkle ReBAC).
- `phasecontrol/`: Detailed phase specifications.

## 4. Execution State
- [x] **Phase 0:** Core engine, Pydantic business rules, Hash chain validation.
- [x] **Phase 1:** Node Registry heartbeat, background sweeper, Debounce window, Security Agent, Reconciliation Agent.
- [x] **Phase 2:** Postgres Adapter with asyncpg, idempotency, Multi-master read APIs.
- [x] **Phases 3-8 (ER Fabric):** Relational Merkle DAG, Compound Commits, ReBAC Graph Access Control, Regional Scaled Partitioning (100k+ entities).
- [x] **Phases 9-10:** CI/CD Workflow (`.github/workflows/ci.yml`), Ops routines (`ops/`), Tenant Config schema (`core/tenant_config.py`).
- [x] **Phase 11 (State Management):** Optimistic Concurrency Control (OCC), WebSocket Real-Time Sync, and Session Presence.
- [x] **Phases 12-14 (Real-World Ops & Domains):** Device-Style Node Handshake, User & Payment Services, Interactive Commit Lab.
- [x] **Phases 15-17 (Cache Sync & Operations):** Eventual Consistency Sync Loop, Nmap-style Cluster Scanner, Menu-Driven CLI Demo.
- [x] **Phases 18-21 (Raft Consensus, Sharding, Write-Behind, Developer API):** Complete.
- [x] **Interactive Operations Console:** Live interactive dashboard at `http://127.0.0.1:8000/v4_dashboard.html`.
- [x] **Phase 22 (v4 Full Architecture — ALL 4 DOMAINS):**
  - [x] Security: tenant, lease, audit_log, auth, rate_limit, routes (20/25 risk score)
  - [x] Cloud/Infra: topology, storage_adapter, network_policy, region_router, dr_failover
  - [x] Scale: shard_router, tenant_queue_pool, ingress_backpressure, read_replica_router
  - [x] AI/ML: priority_model, anomaly_detector, agent_guardrail
  - [x] UI/MVC: v4_dashboard.html, developer_demo.html, test_cases.html, services_v4.js, app_v4.js
  - [x] Batches: start.bat, setup.bat, .env.example, requirements.txt, README.md, PROJECT_INDEX.md updated

## 5. Phase 22 Audit Results

| Category | Score | Status |
|----------|-------|--------|
| 1. Security Architecture Bugs | 5/5 | FAIL |
| 2. Over-Engineering Bugs | 0/5 | PASS |
| 3. Under-Engineering Bugs | 5/5 | FAIL |
| 4. API / IAM Bugs | 5/5 | FAIL |
| 5. Scalability/Observability Bugs | 5/5 | FAIL |
| **Total** | **20/25** | **HIGH RISK** |

Run `python audit_checklist.py` to generate the full report. Run `python audit_checklist.py --json` for structured JSON output.

## 6. Complete File Inventory (22 files)

### Security (10 files)
| File | Domain | Purpose |
|------|--------|---------|
| `core/tenant.py` | Core | Tenant model + registry, tenant_id from JWT only |
| `core/lease.py` | Core | Time-boxed HMAC-signed leases for all repairs |
| `core/audit_log.py` | Core | HMAC-signed tamper-evident event log |
| `api/auth.py` | API/IAM | Short-lived JWT + tenant scoping |
| `api/rate_limit.py` | API/IAM | Per-(tenant,identity) rate limiting |
| `api/routes.py` | API/IAM | RouteGuard — all gates enforced |
| `api/agent_guardrail.py` | AI/ML | AI proposals through same authz |
| `coordination/gossip_worker.py` | Scale | Independent gossip producing StalenessReports |
| `coordination/repair_worker.py` | Scale | Bounded queue + exponential backoff |
| `observability/metrics.py` | Scale | Full success/reject/timeout/error counters |

### Cloud/Infra (5 files)
| File | Domain | Purpose |
|------|--------|---------|
| `infra/topology.py` | Infra | Region/node hierarchy, 30s TTL |
| `infra/storage_adapter.py` | Infra | DB-agnostic, fencing tokens, Vault/KMS |
| `infra/network_policy.py` | Infra | Per-tier network zone isolation |
| `infra/region_router.py` | Infra | Home-region routing, max 1 forward hop |
| `infra/dr_failover.py` | Infra | Quorum-based failover, no auto-failback |

### Scale Depth (4 files)
| File | Domain | Purpose |
|------|--------|---------|
| `scale/shard_router.py` | Scale | Consistent hashing with virtual nodes |
| `scale/tenant_queue_pool.py` | Scale | Per-tenant bounded queues, no starvation |
| `scale/ingress_backpressure.py` | Scale | Per-tier thresholds, early 503 |
| `scale/read_replica_router.py` | Scale | Reads to replicas, writes always primary |

### AI/ML Depth (3 files)
| File | Domain | Purpose |
|------|--------|---------|
| `ai/priority_model.py` | AI/ML | Learned priority with safe fallback |
| `ai/anomaly_detector.py` | AI/ML | HMAC-verified audit stream analysis |
| `ai/agent_guardrail.py` | AI/ML | All AI decisions through same authz |

### UI/MVC (5 files)
| File | Domain | Purpose |
|------|--------|---------|
| `ui/services_v4.js` | UI/MVC | Model layer — 17 API client classes |
| `ui/app_v4.js` | UI/MVC | Controller layer — all UI interactions |
| `ui/v4_dashboard.html` | UI/MVC | View layer — v4 operations console |
| `ui/developer_demo.html` | UI/MVC | Developer API sandbox with v4 endpoints |
| `ui/test_cases.html` | UI/MVC | 27 interactive test cases across all domains |

### Batches & Config (4 files)
| File | Domain | Purpose |
|------|--------|---------|
| `start.bat` | Config | Launch v4 cluster with all services |
| `setup.bat` | Config | Create venv, deps, module structure |
| `.env.example` | Config | All v4 environment variables |
| `requirements.txt` | Config | All v4 dependencies |

## 7. MVC Protocol

All UI code follows strict MVC:
- **Model** (`services_v4.js`): 17 model classes — never touch raw fetch()
- **View** (`v4_dashboard.html`, `developer_demo.html`, `test_cases.html`): HTML-only rendering
- **Controller** (`app_v4.js`): All interactions route through `Controller.*` methods
- **Tests** (`test_cases.html`): 27 test cases, 5 categories (auth, infra, scale, ai, ui)
