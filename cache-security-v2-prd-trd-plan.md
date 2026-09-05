# Secure Distributed Commit-Cache Platform — v2
## myOnsite Healthcare + medinovAI backend (generalized, multi-country)
### For hand-off to build agent — backend only, UI is separately owned

---

## 1. PRD (Product Requirements)

### 1.1 Problem (consolidated)
Patient/clinical data is served from multiple cache nodes across countries. Origin updates must reach every node correctly even when invalidation messages are delayed/dropped, without overloading origin (stampede), without wasting node resources on redundant repeat requests, and without leaking data to nodes that don't need it. Every change must be traceable (who/when/what, like git history) and verifiable (tamper-evident), and ops must be able to see, from one place, exactly what every node currently holds and query any master node on demand.

### 1.2 Goals
1. Every node's data is provably correct or provably stale — never silently wrong (hash-chain verified).
2. Origin never exceeds its stampede budget; nodes never spam origin with duplicate requests (debounced).
3. Full commit history (git-style) — every change is a traceable, hash-linked, rollback-capable object.
4. One place shows live state of every node (current version, cache summary, health) and lets ops query any master/region on demand.
5. Nodes only ever receive the data fields they're scoped for (least-privilege, enforced structurally).

### 1.3 Non-goals
- Dashboard UI implementation (functional requirements only — Section 5)
- Cross-region replication of raw PHI (only commit metadata/hashes cross regions)

---

## 2. TRD (Technical Requirements)

### 2.1 Commit model (git-style, core primitive)
```
Commit {
  commit_hash        // SHA256(parent_hash + json_manifest + signing_key)
  parent_hash
  version_number
  json_manifest       // diff only — changed fields, not full record
  affected_entity_id
  timestamp
  test_gate_result    // pass/fail from auto-test gate
}
```
- Commits form a hash-linked chain per entity (like git log) — full audit + rollback.
- Only diffs travel, not full snapshots — reduces bandwidth and node processing load.

### 2.2 Auto-test gate (pre-publish hook)
- Before a commit is broadcastable: schema validation, business-rule checks, field-mask consistency check.
- Fail → commit rejected, master state untouched, failure logged (not silently retried).

### 2.3 Debounced / coalesced propagation
- Each node holds a local debounce window (config: 500ms–2s default).
- Multiple triggers within the window collapse into **one** fetch that resolves straight to latest commit — prevents duplicate-request resource waste / self-inflicted node overload.
- Origin-side stampede budget (per region) is the second, independent safety layer.

### 2.4 Node hierarchy + agents (per earlier design, unchanged)
Global coordinator (meta) → Region cluster (per country, data-residency boundary) → Main node (cluster head, runs reconciliation + security agent) → Sub-nodes (shards, ~1L users each, local staleness scorer).

| Tier | Agent | Model type |
|---|---|---|
| Main node | Security agent | Anomaly detection (isolation forest) on access patterns |
| Main node | Reconciliation agent | Deterministic hash-chain check + classifier fallback |
| Sub-node | Staleness scorer | Lightweight threshold/regression, self-flags before being asked |
| Dashboard backend | Aggregation agent | Rule-based aggregation, drives auto-remediation |

### 2.5 Health-check & node registry service (new)
Central service every node/main-node heartbeats into:
```
NodeStatus {
  node_id, region, tier (main/sub)
  current_commit_hash, version_number
  cache_summary            // field names + hashes only, never raw PHI values
  last_heartbeat, health (ok/stale/quarantined)
  agent_flags              // security_agent / staleness_scorer outputs
}
```
- This is the single source ops query for "what does every node currently hold."
- Edits (manual annotation, forced-refresh, quarantine override) go through Controller layer and are themselves recorded as commits — so an edit is auditable, never a silent overwrite.

### 2.6 Request/query model (new — supports single or multiple masters)
```
QueryRequest {
  requester_scope        // from Controller, enforces field_mask
  target: node_id | region | "all_masters" | [master_id, ...]
  query_type: status | cache_contents | commit_history
}
```
- Supports checking one master, a named subset, or all masters (multi-country) in one call.
- Query itself is Controller-gated — same least-privilege rule applies to reads as to node scoping. A query for fields outside the requester's scope returns nothing for those fields, not an error that reveals they exist.

### 2.7 DB-agnostic adapter layer (reuse across companies)
```
CommitStore interface: write(commit), read(hash), list_history(entity_id)
```
- One interface, swappable backend (Postgres/Mongo/whatever each company already runs).
- Dashboard and registry service talk only to this interface — new DB = new adapter, zero change elsewhere.

### 2.8 Reuse map (shared core, do not duplicate per company)
| Shared core (build once) | Company-specific (config only) |
|---|---|
| `hash_chain()` — used for version integrity AND sensitive-field tamper detection | Entity schemas (visit_status, lab_result, trial_stage, risk_score) |
| Commit object + auto-test gate | Field_mask per consumer type |
| Debounce/coalesce queue | Region/data-residency config |
| CommitStore adapter interface | Actual DB adapter implementation per stack |
| Node registry + query model | — |

---

## 3. Implementation Plan (phased, for build agent)

| Phase | Deliverable | Depends on |
|---|---|---|
| 0 | Commit engine: object schema, hash chain, auto-test gate | — |
| 1 | Node hierarchy skeleton: coordinator, region, main node, sub-node + heartbeat | Phase 0 |
| 2 | Debounce/coalesce layer + per-region stampede budget | Phase 1 |
| 3 | Security agent (anomaly detection) + reconciliation agent | Phase 1 |
| 4 | Node registry + health-check service | Phase 1, 2 |
| 5 | Request/query model (single + multi-master) | Phase 4 |
| 6 | DB adapter interface + one reference adapter (Postgres) | Phase 0 |
| 7 | Field-mask/MVC access boundary (Model/Controller/View split) | Phase 0 |
| 8 | Dashboard backend APIs (read-only endpoints for UI to consume) | Phase 4, 5 |

---

## 4. Dashboard UI requirements (functional spec — you build the UI, this is what it must support)

1. **Node map** — visual hierarchy (global → region → main → sub), color-coded by `health` field from registry.
2. **Cache content viewer** — per node, show `cache_summary` (field names + hashes) — never raw PHI values in UI.
3. **Commit history / audit timeline** — git-log-style view per entity: hash, parent, timestamp, test_gate_result.
4. **Multi-master query panel** — pick one/many masters or "all," run a query, show results side by side.
5. **Security/anomaly feed** — live stream of `agent_flags` from security agent.
6. **Editable annotations** — any manual edit/override must itself create a commit (shown in history, not a silent DB write).
7. **DB connector status** — which adapter is active, connection health, per company.
8. **Auto-remediation log** — every auto-action taken, with a rollback control (human-in-loop for destructive actions).

---

## 5. Open decision before build starts
Stack for Phase 0 (Python/asyncio vs Go/Rust) — still unconfirmed.
