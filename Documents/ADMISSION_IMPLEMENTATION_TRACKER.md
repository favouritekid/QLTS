# Admission Implementation Tracker

**Source spec:** `Documents/ADMISSION_REFACTOR_PLAN.md` v2.13.1
**Cutover runbook:** `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md`
**Risk log:** `Documents/ADMISSION_REFACTOR_RISK_REVIEW.md`
**Branch:** `feat/admission-full-cutover` (parent của sub-feature branches)

**Last updated:** 2026-05-01 (round 22 cleanup: Q11 closed, Q9 defer 3 task, phase3_02/03 SUPERSEDED, sequencing fix #17/LS-map/FE Zod, blocker ID standardize, "9 → 11" direct sites, "Phase 3 = 2 → 1" align)
**Current sprint focus:** Task 0 prerequisites (T0-1, T0-2, T0-3, T0-4a/4b, T0-5) + maintenance window timing lock + 7 stakeholder sign-off

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
| T0-4a | Celery beat `dispatch_pending_outbox` **skeleton task** (no-op safe registration: function defined, beat schedule registered, log "outbox not yet active" + return early — KHÔNG insert/dispatch). Kịch bản: B2/M-1-19a chưa ship, beat task vẫn registered nhưng KHÔNG crash worker. | BE | TODO | | U:- I:- | (none — no dep, ship parallel với T0-1/2/3/5) | RUNBOOK §3.5 + PLAN §3.3.e |
| T0-4b | Celery beat `dispatch_pending_outbox` **real worker wiring** (3-step claim/dispatch/finalize, query NotificationOutbox table, dispatch SystemEvents enum). Replace skeleton T0-4a. | BE | TODO | | U:- I:- R:- (concurrency + crash recovery rig) | **B2** + **M-1-19a** ship trước (NotificationOutbox model + table tồn tại) | RUNBOOK §3.5 + PLAN §3.3.e |
| T0-5 | `POST /api/v2/admin/casbin/reload` admin endpoint | BE | TODO | | U:- I:- | | RUNBOOK §3.5 |

---

## Section 2 — Phase 0 Foundation (hot-fix + applied_rules trigger)

| ID | Task | Type | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|---|
| P0c | `admission_config_repository.py:76,84` field name `criteria_id` hot-fix | Code | BE | TODO | | U:- | | PLAN §0c |
| M-P0a | `phase0_add_selected_subject_group_id_to_profile` | Migration | BE | TODO | | M:- | | PLAN §4 P0 |
| M-P0b | `phase0b_relax_applied_rules_immutability_for_payment_keys` | Migration | BE | TODO | | M:- | | PLAN §4 Phase 0b |

---

## Section 3 — Phase 1 Code Task Gates (BLOCK migration #11)

| ID | Task | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| B1 | Casbin auth_model deny-first + adapter v3 mapping + 16 deny rules accountant | BE | TODO | | U:- I:- R:- (4×14 matrix) | | PLAN §3.3.b RBAC + RISK_REVIEW B1 |
| B2 | EventDefinition extend (`requires_outbox`, `bypass_consent_check`) + 12 ADMISSION_* enum + EVENT_CATALOG seed + `dispatch_event` wrapper + `NotificationOutbox` model + migration | BE | TODO | | U:- I:- | | PLAN §3.3.d-f + RISK_REVIEW B2 |
| #15 | `approved → admitted` workflow remap 23 file caller + `is_admitted_like()` + `effective_status()` helpers | BE | TODO | | U:- I:- | B2 ship trước (event mapping) | PLAN §4 task #15 |
| #16 | Refactor 11 direct `profile.status = '...'` sang `state_service.transition()` + lint rule AST check | BE | TODO | | U:- I:- R:- (lint rule) | B1 + B2 ship trước | PLAN §4 task #16 + RISK_REVIEW B5 |

---

## Section 4 — Phase 1 Schema Migrations (additive + status history)

| ID | Migration | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| M-1-01 | `phase1_01_add_degree_level_fk_to_major_program` | BE | TODO | | M:- | | PLAN §4 P1 #01 |
| M-1-02 | `phase1_02_add_bonus_rule_to_method_and_path` | BE | TODO | | M:- | | PLAN §4 P1 #02 |
| M-1-03 | `phase1_03_add_applicable_to_method_quota_to_path` (kèm BE schema + service + FE Zod) | BE+FE | TODO | | M:- I:- | | PLAN §4 P1 #03 |
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
| M-1-19a | `phase1_19a_create_outbox_table` (+ claim columns + 2 partial index) | BE | TODO | | M:- | B2 ship cùng (NotificationOutbox model) | PLAN §4 P1 #19a |
| M-1-19b | `phase1_19b_seed_event_catalog_db_rows` (12 ADMISSION_* notification_rule rows) | BE | TODO | | M:- I:- | M-1-19a + B2 | PLAN §4 P1 #19b |
| M-1-19c | `phase1_19c_register_celery_beat_archive_task` (cùng task T0-4) | BE | TODO | | I:- | T0-4 ship cùng | PLAN §4 P1 #19c |
| M-1-19d | `phase1_19d_seed_notification_rules` (channel routing per audience) | BE | TODO | | M:- I:- | M-1-19a | PLAN §4 P1 #19d |
| M-1-casbin | `phase1_backfill_casbin_eft_v3_and_seed_deny_rules` (16 deny rules accountant) | BE | TODO | | M:- I:- | B1 auth_model rewrite | PLAN §4 P1 + RISK_REVIEW B1 |

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
| FE-zod-path | Zod `admission-path.ts` thêm `applicable_to`, `method_quota`, `admission_round_id`, `bonus_rule_override` | FE | TODO | | tsc:- vitest:- | M-1-03 | PLAN §4 Phase 3 FE #5 |
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
| BF-casbin | Casbin v3='allow' backfill + 16 deny rules seed | BE | TODO | | M:- I:- | M-1-casbin + B1 | RUNBOOK §7.2 |

---

## Section 10 — CI/Coverage Tooling

| ID | Task | Owner | Status | Branch/PR | Tests | Blocker | Plan ref |
|---|---|---|---|---|---|---|---|
| CI-status | `check_status_assignment.py` AST tool 4 patterns + 6 fixture | BE | TODO | | U:- | #16 refactor xong | RISK_REVIEW Phần 8 patches |
| CI-event | `check_notification_event_coverage.py` extend namespace collision + outbox INSERT site | BE | TODO | | U:- | B2 | RISK_REVIEW Phần 8 |
| CI-workflow | GitHub Action `admission-contract-check.yml` + pre-commit hook | BE | TODO | | I:- | CI-status + CI-event | RISK_REVIEW Phần 8 |

---

## Section 11 — P0 Blocker Tracker (source of truth: PLAN §1.4 top blocker list lines 57-65)

**Plan Blocker → Tracker Task ID mapping:**

| Plan Blocker ID | Description (PLAN line 57-65) | Tracker active task IDs | Status | Notes |
|---|---|---|---|---|
| **B1** | Casbin `auth_model.conf` không support deny effect | `B1` (Section 3) + `M-1-casbin` (Section 4) | TODO | OPEN — code task B1 ship trước M-1-casbin migration. PATCH-16. |
| **B2** | `EventDefinition` thiếu `requires_outbox`/`bypass_consent_check` + 12 SystemEvents enum chưa có | `B2` (Section 3) + `M-1-19a` + `M-1-19b` + `M-1-19c` + `M-1-19d` (Section 4) | TODO | OPEN — code task B2 bundle với NotificationOutbox model + migration. PATCH-17. |
| ~~B3~~ | ~~T17 cascade Student~~ | (none — Q1 strict reject) | **CLOSED** | Resolved Q1 chốt 2026-05-01 — Student schema unchanged. |
| **B4** | `system_config` table + `current_intake_year` không tồn tại | `M-1-systemconfig` (Section 4) | TODO | OPEN — bundle với LS-projection (Section 7). |
| **B5** | **11 direct** `profile.status = '...'` ở `admission_service.py` (3918, 5014, 5317, 5517, 5708, 6085, 6284, 6862, 7786, 7994, 8214) | `#16` (Section 3) | TODO | OPEN — task #16 PR scope cập nhật cover 11 sites. |
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
| T0-1 2 entrypoint env flag gates shipped (RUN_MIGRATIONS_ON_STARTUP + RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP) | TODO | T0-1 |
| T0-2 ADMISSION_FROZEN middleware shipped (3 prefix verified-from-code, path-segment match) | TODO | T0-2 |
| T0-3 Nginx admission block shipped (envsubst-driven, regex match T0-2) | TODO | T0-3 |
| T0-4a dispatch_pending_outbox skeleton (no-op safe) | TODO | T0-4a |
| T0-4b dispatch_pending_outbox real worker wiring (sau B2 + M-1-19a) | TODO | T0-4b |
| T0-5 Casbin reload endpoint shipped | TODO | T0-5 |
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
