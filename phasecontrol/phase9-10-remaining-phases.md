# Remaining Phases — Deployment/Ops & Multi-company Onboarding

---

## Phase 9 — Deployment / Ops

**Build:**
- CI/CD pipeline: run full test suite (unit → integration → adversarial → load → agents → demo, in that order — per Testing & Verification doc) on every PR; block merge if any gate fails.
- Secrets management: origin signing key, per-region DB credentials, mTLS certs — never in code/config files, pulled from a secrets manager (Vault/AWS Secrets Manager/equivalent) at boot.
- Monitoring/alerting: registry `health` state changes, security-agent flags, and stampede-budget near-exhaustion all emit metrics — wire to an alerting channel (not just visible on dashboard; someone must get paged if quarantines spike).
- Key rotation job: scheduled rotation for origin signing key and per-node scope keys (ties back to the "access revocation" requirement from the security design — revoke must actually rotate a key, not just flip a flag).
- Backup/restore for commit store: since commits are the audit trail, backup cadence and a tested restore path are mandatory before this touches real patient data — an unverified backup is not a backup.

**ML/Agent:** none new — this phase operationalizes what Phases 0–3 already built.

**QA:**
1. CI blocks a PR when any existing test gate fails (verify with a deliberately broken commit).
2. Secrets never appear in logs, error messages, or version control history (scan for it).
3. Alerting test — force a quarantine event, confirm a page/alert fires, not just a dashboard flag.
4. Key rotation test — rotate mid-session, confirm the old key stops working immediately (no grace window that defeats revocation).
5. Backup/restore drill — restore from backup into a clean environment, confirm commit chain integrity (hash verification) holds post-restore.

**Gate to pass:** all 5 above green before any real (non-synthetic) data touches the system.

---

## Phase 10 — Multi-company onboarding

**Build:**
- Tenant config object: `{tenant_id, regions[], db_adapter_choice, field_masks_per_entity, stampede_budgets_per_region}` — onboarding a new company (beyond myOnsite/medinovAI) means filling this config, not writing new core code (this is the payoff of the reuse map from the v2 TRD).
- Tenant isolation check: one tenant's data/commits must never be readable by another tenant's requester scope — this is a new dimension of the field-mask/access_control system, not a separate mechanism.
- Onboarding checklist/runbook: steps to stand up a new tenant's region cluster, connect their DB adapter, and run the Phase 2 contract-test suite against their chosen DB before go-live.

**ML/Agent:** security agent's anomaly baseline must be retrained per-tenant (traffic patterns differ company to company) — do not share one global baseline across tenants, or a legitimate pattern for one company gets flagged as anomalous for another.

**QA:**
1. Tenant isolation adversarial test — attempt a cross-tenant query, must be denied same as any other scope violation (reuses `test_scope_leak.py` pattern with a tenant dimension added).
2. Onboarding dry-run — stand up a third synthetic tenant end-to-end using only the config object and existing runbook, zero core code changes required (proves the reuse design actually holds).
3. Per-tenant security-agent baseline — confirm tenant A's normal traffic doesn't trigger tenant B's model and vice versa.

**Gate to pass:** a new tenant can go live using config + runbook only; 0 cross-tenant leak cases in adversarial suite.

---

## Status after this
With Phase 9 and 10 designed, every phase from Phase 0 through Phase 10 now has a spec. Nothing backend-side remains undesigned. Execution (writing code, running the QA gates, building the UI per the strict rules given) is the only work left.
