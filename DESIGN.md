# CacheSplit Technical Architecture & Design Document (v4)

## Executive Overview
**CacheSplit** is a specialized distributed data fabric built for regulated, graph-structured domains (healthcare, supply chain, audit trails) where cryptographic integrity, relationship-aware access control (ReBAC), and stampede-safe cache invalidation recovery matter more than raw unstructured key-value throughput.

---

## 1. Problem Formulation: Partial Cache Invalidation Recovery Without Stampede

In distributed multi-node caching systems:
1. **Unreliable Invalidation Bus**: Cache invalidation signals can be dropped or delayed over realistic network links, causing node state divergence.
2. **Origin Overload Risk**: When multiple nodes discover they hold stale data, naive refresh strategies trigger a thundering herd (stampede) that overwhelms the bounded origin capacity.
3. **Multi-Version Inconsistency**: Overlapping writes can occur while recovery is in flight, placing nodes multiple versions behind.

### CacheSplit v4 Solution Architecture:
```
[ Origin (Bounded RPS Token Bucket) ]
               ▲
               │ Deduplicated Batch Fetch (1 origin read per key)
[ Recovery Coordinator (Gossip Staleness Detection + Queue) ]
               ▲
   Version Vectors & Gossip Sync
               ▼
[ Regional Cache Nodes (State Machine: FRESH -> STALE -> REPAIRING -> FRESH) ]
               ▲
   Lossy Invalidation Bus (Probabilistic Drops + Random Delay)
               ▼
       [ Write Client ]
```

---

## 2. Core Architectural Subsystems

### A. Token-Bucket Rate Limiter (`core/stampede_limiter.py` & `core/origin.py`)
- Provides a mathematical ceiling on origin reads via non-blocking token consumption.
- Prevents thundering herds by raising `OriginOverload` when the capacity budget is exceeded, forcing backoff and queueing.

### B. Gossip-Based Staleness Detection & Dedup Repair (`core/recovery_coordinator.py`)
- Nodes communicate via lightweight version vectors (`{key: version}`).
- Gossip rounds compare node version vectors against the authoritative origin vector.
- Only stale keys (`local_v < origin_v`) are queued for repair (fresh entries are untouched).
- **Deduplication Engine**: When $N$ nodes require a refresh for key $K$, the coordinator issues exactly $1$ origin fetch and fans the result out to all $N$ waiting nodes.

### C. Relational Merkle-DAG Integrity (`core/merkle_dag.py` & `core/compound_commit.py`)
- Entities form directed acyclic graphs (`Patient -> Visit -> Lab / Billing / Payment`).
- Mutations to child entities deterministically ripple SHA-256 hashes up to root nodes.
- Compound commits apply atomic multi-entity mutations with Optimistic Concurrency Control (OCC) version guards.

### D. Relationship-Based Access Control (`core/rebac.py`)
- Access authorization is evaluated over graph connectivity (`ASSIGNED_TO`, `BELONGS_TO`) rather than coarse static roles.
- Least-privilege field masking filters sensitive attributes dynamically based on requester relationship paths.

### E. Consistent Hash Ring (`core/consistent_hash.py`)
- Employs a $2^{32}$ hash ring with 150 virtual nodes per physical node using SHA-256.
- Ensures uniform key distribution with minimal remapping upon node churn.

### F. Security & ML Anomaly Detection (`agents/security_agent.py` & `agents/graph_security_agent.py`)
- Uses scikit-learn `IsolationForest` trained on multidimensional access patterns (request rate, entity jurisdiction, time-of-day, payload size) to detect and quarantine rogue access.
- Heuristic graph scanners identify orphan entities and cross-region leakage.

---

## 3. Deployment & Integration Topology

| Layer | Implementation | Purpose |
|---|---|---|
| **API Layer** | FastAPI / Uvicorn (ASGI) | REST endpoints, WebSocket event streams, developer API |
| **In-Memory Cache** | Python Dicts + Merkle DAG | Sub-millisecond localized graph traversal & state machine |
| **Persistence** | SQLite with WAL Mode (`aiosqlite`) | Resilient transaction logs, node registry, and security events |
| **Consensus & Sync** | Raft-inspired Leader Election & Background Sync Loop | Node health heartbeats and inter-node reconciliation |
| **Operations Console** | Vanilla HTML5 / ES6 + WebSockets | Zero-dependency operations dashboard, commit lab, and simulation UI |

---

## 4. API Specification Summary

- **Simulation**:
  - `POST /api/sim/start` — Initialize cluster simulation
  - `GET /api/sim/snapshot` — Poll real-time node state machine and token bucket
  - `POST /api/sim/update` — Trigger origin update with lossy invalidations
  - `POST /api/sim/step` — Advance one gossip and recovery cycle
- **Developer API**:
  - `POST /api/dev/keys` — Generate developer API key
  - `POST /api/dev/ops` — Push unified compound commit payload
- **Cluster & Scanner**:
  - `GET /api/dashboard/node-map` — View cluster status and health
  - `GET /api/scan/{entity_id}` — Nmap-style cluster propagation matrix
  - `GET /api/sharding/locate/{entity_id}` — Locate key on consistent hash ring
