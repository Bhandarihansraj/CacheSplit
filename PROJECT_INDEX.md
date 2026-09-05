# PROJECT INDEX: CacheSplit v3
> This document is the Single Source of Truth (SSoT) for the CacheSplit project. Read this before touching any code.

## 1. Project Identity
- **Name:** CacheSplit
- **Type:** Secure Distributed Commit-Cache Platform (v3)
- **Stack:** Python, FastAPI, asyncio, Pydantic, uv, TailwindCSS/HTML (UI)
- **Status:** Execution Phase (Phases 0-10 being implemented)

## 2. Architecture & Design Rules
- **Core Principle:** Provable deterministic verification for commits (Phase 0).
- **Relational Merkle DAG:** Entities form a Merkle Directed Acyclic Graph (Patient -> Visit -> LabResult / BedAllocation). Parent Root Hash = SHA256(Parent Data || sum(Child Hashes)). Child mutations deterministically ripple to parent root.
- **Compound Commits:** Multi-entity atomic transactions (`core/compound_commit.py`) across foreign keys in a single atomic memory swap.
- **ReBAC:** Relationship-Based Access Control (`core/rebac.py`) enforcing contextual graph path authorization (Clinician -> ASSIGNED_TO -> Visit -> CONTAINS -> LabResult).
- **Colocation Affinity:** Partitioning by Anchor Root Key (`patient_id`) ensuring relational subtrees reside on the same cache pod for sub-millisecond graph joins with zero cross-pod network hops.
- **Hierarchy & Debounce:** Global nodes route via `NodeRegistry`. Stampede budget and SingleFlight request coalescing.
- **ML Agents:** Isolation Forest anomaly detection & graph anomaly agent (detecting orphan scraping and cross-jurisdiction boundary breaches).
- **UI:** Anthropic Design System (Newsreader serif + Inter), live Merkle DAG inspector, interactive live mutator, compound commit form, ReBAC access tester, and node failure/recovery toggles.

## 3. Directory Structure
- `core/`: Immutable core logic, Commit schema, Hash verification, Access Control, `merkle_dag.py`, `compound_commit.py`, `rebac.py`, `tenant_config.py`.
- `services/`: Node Registry, Debounce / SingleFlight, `cache_store.py` (high-volume regional cache fabric).
- `agents/`: Security Agent (Isolation Forest), Reconciliation Agent, `graph_security_agent.py`.
- `api/`: FastAPI server, query, and comprehensive dashboard APIs (`dashboard.py`).
- `adapters/`: Database interfaces (`interface.py`, `postgres_adapter.py`, `sqlite_mock.py`).
- `ui/`: Enterprise Operations Console (`dashboard.html`, `index.html`, `app.js`).
- `tests/`: Pytest suite (16 test gates covering core, registry, agents, debounce, postgres, and ER Merkle ReBAC).
- `phasecontrol/`: Detailed phase specifications.

## 4. Execution State
- [x] **Phase 0:** Core engine, Pydantic business rules, Hash chain validation.
- [x] **Phase 1:** Node Registry heartbeat, background sweeper, Debounce window, Security Agent, Reconciliation Agent.
- [x] **Phase 2:** Postgres Adapter with asyncpg, idempotency, Multi-master read APIs.
- [x] **Phases 3-8 (ER Fabric):** Relational Merkle DAG, Compound Commits, ReBAC Graph Access Control, Regional Scaled Partitioning (100k+ entities).
- [x] **Phases 9-10:** CI/CD Workflow (`.github/workflows/ci.yml`), Ops routines (`ops/`), Tenant Config schema (`core/tenant_config.py`).
- [x] **Interactive Operations Console:** Live interactive dashboard at `http://127.0.0.1:8000/`.
