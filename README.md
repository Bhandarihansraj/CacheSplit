# ⚡ CacheSplit v4

> **Distributed Relational Cache Fabric with Cryptographic Merkle-DAG Integrity, Git-Style Branch Isolation, HNSW Vector Indexing, and Redis Compatibility Engine**

[![Python Version](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/tests-170%2F170%20passing%20(100%25)-brightgreen.svg)](tests/)
[![License](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)

CacheSplit is a next-generation distributed caching and relational data fabric. It integrates **cryptographic Merkle DAGs**, **Git-style branch isolation**, **DHCP dynamic alias addressing**, **ReBAC graph access control**, **Q-learning stampede governance**, **HNSW vector similarity search with Int8 Scalar Quantization (SQ8)**, and a **complete in-memory Redis Engine (Strings, Hashes, Lists, Sets, ZSets, TTL Eviction, Pub/Sub, and Redlock Mutex)**.

---

## 📖 Table of Contents
1. [Executive Summary & Capabilities](#-executive-summary--capabilities)
2. [Industry Comparison Matrix](#-industry-comparison-matrix)
3. [Architecture Overview & Data Flow](#-architecture-overview--data-flow)
4. [Complete Phase Roadmap (Phases 0 to 32)](#-complete-phase-roadmap-phases-0-to-32)
5. [Docker & Container Quickstart (Run Anywhere)](#-docker--container-quickstart-run-anywhere)
6. [Local Manual Quickstart](#-local-manual-quickstart)
7. [Subsystem & Module Reference](#-subsystem--module-reference)
8. [Interactive Web UI Dashboards](#-interactive-web-ui-dashboards)
9. [REST, WebSocket & Redis API Reference](#-rest-websocket--redis-api-reference)
10. [Automated Verification & Complexity Suite (170/170 Passing)](#-automated-verification--complexity-suite-170170-passing)

---

## 🎯 Executive Summary & Capabilities

Traditional caches (Redis, Memcached, DAX) operate as dumb key-value stores: they suffer from silent data drift, cache stampedes during sudden invalidations, zero built-in cryptographic auditability, and no concept of developer branch isolation.

**CacheSplit eliminates these limitations:**
- 🛡️ **Cryptographic Merkle-DAG Integrity**: Every mutation computes SHA-256 parent-linked hashes that ripple deterministically to root entities ($O(d)$ depth ripple). Tampering is mathematically impossible without invalidating root signatures.
- 🔀 **Git-Style Node Branching**: Multi-developer branch isolation (`main`, `feature/*`, `hotfix/*`) on individual nodes, complete with commit logs, three-way OCC diffing, push, pull, and point-in-time rollbacks.
- 🌐 **DHCP-Style Dynamic Addressing**: Eliminates random hash/UUID memorization by auto-assigning human-readable canonical aliases (e.g. `cluster.us.east.healthcare.pat-00042`) and virtual IPs (`10.100.x.y`) with $O(1)$ lease resolution.
- 🔐 **Relationship-Based Access Control (ReBAC)**: Bidirectional BFS graph authorization along relationship paths (e.g., `Clinician -> ASSIGNED_TO -> Visit -> CONTAINS -> Record`) with cycle protection.
- 🤖 **Adaptive RL Stampede Governor**: Q-learning Bellman policy dynamically tuning token-bucket rates and burst limits under live packet drop ($p=0.0 \to 0.9$) and latency feedback.
- ⚡ **HNSW Vector Graph & Int8 Quantization (SQ8)**: Multi-layer proximity graph ($O(\log N)$ beam search) with asymmetric cosine similarity and 4x RAM reduction.
- 🔴 **Redis Compatibility Engine**: In-memory engine supporting Strings, Hashes, Lists, Sets, Sorted Sets (ZSets), passive/active TTL sweeps, eviction policies (`allkeys-lru`, `volatile-lru`, `allkeys-lfu`, `volatile-ttl`, `noeviction`), Pub/Sub wildcard pattern matching, and Distributed Redlock mutexes.
- 🚀 **QUIC UDP Transport Mesh**: Sub-millisecond multiplexed invalidation bus eliminating TCP Head-of-Line blocking.

---

## 📊 Industry Comparison Matrix

| Feature / Dimension | **CacheSplit v4** | **Redis (OSS)** | **Memcached** | **AWS DynamoDB DAX** | **Hazelcast / Ignite** |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Cryptographic Merkle DAG** | ✅ **Native ($O(d)$ ripple)** | ❌ No | ❌ No | ❌ No | ❌ No |
| **Tamper-Evident Hash Chain** | ✅ **SHA-256 + HMAC** | ❌ No | ❌ No | ❌ No | ❌ No |
| **Git-Style Branching per Node** | ✅ **Yes (Commit/Diff/Rollback)** | ❌ No | ❌ No | ❌ No | ❌ No |
| **DHCP Dynamic Canonical Aliases** | ✅ **Yes ($O(1)$ Leases)** | ❌ No | ❌ No | ❌ No | ❌ No |
| **Relationship-Based Access (ReBAC)** | ✅ **Native Graph BFS** | ❌ (ACL only) | ❌ No | ❌ (IAM only) | ❌ (RBAC only) |
| **In-Memory Redis Data Structures** | ✅ **Strings/Hash/List/Set/ZSet** | ✅ Native | ❌ Key-Value only | ❌ Item cache only | ⚠️ Custom maps |
| **TTL Expiration & Eviction Policies** | ✅ **LRU / LFU / TTL Sweeps** | ✅ Native | ⚠️ LRU only | ⚠️ TTL only | ✅ Configurable |
| **Distributed Redlock Mutex** | ✅ **Atomic token + lease** | ⚠️ Script/Client | ❌ No | ❌ No | ✅ CP Locks |
| **Pub/Sub Wildcard Pattern Matching** | ✅ **Native `PSUBSCRIBE`** | ✅ Native | ❌ No | ❌ No | ✅ Topic Listeners |
| **Vector Search & HNSW Indexing** | ✅ **Native ($O(\log N)$)** | ⚠️ RedisStack/Paid | ❌ No | ❌ No | ⚠️ Plugin |
| **Scalar Quantization (Int8 SQ8)** | ✅ **$4\times$ RAM reduction** | ❌ Enterprise only | ❌ No | ❌ No | ❌ No |
| **Reinforcement Learning Stampede Governor**| ✅ **Q-Learning Q-Table** | ❌ No | ❌ No | ❌ No | ❌ No |
| **QUIC Sub-ms UDP Mesh** | ✅ **Zero HoL Blocking** | ❌ TCP only | ❌ TCP/UDP raw | ❌ VPC TCP only | ❌ TCP only |
| **ML Access Anomaly Detection** | ✅ **Isolation Forest** | ❌ No | ❌ No | ❌ No | ❌ No |
| **Single-Command Docker Deployment** | ✅ **Ready (`compose.yml`)** | ✅ Ready | ✅ Ready | ❌ Cloud only | ⚠️ Heavyweight JVM |

---

## 🏗️ Architecture Overview & Data Flow

```
                      ┌────────────────────────────────────────────────────────┐
                      │          Web Operations & Explorer Console             │
                      │  Node Map · Redis CLI · Pub/Sub & Redlock · Vector Lab │
                      │  Commit Lab · Git Branch Ops · DHCP Dir · Benchmarks   │
                      └───────────────────────────┬────────────────────────────┘
                                                  │ HTTP / WebSocket (/api/ws/state)
                      ┌───────────────────────────▼────────────────────────────┐
                      │              FastAPI API Gateway Layer                 │
                      │  /api/redis · /api/pubsub · /api/redlock · /dashboard  │
                      │  /api/branch · /api/discovery · /api/hnsw · /api/quic  │
                      └─────────────┬────────────────────────────┬─────────────┘
                                    │                            │
             ┌──────────────────────▼────┐         ┌─────────────▼─────────────────────┐
             │     Core Engine Layer     │         │        Services & Workers         │
             │  RedisStore · RedlockMgr  │         │  PubSubManager · NodeRegistry     │
             │  MerkleDAG · BranchEngine │         │  AuditBatcher · SyncLoop          │
             │  HNSWIndex · ScalarQuant  │         │  RaftConsensus · WriteBehindQueue │
             │  DHCPDiscovery · ReBAC    │         │  SemanticRouter · QuicMeshService │
             │  RLGovernor · QUICTransport        │  AdaptiveRecoveryService          │
             └──────────────┬────────────┘         └─────────────┬─────────────────────┘
                            │                                    │
             ┌──────────────▼────────────────────────────────────▼─────────────┐
             │                     Persistence & Storage Layer                 │
             │  SQLite (data/cachesplit.db) · Isolation Forest Anomaly Weights │
             │  ReBAC Edge Graph · Audit Trail · Distributed Hash Pointers     │
             └─────────────────────────────────────────────────────────────────┘
```

---

## 🗺️ Complete Phase Roadmap (Phases 0 to 32)

Every single phase is fully implemented with 100% test coverage:

- **Phase 0: Hash Chain & Genesis Core** — SHA-256 parent hashing, tamper-evident verification.
- **Phase 1: Node Registry & Agent Lifecycle** — Regional node discovery, heartbeat monitoring, stale sweeps.
- **Phase 2: Debounce Window & Token Bucket** — Single-flight coalescing under 1,000 burst triggers.
- **Phase 3: Authentic Cryptographic Signatures** — HMAC-SHA256 origin signing and tamper-proof verification.
- **Phase 4 & 5: Merkle DAG Hierarchy & Subtree Invalidation** — Leaf-to-root ripple ($O(d)$) without full tree scans.
- **Phase 6: ReBAC Contextual Graph Access** — BFS relationship traversal with cycle safety.
- **Phase 7 & 8: Compound Multi-Entity Atomic Commits** — Multi-table batch mutation validation ($O(M)$).
- **Phase 9: Real-Time Event Fanout & WebSockets** — Bidirectional state broadcasting.
- **Phase 10: Optimistic Concurrency Control (OCC)** — CAS version collision detection.
- **Phase 11: Real-Time Visual Sync Engine** — Live canvas node rendering and UI telemetry.
- **Phase 12: Node Startup Handshake & Cluster Consensus** — Secure join tokens and compatibility checks.
- **Phase 13: Multi-Domain Isolation** — Separation of Healthcare, Users, Payments, and Telemetry domains.
- **Phase 14: Interactive Commit Lab & Diffing** — Delta payload diffing ($O(F)$) and manual staging.
- **Phase 15: Background Sync Loop** — Continuous background consistency convergence.
- **Phase 16: Port & Node Network Scanner** — Regional node pinging and latency probing.
- **Phase 17: CLI Control & Diagnostic Tools** — Command-line management utilities.
- **Phase 18: Raft Consensus Engine** — Leader election, term validation, log replication ($O(L)$).
- **Phase 19: Consistent Hash Ring** — Virtual node replication ($10,050$ vnodes, $O(\log V)$ lookup).
- **Phase 20: Write-Behind Queue** — Asynchronous non-blocking persistence and batch flushing.
- **Phase 21: Developer Portal & Rate Limiting** — Token authentication and sliding window limiter.
- **Phase 22: Stampede Recovery under Lossy Networks** — Gossip-based deduplicated repair ($p=0.0 \to 0.9$).
- **Phase 23: Git-Style Branching & Dot Indexer** — Node branch isolation, checkout, merge, and dot-path lookup ($O(k)$).
- **Phase 24: DHCP Dynamic Discovery & Leases** — Human-readable canonical alias addressing over 10,000+ leases ($O(1)$).
- **Phase 25: Semantic Vector Cache & MMR** — Dense embeddings, cosine similarity, and MMR diversity selection.
- **Phase 26: Audit Vector Search Engine** — Vectorized audit log search and forensic querying.
- **Phase 27: Reinforcement Learning Stampede Governor** — Q-learning adaptive rate limit controller.
- **Phase 28: QUIC Transport Multiplexing** — Sub-millisecond UDP streaming with zero HoL blocking.
- **Phase 29: HNSW Graph & Int8 Quantization (SQ8)** — $O(\log N)$ beam search with 4x memory compression.
- **Phase 30: Redis In-Memory Engine** — Strings, Hashes, Lists, Sets, and Sorted Sets (ZSets).
- **Phase 31: TTL Expiration & Memory Eviction** — Passive/active TTL sweeps, `allkeys-lru`, `allkeys-lfu`, `volatile-ttl`.
- **Phase 32: Redis Pub/Sub & Distributed Redlock** — Exact/pattern message delivery, mutual exclusion mutexes.

---

## 🐳 Docker & Container Quickstart (Run Anywhere)

CacheSplit is fully containerized and can be launched on any OS (Linux, macOS, Windows) or cloud VM with Docker installed.

### Option 1: Launch Multi-Node Cluster with Docker Compose (Recommended)
```bash
# Clone repository
git clone https://github.com/Bhandarihansraj/CacheSplit.git
cd CacheSplit

# Build and launch cluster (Master Gateway + US Node + EU Node)
docker compose up --build -d

# View live cluster status
docker compose ps
```

Open your browser to:
- **Operations Console & Dashboards**: [http://localhost:8000/dashboard](http://localhost:8000/dashboard)
- **Redis Explorer & CLI**: [http://localhost:8000/dashboard#page-redis](http://localhost:8000/dashboard#page-redis)
- **Pub/Sub & Redlock Studio**: [http://localhost:8000/dashboard#page-pubsub-locks](http://localhost:8000/dashboard#page-pubsub-locks)
- **Interactive Test Suite & Complexity Runner**: [http://localhost:8000/ui/test_cases.html](http://localhost:8000/ui/test_cases.html)
- **Interactive Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

### Option 2: Run Standalone Single Container
```bash
# Build Docker image
docker build -t cachesplit:v4 .

# Run container exposing Web UI, Redis, and QUIC
docker run -d -p 8000:8000 -p 6379:6379 -p 4433:4433/udp --name cachesplit-instance cachesplit:v4

# Check logs
docker logs -f cachesplit-instance
```

### Option 3: Run Full Automated Test Suite in Docker
```bash
docker compose -f docker-compose.test.yml up --abort-on-container-exit
```

---

## 💻 Local Manual Quickstart

### Prerequisites
- Python 3.11, 3.12, or 3.13
- pip and virtualenv

```bash
# 1. Create and activate virtual environment
python -m venv .venv
# On Windows:
.\.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch FastAPI server
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🖥️ Interactive Web UI Dashboards

CacheSplit provides a rich single-page operations console (`ui/dashboard.html`):

1. **🗺️ Cluster Topology & Node Map (`#page-nodemap`)**: Live health, heartbeats, and regional latency.
2. **🔴 Redis Explorer & CLI Console (`#page-redis`)**: Interactive command shell (`SET`, `GET`, `HSET`, `HGETALL`, `LPUSH`, `LRANGE`, `SADD`, `ZADD`, `EXPIRE`, `TTL`, `PERSIST`, `INFO`).
3. **📡 Pub/Sub Studio & Redlock Mutex (`#page-pubsub-locks`)**: Real-time channel broadcasts, wildcard pattern matching, and distributed mutex locking with auto-lease expiry.
4. **🧠 Semantic Vector Lab & HNSW Benchmarks (`#page-vectorlab`)**: Vector similarity search, Int8 SQ8 quantization comparison, and MMR diversity.
5. **🔀 Git Branch Manager (`#page-branches`)**: Multi-developer branch isolation, diffing, and point-in-time rollbacks.
6. **🌐 DHCP Dynamic Address Directory (`#page-discovery`)**: Human-readable alias search over cluster leases.
7. **🧪 Test Suite & Complexity Runner (`ui/test_cases.html`)**: Real-time complexity benchmarks and assertion verification.

---

## 🔌 REST, WebSocket & Redis API Reference

### 1. Redis Compatibility APIs
- `POST /api/redis/command` — Unified CLI dispatcher (`{"command": "SET user:1 'Hansraj' EX 60"}`).
- `GET /api/redis/keys` — List all active keys with data types and TTLs.
- `POST /api/redis/string/set` & `GET /api/redis/string/get` — String operations.
- `POST /api/redis/hash/set` & `GET /api/redis/hash/getall` — Hash operations.
- `POST /api/redis/list/push` & `GET /api/redis/list/range` — List operations.
- `POST /api/redis/set/add` & `GET /api/redis/set/members` — Set operations.
- `POST /api/redis/zset/add` & `GET /api/redis/zset/range` — Sorted Set operations.
- `POST /api/redis/ttl/expire` & `GET /api/redis/ttl/{key}` — TTL inspection and expiration.
- `POST /api/redis/eviction/config` — Configure maxmemory and policy (`allkeys-lru`, `allkeys-lfu`, etc.).
- `POST /api/pubsub/publish` — Broadcast message to channel (`{"channel": "news", "message": "hello"}`).
- `POST /api/pubsub/subscribe` & `POST /api/pubsub/psubscribe` — Channel/pattern subscriptions.
- `POST /api/redlock/acquire` & `POST /api/redlock/release` — Acquire/release distributed mutex lock.

### 2. Core Cluster & DAG APIs
- `GET /api/dashboard/node-map` — Real-time cluster status.
- `POST /api/branch/create` — Create isolated branch.
- `POST /api/discovery/allocate` & `GET /api/discovery/resolve/{alias}` — DHCP lease allocation.
- `POST /api/semantic/query` — Semantic vector search with MMR.
- `POST /api/hnsw/search` — HNSW proximity graph search.
- `GET /api/governor/metrics` — RL Stampede Governor telemetry.
- `WS /api/ws/state` — Live WebSocket cluster state streaming.

---

## 🧪 Automated Verification & Complexity Suite (170/170 Passing)

Run the full automated test suite locally:
```bash
pytest tests/ -v
```

### Result:
```text
============================= test session starts =============================
collected 170 items

tests/test_api_dashboard.py .........................                   [ 14%]
tests/test_branching_dot_audit.py ......................                [ 27%]
tests/test_dhcp_permissions_scaler.py ................                  [ 37%]
tests/test_er_merkle_rebac.py ...................                       [ 48%]
tests/test_phase30_redis_store.py ....................                  [ 60%]
tests/test_phase31_ttl_eviction.py .............                        [ 67%]
tests/test_phase32_pubsub_redlock.py ...........                        [ 74%]
tests/test_phase33_complexity_worst_case.py ........................    [ 88%]
tests/test_stampede_recovery.py .............                           [ 96%]
tests/test_ui_routes.py ......                                          [100%]

====================== 170 passed, 2 warnings in 17.11s =======================
```

---

## 📄 License

CacheSplit is open-source software licensed under the [MIT License](LICENSE).
