# Phase 7 Implementation — Access Control / MVC Controller Boundary
Scope: `core/access_control.py` — this is the only piece of Phases 3-8 not yet detailed elsewhere.
Cross-reference: Phase 3/4/5 detail → `phase1-implementation.md`. Phase 6/8 detail → `phase2-implementation.md`. This doc covers Phase 7 only.

---

## 1. Purpose (recap)
This is the Controller in the MVC-as-security-boundary design: it decides what a node/caller is allowed to know *before* data leaves the Model. Nothing downstream (View/API serialization) should need to re-derive permissions — it only enforces what this layer already decided, as a second independent check (defense-in-depth, per earlier review).

## 2. Data contract
```
CapabilityScope:
  scope_id: str
  tenant_id: str                      # ties to Phase 10 multi-tenant isolation
  region: str
  entity_types: list[str]             # e.g. ["visit_status", "lab_result"]
  field_mask: dict[str, list[str]]    # entity_type -> allowed field names
  issued_at: datetime
  revoked: bool
  key_version: int                    # bumped on rotation/revocation
```

## 3. Interface
```
class AccessController:
    def issue_scope(tenant_id, region, entity_types, field_mask) -> CapabilityScope
    def revoke_scope(scope_id) -> None          # bumps key_version, does NOT just flip a bool
    def check_field_access(scope_id, entity_type, field_name) -> bool
    def filter_record(scope_id, entity_type, record: dict) -> dict   # strips disallowed fields before return
```

**Enforcement point:** `filter_record()` is called inside the Model layer, before any data object crosses into Controller/View code — not as an afterthought filter on an already-assembled response. This is what makes "a node can't tamper with a param it never received" true, not just aspirational.

## 4. Revocation semantics (ties to Phase 9 key rotation)
- `revoke_scope()` must invalidate any already-cached encrypted data tied to that scope's key — per the earlier design, encryption keys are tied to scope, so revocation without key rotation is not real revocation.
- No grace window: a revoked scope's next request must be denied immediately, not "denied after cache expiry."

## 5. Defense-in-depth wiring (closes the loop with Phase 5's `api/query.py` and Phase 8's dashboard endpoints)
Every response-producing endpoint calls `filter_record()` twice conceptually:
1. Inside the Model/service layer (primary).
2. A cheap re-check in the API serialization layer — iterate the outgoing payload's fields against `check_field_access()` one more time before it's sent.

This is intentionally redundant. The QA gate (`test_controller_bypass.py`, already in the Testing & Verification doc) exists specifically to prove the second check catches what the first one misses when deliberately broken.

## 6. QA (adds to existing gate list, no new test files needed — these slot into the ones already defined)
1. `check_field_access` denies any field not explicitly in `field_mask` — default-deny, not default-allow.
2. Revocation test: revoke mid-session, immediate next request denied, cached data unreadable (key mismatch).
3. Tenant boundary: a scope for tenant A must return `False` on any `check_field_access` call scoped to tenant B's entities, even if field names happen to match.
