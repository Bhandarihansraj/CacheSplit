# CacheSplit v4

**Distributed Relational Cache Fabric with Cryptographic Merkle-DAG Integrity & Dynamic Addressing**

CacheSplit is a distributed caching prototype and simulation engine built with **Python 3.13, FastAPI, SQLite (aiosqlite), scikit-learn, and WebSocket event streaming**. It demonstrates how distributed cache nodes can maintain cryptographic consistency, prevent cache stampedes, isolate concurrent developer mutations via Git-style branching, enforce contextual ReBAC access control, and provide human-readable DHCP dynamic addressing without memorizing raw UUIDs or hashes.

---

## 📖 Table of Contents
1. [Overview & Scope](#-overview--scope)
2. [Architecture Overview](#-architecture-overview)
3. [Module & Subsystem Breakdown](#-module--subsystem-breakdown)
4. [Completed Development Phases](#-completed-development-phases)
5. [Quick Start & Setup](#-quick-start--setup)
6. [Cluster Scaling & Seeding Benchmark](#-cluster-scaling--seeding-benchmark)
7. [API Reference](#-api-reference)
8. [Testing & Verification](#-testing--verification)

---

## 🎯 Overview & Scope

### What CacheSplit Is:
- **Cryptographic State Integrity**: Uses deterministic Merkle DAGs and SHA-256 hash chains where every mutation deterministically ripples up to root entities.
- **Git-Style Node Branching**: Enables multi-developer branch isolation (`main`, `dev/*`, `qa/*`) on individual nodes, with commit histories, three-way diffing, push, pull, and rollback restore.
- **DHCP-Style Dynamic Addressing**: Eliminates random hash/UUID memorization by assigning human-readable canonical aliases (e.g. `cluster.us.east.healthcare.pat-00042`) and virtual IPs (`10.100.x.y`).
- **Cross-Node Permission Governance**: Implements node-owner approval workflows with time-boxed leases for cross-node operations.
- **Stampede Recovery Engine**: Token-bucket rate limiting with deduplicated single-flight fetch coalescing to protect upstream databases.
- **Compliance Audit & Anomaly Detection**: High-throughput micro-batched audit ingestion with structural data validation and Isolation Forest ML risk scoring.

### What CacheSplit Is Not:
- CacheSplit is **not** a drop-in replacement for production-grade Redis or DynamoDB clusters at petabyte scale. It is a working architectural reference implementation and simulation platform designed to explore and validate distributed consistency patterns.

---

## 🏗️ Architecture Overview

```
                      ┌─────────────────────────────────────────┐
                      │    Web Operations Console (app.js)      │
                      │  Node Map · Entity Explorer · DHCP Dir  │
                      │  Commit Lab · Branch Ops · Audit Trail  │
                      └────────────────────┬────────────────────┘
                                           │ HTTP / WebSocket (/api/ws/state)
                      ┌────────────────────▼────────────────────┐
                      │       FastAPI API Gateway Layer         │
                      │  /dashboard · /branch · /discovery      │
                      │  /permissions · /audit · /sim · /dev    │
                      └────────────┬───────────────┬────────────┘
                                   │               │
            ┌──────────────────────▼────┐    ┌─────▼─────────────────────┐
            │     Core Engine Layer     │    │   Services & Workers      │
            │  MerkleDAG · BranchEngine │    │  Registry · CacheStore    │
            │  DHCPDiscovery · ReBAC    │    │  AuditBatcher · SyncLoop  │
            │  DotIndexer · LazyCache   │    │  RaftNode · WriteBehind   │
            └──────────────┬────────────┘    └─────┬─────────────────────┘
                           │                       │
            ┌──────────────▼───────────────────────▼─────────────┐
            │              Persistence & ML Layer                │
            │  SQLite (data/cachesplit.db) · Isolation Forest    │
            │  ReBAC Edge Graph · Audit Trail · Hash Pointers    │
            └────────────────────────────────────────────────────┘
```

---

## 📦 Module & Subsystem Breakdown

### 1. Core Engine (`core/`)
| Module | Purpose |
|---|---|
| [`merkle_dag.py`](file:///D:/myonsite/CacheSplit/core/merkle_dag.py) | In-memory relational entity DAG with deterministic local and Merkle root hash computation. |
| [`compound_commit.py`](file:///D:/myonsite/CacheSplit/core/compound_commit.py) | Atomic multi-entity mutations and relationship edge updates with OCC version checks. |
| [`branch_engine.py`](file:///D:/myonsite/CacheSplit/core/branch_engine.py) | Git-style branch isolation per node (`create_branch`, `commit`, `push`, `pull`, `restore`, `diff`, `log`). |
| [`dhcp_discovery.py`](file:///D:/myonsite/CacheSplit/core/dhcp_discovery.py) | DHCP-style dynamic lease allocation, canonical alias naming, and $\mathcal{O}(1)$ directory search. |
| [`node_permissions.py`](file:///D:/myonsite/CacheSplit/core/node_permissions.py) | Cross-node access control with owner review workflows and time-boxed lease management. |
| [`dot_indexer.py`](file:///D:/myonsite/CacheSplit/core/dot_indexer.py) | Hierarchical dot-notation path resolver (e.g. `nodes.us-east-1.branches.main.merkle_root`). |
| [`lazy_cache.py`](file:///D:/myonsite/CacheSplit/core/lazy_cache.py) | Lightweight 32-byte hash pointer cache with lazy on-demand payload hydration from SQLite. |
| [`consistent_hash.py`](file:///D:/myonsite/CacheSplit/core/consistent_hash.py) | Hash ring with virtual nodes for partition placement and shard balancing. |
| [`semantic_cache.py`](file:///D:/myonsite/CacheSplit/core/semantic_cache.py) | AgentDB-inspired vector store with Cosine/Euclidean/Dot metrics, hybrid metadata filters, and MMR. |
| [`semantic_invalidation.py`](file:///D:/myonsite/CacheSplit/core/semantic_invalidation.py) | Semantic neighborhood invalidator broadcasting cluster invalidations based on distance radius. |
| [`audit_embedder.py`](file:///D:/myonsite/CacheSplit/core/audit_embedder.py) | Deterministic dense feature & text embedder projecting audit events into 32-D vector space. |
| [`audit_vector_index.py`](file:///D:/myonsite/CacheSplit/core/audit_vector_index.py) | Hybrid vector index combining Cosine similarity with relational audit filters (`is_bad_data`, `min_risk`). |
| [`rebac.py`](file:///D:/myonsite/CacheSplit/core/rebac.py) | Relationship-Based Access Control evaluator over relational graph edges. |
| [`stampede_limiter.py`](file:///D:/myonsite/CacheSplit/core/stampede_limiter.py) | Token-bucket rate limiter preventing upstream origin overload. |
| [`simulation_engine.py`](file:///D:/myonsite/CacheSplit/core/simulation_engine.py) | Lossy network simulation and convergence engine for cache stampede scenarios. |

### 2. Services Layer (`services/`)
| Module | Purpose |
|---|---|
| [`cache_store.py`](file:///D:/myonsite/CacheSplit/services/cache_store.py) | Regional cache store coordinating Merkle DAG operations with SQLite persistence. |
| [`semantic_router.py`](file:///D:/myonsite/CacheSplit/services/semantic_router.py) | Semantic router intercepting queries, computing hit/miss scores, and managing access telemetry. |
| [`registry.py`](file:///D:/myonsite/CacheSplit/services/registry.py) | Node registration, heartbeat monitoring, and failure injection testing. |
| [`audit_batcher.py`](file:///D:/myonsite/CacheSplit/services/audit_batcher.py) | Async ring buffer with micro-batched vectorized database flush ($500$ events / $100\text{ms}$). |
| [`audit_trail_service.py`](file:///D:/myonsite/CacheSplit/services/audit_trail_service.py) | Query service for compliance logs with bad-data and risk filters. |
| [`sync_loop.py`](file:///D:/myonsite/CacheSplit/services/sync_loop.py) | Background synchronization loop pulling missing commits across cluster nodes. |
| [`raft_node.py`](file:///D:/myonsite/CacheSplit/services/raft_node.py) | Raft consensus candidate election and leader heartbeat management. |
| [`write_behind.py`](file:///D:/myonsite/CacheSplit/services/write_behind.py) | Asynchronous write-behind queue buffering persistent mutations. |
| [`state_manager.py`](file:///D:/myonsite/CacheSplit/services/state_manager.py) | WebSocket connection manager broadcasting state changes to all connected clients. |

### 3. Agents & Verification (`agents/`)
| Module | Purpose |
|---|---|
| [`audit_ml_verifier.py`](file:///D:/myonsite/CacheSplit/agents/audit_ml_verifier.py) | Structural validator (`is_bad_data`) and Isolation Forest risk scoring engine. |
| [`graph_security_agent.py`](file:///D:/myonsite/CacheSplit/agents/graph_security_agent.py) | Relational traversal inspector flagging orphan records and unauthorized cross-region reads. |
| [`security_agent.py`](file:///D:/myonsite/CacheSplit/agents/security_agent.py) | Behavioral anomaly detector monitoring mutation patterns and request velocity. |
| [`reconciliation_agent.py`](file:///D:/myonsite/CacheSplit/agents/reconciliation_agent.py) | Hash chain verification agent identifying stale or tampered node states. |

---

## 📈 Completed Development Phases

| Phase | Title | Key Deliverables | Status |
|---|---|---|---|
| **Phase 0–2** | **Core Foundation** | Hash chain verification, Node Registry, Debounce coalescing, SQLite adapter | ✅ Complete |
| **Phase 3–8** | **Merkle DAG & ReBAC** | Relational entity trees, Compound Commits, ReBAC BFS authorization | ✅ Complete |
| **Phase 9–11** | **Real-Time & OCC** | WebSocket live synchronization, Optimistic Concurrency Control, Conflict detection | ✅ Complete |
| **Phase 12–14** | **Handshake & Commit Lab** | Device version handshake, multi-domain schemas (User/Payment), Commit Lab UI | ✅ Complete |
| **Phase 15–17** | **Sync & CLI Demo** | Background sync loop, Nmap-style entity scanner, Interactive terminal CLI | ✅ Complete |
| **Phase 18–21** | **Raft & Sharding** | Raft consensus terms, Consistent hash ring, Write-behind queue, Developer API | ✅ Complete |
| **Phase 22** | **Stampede Recovery** | Token-bucket capacity ceiling, Lossy network simulator, Recovery convergence | ✅ Complete |
| **Phase 23** | **Git Branching & Audit** | Node branch engine (`commit`, `push`, `pull`, `restore`), Dot indexer, Audit batcher | ✅ Complete |
| **Phase 24** | **10K+ Scaler & DHCP** | 30,000+ entity seeder, DHCP dynamic addressing, Cross-node permission governance | ✅ Complete |
| **Phase 25** | **AgentDB Semantic Cache** | Vector indexing (Cosine/Euclidean/Dot), Hybrid metadata filters, MMR diversity, Semantic neighborhood invalidator | ✅ Complete |
| **Phase 26** | **Hybrid Audit Vector Search** | Dense text & event embedder, hybrid relational search, natural language audit query API & UI | ✅ Complete |

### 4. API & User Interface (`api/` & `ui/`)
- **FastAPI Endpoints**: Full CRUD and execution routers mounted in [`api/server.py`](file:///D:/myonsite/CacheSplit/api/server.py).
- **Operations Console**: Single-page application ([`dashboard.html`](file:///D:/myonsite/CacheSplit/ui/dashboard.html) / [`app.js`](file:///D:/myonsite/CacheSplit/ui/app.js)) with 10 dedicated management panels:
  1. **Node Map**: Live regional node cluster health and heartbeat controls.
  2. **Entity Explorer**: Relational ER trees with Merkle hash breakdown.
  3. **Scanner**: Nmap-style cluster presence and version inspection.
  4. **Developer Portal**: Live API key generation and curl snippets.
  5. **Stampede Simulator**: Interactive lossy write injection and recovery stepping.
  6. **DHCP Directory**: Instant alias lookup and canonical search across 30,000+ entries.
  7. **Commit Lab**: Visual staging area, JSON diff mode, and atomic compound commits.
  8. **Multi-Master Query**: Multi-node status, cache contents, and commit history queries.
  9. **Access Control (ReBAC)**: Visual care-team authorization path verification.
  10. **Branch Ops & Dot Indexer**: Multi-branch Git operations and dot-notation resolution.
  11. **Compliance Audit Trail**: Vectorized micro-batch log stream with QA anomaly diagnostics.
  12. **Security Event Feed**: ML graph security alerts and quarantine management.

---

## 📈 Completed Development Phases

| Phase | Title | Key Deliverables | Status |
|---|---|---|---|
| **Phase 0–2** | **Core Foundation** | Hash chain verification, Node Registry, Debounce coalescing, SQLite adapter | ✅ Complete |
| **Phase 3–8** | **Merkle DAG & ReBAC** | Relational entity trees, Compound Commits, ReBAC BFS authorization | ✅ Complete |
| **Phase 9–11** | **Real-Time & OCC** | WebSocket live synchronization, Optimistic Concurrency Control, Conflict detection | ✅ Complete |
| **Phase 12–14** | **Handshake & Commit Lab** | Device version handshake, multi-domain schemas (User/Payment), Commit Lab UI | ✅ Complete |
| **Phase 15–17** | **Sync & CLI Demo** | Background sync loop, Nmap-style entity scanner, Interactive terminal CLI | ✅ Complete |
| **Phase 18–21** | **Raft & Sharding** | Raft consensus terms, Consistent hash ring, Write-behind queue, Developer API | ✅ Complete |
| **Phase 22** | **Stampede Recovery** | Token-bucket capacity ceiling, Lossy network simulator, Recovery convergence | ✅ Complete |
| **Phase 23** | **Git Branching & Audit** | Node branch engine (`commit`, `push`, `pull`, `restore`), Dot indexer, Audit batcher | ✅ Complete |
| **Phase 24** | **10K+ Scaler & DHCP** | 30,000+ entity seeder, DHCP dynamic addressing, Cross-node permission governance | ✅ Complete |

---

## 🚀 Quick Start & Setup

### Prerequisites
- Python 3.11+ (Python 3.13 tested)
- Git

### Installation
```bash
# 1. Clone the repository
git clone https://github.com/Bhandarihansraj/CacheSplit.git
cd CacheSplit

# 2. Set up virtual environment
python -m venv .venv
.\.venv\Scripts\activate   # On Windows (or 'source .venv/bin/activate' on Linux/macOS)

# 3. Install dependencies
pip install -r requirements.txt
```

### Running the Application
```bash
# Set PYTHONPATH and launch server
$env:PYTHONPATH="."
uvicorn api.server:app --host 127.0.0.1 --port 8000
```
- Open **Operations Console**: [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)
- Interactive **API Docs (Swagger UI)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## ⚡ Cluster Scaling & Seeding Benchmark

To generate **10,000+ realistic relational entities per node** across 3 regional nodes (**30,000+ total**) with DHCP dynamic aliases and branch commits:

```bash
python seed_10k_cluster.py
```

### Seeding Performance Results:
- **Total Relational Entities**: **30,601 entities**
- **Dynamic DHCP Leases**: **30,000 leases allocated**
- **Lazy Cache Pointers**: **30,000 pointers cached**
- **Execution Time**: **2.46 seconds** (SQLite batch transaction)

---

## 📡 API Reference (Core Endpoints)

### DHCP Auto-Discovery & Permissions
- `POST /api/discovery/allocate` — Allocate dynamic DHCP lease and canonical alias.
- `GET /api/discovery/resolve?alias={alias}` — Resolve canonical alias to entity coordinates.
- `GET /api/discovery/search?q={query}` — Search directory across aliases, nodes, and categories.
- `GET /api/discovery/catalog` — Retrieve cluster-wide lease statistics.
- `POST /api/permissions/request` — Submit cross-node access request (`READ`, `WRITE`, `MERGE`, `ADMIN`).
- `POST /api/permissions/review` — Node owner approves or rejects pending request.
- `GET /api/permissions/list` — List active permission requests.
- `GET /api/permissions/check` — Verify if active lease allows cross-node operation.

### Git Branching & Dot Indexer
- `POST /api/branch/create` — Create isolated developer branch on a node.
- `POST /api/branch/commit` — Submit atomic compound commit to a branch.
- `POST /api/branch/push` — Push branch changes to target branch (`main`).
- `POST /api/branch/pull` — Pull updates into developer branch.
- `POST /api/branch/restore` — Rollback branch to historical commit hash.
- `GET /api/branch/diff` — Compare Merkle roots and entities between branches.
- `GET /api/dot/resolve?path={path}` — Resolve $\mathcal{O}(1)$ hierarchical dot path.

### Compliance Audit Trail
- `POST /api/audit/log` — Ingest audit event into high-throughput batch buffer.
- `GET /api/audit/trail` — Retrieve immutable audit trail with optional QA bad-data filter.
- `GET /api/audit/stats` — Retrieve micro-batch buffer depth and average ML risk score.

---

## 🧪 Testing & Verification

The test suite runs with `pytest` and validates all architectural layers:

```bash
pytest tests/ -v
```

### Test Suite Summary:
- **72/72 Unit & Integration Tests Passing**
- Covers:
  - Merkle-DAG ripple integrity and compound commit atomicity.
  - ReBAC authorization and graph anomaly detection.
  - Machine learning feature extraction and Isolation Forest scoring.
  - Raft leader election, heartbeat timeouts, and log replication.
  - Consistent hashing ring distribution and virtual node balancing.
  - Lossy network recovery and stampede token-bucket ceilings.
  - Git branching, diff, rollback, and dot-notation resolution.
  - DHCP dynamic allocation, alias resolution, and cross-node permission leases.

---

## 📄 License
MIT License. Created by [Bhandarihansraj](https://github.com/Bhandarihansraj).
