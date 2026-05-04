# Admission Implementation Tracker

**Source spec:** `Documents/ADMISSION_REFACTOR_PLAN.md` v2.13.1
**Cutover runbook:** `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md`
**Risk log:** `Documents/ADMISSION_REFACTOR_RISK_REVIEW.md`
**Branch:** `feat/admission-full-cutover` (parent của sub-feature branches)

**Last updated:** 2026-05-03 (B2.4 / T0-4b merged via [#200](https://github.com/favouritekid/QLTS/pull/200) squash `737eb1bc`. **B1 merged via [#201](https://github.com/favouritekid/QLTS/pull/201) squash `6eac329e`** (mergedAt 2026-05-03T05:57:46Z) — atomic single-PR Strategy A: 4-field auth_model.conf + canonical Casbin allow-and-deny effect + 6 accountant deny rules + RUN_CASBIN_LOAD_ON_STARTUP cold-cutover gate (mirror T0-1, 3rd flag) + migration `phase1_19b_backfill_casbin_eft_and_seed_deny_rules` (210 row v3=NULL → v3='allow' + 6 INSERT) + RUNBOOK §7.2 3-flag cutover sequence + Patch A (boot-gate empty-policy bypass guard, Codex catch). Post-merge re-run on parent `6eac329e`: **225 passed + 1 skipped** full B1+B2 regression 13 files (75.89s); 48 B1 focused (19.79s). Live alembic upgrade trên parent: dev DB `phase1_19a → phase1_19b (head)` ✓ (210 v3='allow' + 6 v3='deny' verified). **Diamond inheritance gotcha** documented + matrix-encoded (admin DENY trên 6 v2 routes via accountant deny propagation); resolution deferred follow-up alongside #15. **B1 + B2 wave cả 2 TESTED on parent — #16 unblocked**; can start `state_service.transition()` qua `dispatch_event()` wiring next. B1 thematic checkbox trên issue #183 PENDING tick chờ post-merge tracking commit lands per SOP.)
**Current sprint focus:** Phase 1 Code — B-cluster đóng (B1 + B2 cả 2 TESTED). NEXT = #15 / #16 wave (workflow remap + state_service.transition wiring + diamond admin↔accountant resolution co-shipped với /api/v2 internal staff routes)

---

## Legend

| Status | Meaning |
|---|---|
| `TODO` | Chưa start |
| `IN_PROGRESS` | Đang code, chưa PR ready |
| `BLOCKED` | Có blocker (xem cột Blocker) |
| `CODE_DONE` | PR opened, chờ review/merge |
| `TESTED` | Merged + unit/int test PASS local |
| `REHEARSED` | Migration rehearsal staging clone PASS (chỉ áp dụng migration tasks) |
| `DONE` | Production ready (cho cutover bundle) |

**Test column legend:** `U` = unit test, `I` = integration test, `E2E` = end-to-end, `M` = migration rehearsal, `R` = matrix/regression. Format: `U:✓ I:✗ E2E:-` (✓ pass, ✗ fail, `-` not yet).

---

## Section 0 — Decision Gates

**Scope clarification (chốt 2026-05-01):** D1 CLOSED, không chặn implementation. D2/D3 KHÔNG chặn Task 0/Phase 0/Phase 1 dev — chỉ chặn production cutover (Go decision). Sub-PR vào `feat/admission-full-cutover` có thể merge song song trong khi D2/D3 chờ.

| ID | Decision | Owner | Status | Blocks | Notes |
|---|---|---|---|---|---|
| ~~D1~~ | ~~Q11: profile creation flow~~ | — | **CLOSED 2026-05-01** | nothing | Resolved trong PLAN §3.3.g.1 (lines 2081-2098): officer/admin tạo Lead → system auto-create draft AdmissionProfile (`uses_choice_engine=true`) + auto-issue submit token (action_type='submit', TTL 7d) → candidate click link submit form. KHÔNG cần product decision riêng. |
| D2 | Maintenance window timing (date + start time) | Ops Lead + Admission Ops | TODO | **cutover only** (không chặn dev) | Recommend Sat-Sun đêm Việt Nam. RUNBOOK §7 |
| D3 | 7 stakeholder sign-off | All | TODO | **Go production only** (không chặn dev) | RUNBOOK §10 — collect dần khi mỗi role's scope ready, không cần chờ tất cả từ đầu |

---

## Section 1 — Task 0 Prerequisites (BLOCK staging rehearsal)

| ID | Task | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| T0-1 | 2 entrypoint env flag gates: `RUN_MIGRATIONS_ON_STARTUP` + `RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP` | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#189](https://github.com/favouritekid/QLTS/pull/189) merged 2026-05-02 squash `bebb31fe` | U:✓ (14-case bash gate logic re-run on parent post-merge: 9 matrix + 5 defensive variants PASS) | DONE chờ staging clone D12-D14 smoke (apply 2 flag → observe entrypoint output → API ready ≤5s) | RUNBOOK §3.5 |
| T0-2 | `ADMISSION_FROZEN` middleware + 4 write method × 3 prefix matrix (verified-from-code: `/api/admissions`, `/api/admission-config`, `/api/public/admissions`; path-segment match) | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#190](https://github.com/favouritekid/QLTS/pull/190) merged 2026-05-02 squash `1a8e0ca2` | U:✓ (47-case pytest re-run on parent post-merge: 12 unfrozen pass-through + 12 frozen-block + 9 frozen-read-allowed + 4 non-admission baseline + 4 lookalike-rejection + 3 bare-prefix + 1 contract-shape sanity + 1 route-table drift catch via `fastapi_app.routes` + 1 health) | DONE chờ staging clone D12-D14 smoke (apply ADMISSION_FROZEN=true → restart → curl POST /api/admissions/* → 503; curl GET → 200; non-admission unaffected) | RUNBOOK §3.5 |
| T0-3 | Nginx admission block env-driven `NGINX_ADMISSION_FROZEN` (regex `^/api/(admissions\|admission-config\|public/admissions)(/.*)?$`; envsubst at deploy time; pair với T0-2 backend middleware) | Ops | TESTED (PR merged, chờ staging smoke → DONE) | [#191](https://github.com/favouritekid/QLTS/pull/191) merged 2026-05-02 squash `092a12bd` | U:✓ (32-case re-run on parent post-merge: 15 render-substitution + 3 nginx -t syntax in Docker + 14 regex URI match including 4 lookalike rejection); live HTTP smoke deferred staging | DONE chờ staging clone D12-D14 smoke (apply `NGINX_ADMISSION_FROZEN=true` + envsubst regenerate → `nginx -s reload` → curl POST 503 from edge / GET → 200 / non-admission unaffected) | RUNBOOK §3.5 |
| T0-4a | Celery beat `dispatch_pending_outbox` **skeleton task** (no-op safe registration: function defined, beat schedule registered, log "outbox not yet active" + return early — KHÔNG insert/dispatch). Kịch bản: B2/M-1-19a chưa ship, beat task vẫn registered nhưng KHÔNG crash worker. | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#192](https://github.com/favouritekid/QLTS/pull/192) merged 2026-05-02 squash `e239ba35` | U:✓ (13-case pytest re-run on parent post-merge: beat-schedule cadence + static `conf.include` + subprocess cold-import regression (bite-verified) + post-import sanity + result-shape + AST no-NotificationOutbox guard skeleton + `__init__.py` + models gap canary + autodiscover smoke + zero-arg signature; 2 existing celery_task_registry guards) | DONE chờ staging clone D12-D14 smoke (apply T0-4a → restart `celery-worker` + `celery-beat` → tail logs cho `dispatch_pending_outbox skeleton tick: outbox not yet active` mỗi 30s; `celery -A app.celery_app inspect registered \| grep dispatch_pending_outbox`) | RUNBOOK §3.5 + PLAN §3.3.e |
| T0-4b | Celery beat `dispatch_pending_outbox` **real worker wiring** (3-step claim/dispatch/finalize, query NotificationOutbox table, dispatch SystemEvents enum). Replace skeleton T0-4a. | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#200](https://github.com/favouritekid/QLTS/pull/200) merged 2026-05-03 squash `737eb1bc` | U:✓ post-merge full notification regression 177 passed + 1 skipped on parent `737eb1bc` (58.95s). Includes 10 worker behavior tests on real DB (empty queue / dispatched_at marking / failure → last_error + claim release / expired-lease re-claim / active-lease blocks re-claim / DLQ at MAX_ATTEMPTS=5 / mixed batch isolation / post-commit callback awaited / retry success clears stale last_error / single-row lease ~PER_ROW_TIMEOUT_SECONDS not BATCH_LIMIT × PER_ROW_TIMEOUT_SECONDS) + 8 retained registration/AST guards. Coverage invariant: exit `1` with 12 expected `no-dispatch-site` + 0 raw-dispatch-of-outbox-event (worker module allowlisted per B2.3 detector). | DONE chờ staging clone D12-D14 smoke (apply T0-4b → restart `celery-worker` + `celery-beat` → tail logs cho `dispatch_pending_outbox: queue empty` mỗi 30s khi outbox rỗng / `dispatch_pending_outbox: tick complete claimed=N dispatched=N failed=N` khi có rows; chèn 1 outbox row test → quan sát lifecycle claimed_at → dispatched_at within ~30s). | RUNBOOK §3.5 + PLAN §3.3.e/f |
| T0-5 | `POST /api/v2/admin/casbin/reload` admin endpoint — **current-process scope** (chỉ reload 1 Gunicorn worker; multi-worker fleet-wide reload = restart backend per §7.2 T+3:15). `Depends(require_admin)` + `@limiter.limit(ADMIN_WRITE)`; thin router gọi `enforcer.load_policy()` + activity_service.log_activity audit + response field `scope: "current_process"`; KHÔNG touch auth_model.conf/deny/templates — B1 scope. | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#193](https://github.com/favouritekid/QLTS/pull/193) merged 2026-05-02 squash `9d34e820` | U:✓ (9-case re-run on parent post-merge: admin success + response-shape lock + non-negative policy_count + 4-role deny matrix + reload-failure structured 500 + subsequent-reload-recovers resilience + endpoint-registration path lock) | DONE chờ staging clone D12-D14 smoke (seed deny rule direct DB → restart backend per §7.2 T+3:15 → verify deny enforce từ ALL Gunicorn workers; endpoint diagnostic cho 1 worker) | RUNBOOK §3.5 + §7.2 T+3:15 |

---

## Section 2 — Phase 0 Foundation (hot-fix + applied_rules trigger)

| ID | Task | Type | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|---|
| P0c | `admission_config_repository.py:76,84` field name `criteria_id` hot-fix (rename `OfferingAdmissionConfig.admission_criteria_id` + `AdmissionPath.admission_criteria_id` → `criteria_id` để match model thực tế; pre-fix `check_criteria_usage` raise `AttributeError` runtime, ngăn `delete_criteria` BusinessRuleViolation chạy) | Code | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#194](https://github.com/favouritekid/QLTS/pull/194) merged 2026-05-02 squash `36d095a4` | U:✓ (6-case re-run on parent post-merge: 3 behaviour + 2 model-contract + 1 source-grep regression trap; bite-verified) | DONE chờ staging clone D12-D14 / Phase 1 full-integration wave (admin DELETE in-use criteria → BusinessRuleViolation 400 thay vì 500 AttributeError) | PLAN §0c |
| M-P0a | `phase0_add_selected_subject_group_id_to_profile` (revision `phase0sg01`, down `admstrict01`); ADD COLUMN `AdmissionProfile.selected_subject_group_id INT NULL` + FK `fk_admission_profile_selected_subject_group_id` → `subject_group(id) ON DELETE SET NULL` (match `offering_admission_config_id` traceability convention) + INDEX `ix_admission_profile_selected_subject_group_id`; idempotent guards `column_exists`/`fk_exists`/`index_exists`; reverse downgrade index→FK→column; model field `Mapped[int \| None]` co-shipped | Migration | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#195](https://github.com/favouritekid/QLTS/pull/195) merged 2026-05-02 squash `2fe77921` | M:✓ live alembic dev DB roundtrip + U:✓ 9-case re-run on parent post-merge | DONE chờ staging clone D12-D14 (alembic upgrade applies trên prod-data clone không conflict; existing rows giữ NULL) | PLAN §4 P0 |
| M-P0b | `phase0b_relax_applied_rules_immutability_for_payment_keys` (revision `phase0br01`, down `phase0sg01`); CREATE OR REPLACE FUNCTION `prevent_applied_rules_update` với per-key classifier; whitelist **5 key** add/update (`fee_status` + `fee_paid_at` + `fee_payment_data` + `fee_calculated_at` + `fee_invoice_id`) — `fee_status` thêm trong PR review (PLAN listed 4 miss); deletion guard reject xóa whitelisted key; downgrade restore v1 strict literal-for-literal từ `b5c6d7e8f9a0`. PLAN §3.4 lines 2516-2557 patched cùng PR (drift fix verified). | Migration | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#196](https://github.com/favouritekid/QLTS/pull/196) merged 2026-05-02 squash `080a8b26` | M:✓ live alembic + 6-scenario psql + 14/14 fee tests + U:✓ 4-case re-run on parent + 1-case fee `test_admin_can_record_fee_payment` re-run on parent (5/5 PASS, 12.05s) | DONE chờ staging clone D12-D14 (alembic upgrade applies trên prod-data clone không conflict; existing applied_rules rows untouched; record_payment endpoint không break) | PLAN §4 Phase 0b |

---

## Section 3 — Phase 1 Code Task Gates (BLOCK migration #11)

| ID | Task | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| B1 | Casbin auth_model deny-first + adapter v3 mapping + 6 deny rules accountant (PLAN §3.3.b lines 1411-1415, waitlist-* expanded thành 2 row) + RUN_CASBIN_LOAD_ON_STARTUP gate | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#201](https://github.com/favouritekid/QLTS/pull/201) merged 2026-05-03 squash `6eac329e` (mergedAt 2026-05-03T05:57:46Z). Atomic single-PR per Strategy A: shipped migration + 4-field model + 4-tuple plumbing + 6 deny rules + boot gate + runbook §7.2 patch trong 1 PR — preflight evidence (Casbin Python lib breaks if model + DB rule width mismatch trong cả 2 chiều) đã được verify trước code; bundle tránh deploy gap. | U:✓ 39 B1 lock-in tests (29 unit deny-first model + plumbing + boot gate incl. `test_boot_gate_skip_bypasses_empty_policy_fail_fast` added per Codex reviewer patch round, 7 unit migration revision + idempotency + deny-rule-set lock, 3 integration 4×14 matrix incl. bite-verify on real DB) + 9 existing Casbin tracking regression PASS = **48 B1 focused post-merge re-run on parent `6eac329e` (19.79s)**. Full B1+B2 regression 13 files: **225 passed + 1 skipped post-merge re-run on parent (75.89s)**. Live alembic upgrade on parent: dev DB advanced `phase1_19a → phase1_19b (head)`; DB state 210 v3='allow' + 6 v3='deny' verified. Live alembic roundtrip on dev DB: phase1_19a → phase1_19b upgrade (210 row v3=NULL → v3='allow' + 6 deny rows seeded) → idempotent re-apply no-op → downgrade revert clean → re-upgrade idempotent. Bite-verified: removing accountant deny rule + injecting synthetic inherited allow flips matrix outcome → deny rule load-bearing, không tautology. **Diamond inheritance gotcha documented**: admin inherits accountant via `g, role:admin, role:accountant`, deny-first effect propagates accountant deny to admin → admin denied on v2 routes. PLAN §3.3.b line 1407 admin-allow-on-v2 contract requires diamond resolution (drop edge or custom matcher) — deferred follow-up alongside #15 wiring. | After B1 merge: M-1-casbin row → MERGED, BF-casbin → READY for cutover T+3:00 backfill step. **#16 remains blocked until B1 + B2 are both TESTED on parent**; then proceed #15 / #16 per sequence. Diamond admin↔accountant resolution + admin-allow on /api/v2/admissions/* deferred (likely co-shipped with #15 internal staff route wiring). | PLAN §3.3.b RBAC + RISK_REVIEW B1 |
| B2 | EventDefinition extend (`requires_outbox`, `bypass_consent_check`) + 12 ADMISSION_* enum + EVENT_CATALOG seed + `dispatch_event` wrapper + `NotificationOutbox` model + migration. **Split 4 sub-PR**: B2.1 (catalog + group + seed) → B2.2 (model + migration) → B2.3 (wrapper) → B2.4 (T0-4b worker). | BE | TESTED (B2.1-B2.4 all merged 2026-05-03) | B2.1: [#197](https://github.com/favouritekid/QLTS/pull/197) squash `df2111a9`; B2.2 / M-1-19a: [#198](https://github.com/favouritekid/QLTS/pull/198) squash `e05732c2`; B2.3: [#199](https://github.com/favouritekid/QLTS/pull/199) squash `f2f0d62b`; B2.4 / T0-4b: [#200](https://github.com/favouritekid/QLTS/pull/200) squash `737eb1bc`. | B2.1 U:✓ 103/103. B2.2 U:✓ 26/26. B2.3 U:✓ 169 passed + 1 skipped post-merge. B2.4 U:✓ 177 passed + 1 skipped post-merge on parent `737eb1bc` (58.95s). Coverage invariant after B2.4: 0 raw-dispatch-of-outbox-event violations, 12 expected `no-dispatch-site` gaps, 7 outbox events tracked, `outbox_raw_sites=[]`. Alembic head still `phase1_19a`. | B2 complete; **NEXT = B1 Casbin deny-first**. **#16 remains blocked** until B1 + B2 are both TESTED; then proceed #15 / #16 per sequence. The 12 expected `no-dispatch-site` gaps stay until #16 wires `state_service.transition()` through `dispatch_event()`. | PLAN §3.3.d-f + RISK_REVIEW B2 |
| #15 | `approved → admitted` workflow remap 23 file caller + `is_admitted_like()` + `effective_status()` helpers + `is_confirmation_eligible()` (Codex split: overridden bypass confirmed → enrolled) | BE | TESTED (PR merged 2026-05-03, post-merge tests green on parent) | [PR #202](https://github.com/favouritekid/QLTS/pull/202) — squash `e3b09eaa` (mergedAt 2026-05-03T08:52:13Z). Parent advanced `f382bc6b → e3b09eaa`. 13 files changed, 789 insertions(+), 27 deletions(-). Scope: helpers module + `ADMISSION_TO_LEAD_STATUS_MAP` + 3 forward-compat (admitted/reviewing/waitlisted) + `result_published` no-op + floor rule (regress prevention) + 7 admission caller refactor (admission_service permission compute + read checks, lead_admission_sync, lead_profile_sync LOCKED set, phase_manager:119, fees.py:81 fee_calc_authorized, admission_tasks.py survey beat SQL) + QUOTA_OCCUPYING_STATUSES += admitted + 1 audit-log capture pre-transition status in `verify_and_confirm`. Helper-module split: `is_admitted_like` (3 status: approved/overridden/admitted) cho phase/fee/quota/read; `is_confirmation_eligible` (2 status: approved/admitted) cho 4 magic-link site only — `overridden` excluded vì state machine route `overridden → enrolled` direct, bypass `confirmed`. | U:✓ 232 passed, 6 warnings (137.45s) target 3 file: `tests/unit/test_admission_status_helpers.py` + `tests/unit/test_lead_admission_sync_extended_map.py` + `tests/integration/test_lead_admission_sync.py`. **Post-merge re-run on parent `e3b09eaa`: 232 passed, 6 warnings (136.56s) — confirms squash collapsed cleanly.** Wide regression 1697 passed + 8 pre-existing fail (verified stash on parent `f382bc6b` → cùng 8 fail) + 1 deselected pre-existing. KHÔNG đụng profile.status write site, DB CHECK constraint, /api/v2 wiring, Casbin diamond. | (none — B1+B2 đã TESTED, prod audit confirm 0 admitted/confirmed/enrolled hồ sơ → zero data risk). User chốt deviation từ PLAN line 3380-3395: reviewing/waitlisted → sts07 (PLAN sts06, sai semantic — pre-submission), result_published explicit no-op (PLAN sts09, không phải status mà là T6 broadcast marker). | PLAN §4 task #15 + DAILY_LOG 2026-05-03 #15 entry + Phần 9 mapping deviation note |
| #16 | Refactor 11 direct `profile.status = '...'` sang `state_service.transition()` + lint rule AST check + 8/12 ADMISSION_* events wired (4 deferred: T6/T8/T10/T17 — Phase 3 choice-engine writers) | BE | TESTED (PR merged 2026-05-03, post-merge tests green on parent) | [PR #203](https://github.com/favouritekid/QLTS/pull/203) — squash `a7b6c5c9` (mergedAt 2026-05-03T11:33:39Z). Parent advanced `3f7ead4d → a7b6c5c9`. Pre-merge fix `aca9f83c` (transition() dedupe key includes `:v{post_version}`; legal cycle regression test) collapsed into squash. Atomic 1-PR per user chốt — avoids unused transition service intermediate state. New file `admission_state_service.py` exports `transition()`, `LEGACY_STATUS_TO_EVENT` (9 entries → 8 distinct events; approved + overridden share T7 with `override=true` payload metadata), `DEFERRED_ADMISSION_EVENTS` (4 frozenset). 11 legacy write sites refactored: `submit_and_evaluate` (skip_dispatch=True; router fires T1 best-effort post-commit), `request_revision`, `resubmit_profile`, `approve_profile`, `reject_profile`, `bulk_approve`, `bulk_reject`, `verify_and_confirm` (magic-link), `enroll_student`, `withdraw_profile`, `override_profile` (skip_audit=True; log_changes covers richer ADM-014 audit). Coverage-script anchor docstring `_DISPATCH_ANCHORS` keeps grep happy when transition() resolves event via mapping dict. New AST lint `check_status_assignment.py` blocks direct writes outside `admission_state_service.py` allow-list; leftmost-name allowlist `ADMISSION_PROFILE_VAR_NAMES` covers 6 aliases (`profile` canonical + `locked_profile`/`admission_profile`/`current_profile`/`profile_row`/`prof` forward-prevention; codebase audit 2026-05-03 confirmed zero existing alias writes) avoids false positives on Fee/User/ZaloDelivery. Coverage script `--allow-deferred` flag with strict semantics (typo / wired / extra-gap → fail). | U:✓ 59 passed target 4 file (1.86s post-merge re-run on parent `a7b6c5c9`; 58 baseline + 7 alias coverage + 1 dedupe-key cycle regression): `test_admission_state_service.py` + `test_admission_state_service_event_mapping.py` + `test_check_status_assignment.py` + `test_check_notification_event_coverage_deferred.py`. Live: lint 0 violations across 148 files; coverage script with `--allow-deferred=ADMISSION_RESULT_PUBLISHED,ADMISSION_DECISION_WAITLISTED,ADMISSION_WAITLIST_PROMOTED,ADMISSION_ROLLED_BACK` exit 0 (8 wired + 4 deferred). Wide regression 1768 passed + 8 pre-existing fail + 1 deselected (verified stash on parent `3f7ead4d` reproducing same 8). Service tests `test_admission_service.py` + `test_admission_quota.py` 45 fixture-setup errors verified pre-existing on parent (memory `[test-debt-admission-workflow-e2e]` covers subset). KHÔNG đụng enum, DB CHECK, Alembic, /api/v2 wiring, Casbin diamond, pre-commit/Github Action wiring (deferred to CI-tooling row). | (none — B1+B2+#15 đã TESTED on parent). Coverage → 8/12 wired + 4 deferred (per user chốt 2026-05-03 §1 Option B'). Pre-commit/CI wiring deferred per §5 to keep #16 scope tight. | PLAN §4 task #16 + RISK_REVIEW B5 + DAILY_LOG 2026-05-03 #16 entry |

---

## Section 4 — Phase 1 Schema Migrations (additive + status history)

| ID | Migration | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| M-1-01 | `phase1_01_add_degree_level_fk_to_major_program` | BE | TESTED (PR merged 2026-05-03, chờ staging clone D12-D14 → DONE) | [#205](https://github.com/favouritekid/QLTS/pull/205) merged 2026-05-03 squash `a50cdb79` (Wave 1 PR-1A bundle phase1_01 + phase1_02). | M:✓ 20-row backfill 100% match (12 Cao đẳng + 8 Trung cấp); idempotency re-apply no-op verified. | | PLAN §4 P1 #01 |
| M-1-02 | `phase1_02_add_bonus_rule_to_method_and_path` | BE | TESTED (PR merged 2026-05-03, chờ staging clone D12-D14 → DONE) | [#205](https://github.com/favouritekid/QLTS/pull/205) merged 2026-05-03 squash `a50cdb79` (Wave 1 PR-1A bundle phase1_01 + phase1_02). | M:✓ JSONB nullable add + drop roundtrip clean; ORM fields wired `method.py:80` + `admission_path.py:168`. | | PLAN §4 P1 #02 |
| M-1-03 | `phase1_03_add_applicable_to_method_quota_to_path` (BE schema + service + repo + FE Zod; UI form tách PR-1B'-FE) | BE+FE | TESTED (PR merged 2026-05-04, chờ staging clone D12-D14 GIN auto-pick smoke → DONE) | [#206](https://github.com/favouritekid/QLTS/pull/206) merged 2026-05-04 squash `4547f881` (Wave 1 PR-1B'-BE). | M:✓ live alembic upgrade/downgrade/re-upgrade idempotent on dev DB; uq_admission_path_offering_method + uq_admission_path_criteria_id PRESERVED. U:✓ 117/117 (4 new file 59 case incl. 4 compile-dialect test post Codex round 4 fix `_AUDIENCE_ARRAY_TYPE` + 5 regression file 58 case). I:✓ GIN reachable via enable_seqscan=off → Bitmap Index Scan on ix_admission_path_applicable_to. | UI form ship PR-1B'-FE riêng off `4547f881`. | PLAN §4 P1 #03 |
| ~~M-1-04~~ | ~~`phase1_04_add_extra_thresholds_to_criteria`~~ | — | **DEFERRED Q1/2027** | | | Q9 defer per PLAN §8 cheat sheet line 4402 + Phần 7.1 | Phase 4 Section 13 |
| M-1-05 | `phase1_05_add_subject_kind_and_score_bounds` (+ seed 6 subject ảo TB_HK1_L12, DGNL_DHQGHN, ...) | BE | TODO | | M:- | | PLAN §4 P1 #05 |
| M-1-06 | `phase1_06_add_path_id_to_document_group` (+ resolution rule 3 tầng) | BE | TODO | | M:- I:- | | PLAN §4 P1 #06 |
| ~~M-1-07~~ | ~~`phase1_07_add_demographics_to_profile`~~ | — | **DEFERRED Q1/2027** | | | Q9 defer per PLAN §8 cheat sheet line 4402 + Phần 7.1 | Phase 4 Section 13 |
| M-1-07b | `phase1_07b_create_backfill_exceptions_table` | BE | TODO | | M:- | | PLAN §4 P1 #07b (active — required cho M-1-12 + M-3-01 backfill exceptions) |
| M-1-08 | `phase1_08_add_uses_choice_engine_flag_to_profile` | BE | TODO | | M:- | | PLAN §4 P1 #08 |
| M-1-09a | `phase1_09a_add_eligibility_scalars_and_backfill` (gpa_overall + graduation_year — KHÔNG conduct/health vì M-1-04 defer) | BE | TODO | | M:- I:- | | PLAN §4 P1 #09a |
| ~~M-1-09b~~ | ~~`phase1_09b_create_eligibility_lock_trigger`~~ | — | **DEFERRED Q1/2027** | | | Q9 defer per PLAN §8 cheat sheet line 4402; lock-after-draft trigger không active mùa 2026 | Phase 4 Section 13 |
| M-1-10 | `phase1_10_create_status_history_table_and_backfill` (1 row/profile + 5 scattered scalar) | BE | TODO | | M:- I:- | | PLAN §4 P1 #10 + RISK_REVIEW B-status-history |
| M-1-systemconfig | `phase1_create_system_config_table` (+ seed current_intake_year=2026) | BE | TODO | | M:- I:- | | PLAN §4 P1 + RISK_REVIEW B4 |
| M-1-archive-profile | `phase1_create_archived_admission_profile_table` | BE | TODO | | M:- | | PLAN §7.5 archive |
| M-1-archive-outbox | `phase1_create_archived_outbox_failed_table` | BE | TODO | | M:- | | PLAN §3.3.e archive |
| M-1-11 | `phase1_11_extend_profile_status_check_constraint` (14 state) ⚠️ ONE-WAY | BE+FE | TODO | | M:- I:- E2E:- | #15 + #16 + LS-map + FE-zod-status + FE-badge + FE-tabs ALL ship trước hoặc cùng wave (atomic deploy: BE migration + FE Zod 14 state + lead sync map) | PLAN §4 P1 #11 |
| M-1-12 | `phase1_12_backfill_selected_subject_group_id` (decision tree 3 rule) | BE | TODO | | M:- I:- | M-1-10 + M-P0a | PLAN §4 P1 #12 |
| M-1-15 | `phase1_15_drop_lead_id_unique_constraint` + composite `(lead_id, academic_year)` ⚠️ ONE-WAY | BE | TODO | | M:- I:- | | PLAN §4 P1 #15 + RISK_REVIEW B8 |
| M-1-15-model | Lead one-to-many model + schema + repository + service + 3 caller migrate + drop `delete-orphan` cascade | BE | TODO | | U:- I:- E2E:- | M-1-15 migration ship trước | RISK_REVIEW B8 |
| M-1-15-fe | FE migrate `admission_profile` singular → `admission_profiles` plural | FE | TODO | | tsc:- vitest:- | M-1-15-model ship trước | PLAN §4 Phase 3 FE |
| M-1-18 | `phase1_18_extend_confirmation_token_for_multi_action` (action_type + partial UNIQUE + revoked audit) ⚠️ ONE-WAY | BE | TODO | | M:- I:- | | PLAN §4 P1 #18 |
| M-1-19a | `phase1_19a_create_notification_outbox` (10 cột + named UNIQUE `uq_notification_outbox_idempotency_key` + 2 partial WHERE idx `ix_outbox_pending(created_at)` / `ix_outbox_claim(claimed_until)` cùng predicate `dispatched_at IS NULL`; idempotent guards `table_exists` + `index_exists`; downgrade short-circuits if table gone, drops indexes then table). `down_revision='phase0br01'`, ship cùng B2.2 sub-PR. | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#198](https://github.com/favouritekid/QLTS/pull/198) merged 2026-05-03 squash `e05732c2` | M:✓ live alembic upgrade on parent post-merge: dev DB `phase0br01 → phase1_19a (head)`; pre-merge roundtrip (downgrade + re-upgrade idempotent) on local branch. U:✓ 26/26 post-merge re-run on parent `e05732c2` (4.29s): 14 ORM ⇄ migration parity (column shape + BIGSERIAL + JSONB + named UNIQUE + 2 partial WHERE + revision chain + head no-children + name constants) + 10 outbox skeleton regression + 2 celery_task_registry. | DONE chờ staging clone D12-D14 (alembic upgrade trên prod-data clone không conflict; existing tables untouched; CREATE TABLE additive) | PLAN §4 P1 #19a |
| M-1-19b | `phase1_19b_seed_event_catalog_db_rows` (12 ADMISSION_* notification_rule rows) | BE | TODO | | M:- I:- | M-1-19a + B2 | PLAN §4 P1 #19b |
| M-1-19c | `phase1_19c_register_celery_beat_archive_task` (cùng task T0-4) | BE | TODO | | I:- | T0-4 ship cùng | PLAN §4 P1 #19c |
| M-1-19d | `phase1_19d_seed_notification_rules` (channel routing per audience) | BE | TODO | | M:- I:- | M-1-19a | PLAN §4 P1 #19d |
| M-1-casbin | `phase1_19b_backfill_casbin_eft_and_seed_deny_rules` — UPDATE casbin_rule SET v3='allow' WHERE ptype='p' AND v3 IS NULL (idempotent predicate-bounded) + 6 INSERT deny rules accountant (WHERE NOT EXISTS guard, template_id='_system_b1_deny' marker, asyncpg-safe `CAST(:p AS varchar)` casts to avoid AmbiguousParameterError on parameter reuse). `down_revision='phase1_19a'`. Downgrade reverses both: DELETE 6 deny rows by exact match, UPDATE v3=NULL WHERE v3='allow'. | BE | TESTED (PR merged, chờ staging smoke → DONE) | [#201](https://github.com/favouritekid/QLTS/pull/201) merged 2026-05-03 squash `6eac329e` (shipped trong B1 PR). | M:✓ live alembic upgrade on parent post-merge: dev DB `phase1_19a → phase1_19b (head)`; pre-merge roundtrip evidence (downgrade + re-upgrade idempotent). U:✓ 7 lock-in tests post-merge re-run (revision contract, predicate-guard regex, asyncpg cast count, 6-rule explicit set, template_id marker). | DONE chờ staging clone D12-D14 (alembic upgrade trên prod-data clone không conflict; existing 210 row backfill + 6 INSERT idempotent; post-cutover Casbin enforcer reload smoke). | PLAN §4 P1 + RISK_REVIEW B1 |

---

## Section 5 — Phase 2 Migrations (multi-round + multi-NV core)

| ID | Migration | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| #17 | `public_admissions_service` migrate sang round + audience filter + 3-tier doc resolution | BE+FE | TODO | | U:- I:- E2E:- | (none — gate BEFORE phase2_02b: #17 phải merge TRƯỚC M-2-02b để storefront resolve path đúng round sau swap unique) | PLAN §4 task #17 line 4410 (GATE BEFORE phase2_02b) |
| M-2-01 | `phase2_01_create_offering_admission_round` (+ admit_quota field + lifecycle audit) | BE | TODO | | M:- I:- | | PLAN §4 P2 #01 + RISK_REVIEW Q6 |
| M-2-01b | `phase2_01b_add_admission_round_id_to_profile_with_fk` (normalized FK) | BE | TODO | | M:- I:- | M-2-01 | PLAN §4 P2 |
| M-2-02 | `phase2_02_add_admission_round_id_to_admission_path` (Step 1-3 nullable + backfill DOT_1) | BE | TODO | | M:- I:- | | PLAN §4 P2 #02 |
| M-2-02b | `phase2_02b_admission_path_round_not_null_swap_unique` ⚠️ ONE-WAY | BE | TODO | | M:- I:- | M-2-02 | PLAN §4 P2 #02b |
| M-2-03 | `phase2_03_create_path_subject_group_config_and_item` (3-tier scoring override) | BE | TODO | | M:- I:- | | PLAN §4 P2 #03 |
| M-2-04 | `phase2_04_widen_score_precision` ⚠️ ONE-WAY (Numeric(8,2) chứa DGNL/V-ACT) | BE | TODO | | M:- | | PLAN §4 P2 #04 |

---

## Section 6 — Phase 3 Multi-NV + Choice Engine

| ID | Task | Type | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|---|
| M-3-01 | `phase3_01_create_admission_profile_choice_and_score` (multi-NV core tables) | Migration | BE | TODO | | M:- I:- | M-2-* | PLAN §4 P3 #01 |
| ~~M-3-02~~ | ~~`phase3_02_seed_12_milestone_events_and_rules`~~ | — | **MOVED to Phase 1** | | | 12 milestone events + outbox đã move lên Phase 1 #19a/19b/19c/19d (PLAN §8 cheat sheet line 4401: "Phase 3: 1 (01 choice/score) — outbox + 12 events seed moved sang Phase 1 #19a/b/c/d"). KHÔNG active task ở Phase 3. | M-1-19a..d |
| ENG-validation | 6-rule validation engine + 3-tier resolution + bonus rule resolution | Code | BE | TODO | | U:- I:- (30+ case) | M-2-03 + M-3-01 | PLAN §3.1-3.2 + §6 test strategy |
| ENG-formula | `ScoreFormulaConfig` Pydantic discriminated union (whitelist `weighted_sum`) | Code | BE | TODO | | U:- | | PLAN §2.3.a |
| ENG-flags | 3 feature flags `FLAG_MULTI_NV_ENABLED`, `FLAG_USE_PATH_CONFIG`, `FLAG_USE_BONUS_RULE` wiring | Code | BE | TODO | | U:- I:- | | PLAN §4 Phase 3 |

---

## Section 7 — Lead Sync + Public + Cross-module

| ID | Task | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| LS-map | `lead_admission_sync.py` 4 new state mapping + remove silent `False` fallback + caller audit + soft-fatal wrap | BE | TODO | | U:- I:- | (none — gate BEFORE/WITH M-1-11: LS-map phải ready CÙNG hoặc TRƯỚC M-1-11 để khi DB CHECK extend cho 4 new state, sync map sẵn sàng project lead status; nếu sau M-1-11 → silent `False` fallback bùng nổ ngay phút profile đầu chuyển sang reviewing) | RISK_REVIEW B6 + PLAN §4 task #15 |
| LS-event-map | `admission_event_mapping.py` 4 entry mới ADMISSION_EVENT_PROJECTIONS | BE | TODO | | U:- | LS-map (cùng PR bundle) | PLAN §4 task #15 step 3 |
| LS-projection | Lead pipeline projection multi-year fallback chain (current → last_terminal → pre_admission) | BE | TODO | | U:- I:- | LS-map + system_config | PLAN §2.5.b |
| TOK-multi | Magic link multi-action: action_type + atomic claim `UPDATE...RETURNING` + CCCD verify + `attempt_count++` separate tx | BE | TODO | | U:- I:- E2E:- (anti-bruteforce) | M-1-18 | PLAN §3.3.g + RISK_REVIEW P1-08 |

---

## Section 8 — Frontend (full multi-NV per PLAN §4 Phase 3)

| ID | Deliverable | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| FE-zod-status | Zod 14 status enum + plural `admission_profiles` + typed `available_actions` | FE | TODO | | tsc:- vitest:- | (none — gate BEFORE/WITH M-1-11: FE Zod 14 state phải ship CÙNG hoặc TRƯỚC backend migration extend status CHECK; nếu BE deploy trước FE → response strict enum legacy parse fail → mass user crash) | PLAN §4 Phase 3 FE #1 + RISK_REVIEW P1-01 |
| FE-zod-path-parse | Zod `admission-path.ts` parse parity 3 field (`applicable_to`, `method_quota`, `bonus_rule_override`) — Create/Update/Response + `admissionAudienceEnum` + `bonusRuleOverrideSchema.strict()` | FE | TESTED (PR #206 merged 2026-05-04, chờ staging clone D12-D14 → DONE) | [#206](https://github.com/favouritekid/QLTS/pull/206) merged squash `4547f881` (Wave 1 PR-1B'-BE bundle Zod cùng BE per Q3 chốt 2026-05-04 — parse drift guard). | tsc:✓ vitest:- (FE form UI tách FE-form-path-admin — vitest sẽ ship cùng UI PR) | | PLAN §4 Phase 3 FE #5 (parse parity portion); `admission_round_id` Zod field defer Phase 2 cùng M-2-02 |
| FE-form-path-admin | Admin form UI 3 field: audience multi-select dropdown + method_quota integer input + `BonusRuleOverride` structured form 3 sub-field (NOT raw JSON editor per Codex P2) + i18n keys | FE | TODO | | tsc:- vitest:- | M-1-03 SHIPPED → unblocked off `4547f881` (PR-1B'-FE) | PLAN §4 Phase 3 FE #5 (UI portion); admin-only governance — non-admin caller hide section |
| FE-badge | `STATUS_BADGE_CONFIG` extend 14 status + i18n inline 25 keys (3 file existing) + lint rule sync | FE | TODO | | tsc:- vitest:- | FE-zod-status (cùng PR bundle, ship CÙNG/TRƯỚC M-1-11) | PLAN §4 Phase 3 FE #6 |
| FE-tabs | `AdmissionsClient.tsx STATUS_TABS` extend 14 status filter | FE | TODO | | tsc:- vitest:- | FE-badge (cùng FE wave với FE-zod-status, ship CÙNG/TRƯỚC M-1-11) | PLAN §4 Phase 3 FE |
| FE-confirm | `ConfirmAdmissionForm` extend 4 action (submit/resubmit/confirm/withdraw) + CCCD verify | FE | TODO | | tsc:- vitest:- E2E:- | TOK-multi backend | PLAN §3.3.g |
| FE-multi-NV | 5 component mới: `ChoiceListEditor`, `ChoiceScoreCard`, `EligibilityResultViewer`, `DecisionBadge`, `AuditReasonDialog` | FE | TODO | | tsc:- vitest:- | M-3-01 + ENG-validation | PLAN §4 Phase 3 FE C1-C5 |
| FE-lead-detail | `LeadDetailPanel` plural admission_profiles + year tab switcher + dual-read `profile.gpa_overall ?? lead.gpa` | FE | TODO | | tsc:- vitest:- | M-1-15-fe | PLAN §2.5.a |
| FE-stepper | `AdmissionStepper` bổ sung 4 step mới cho choice-engine flow | FE | TODO | | tsc:- vitest:- | FE-multi-NV | PLAN §4 Phase 3 FE |
| FE-socket | Socket events register 12 admission events + cache invalidate via React Query | FE | TODO | | vitest:- E2E:- | B2 ship trước | PLAN §4 Phase 3 FE |

---

## Section 9 — Backfill Scripts (run sau migration apply)

| ID | Backfill | Owner | Status | Branch/PR | Rehearsal | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| BF-status-history | status_history initial 1 row/profile + 5 scattered scalar audit migrate | BE | TODO | | M:- | M-1-10 | PLAN §4 P1 #10 |
| BF-selected-group | `selected_subject_group_id` decision tree 3 rule + exception report | BE | TODO | | M:- | M-1-12 + M-P0a | PLAN §4 P1 #12 |
| BF-gpa | `gpa_overall` backfill từ academic_history JSON (length-bounded regex + range guard) | BE | TODO | | M:- | M-1-09a | PLAN §5b Pattern C |
| BF-grad-year | `graduation_year` backfill từ academic_history | BE | TODO | | M:- | M-1-09a | PLAN §5b |
| BF-casbin | Casbin v3='allow' backfill + 6 deny rules seed (deploy-time execution per RUNBOOK §7.2 T+3:00) | BE | TODO (deploy-time only — code + migration đã land trong B1 PR) | shipped logic trong M-1-casbin (`phase1_19b_backfill_casbin_eft_and_seed_deny_rules`); ops chạy `alembic upgrade head` ở cutover T+3:00 sau khi backend đã deploy với `RUN_CASBIN_LOAD_ON_STARTUP=false` (T+1:00); restart at T+3:15 với flag flipped back để lifespan reload | M:- (cutover step, không có pre-cutover staging smoke vì backfill mục tiêu là prod casbin_rule) I:- | B1 + M-1-casbin merge trên parent + cutover window scheduled | RUNBOOK §7.2 T+3:00 step |

---

## Section 10 — CI/Coverage Tooling

| ID | Task | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| CI-status | `check_status_assignment.py` AST tool 4 patterns + 6 fixture + `.contract-allowlist.yaml` config | BE | TESTED (PR merged 2026-05-03, post-merge tests green on parent) | [PR #204](https://github.com/favouritekid/QLTS/pull/204) — squash `64314f0f` (mergedAt 2026-05-03T12:55:12Z). Parent advanced `d5a01ba8 → 64314f0f`. Self-test workflow GREEN on PR (status-assignment job 11s + notification-coverage job 44s). Pattern 1.1 (direct assign) + 1.2 (setattr) shipped trong #16; Pattern 1.3 (`__setattr__` dunder bypass) + 1.4 (regex grep fallback for `setattr` 3-arg + `__setattr__` 2-arg) thêm trong CI-tooling PR. YAML config loaded at module init; allow-list 5 globs (state_service + alembic/versions/*.py + tests/*.py + tests/*/*.py + tests/*/*/*.py). Smart de-dupe `ast_caught_lines | ast_rejected_lines` so regex over-broad không flag Fee/User/ZaloDelivery `.status` writes. | U:✓ 43 case `test_check_status_assignment.py` (28 baseline + 15 mới: 5 alias dunder + 1 non-admission dunder + 3 regex fallback positive/negative cases + YAML config + glob coverage). Lint live: 0 violations across 148 files. | (none — #16 đã TESTED on parent) | RISK_REVIEW Phần 8 patches + PR_DRAFTS_2026-05-01 §103-109 |
| CI-event | `check_notification_event_coverage.py` extend namespace collision + outbox INSERT site | BE | CODE_DONE local (push pending) | Branch same as CI-status. Outbox INSERT detector đã ship via `raw-dispatch-of-outbox-event` gap trong B2.3. Namespace collision detector mới: `_scan_dual_namespace_pairs()` AST walker finds functions dispatching BOTH `APPLICATION_*` legacy AND `ADMISSION_*` new events; `_print_dual_namespace_pairs()` reporter (default `strict=False` informational warn → exit 0; `--strict-namespace` elevates to hard failure for Phase 4 retire flip). | U:✓ 9 case `test_check_notification_event_coverage_namespace.py` (DualNamespacePair shape + default-vs-strict verdict + AST walker dual/single/nested/non-admission-legacy fixtures + live scan integration confirming submit-router cohabitation). Coverage script live: exit 0 default mode (1 pair: `submit_admission_profile` legacy bundle + ADMISSION_PROFILE_SUBMITTED), exit 1 `--strict-namespace`. | (none — B2 đã TESTED) | RISK_REVIEW Phần 8 + PR_DRAFTS_2026-05-01 §110-112 |
| CI-workflow | GitHub Action `admission-contract-check.yml` + pre-commit hook | BE | CODE_DONE local (push pending) | Branch same as CI-status. New `.github/workflows/admission-contract-check.yml`: triggers on push/PR touching admission/notification/event surface; 2 parallel jobs (`status-assignment` minimal deps + `notification-coverage` full requirements). New `.pre-commit-config.yaml`: 2 `local` hooks mirror GH Action commands; `pass_filenames: false`; file-path filter regex matches GH Action `paths:` triggers. | I:✓ verified ENTRY shape locally (`python -m app.scripts.check_status_assignment` exit 0; `python -m app.scripts.check_notification_event_coverage --allow-deferred=...` exit 0). Live GH Action run pending merge. | (none — CI-status + CI-event ship same atomic PR) | RISK_REVIEW Phần 8 + PR_DRAFTS_2026-05-01 §113-114 |

---

## Section 11 — P0 Blocker Tracker (source of truth: PLAN §1.4 top blocker list lines 57-65)

**Plan Blocker → Tracker Task ID mapping:**

| Plan Blocker ID | Description (PLAN line 57-65) | Tracker active task IDs | Status | Notes |
|---|---|---|---|---|
| **B1** | Casbin `auth_model.conf` không support deny effect | `B1` (Section 3) + `M-1-casbin` (Section 4) | **CLOSED / TESTED 2026-05-03** | Code gate closed via PR #201 squash `6eac329e` (Section 3 row B1 TESTED). `M-1-casbin` Section 4 row remains separate downstream task for cutover backfill. PATCH-16. |
| **B2** | `EventDefinition` thiếu `requires_outbox`/`bypass_consent_check` + 12 SystemEvents enum chưa có | `B2` (Section 3) + `M-1-19a` (Section 4) | **CLOSED / TESTED 2026-05-03** | Code gate closed via #197-#200; `M-1-19a` model/migration shipped. Downstream notification seed migrations `M-1-19b/c/d` remain Section 4 tasks, not B2 blocker. |
| ~~B3~~ | ~~T17 cascade Student~~ | (none — Q1 strict reject) | **CLOSED** | Resolved Q1 chốt 2026-05-01 — Student schema unchanged. |
| **B4** | `system_config` table + `current_intake_year` không tồn tại | `M-1-systemconfig` (Section 4) | TODO | OPEN — bundle với LS-projection (Section 7). |
| **B5** | **11 direct** `profile.status = '...'` ở `admission_service.py` (3918, 5014, 5317, 5517, 5708, 6085, 6284, 6862, 7786, 7994, 8214) | `#16` (Section 3) | **CLOSED / TESTED 2026-05-03** | Closed via PR #203 squash `a7b6c5c9` — 11 sites refactored sang `state_service.transition()` + AST lint `check_status_assignment.py` 0 violations across 148 files. |
| **B6** | `lead_admission_sync.py:121` `return False` cho unknown status (NOT `sts13` fallback per round 20 verify) | `LS-map` (Section 7) | TODO | OPEN — bundle với caller audit + soft-fatal wrap. |
| ~~B7~~ | ~~Effort 15w buffer 0~~ | (none — strategy deprecated) | **CLOSED** | Resolved 2026-05-01: cold cutover full scope ~13 weeks per cutover plan. |
| **B8** | PR Phase 1 #15 lead one-to-many bundle scope quá lớn | `M-1-15` + `M-1-15-model` + `M-1-15-fe` (Section 4) | TODO | OPEN — atomic local implementation, KHÔNG staged 3 PR sequence + soak windows. |

**Task ID format ở tracker** (không dùng prefix `T-` vì PLAN dùng raw ID):
- Code task gates Section 3: `B1`, `B2`, `#15`, `#16`, `#17`.
- Migration: `M-{phase}-{number}` (e.g., `M-1-11`).
- Code other: `LS-*` (lead sync), `TOK-*` (token), `FE-*` (frontend), `BF-*` (backfill), `CI-*` (CI tooling), `T0-*` (Task 0 prerequisites).

---

## Section 12 — Cutover Readiness (xem RUNBOOK §9 Go/No-Go)

### 12.1. Backup
| Check | Status | Owner | Date |
|---|---|---|---|
| DB pg_dump verified offsite + restore rehearsal PASS | TODO | DBA | |
| Uploads tar verified | TODO | DBA | |
| Env/config bundle uploaded S3 | TODO | Ops | |
| Image tag pre-cutover pushed registry | TODO | Ops | |

### 12.2. Staging rehearsal
| Check | Status | Owner | Date |
|---|---|---|---|
| Migration chain apply lần 1 PASS staging clone | TODO | DBA + BE | |
| Migration chain apply lần 2 idempotency PASS | TODO | DBA | |
| 5 backfill scripts run PASS | TODO | BE | |
| E2E vận hành 8 critical journey PASS | TODO | QA | |
| Casbin matrix 4×14 PASS | TODO | QA | |
| Outbox worker rig (concurrency + crash) PASS | TODO | BE + QA | |
| Frontend full multi-NV E2E PASS | TODO | FE + QA | |

### 12.3. Production readiness (Task 0 prerequisites)
| Check | Status | Mapped task |
|---|---|---|
| T0-1 2 entrypoint env flag gates shipped (RUN_MIGRATIONS_ON_STARTUP + RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP) | TESTED | T0-1 |
| T0-2 ADMISSION_FROZEN middleware shipped (3 prefix verified-from-code, path-segment match) | TESTED | T0-2 |
| T0-3 Nginx admission block shipped (envsubst-driven, regex match T0-2) | TESTED | T0-3 |
| T0-4a dispatch_pending_outbox skeleton (no-op safe) | TESTED | T0-4a |
| T0-4b dispatch_pending_outbox real worker wiring (sau B2 + M-1-19a) | TESTED | T0-4b |
| T0-5 Casbin reload endpoint shipped (current-process scope; fleet reload = restart backend §7.2 T+3:15) | TESTED | T0-5 |
| ~~Q11 product decision chốt~~ | **CLOSED** | Resolved PLAN §3.3.g.1 |
| Maintenance window communicated 7d trước | TODO | D2 |
| Standby team confirmed availability | TODO | D2 |
| Rollback compose override file ready | TODO | Ops |

### 12.4. Sign-off (RUNBOOK §10)
| Role | Signed by | Date | Decision |
|---|---|---|---|
| Backend Lead | | | |
| Frontend Lead | | | |
| DBA / Ops Lead | | | |
| QA Lead | | | |
| Product Owner | | | |
| Admission Ops | | | |
| Legal/Compliance | | | |

---

## Section 13 — Phase 4 Cleanup + Q9 Deferred (Q1/2027, KHÔNG track active)

Track riêng sau cutover GA + soak 1-2 tháng. KHÔNG ship trong cutover bundle hiện tại.

**Drop legacy (Q5 chốt 2026-05-01):**
- Drop `Lead.gpa` (text)
- Drop `AdmissionPath.academic_info_id`
- Drop `MajorProgram.degree_level` text (sau khi `degree_level_id` FK active)
- Deprecate `CriteriaSubjectGroup` (thay bằng PathSubjectGroupConfig)
- i18n next-intl migration (replace inline 3 file)

**Q9 defer scope (decision 2026-05-01, áp PLAN §8 cheat sheet line 4402 + Phần 7.1):**
- `phase1_04_add_extra_thresholds_to_criteria` — `min_conduct` / `min_health_category` / `required_graduation_year_min/max` thresholds + admin UI input.
- `phase1_07_add_demographics_to_profile` — `area_code` / `priority_object_codes[]` / `candidate_education_level` + auto-compute area logic.
- `phase1_09b_create_eligibility_lock_trigger` — txid-bound audit token bypass + `AdmissionMaintenanceService.bulk_review_eligibility` admin UI.

Lý do defer Q9: scope drop để giữ timeline Wave A 2026-07-23 hard. Reactivate khi Phase 4 nếu nghiệp vụ thực tế cần (priority bonus + lock-after-draft compliance).

---

## How to use tracker

**Daily standup:**
1. Mỗi BE/FE update Status + Branch/PR + Tests cho task của mình.
2. Owner cột Status: `TODO` → `IN_PROGRESS` khi start; `BLOCKED` nếu waiting; `CODE_DONE` khi PR opened.
3. Reviewer: sau merge, owner update `TESTED` (sau khi unit/int PASS local) → `REHEARSED` (chỉ migration/backfill, sau staging clone PASS).
4. Cutover D-1: tất cả task ở status `DONE`; nếu còn `IN_PROGRESS` hoặc `BLOCKED` → No-Go.

**Weekly review:**
- PM aggregate Status counts per Section.
- Identify blockers > 3 ngày → escalate.
- Update last_updated date đầu file + current sprint focus.

**KHÔNG copy logic nghiệp vụ vào tracker.** Mọi câu hỏi về spec → đọc PLAN. Tracker chỉ trả lời "task nào ở đâu" + "ai làm" + "khi nào xong".

**GitHub Project board pattern (chốt 2026-05-02):**
- Board = Mức 1 high-level kanban: chỉ 8 thematic issue #181-#188.
- Owner manual move card Todo → In Progress (khi sub-PR đầu tiên start) → Done (khi tất cả sub-PR thuộc thematic merged).
- Sub-PR (T0-1, T0-2, ..., M-1-NN, B1-task-N, ...) **KHÔNG add card vào board**.
- Auto-add to project workflow đã DISABLED — không revert.
- Sub-PR detail track: TRACKER row-level (cột Status + Branch/PR) + DAILY_LOG entry + GitHub PR list URL filter (`is:pr base:feat/admission-full-cutover`).
- Lý do: 30-50+ sub-PR sẽ pollute board; row-level + audit trail đủ để recover progress.

---

**Companion documents:**
- Spec: `Documents/ADMISSION_REFACTOR_PLAN.md` v2.13.1
- Risk evidence: `Documents/ADMISSION_REFACTOR_RISK_REVIEW.md`
- Cutover ops: `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md`

**Code source of truth:**
- `Backend_FastAPI/app/core/admission_event_mapping.py`
- `Backend_FastAPI/app/services/lead_admission_sync.py`
- `Backend_FastAPI/scripts/data/consultation_status_v3.csv`
- `Backend_FastAPI/scripts/data/allowed_transitions_v3.csv`
