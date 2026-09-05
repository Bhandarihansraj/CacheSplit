# CacheSplit v4

**Distributed Relational Cache Fabric with Cryptographic Merkle-DAG Integrity & Dynamic Addressing**

CacheSplit is a distributed caching prototype and simulation engine built with **Python 3.13, FastAPI, SQLite (aiosqlite), scikit-learn, and WebSocket event streaming**. It demonstrates how distributed cache nodes can maintain cryptographic consistency, prevent cache stampedes, isolate concurrent developer mutations via Git-style branching, enforce contextual ReBAC access control, and provide human-readable DHCP dynamic addressing without memorizing raw UUIDs or hashes.

---

## 📖 Table of Contents
1. [Overview & Scope](#-overview--scope)
2. [PRD Requirements vs Delivered Implementation Matrix](#-prd-requirements-vs-delivered-implementation-matrix)
3. [Architecture Overview](#-architecture-overview)
4. [Module & Subsystem Breakdown](#-module--subsystem-breakdown)
5. [Completed Development Phases (Phases 0–29)](#-completed-development-phases-phases-029)
6. [Quick Start & Setup](#-quick-start--setup)
7. [Cluster Scaling & Seeding Benchmark](#-cluster-scaling--seeding-benchmark)
8. [API Reference](#-api-reference)
9. [Testing & Verification](#-testing--verification)

---

## 🎯 Overview & Scope

### What CacheSplit Is:
- **Cryptographic State Integrity**: Uses deterministic Merkle DAGs and SHA-256 hash chains where every mutation deterministically ripples up to root entities.
- **Git-Style Node Branching**: Enables multi-developer branch isolation (`main`, `dev/*`, `qa/*`) on individual nodes, with commit histories, three-way diffing, push, pull, and rollback restore.
- **DHCP-Style Dynamic Addressing**: Eliminates random hash/UUID memorization by assigning human-readable canonical aliases (e.g. `cluster.us.east.healthcare.pat-00042`) and virtual IPs (`10.100.x.y`).
- **Cross-Node Permission Governance**: Implements node-owner approval workflows with time-boxed leases for cross-node operations.
- **Stampede Recovery Engine**: Token-bucket rate limiting with deduplicated single-flight fetch coalescing to protect upstream databases.
- **AgentDB Semantic Vector Cache**: In-memory vector store with Cosine/Euclidean/Dot metrics, hybrid metadata filters, MMR diversity, and semantic neighborhood invalidation.
- **HNSW Vector Graph Index & Int8 Scalar Quantization (SQ8)**: Multi-layer proximity graph ($O(\log N)$ search) with 4x memory reduction.
- **Adaptive RL Stampede Governor**: Q-learning Bellman policy dynamically tuning token bucket rate limits based on live latency and reject feedback.
- **QUIC Cross-Node Transport Mesh**: Sub-millisecond multiplexed UDP invalidation bus eliminating Head-of-Line blocking.
- **Compliance Audit & Anomaly Detection**: High-throughput micro-batched audit ingestion with structural data validation and Isolation Forest ML risk scoring.

### What CacheSplit Is Not:
- CacheSplit is **not** a drop-in replacement for production-grade Redis or DynamoDB clusters at petabyte scale. It is a working architectural reference implementation and simulation platform designed to explore and validate distributed consistency patterns.

---

## ⚖️ PRD Requirements vs Delivered Implementation Matrix

This table maps every original product and technical requirement from **PRD #16 (`cache-security-v2-prd-trd-plan.md`)** directly to the actual code implementation and automated test verification.

| PRD Requirement | Specification in PRD #16 | Actual System Implementation | Automated Verification |
|---|---|---|---|
| **1. Multi-Node + Versioned Records** | Patient/clinical data served across multiple cache nodes across countries; verifiable state per key. | Implemented in [`core/cache_node.py`](file:///D:/myonsite/CacheSplit/core/cache_node.py) and [`core/merkle_dag.py`](file:///D:/myonsite/CacheSplit/core/merkle_dag.py). Nodes track per-key version numbers, commit hashes, and status states (`FRESH`, `STALE`, `REPAIRING`). | `test_merkle_dag_deterministic_ripple`, `test_hierarchy_heartbeat` |
| **2. Bounded Origin / Stampede Budget** | Origin never exceeds its stampede budget; nodes never spam origin with duplicate requests (debounced). | Implemented in [`core/stampede_limiter.py`](file:///D:/myonsite/CacheSplit/core/stampede_limiter.py) (`TokenBucket`) and [`services/debounce.py`](file:///D:/myonsite/CacheSplit/services/debounce.py) (`DebounceCoalescer`). Throws `OriginOverloadError` on budget exhaustion; coalesces 50 triggers to 1 origin fetch. | `test_token_bucket_blocks_over_burst`, `test_coalescing_50_triggers_to_1_fetch`, `test_origin_overload_raised` |
| **3. Delayed/Dropped Invalidation Handling** | Origin updates reach nodes correctly even when invalidation messages are delayed or dropped. | Implemented in [`core/invalidation_bus.py`](file:///D:/myonsite/CacheSplit/core/invalidation_bus.py) and [`core/simulation_engine.py`](file:///D:/myonsite/CacheSplit/core/simulation_engine.py). Simulates configurable packet loss probabilities and delayed callback delivery. | `test_bus_drops_all_at_zero_prob`, `test_bus_delivers_all_at_full_prob`, `test_cache_node_invalidate_marks_stale` |
| **4. Multi-Version Behind & Overlapping Invalidation** | Nodes 2+ versions behind recover correctly; overlapping concurrent invalidations converge to latest state without silent data corruption. | Implemented in [`core/recovery_coordinator.py`](file:///D:/myonsite/CacheSplit/core/recovery_coordinator.py) and [`core/simulation_engine.py`](file:///D:/myonsite/CacheSplit/core/simulation_engine.py). Coordinator reconciles multi-step staleness to latest version. | `test_overlap_scenario_reaches_latest_version`, `test_full_scenario_converges` |
| **5. Provable Correctness / Tamper-Evident Hash Chain** | Every change is hash-linked (`SHA256(parent + manifest + key)`); never silently wrong. | Implemented in [`core/hash_chain.py`](file:///D:/myonsite/CacheSplit/core/hash_chain.py), [`core/compound_commit.py`](file:///D:/myonsite/CacheSplit/core/compound_commit.py), and [`core/merkle_dag.py`](file:///D:/myonsite/CacheSplit/core/merkle_dag.py). Deterministic ripple hashing across ER entities. | `test_hash_chain_tampering`, `test_compound_commit_signed_hash_roundtrip`, `test_commit_tampering_breaks_signature` |
| **6. Least-Privilege Access Boundary & ReBAC** | Nodes and users only receive data they are authorized for; field-mask scoping. | Implemented in [`core/rebac.py`](file:///D:/myonsite/CacheSplit/core/rebac.py), [`core/access_control.py`](file:///D:/myonsite/CacheSplit/core/access_control.py), and [`core/node_permissions.py`](file:///D:/myonsite/CacheSplit/core/node_permissions.py). Breadth-First-Search traversal over `rebac_edges` and time-boxed lease governance. | `test_rebac_contextual_authorization`, `test_cross_node_permission_workflow` |
| **7. ML Access Anomaly Detection** | Isolation Forest on access patterns; deterministic hash reconciliation with classifier fallback. | Implemented in [`agents/security_agent.py`](file:///D:/myonsite/CacheSplit/agents/security_agent.py), [`agents/reconciliation_agent.py`](file:///D:/myonsite/CacheSplit/agents/reconciliation_agent.py), and [`services/analytics.py`](file:///D:/myonsite/CacheSplit/services/analytics.py). Real scikit-learn Isolation Forest trained on live access feature vectors. | `test_security_agent_flags_anomalous_event`, `test_reconciliation_agent_zero_percent_tampered_as_ok`, `test_model_trains_on_real_data` |
| **8. Central Node Registry & Multi-Master Query** | One place shows live state of all nodes (health, version, cache summary) and allows multi-master querying. | Implemented in [`services/registry.py`](file:///D:/myonsite/CacheSplit/services/registry.py), [`api/query.py`](file:///D:/myonsite/CacheSplit/api/query.py), and [`api/dashboard.py`](file:///D:/myonsite/CacheSplit/api/dashboard.py). Exposes `/api/dashboard/node-map` and `/api/query`. | `test_hierarchy_heartbeat`, `test_failure_injection_stale_node`, `test_root_and_dashboard_pages` |
| **9. Database Adapter Abstraction Layer** | DB-agnostic adapter interface with swappable implementations (`write`, `read`, `list_history`). | Implemented in [`adapters/interface.py`](file:///D:/myonsite/CacheSplit/adapters/interface.py), [`adapters/sqlite_mock.py`](file:///D:/myonsite/CacheSplit/adapters/sqlite_mock.py), and [`adapters/postgres_adapter.py`](file:///D:/myonsite/CacheSplit/adapters/postgres_adapter.py). | `test_write_idempotent`, `test_read`, `test_list_history` |
| **10. Developer API & Unified JSON Ops** | Developers push compound mutations without needing internal DAG mechanics knowledge. | Implemented in [`api/developer.py`](file:///D:/myonsite/CacheSplit/api/developer.py) (`POST /api/dev/ops`) and [`ui/developer_demo.html`](file:///D:/myonsite/CacheSplit/ui/developer_demo.html). | `test_auxiliary_pages`, `test_compound_commit_atomic_swap` |
| **11. Advanced AI/Networking Enhancements (Phases 25–29)** | Semantic vector cache, HNSW graph index ($O(\log N)$), Int8 scalar quantization ($4\times$ RAM savings), RL stampede governor, and QUIC UDP transport mesh. | Implemented in [`core/semantic_cache.py`](file:///D:/myonsite/CacheSplit/core/semantic_cache.py), [`core/hnsw_index.py`](file:///D:/myonsite/CacheSplit/core/hnsw_index.py), [`core/scalar_quantizer.py`](file:///D:/myonsite/CacheSplit/core/scalar_quantizer.py), [`core/rl_stampede_governor.py`](file:///D:/myonsite/CacheSplit/core/rl_stampede_governor.py), [`core/quic_transport.py`](file:///D:/myonsite/CacheSplit/core/quic_transport.py). | `test_phase25_semantic_cache.py`, `test_phase26_audit_vector_search.py`, `test_phase27_rl_stampede_governor.py`, `test_phase28_quic_transport.py`, `test_phase29_hnsw_quantization.py` |

---

## 🏗️ Architecture Overview

```
                      ┌─────────────────────────────────────────┐
                      │    Web Operations Console (app.js)      │
                      │  Node Map · Entity Explorer · DHCP Dir  │
                      │  Commit Lab · Branch Ops · Audit Trail  │
                      │  Semantic Vector Lab · HNSW Benchmark  │
                      └────────────────────┬────────────────────┘
                                           │ HTTP / WebSocket (/api/ws/state)
                      ┌────────────────────▼────────────────────┐
                      │       FastAPI API Gateway Layer         │
                      │  /dashboard · /branch · /discovery      │
                      │  /permissions · /audit · /sim · /dev    │
                      │  /semantic · /governor · /quic · /hnsw  │
                      └────────────┬───────────────┬────────────┘
                                   │               │
            ┌──────────────────────▼────┐    ┌─────▼─────────────────────┐
            │     Core Engine Layer     │    │   Services & Workers      │
            │  MerkleDAG · BranchEngine │    │  Registry · CacheStore    │
            │  HNSWIndex · ScalarQuant  │    │  AuditBatcher · SyncLoop  │
            │  DHCPDiscovery · ReBAC    │    │  RaftNode · WriteBehind   │
            │  DotIndexer · LazyCache   │    │  SemanticRouter · QuicMesh│
            │  RLGovernor · QuicTransport    │  AdaptiveRecoveryService  │
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
| [`semantic_cache.py`](file:///D:/myonsite/CacheSplit/core/semantic_cache.py) | AgentDB-inspired vector store with Cosine/Euclidean/Dot metrics, hybrid metadata filters, MMR, and HNSW backend. |
| [`hnsw_index.py`](file:///D:/myonsite/CacheSplit/core/hnsw_index.py) | Hierarchical Navigable Small World (HNSW) multi-layer vector graph index with $O(\log N)$ search and self-healing node deletion. |
| [`scalar_quantizer.py`](file:///D:/myonsite/CacheSplit/core/scalar_quantizer.py) | Dynamic Int8 Uniform Scalar Quantizer (SQ8) with asymmetric dot product estimation and 4x RAM reduction. |
| [`semantic_invalidation.py`](file:///D:/myonsite/CacheSplit/core/semantic_invalidation.py) | Semantic neighborhood invalidator broadcasting cluster invalidations based on distance radius. |
| [`audit_embedder.py`](file:///D:/myonsite/CacheSplit/core/audit_embedder.py) | Deterministic dense feature & text embedder projecting audit events into 32-D vector space. |
| [`audit_vector_index.py`](file:///D:/myonsite/CacheSplit/core/audit_vector_index.py) | Hybrid vector index combining Cosine similarity with relational audit filters (`is_bad_data`, `min_risk`). |
| [`rl_stampede_governor.py`](file:///D:/myonsite/CacheSplit/core/rl_stampede_governor.py) | AgentDB Q-learning governor optimizing origin rate limits dynamically based on real-time latency & drop rate. |
| [`adaptive_limiter.py`](file:///D:/myonsite/CacheSplit/core/adaptive_limiter.py) | Dynamic token bucket allowing live thread-safe updates to max_rps and burst capacity. |
| [`quic_transport.py`](file:///D:/myonsite/CacheSplit/core/quic_transport.py) | Async UDP/QUIC socket endpoint with stream multiplexing and sub-millisecond transmission. |
| [`quic_mesh.py`](file:///D:/myonsite/CacheSplit/core/quic_mesh.py) | Full-mesh QUIC coordinator broadcasting invalidations across dedicated parallel streams. |
| [`rebac.py`](file:///D:/myonsite/CacheSplit/core/rebac.py) | Relationship-Based Access Control evaluator over relational graph edges. |
| [`stampede_limiter.py`](file:///D:/myonsite/CacheSplit/core/stampede_limiter.py) | Token-bucket rate limiter preventing upstream origin overload. |
| [`simulation_engine.py`](file:///D:/myonsite/CacheSplit/core/simulation_engine.py) | Lossy network simulation and convergence engine for cache stampede scenarios. |
| [`redis_store.py`](file:///D:/myonsite/CacheSplit/core/redis_store.py) | High-performance in-memory Redis data structures store (Strings, Hashes, Lists, Sets, ZSets). |

---

## 📈 Completed Development Phases (Phases 0–30)

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
| **Phase 27** | **Adaptive RL Stampede Governor** | Q-learning governor, dynamic token bucket adaptation, auto-pilot recovery tuning API & UI | ✅ Complete |
| **Phase 28** | **QUIC Low-Latency Transport** | Sub-millisecond multiplexed UDP invalidation bus, stream isolation, zero Head-of-Line blocking | ✅ Complete |
| **Phase 29** | **AgentDB HNSW & Int8 Quantization** | $O(\log N)$ HNSW multi-layer vector graph index, Int8 Scalar Quantization ($4\times$ memory reduction), Live benchmark & visualizer | ✅ Complete |
| **Phase 30** | **Redis Data Types Engine** | In-memory store for Strings, Hashes, Lists, Sets, ZSets, `WRONGTYPE` validation, and `/api/redis/*` API | ✅ Complete |
| **Phase 31** | **TTL & Memory Eviction Engine** | Passive on-access expiration, active background sweeps, LRU/LFU/Volatile-TTL memory pruning | ✅ Complete |

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
# Launch via start.bat or directly:
.\start.bat
```
- Open **Main Dashboard**: [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard)
- Open **Ops Console (v4)**: [http://127.0.0.1:8000/v4_dashboard.html](http://127.0.0.1:8000/v4_dashboard.html)
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

### Semantic Vector Cache & HNSW Index
- `POST /semantic/query` (or `/api/semantic/query`) — Hybrid semantic search with metadata filtering and MMR diversity.
- `POST /semantic/invalidate-neighborhood` — Invalidate cached clusters by vector similarity radius.
- `GET /semantic/stats` — Live semantic cache statistics.
- `GET /api/hnsw/stats` — Live HNSW multi-layer graph topology, layer degrees, and SQ8 RAM compression stats.
- `POST /api/hnsw/benchmark` — Live head-to-head performance benchmark comparing Flat Brute-force vs HNSW Search.
- `POST /api/hnsw/quantize` — Inspect Int8 scalar quantization byte conversion and delta.

### DHCP Auto-Discovery & Permissions
- `POST /api/discovery/allocate` — Allocate dynamic DHCP lease and canonical alias.
- `GET /api/discovery/resolve?alias={alias}` — Resolve canonical alias to entity coordinates.
- `GET /api/discovery/search?q={query}` — Search directory across aliases, nodes, and categories.
- `GET /api/discovery/catalog` — Retrieve cluster-wide lease statistics.
- `POST /api/permissions/request` — Submit cross-node access request (`READ`, `WRITE`, `MERGE`, `ADMIN`).
- `POST /api/permissions/review` — Node owner approves or rejects pending request.

### Git Branching & Dot Indexer
- `POST /api/branch/create` — Create isolated developer branch on a node.
- `POST /api/branch/commit` — Submit atomic compound commit to a branch.
- `POST /api/branch/push` — Push branch changes to target branch (`main`).
- `POST /api/branch/pull` — Pull updates into developer branch.
- `POST /api/branch/restore` — Rollback branch to historical commit hash.
- `GET /api/branch/diff` — Compare Merkle roots and entities between branches.
- `GET /api/dot/resolve?path={path}` — Resolve $\mathcal{O}(1)$ hierarchical dot path.

---

## 🧪 Testing & Verification

The test suite runs with `pytest` and validates all architectural layers:

```bash
pytest tests/ -v
```

### Test Suite Summary:
- **136/136 Unit & Integration Tests Passing (100%)**
- Covers:
  - Merkle-DAG ripple integrity and compound commit atomicity.
  - ReBAC authorization and graph anomaly detection.
  - Machine learning feature extraction and Isolation Forest scoring.
  - Raft leader election, heartbeat timeouts, and log replication.
  - Consistent hashing ring distribution and virtual node balancing.
  - Lossy network recovery and stampede token-bucket ceilings.
  - Git branching, diff, rollback, and dot-notation resolution.
  - DHCP dynamic allocation, alias resolution, and cross-node permission leases.
  - AgentDB semantic vector caching, MMR, and semantic neighborhood invalidation.
  - Dense text embedding and hybrid relational audit log vector search.
  - Q-learning RL stampede governor and adaptive token-bucket dynamic tuning.
  - Async QUIC transport UDP packet serialization and stream isolation.
  - HNSW multi-layer vector graph index, Int8 scalar quantization, and self-healing deletion.
  - Frontend static routing and asset delivery.

---

## 📄 License
MIT License. Created by [Bhandarihansraj](https://github.com/Bhandarihansraj).
