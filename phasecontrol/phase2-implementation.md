# Phase 2 Implementation — DB Adapter (Postgres reference) & Dashboard Backend APIs
Depends on: Phase 0 (`adapters/interface.py` scaffolded), Phase 1 (registry, agents, query endpoint working).

---

## 1. `adapters/postgres_adapter.py` — reference implementation

**Purpose:** first real (non-mock) implementation of `CommitStore`, proving the interface is genuinely swappable — this is what lets a new multinational client drop in Oracle/Mongo later without touching `core/`.

**Interface (already defined in `adapters/interface.py`, implement against it exactly):**
```
class PostgresAdapter(CommitStore):
    def __init__(dsn, pool_min=2, pool_max=10)
    async def write(commit: Commit) -> None
    async def read(commit_hash: str) -> Commit
    async def list_history(entity_id: str) -> list[Commit]
```

**Implementation notes:**
- Connection pooling required (`asyncpg` pool) — a single connection per request will not survive the load-test scale from Phase 2's stampede scenario.
- `write()` must be idempotent on `commit_hash` (primary key) — a retried write from a debounce/retry path must not create a duplicate or error the caller; upsert-on-conflict-do-nothing is correct here.
- `list_history()` returns commits ordered by `version_number` ascending — callers (dashboard, reconciliation agent) rely on chain order, don't make them re-sort.
- No raw PHI values pass through this adapter differently than any other field — the adapter stores whatever `json_manifest` contains; field-masking happens above this layer (`core/access_control.py`), never inside the adapter. Keep that boundary strict — an adapter that starts doing its own filtering duplicates logic that must live in exactly one place.

**Contract test (ties to Section 6 QA gate):** run the exact same test suite that validates `sqlite_mock.py` against `PostgresAdapter` — identical pass/fail results required. If a test needs different assertions for Postgres, the interface itself is leaking implementation details and needs fixing before this is "done."

---

## 2. Dashboard backend APIs (`api/dashboard.py` — new file)

**Purpose:** read-only endpoints the UI (owned separately by you) consumes. Every endpoint here maps to one of the 8 dashboard requirements from the v2 doc — no endpoint should exist that isn't backing a stated requirement, and no requirement should lack an endpoint.

| Endpoint | Backs requirement | Returns |
|---|---|---|
| `GET /dashboard/node-map` | Node map (health color-coded) | list of `NodeStatus` (region, tier, health only — no raw data) |
| `GET /dashboard/node/{node_id}/cache-summary` | Cache content viewer | `cache_summary` (field names + hashes only) |
| `GET /dashboard/history/{entity_id}` | Commit history timeline | `list_history()` output, already plain-language mapped (see below) |
| `POST /dashboard/query` | Multi-master query panel | proxies to `api/query.py`, same field-mask enforcement |
| `GET /dashboard/security-feed` | Security/anomaly feed | recent `agent_flags` stream from registry |
| `POST /dashboard/annotate/{node_id}` | Editable annotations | creates a commit (never a silent write) — see Phase 1 reconciliation notes |
| `GET /dashboard/db-status` | DB connector status | active adapter name + connection health, per company/tenant |
| `GET /dashboard/remediation-log` | Auto-remediation log | list of auto-actions taken, each with a `rollback` action reference |

**Plain-language response mapping (per your non-technical-user-flow requirement):**
- Every field going to a dashboard endpoint must already carry a `status_label` (e.g. `"needs attention"`) alongside the raw `health` enum — translation happens server-side, not in the UI. This was the explicit rule from the earlier flow discussion; enforce it here so the UI layer never has to guess or duplicate that mapping.
- No `commit_hash`, `version_number`, or raw field values appear in any dashboard response — only what Section 4 (v2 doc) actually asked the UI to show.

**Rate/debounce note:** dashboard polling must go through the same `services/debounce.py` mechanism as node-originated triggers — a UI auto-refreshing every 2 seconds from 10 ops sessions is itself a stampede risk if it hits origin directly. Dashboard reads should serve from the registry's cached state, not force a fresh origin fetch per poll.

---

## 3. Acceptance criteria (adds to the running QA gate list)
1. `PostgresAdapter` passes identical contract-test suite as `sqlite_mock` — 100% parity.
2. Idempotent write confirmed — retried write with same `commit_hash` does not error or duplicate.
3. Every one of the 8 dashboard requirements has a working endpoint (traceable 1:1, Section 2 table above).
4. Dashboard responses contain zero raw technical fields (`commit_hash`, `version_number`, unmapped `health` enum) — plain-language `status_label` present on every status field.
5. Dashboard polling load test — 10 concurrent sessions, 2s poll interval — confirmed served from registry cache, zero additional origin fetches triggered.
