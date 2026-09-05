# CacheSplit v4 — Phase 22 Handoff Spec

> This document maps 1:1 to the 9 audit findings. Each file spec includes purpose, inputs/outputs, security requirement, and must-not constraints so the coding agent cannot skip the fix.

---

## 1. `commitcache/core/tenant.py` — Tenant Model + Scoping

**Finding:** No tenant/identity concept at all yet — every endpoint is unscoped (Critical, blocks billing + security)

**Purpose:** Every request, query, and mutation must carry a tenant_id — no unscoped operations exist.

**Inputs:** `tenant_id: str`, `identity: str` (user/service account)
**Outputs:** `Tenant` object with `tenant_id`, `identity`, `region`, `role`, `permissions: List[str]`

**Security requirement:** Tenant ID is validated against a registry before any operation. All API routes extract tenant_id from auth token, never from query parameters.

**Must not:** Allow any API endpoint to operate without an explicit tenant_id. Never pass tenant_id in query params or URL path.

---

## 2. `commitcache/core/lease.py` — Time-Boxed Lease

**Finding:** No lease/signed events — any node can forge a repair claim (Critical)

**Purpose:** Acquire a time-boxed lease on `(tenant_id, key)` before any repair operation. Leases prevent concurrent repairs and forge-able claims.

**Inputs:** `tenant_id: str`, `key: str`, `ttl_ms: int` → **Output:** `lease_token: str` or `None` (acquisition failed)
**Inputs:** `lease_token: str` → **Output:** `bool` (release success)

**Security requirement:** Lease acquisition uses atomic `SET NX PX` semantics. No read-then-write race. Lease token is HMAC-signed so it cannot be forged.

**Must not:** Allow repair to proceed without a valid, non-expired `lease_token`. Never allow lease renewal without re-acquisition.

---

## 3. `commitcache/core/audit_log.py` — HMAC-Signed Event Log

**Finding:** Dashboard has no auth on `/api/sim/snapshot` (High); No signed events → any node can forge repair claim (Critical)

**Purpose:** Every state-mutating event is HMAC-signed. Audit log provides tamper-evident trail of all repairs, leases, and state changes.

**Inputs:** `event_type: str`, `tenant_id: str`, `payload: dict`, `signing_key: str`
**Outputs:** `signed_event: dict` with `event_id`, `timestamp`, `hmac_signature`, `payload_hash`

**Security requirement:** Each event is signed with `HMAC-SHA256(tenant_key, canonical_json)`. Verification function rejects any event with invalid signature.

**Must not:** Allow any event to be appended to the audit log without a valid signature. Never log unverified state changes.

---

## 4. `commitcache/coordination/gossip_worker.py` — Independent Task

**Finding:** Gossip + repair coupled in one loop — one stalls the other (High)

**Purpose:** Decouple gossip from repair by running gossip as an independent async task that produces `StalenessReport` objects, not directly triggering repairs.

**Inputs:** `nodes: List[CacheNode]`, `origin: Origin`, `report_queue: asyncio.Queue`
**Outputs:** `StalenessReport` pushed to `report_queue`

**Security requirement:** Gossip worker never calls repair directly. It only produces reports. Communication is via bounded queue.

**Must not:** Gossip worker must not block on repair operations. Must not directly modify node state — only produce reports.

---

## 5. `commitcache/coordination/repair_worker.py` — Bounded Queue + Backoff

**Finding:** No backoff on re-queue → spin loop under load (Critical); `handle_read_miss` unreachable → miss path untested in prod (High)

**Purpose:** Consume `StalenessReport` from gossip_worker via bounded queue. Apply exponential backoff on re-queue. Make `handle_read_miss` reachable.

**Inputs:** `report_queue: asyncio.Queue` (bounded), `origin: Origin`, `state_manager`
**Outputs:** Repaired nodes, metrics (success/reject/timeout)

**Security requirement:** Re-queue uses exponential backoff starting at 1s, doubling each attempt, capped at 60s. Maximum 5 retries before escalating. `handle_read_miss` must be reachable and tested.

