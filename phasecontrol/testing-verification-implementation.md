# Testing & Verification — Implementation Spec
Scope (per your checklist): "Verify component integration" + "Commit all changes to Git repo"
Depends on: Phase 0 + Phase 1 scaffolding complete.

---

## 1. Test harness structure

```
tests/
├── unit/
│   ├── test_commit.py            # Phase 0 — hash chain, business-rule validators
│   ├── test_access_control.py    # Phase 0/7 — field_mask enforcement
│   └── test_registry.py          # Phase 1 — staleness timing, NodeStatus contract
├── integration/
│   ├── test_hierarchy.py         # region -> main -> sub wiring, heartbeat propagation
│   └── test_query_flow.py        # end-to-end: commit -> debounce -> node fetch -> registry update
├── adversarial/
│   ├── test_tamper_commit.py     # forged commit / broken parent_hash
│   ├── test_scope_leak.py        # out-of-scope field query attempts
│   └── test_controller_bypass.py # simulated access_control bypass, secondary check must catch
├── load/
│   ├── test_debounce_burst.py    # 50 simultaneous triggers -> 1 fetch
│   └── test_stampede_budget.py   # 20 nodes stale at once -> origin rate bound
├── agents/
│   ├── test_security_agent.py    # recall/false-positive on injected anomalies
│   └── test_reconciliation_agent.py  # tampered-as-ok must be 0%
└── demo/
    └── test_full_demo_suite.py   # the 5-point "convincing demonstration" — final release gate
```

Framework: `pytest` + `pytest-asyncio` (matches asyncio core). Load tests: `pytest` with manual concurrent task spawning is enough at this scale — no need for a separate load-testing tool unless node count grows past what a single test process can simulate.

---

## 2. Test-to-gate mapping (traceability — every QA gate from the v3 plan needs an owning test file)

| v3 QA gate | Test file | Pass condition |
|---|---|---|
| Tamper/forge rejection (Phase 0) | `test_tamper_commit.py` | 100% detection, 0 false rejections on valid commits |
| Staleness flips within 1 heartbeat interval | `test_registry.py` | timing assertion, not just eventual-consistency |
| Debounce collapses N triggers to 1 fetch | `test_debounce_burst.py` | exactly 1 fetch call recorded |
| Stampede budget never exceeded | `test_stampede_budget.py` | origin call rate assertion across full recovery window |
| Security agent recall/FP | `test_security_agent.py` | ≥90% recall, <5% FP on defined synthetic set |
| Reconciliation 0% tampered-as-ok | `test_reconciliation_agent.py` | hard assertion, test fails the whole suite if violated |
| Query scope-leak | `test_scope_leak.py` | 0 leaked fields across adversarial field list |
| Controller bypass caught by secondary check | `test_controller_bypass.py` | secondary check blocks 100% of simulated bypasses |
| Final demo suite (5-point) | `test_full_demo_suite.py` | all 5 conditions pass in one continuous run |

**Rule:** no test file in this table is optional. A phase is not "verified" if its row here isn't green — this is the literal definition of your unchecked "Verify component integration" box.

---

## 3. Integration verification procedure (concrete steps, not just "run pytest")

1. Boot a minimal cluster in-process: 1 region, 1 main node, 3 sub-nodes (matches Phase 1 QA setup).
2. Run `unit/` — must be 100% green before anything else runs (no point integration-testing on top of a broken primitive).
3. Run `integration/` — confirms wiring, not correctness of edge cases yet.
4. Run `adversarial/` — this is where most real bugs will surface; expect to iterate here.
5. Run `load/` — confirms Phase 2 debounce/stampede behavior under concurrency, not just single-request correctness.
6. Run `agents/` — confirms ML/rule-based components meet numeric targets, not just "it runs without crashing."
7. Run `demo/test_full_demo_suite.py` last — this is the release gate. If any earlier layer test is red, do not attempt this one; it will fail for reasons that mask the real root cause.

---

## 4. Git workflow ("commit all changes to Git repo")

**Branching:** one branch per phase/work-stream — `phase0-commit-engine`, `phase1-node-hierarchy`, `testing-verification` — merged to `main` only after that phase's row(s) in Section 2 are green.

**Commit message convention** (ties code history to your phase checklist, useful for audit later given this is a healthcare project):
```
[phase0] core: add hash chain verification
[phase1] registry: add heartbeat sweep for staleness timing
[test] adversarial: add scope-leak test for query endpoint
```

**Do not commit and mark a phase done in the same commit as its scaffolding** — commit scaffolding first, then a separate commit once its test file goes green. This keeps the history itself an audit trail of "built" vs "verified," matching the project's own commit-chain philosophy (Section 2.1 of the TRD) rather than contradicting it.

---

## 5. Definition of done for this phase
- Every row in Section 2 is green.
- `demo/test_full_demo_suite.py` passes in one continuous run (not patched together from separate partial runs).
- All work committed with the convention above, `testing-verification` branch merged to `main`.
