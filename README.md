# CacheSplit

A research/demo implementation of a **secure distributed commit-cache platform** for healthcare-style entity data. Written in Python (FastAPI + asyncio), backed by SQLite, with a single-page ops console.

> **Status: functional demo, not production software.** It demonstrates the core ideas end-to-end locally (single process, in-memory + SQLite). Distributed network behavior, real cryptography, and scale are **simulated or not implemented** — see [Honest limitations](#honest-limitations).

## What it demonstrates

- **Git-style commit chains** — every data change produces a SHA-256 hashed commit object; tampering with a committed manifest breaks hash verification (`core/hash_chain.py`).
- **Authentic (keyed) commit signing** — commit hashes are chained with an HMAC-SHA256 signature over the signed payload; a valid chain can only be produced by a key-holder, and every persisted commit stores the exact payload for later re-verification (`core/hash_chain.py`, `core/commit.py`, `core/compound_commit.py`).
- **Relational Merkle DAG** — entities (Patient → Visit → LabResult/Bed) form a DAG where a parent root hash depends on child hashes; mutating a child deterministically ripples to the parent root (`core/merkle_dag.py`).
- **Compound atomic commits** — multiple entity mutations + relationship edges applied in one in-memory operation with a single signed commit hash (`core/compound_commit.py`).
- **Wired propagation pipeline** — invalidation events coalesce into ONE origin fetch per debounce window, every fetch is gated by a per-node stampede budget, and the fetched chain is cryptographically verified. Live endpoints + tests (`services/propagation.py`, `api/propagation.py`).
- **ReBAC** — relationship-based access control via BFS over an edge table: a clinician is only authorized if a care-team path exists to the target (`core/rebac.py`, `db/security_repo.py`).
- **Node registry + health sweeps** — nodes heartbeat into a registry; stale or quarantined nodes are flagged, with background sweep and auto-heartbeat (`services/registry.py`).
- **Graph security agent** — rule-based anomaly checks for cross-jurisdiction access and orphan (parentless) record scraping; flags quarantine a node and write to a security feed (`agents/graph_security_agent.py`).
- **Multi-master query API** — query one node, a list, or `all_masters` for status / cache contents / commit history (`api/query.py`).
- **Ops console UI** — node map, entity explorer with Merkle tree inspection, compound-commit form, ReBAC tester, security feed, and multi-master query panel.

## Quick start

```
start.bat
```

Or manually:

```powershell
".venv\Scripts\python.exe" -m uvicorn api.server:app --reload --port 8000
".venv\Scripts\python.exe" seed_data.py
```

- UI dashboard: http://127.0.0.1:8000
- Demo walkthrough: `".venv\Scripts\python.exe" demo.py`
- Anomaly injection demo: `".venv\Scripts\python.exe" inject_anomaly.py`

## Tests

```powershell
".venv\Scripts\python.exe" -m pytest -q
```

34 tests cover: hash-chain + signature integrity, commit validation, node registry heartbeat/staleness, agents, debounce/stampede budgets, the Postgres adapter (mocked pool), dashboard APIs, the ER Merkle/ReBAC graph, and the signing + propagation pipeline.

## API surface

| Endpoint | Purpose |
|---|---|
| `GET /api/dashboard/node-map` | Live node health/status for the console |
| `GET /api/dashboard/node/{id}/entities` | Entities cached under a node |
| `GET /api/dashboard/entity/{id}/merkle-tree` | Merkle tree for an entity |
| `GET /api/dashboard/commits/recent` | Recent commit log |
| `POST /api/dashboard/compound-commit` | Apply a multi-entity atomic commit |
| `POST /api/dashboard/rebac/test` | Check a clinician's access path |
| `POST /api/dashboard/security/test-anomaly` | Evaluate a cross-region/orphan traversal |
| `GET /api/dashboard/security-feed` | Security event feed |
| `POST /api/dashboard/node/{id}/toggle-heartbeat` | Pause/resume heartbeat |
| `POST /api/dashboard/node/{id}/recover` | Recover a quarantined/stale node |
| `POST /api/query` | Multi-master query (status/cache_contents/commit_history) |
| `POST /api/propagation/invalidate` | Fire an invalidation hint for a cache node (coalesced) |
| `POST /api/propagation/fetch` | Debounced + budgeted sink fetch with chain verification |
| `GET /api/propagation/metrics` | Propagation stats (coalescing ratio, budget denials, chain results) |
| `POST /api/heartbeat`, `/api/register`, `/api/debug/quarantine` | Node lifecycle |
| `GET /` | Ops console UI |

## Directory layout

```
core/       Commit schema + origin signing key, hash chain/signatures, Merkle DAG, compound commit, ReBAC, access masks, tenant config
services/   Node registry, debounce/stampede, regional cache store, propagation pipeline
agents/     Isolation-Forest security agent, reconciliation agent, graph security agent
api/        FastAPI server + dashboard + multi-master query + propagation routers
db/         Async SQLite schema, node/commit/security repositories
adapters/   CommitStore interface + Postgres adapter + SQLite-mock adapter
ui/         Ops console (HTML/CSS/JS)
ops/        Skeleton backup / monitoring / secrets routines
tests/      Pytest suite
phasecontrol/  Phase implementation notes
```

## Honest limitations

- **Single process, single machine.** "Nodes" are rows in one SQLite DB + entries in one in-memory registry. There is no real network, no distributed pods, and no cross-node replication. "Sub-millisecond", "zero cross-pod hops", and "100k+ entities" in the design docs are **aspirational targets, not measured results**.
- **Signing is symmetric (one shared key), not asymmetric.** Commit hashes are chained with HMAC using a single origin key (dev key: `core/commit.py`). This proves *key-holder authenticity* and catches forgeries, but it is not PKI/mTLS — the PRD's signing-key/cert infrastructure is still a stub (`ops/secrets.py` returns a hardcoded dev string).
- **Propagation is a single-process simulation over loopback HTTP.** The debounce/stampede/verification pipeline is real and tested end-to-end through the API, but the "fetch" reads the same local SQLite commit log — there is no second process or network hop. Legacy unsigned commit rows (written before signing) are correctly flagged as unverifiable.
- **Security agent is rule-based, not learned.** `security_agent.py` fits an Isolation Forest on *random dummy data* and is effectively untested on real traffic; the graph anomaly detection that actually runs in the app is a hand-written rules check, not ML.
- **The Postgres adapter is unit-tested with a mocked pool; it has never run against a real Postgres.**
- **Field masks / least-privilege are not enforced on live endpoints.** The API currently returns full entity data; `core/access_control.py` and `tenant_config.py` define the concept only.
- **Synthetic data only.** Patients/labs/beds are randomly generated placeholders, including the "orphan billing record" used for the anomaly demo.
- **`ops/` routines are stubs** (logging placeholders, no real backup/restore/paging).
- README/`PROJECT_INDEX.md` phase checkmarks describe *intent*, not independent validation.

Everything documented above is what actually runs and is covered by the test suite.

## Completed Phases

- **Phase 15:** Security Event Feed & ReBAC visualization integrated into dashboard.
- **Phase 16:** Extracted API routes (users, payments, propagation, query, scanner) to modularize the application.
- **Phase 17:** Added `ops/demo_menu.py` for a CLI-based interactive demo of core functionality.