**Must not:** Allow infinite re-queue without backoff. Never allow unbounded memory growth from queued repairs.

---

## 6. `commitcache/coordination/repair_queue.py` — Seeded RNG, __lt__

**Finding:** Random key selection with no seed → non-reproducible failures (Medium); `PriorityQueue` used for job that's "biggest gap first" — no `__lt__` on ties → arbitrary ordering (Low)

**Purpose:** Priority queue where priority = biggest version gap first. Ties broken by deterministic seeded RNG. All entries comparable.

**Inputs:** `key: str`, `gap: int`, `seed: int` (optional, default 42)
**Outputs:** Queue entries with deterministic ordering

**Security requirement:** RNG is seeded and deterministic. Same inputs always produce same ordering. No hidden randomness.

**Must not:** Use `random.random()` without a seed. Never allow arbitrary ordering — every tie must be resolved deterministically.

---

## 7. `commitcache/api/auth.py` — Short-Lived JWT + Scope

**Finding:** No tenant/identity concept — every endpoint unscoped (Critical)

**Purpose:** Issue short-lived JWT tokens scoped to tenant + permissions. Every route validates token and extracts tenant_id.

**Inputs:** `identity: str`, `tenant_id: str`, `permissions: List[str]`, `ttl_seconds: int` (default 300)
**Outputs:** `access_token: str`, `refresh_token: str`

**Security requirement:** JWT expiry ≤ 300 seconds. Refresh tokens rotate. Token scope includes tenant_id + explicit permissions. Validate signature on every request.

**Must not:** Issue tokens with expiry > 300s. Never allow token reuse after refresh. Never accept tenant_id from query param — always from JWT.

---

## 8. `commitcache/api/rate_limit.py` — Per-Identity

**Finding:** No per-identity rate limit — rate limit keyed only on IP (implied from audit)

**Purpose:** Rate limit keyed on `tenant_id + identity` token, not IP. Authenticated abuse from single account gets throttled.

**Inputs:** `identity: str`, `tenant_id: str`, `limit: int` (default 100 req/min)
**Outputs:** `bool` (allowed or rejected with 429)

**Security requirement:** Rate limit is per `(tenant_id, identity)` tuple. Unauthenticated requests rate-limited on IP only as fallback.

**Must not:** Rate limit based on IP alone for authenticated requests. Never allow unlimited requests from a single identity.

---

## 9. `commitcache/observability/metrics.py` — Full Counters

**Finding:** Only happy-path counters (`dedup_savings`) — no reject/timeout metrics (Medium)

**Purpose:** Track success, reject, timeout, and error counters for every operation. Every branch gets a metric.

**Inputs:** `metric_name: str`, `value: float`, `tags: dict` (includes `status: success|reject|timeout|error`)
**Outputs:** Prometheus-compatible counters/gauges

**Security requirement:** Every `except` branch, every rejection, and every timeout increments a counter. No silent paths without metrics.

**Must not:** Only emit success counters. Never swallow an exception without incrementing the error counter. Every function must have at least success + error counters.

---

## Integration Rules

1. **All routes must go through `auth.py`** — `api/routes.py` enforces tenant_id extraction from JWT
2. **All repairs must go through `lease.py`** — no repair without lease
3. **All state changes must go through `audit_log.py`** — no unsigned events
4. **Gossip → Queue → Repair** — never direct call between gossip and repair
5. **All metrics in `observability/metrics.py`** — no inline `logger.info` for counting

## Fix Priority

1. `core/tenant.py` + `core/lease.py` + `core/audit_log.py` (unblock all security issues)
2. `api/auth.py` + `api/rate_limit.py` (unblock all API/IAM issues)
3. `coordination/gossip_worker.py` + `repair_worker.py` + `repair_queue.py` (unblock all scalability issues)
4. `observability/metrics.py` (close remaining gap)
5. `api/routes.py` (wire everything together)
