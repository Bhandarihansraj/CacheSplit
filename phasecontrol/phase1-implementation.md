# Phase 1 Implementation — Node Hierarchy & API
Scope (per your checklist): `api/server.py`, `api/query.py`, `services/debounce.py`, `services/registry.py`, `agents/security_agent.py`, `agents/reconciliation_agent.py`
Depends on: Phase 0 (`core/commit.py`, `core/hash_chain.py`, `core/access_control.py`, `adapters/interface.py`) — already scaffolded.

---

## 1. `services/registry.py` — Node Index (the router)

**Purpose:** single source of truth for "what exists where." Global queries hit this index first — never a broadcast to all nodes.

**Data contract:**
```
NodeStatus:
  node_id: str
  region: str
  tier: Literal["main", "sub"]
  parent_node_id: str | None          # sub-node's main-node, main-node's region coordinator
  current_commit_hash: str
  version_number: int
  cache_summary: dict[str, str]        # field_name -> field_hash, NEVER raw values
  last_heartbeat: datetime
  health: Literal["ok", "stale", "quarantined"]
  agent_flags: list[str]               # populated by security_agent / reconciliation_agent
```

**Interface (signatures only):**
```
class NodeRegistry:
    def register_node(node_id, region, tier, parent_node_id) -> None
    def heartbeat(node_id, current_commit_hash, version_number, cache_summary) -> None
    def get_status(node_id) -> NodeStatus
    def list_by_region(region) -> list[NodeStatus]
    def list_all_masters() -> list[NodeStatus]          # tier == "main" across all regions
    def mark_stale(node_id, reason) -> None              # called by reconciliation_agent
    def mark_quarantined(node_id, reason) -> None         # called by security_agent
```

**Staleness detection rule:** a node with `last_heartbeat` older than `2 × heartbeat_interval` is auto-marked `stale` by the registry itself — do not wait for the reconciliation agent to catch every case; this is the structural safety net under the agent.

**Health-check timing note (from Phase 1 QA):** a killed/silent node must flip to `stale` within one heartbeat interval — not two, not "next reconciliation tick." Implement via a background sweep task (`asyncio.create_task`), not lazy evaluation on read.

---

## 2. `services/debounce.py` — Coalescing layer

**Purpose:** collapse N rapid invalidation triggers into 1 fetch per node, per debounce window. This is what prevents the "repeated requests kill the server" scenario.

**Interface:**
```
class DebounceWindow:
    def __init__(node_id, window_ms=1000)
    def trigger(new_version_hint) -> None     # called every time an invalidation event arrives
    async def wait_and_resolve() -> str        # resolves ONCE per window, returns latest known commit_hash to fetch
```

**Behavior contract:**
- Calling `trigger()` multiple times within `window_ms` must NOT create multiple pending fetches — only the window's single scheduled resolve fires.
- If a new `trigger()` arrives while a window is already open, it does not reset an already-firing fetch, but does extend coverage so the fetch resolves to the *latest* hint, not the first one.

**Origin-side companion — stampede budget (separate object, same file or `core/`):**
```
class StampedeBudget:
    def __init__(region, max_requests_per_sec)
    def try_acquire() -> bool     # non-blocking; returns False if budget exhausted this second
```
Every actual origin-fetch (post-debounce) must call `try_acquire()` first. If `False`, the fetch is queued for next tick — never dropped silently.

---

## 3. `agents/security_agent.py`

**Purpose:** anomaly detection on node request patterns — flags possible parameter tampering / scope-violation attempts.

**Model:** Isolation Forest (unsupervised).
**Features per request event:** `{node_id, requested_fields, request_rate_last_60s, time_of_day, request_size_bytes}`.
**Training data:** synthetic baseline generated from Phase 1/2 normal-traffic load tests (no real PHI/production traffic).

**Interface:**
```
class SecurityAgent:
    def __init__(model_path)
    def score_event(request_event) -> float        # anomaly score, higher = more anomalous
    def evaluate(request_event, threshold=0.7) -> bool   # True = flag as anomalous
    def on_flag(node_id, reason) -> None            # calls registry.mark_quarantined(...)
```

**Wiring:** every request through `api/server.py` / `api/query.py` passes through `SecurityAgent.evaluate()` before being served. Flagged events are logged (not silently dropped) and pushed to `agent_flags`.

---

## 4. `agents/reconciliation_agent.py`

**Purpose:** decides stale vs tampered vs corrupted — primary path is deterministic, ML is fallback only for ambiguous cases (per earlier design: reconciliation must stay explainable).

**Interface:**
```
class ReconciliationAgent:
    def check(node_status: NodeStatus, expected_commit_hash: str) -> Literal["ok", "stale", "tampered", "ambiguous"]
    def resolve_ambiguous(node_status) -> Literal["stale", "tampered"]   # rule-based decision tree, not black-box
```

**Decision logic (deterministic primary path):**
1. `node_status.current_commit_hash == expected_commit_hash` → `"ok"`.
2. Hash differs but node's `version_number` is behind and chain is intact (parent hashes verify back to a known-good ancestor) → `"stale"` → registry queues for refresh.
3. Hash differs and chain does NOT verify (broken parent link, or version claims to be ahead of what commit log shows) → `"tampered"` → `mark_quarantined`, do not refresh from this node's claimed state.
4. Partial manifest corruption / can't fully verify either way → `"ambiguous"` → `resolve_ambiguous()` rule-based fallback.

---

## 5. `api/server.py` — Heartbeat / ingress

**Endpoints (signatures, not full routes):**
```
POST /heartbeat        -> registry.heartbeat(...)   # then SecurityAgent.evaluate() on the event
GET  /status/{node_id} -> registry.get_status(node_id)
```
All responses pass through `core/access_control.py` (Controller) before serialization — plus the secondary field-mask check here (defense-in-depth, per earlier review) so a Controller bug can't leak unscoped fields.

## 6. `api/query.py` — Multi-master query

**Endpoint:**
```
POST /query
  body: { requester_scope, target: node_id | region | "all_masters" | [ids...], query_type }
  -> routes via NodeRegistry.list_by_region / list_all_masters (index-based, never a full node broadcast)
  -> each result passes through access_control field-mask before being included in response
```
Cross-region isolation: a query for `all_masters` returns one result object per region — never merges/mixes region payloads together, so a region-scoped requester can be denied specific entries without affecting others.

---

## 7. Acceptance criteria (must pass before Phase 1 is "done" — matches v3 QA gates)
1. Registry: killed node flips to `stale` within one heartbeat interval (background sweep, not lazy).
2. Debounce: 50 simultaneous triggers → exactly 1 resolved fetch.
3. Stampede: origin never exceeds configured `max_requests_per_sec` under 20-node simultaneous staleness.
4. Security agent: ≥90% recall on injected anomalies, <5% false-positive rate on normal-traffic replay.
5. Reconciliation agent: 0% tampered-classified-as-ok (hard gate, no tolerance).
6. Query endpoint: 0 scope-leak cases in adversarial out-of-scope field test; `all_masters` never cross-mixes region data.
