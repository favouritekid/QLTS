# Admission MVP + Cold Cutover Plan

**Strategy:** **Cold cutover** trên production clone — KHÔNG staged production-safe rollout.
**Decision date:** 2026-05-01
**Status:** Active source of truth cho admission refactor.
**Timeline:** D1-D18 (~2.5-3 weeks) cho MVP deploy production.

**Supersedes (mọi document trước đây):**
- `Documents/ADMISSION_REFACTOR_PLAN.md` v2.13.1 (FROZEN — historical reference, KHÔNG dùng làm spec implementation nữa).
- `Documents/ADMISSION_REFACTOR_RISK_REVIEW.md` (FROZEN — risk findings carry-over xem Phần 7).
- `Documents/PR_DRAFTS_2026-05-01.md` v3 (FROZEN — staged PR sequence không còn áp dụng).

**Lý do cold cutover thay vì staged:**
1. Production hiện đang khóa admission — KHÔNG có hot path live cần backward-compat.
2. Staged rollout (FE permissive → BE migration → FE strict + soak windows) tốn 5+ tuần wall-clock và phức tạp hơn cần thiết.
3. Cold cutover trên production clone cho phép rehearse migration lớn nhiều lần đến khi sạch.
4. Maintenance window deploy + smoke test + unlock — risk thấp hơn vừa lái vừa thay bánh.

---

## Phần 0 — Strategy Decision

| Old strategy (v2.13.1 staged) | New strategy (MVP cold cutover) |
|---|---|
| 27 migration + 6 code task chia 4 phase | ~10 migration + ~8 code task ship cùng wave |
| 5 tuần wall-clock với soak windows | 2.5-3 tuần wall-clock |
| Backward-compat từng bước trên production sống | Replace toàn bộ trong maintenance window |
| FE 3-stage deploy choreography | FE single deploy cùng BE |
| Lead one-to-many tách 3 PR + soak | Lead one-to-many ship atomic |
| Wave A 2026-07-23 hard / Wave B 2026-08-13 best-effort | MVP single deploy ~2026-05-19 (D18) |

**Acceptable trade-offs:**
- Maintenance window downtime (estimate 2-4h) — chấp nhận vì admission đang khóa.
- KHÔNG ship multi-NV trong MVP — defer Phase 2 (Q3/2026+).
- KHÔNG ship Phase 4 cleanup trong MVP — defer Q1/2027.
- Test rehearsal trên DB clone, không production canary — chấp nhận vì có backup full + rollback playbook.

**Non-negotiables (5 must-have, KHÔNG ship MVP nếu thiếu bất kỳ):**
1. Backup + restore test xanh trước cutover.
2. RBAC/Casbin deny effect đúng + accountant deny matrix verified.
3. State service + audit history (`AdmissionProfileStatusHistory`) đúng + zero direct `profile.status =` assign.
4. Migration rehearsal trên DB clone PASS 2 lần (idempotency check).
5. E2E vận hành smoke test PASS (toàn bộ admission flow: create → submit → review → approve/reject → confirm → enroll).

---

## Phần 1 — MVP Scope

### 1.1. IN — Must ship MVP (8 items)

| # | Feature | Source | Notes |
|---|---|---|---|
| 1 | **State service + 17 transition matrix** (T1-T17) | Plan Phần 3.3.b/c | Chuẩn duy nhất cho mọi `profile.status` change. Bao gồm 4 new state (reviewing/result_published/admitted/waitlisted) + legacy 10 state. |
| 2 | **Status history audit** | Plan Phần 2.7 | Table `admission_profile_status_history` với `actor_actual_role` + `effective_transition_role` tách. |
| 3 | **Casbin deny effect + accountant guard** | Plan Phần 3.3.b RBAC | `auth_model.conf` rewrite + `casbin_rule.v3` backfill `'allow'` + 16 deny rules cho accountant trên admission action. |
| 4 | **`system_config` table + `current_intake_year`** | Plan Phần 2.5.b | Whitelist key registry + Redis cache + admin-only endpoint. |
| 5 | **Notification outbox + 12 ADMISSION_* events** | Plan Phần 3.3.d-f | `NotificationOutbox` model + table + worker beat + EVENT_CATALOG flag (`requires_outbox`, `bypass_consent_check`) + 12 enum + dispatch_event wrapper. |
| 6 | **FE status enum + STATUS_BADGE_CONFIG + typed available_actions** | Plan Phase 3 FE deliverables | 14 status (10 legacy + 4 new) + i18n inline 25 keys + typed `available_actions: [{action, target, endpoint}]`. |
| 7 | **Magic link 4 actions** (submit/resubmit/confirm/withdraw) | Plan Phần 3.3.g | `AdmissionConfirmationToken.action_type` extend + atomic claim + CCCD verify + `attempt_count` separate tx anti-bruteforce. |
| 8 | **Lead one-to-many** (1 profile/year per lead) | Plan Phase 1 #15 | Composite UNIQUE `(lead_id, academic_year)` + `Lead.admission_profiles` plural relationship + drop `delete-orphan` cascade + service-layer cleanup. |

### 1.2. OUT — Deferred Phase 2/4 (KHÔNG ship MVP)

| # | Feature | Defer to | Reason |
|---|---|---|---|
| D1 | Multi-NV (`AdmissionProfileChoice` + `ProfileChoiceScore`) | Phase 2 (Q3/2026+) | Single-NV đủ nghiệp vụ mùa 2026 (per Q4 chốt 2026-05-01); avoid 27 migration scope. |
| D2 | `PathSubjectGroupConfig` + `PathSubjectGroupItem` (3-tier scoring override) | Phase 2 | Engine xét tuyển hiện dùng `CriteriaSubjectGroup` đã đủ. |
| D3 | `OfferingAdmissionRound` + `admit_quota` + multi-round per offering | Phase 2 | DOT_1 mặc định cho mùa 2026 (per Q3 chốt). |
| D4 | `applicable_to` (audience filter) + `method_quota` + `bonus_rule_override` | Phase 2 | Admin manual filter qua UI hiện có. |
| D5 | `subject_kind` (TERM_AVERAGE/ABILITY_TEST/CERTIFICATE) + score precision widen | Phase 2 | DGNL/V-ACT/IELTS scoring chưa critical mùa 2026. |
| D6 | Demographics (`area_code`, `priority_object_codes`, `candidate_education_level`) | Phase 4 (Q1/2027) | Per Q9 drop scope chốt. |
| D7 | Extra thresholds (`min_conduct`, `min_health_category`, `required_graduation_year_*`) | Phase 4 | Per Q9 drop scope chốt. |
| D8 | `selected_subject_group_id` persist + lock-after-draft trigger | Phase 4 | Manual review qua admin UI hiện có. |
| D9 | Phase 4 drop legacy (`Lead.gpa`, `AdmissionPath.academic_info_id`, `MajorProgram.degree_level` text) | Q1/2027 | Per Q5 chốt. |
| D10 | i18n next-intl migration | Q1/2027 | Inline 3 file existing per Q8 chốt. |
| D11 | Wave B multi-NV UI (ChoiceListEditor, ChoiceScoreCard, etc.) | Phase 2 | Single-NV launch trước. |

### 1.3. Carry-over từ 10 product decisions (Q1-Q10 chốt 2026-05-01)

| Q | Decision | MVP impact |
|---|---|---|
| Q1 | T17 strict reject từ enrolled | State service raise `BusinessRuleViolation`; KHÔNG cần Student schema migration. |
| Q2 | Late submit strict cutoff `end_date`, no grace period | Phần 1.1 #1 state service guard. |
| Q3 | DOT_1+DOT_2 cùng năm BLOCK | Composite UNIQUE `(lead_id, academic_year)` enforce — Phần 1.1 #8. |
| Q4 | Wave A single-NV hard, Wave B slip-able | Wave A = MVP scope; Wave B = Phase 2 deferred. |
| Q5 | Phase 4 Q1/2027 | OUT D9. |
| Q6 | `submission_count` + `admit_quota` tách | Defer Phase 2 (D3) — MVP dùng `round_quota` đơn giản. |
| Q7 | Bypass consent in-app+email only; Zalo/SMS legal flag | Phần 1.1 #5 — `bypass_consent_check` flag mặc định in-app+email; Zalo/SMS gate `zalo_template_approved=False`. |
| Q8 | i18n inline 3 file | Phần 1.1 #6 — KHÔNG xây next-intl. |
| Q9 | Drop scope, không tăng người | OUT D6, D7. |
| Q10 | Officer scope unchanged | RBAC IDOR `get_admission_for_user/manager` reuse — Phần 1.1 #3. |

---

## Phần 2 — Pre-cutover Requirements (5 must-have)

### 2.1. Backup + Restore Test

- [ ] **Full DB backup** trước freeze: `pg_dump -Fc -d qlts_prod -f admission_pre_cutover_${DATE}.dump`.
- [ ] **Upload backup** sang offsite S3/cloud storage (verified accessible from staging env).
- [ ] **Restore test trên staging**: `pg_restore -d qlts_staging admission_pre_cutover_${DATE}.dump` PASS.
- [ ] **Smoke test trên restored DB**: query `SELECT COUNT(*) FROM admission_profile, lead, admission_path, ...` match production count.
- [ ] **Document restore time**: bao lâu để restore full backup (estimate cho rollback playbook).

### 2.2. RBAC/Casbin

- [ ] `auth_model.conf` effect rewrite: `e = !some(where (p.eft == deny)) && some(where (p.eft == allow))`.
- [ ] `casbin_rule.v3` backfill `'allow'` cho mọi p-rule existing.
- [ ] 16 deny rules seed cho accountant trên admission action.
- [ ] CasbinAuth dependency reload: `await enforcer.load_policy()` post-deploy.
- [ ] Test matrix 4 role × 14 action PASS.

### 2.3. State Service + Audit History

- [ ] `AdmissionStateService` ship full matrix T1-T17 (legacy + 4 new state).
- [ ] `AdmissionProfileStatusHistory` table tạo + backfill 1 row/profile + scattered scalar audit migrate.
- [ ] Refactor 11 direct `profile.status = '...'` site sang `state_service.transition()`.
- [ ] Lint rule custom AST check active (no direct assign outside state_service.py).
- [ ] Test 50+ transition case PASS.

### 2.4. Migration Rehearsal trên DB Clone

- [ ] Clone production DB sang staging environment.
- [ ] Apply MVP migration chain 1 lần → smoke test PASS.
- [ ] Reset clone, apply lại 2 lần → idempotency check PASS.
- [ ] Document migration time per step (cho maintenance window estimate).
- [ ] Backfill verification: zero data loss + zero exception row outside expected.

### 2.5. E2E Vận Hành Smoke Test

- [ ] **Lead → Profile create**: officer create lead → auto-create profile draft.
- [ ] **Public submit**: candidate magic_link → CCCD verify → submit → status `submitted`.
- [ ] **Review**: officer claim → status `reviewing` → request revision (status `revision_requested`) → candidate resubmit (status `submitted`).
- [ ] **Decision**: admin/manager approve → status `approved` HOẶC publish-result + system distribute → status `admitted`/`waitlisted`/`rejected`.
- [ ] **Confirm**: candidate magic_link confirm → status `confirmed`.
- [ ] **Enroll**: system enroll job → status `enrolled` + Student record created.
- [ ] **Withdraw**: candidate (admitted/confirmed) hoặc admin (enrolled) withdraw → status `withdrawn`.
- [ ] **Rollback (T17)**: admin rollback admitted → draft với reason.
- [ ] **T17 từ enrolled REJECT**: verify raise `BusinessRuleViolation`, KHÔNG cascade Student.
- [ ] **Notification fanout**: 12 ADMISSION_* events dispatch đúng audience qua outbox + best-effort.
- [ ] **Lead pipeline projection**: `Lead.consultation_status_id` update đúng cho mọi 14 status.
- [ ] **Finance flow**: profile admitted → fee invoice issue → payment → enrollment.
- [ ] **Casbin matrix**: accountant cannot trigger any admission transition (16 action deny).

---

## Phần 3 — Timeline 18 Days

```
D1-D2    Freeze + Clone (2 days)
D3-D7    Backend MVP implementation (5 days)
D8-D11   Frontend implementation (4 days)
D12-D14  Migration rehearsal + E2E vận hành (3 days)
D15      Cutover rehearsal full dry-run (1 day)
D16-D18  Production deploy window + post-deploy soak (3 days)
```

### D1-D2: Freeze + Clone

| Day | Task | Owner |
|---|---|---|
| D1 | Communicate freeze cho stakeholder (admin, officer, candidate). Email + in-app banner. | Product + Ops |
| D1 | Disable admission write endpoints qua feature flag `ADMISSION_FROZEN=true`. Read-only mode. | BE |
| D1 | Full pg_dump production + offsite backup. Verify integrity. | DBA |
| D2 | Restore backup sang staging env. Smoke test count match production. | DBA + BE |
| D2 | Clone uploads (Document files, magic link tokens) sang staging storage. | Ops |
| D2 | Verify admission frozen state — 0 new profile create/submit possible. | QA |

### D3-D7: Backend MVP (5 days)

| Day | Task | Effort | Owner |
|---|---|---|---|
| D3 | Migration: status_history table + extend status CHECK + Casbin v3 backfill + system_config + applied_rules whitelist + token action_type + outbox table + lead_id composite UNIQUE. **8 migration consolidated**. | 1d | Senior BE |
| D3 | Backfill: status_history (1 row/profile + 5 scattered scalar), token action_type='confirm' default, current_intake_year=2026. | (cùng D3) | Senior BE |
| D4 | EventDefinition extend (`requires_outbox`, `bypass_consent_check`) + 12 ADMISSION_* enum + EVENT_CATALOG seed module-level. | 1d | BE |
| D4 | NotificationOutbox model + dispatch_event wrapper + worker beat task. | (cùng D4) | BE |
| D5 | AdmissionStateService skeleton + matrix T1-T17 + can_transition + transition entry + history insert + dispatch_event. | 1d | Senior BE |
| D5 | Refactor 11 direct status site sang state_service.transition. | (cùng D5) | Senior BE |
| D6 | Casbin auth_model rewrite + 16 deny rules seed + reload endpoint + adapter v3 mapping. | 1d | Senior BE |
| D6 | system_config repository + admin endpoint + Redis cache + whitelist key registry. | (cùng D6) | BE |
| D7 | Lead one-to-many: model uselist=True + drop delete-orphan + repository plural method + service guard composite UNIQUE + 3 caller migrate. | 1d | Senior BE |
| D7 | lead_admission_sync 4 new state mapping + caller wrap try/except cho soft-fatal sites. | (cùng D7) | BE |
| D7 | Magic link action_type extend + 4 endpoint (submit/resubmit/confirm/withdraw) + atomic claim + attempt_count separate tx. | (cùng D7) | BE |
| D7 | **Operational gaps fill (5 tasks, ship cùng wave backend)**: xem Phần 2.6 bên dưới. | (cùng D7) | BE + Ops |

### 2.6 — Operational Implementation Gaps (verified 2026-05-01, MUST fill trước D12 rehearsal)

5 gap phát sinh từ verify codebase round 21:

| Gap | Evidence | Fix scope | Owner |
|---|---|---|---|
| **OG-1: Cutover entrypoint** | `Backend_FastAPI/docker-entrypoint.sh:4-5` tự `alembic upgrade head` mỗi container start. Cold cutover cần manual control migration log/time. | Tạo `docker-entrypoint-cutover.sh` HOẶC env var `RUN_MIGRATIONS_ON_STARTUP` (default `true`). Entrypoint check flag → skip alembic nếu false. Document `Backend_FastAPI/CLAUDE.md`. | BE (small, 0.5d) |
| **OG-2: ADMISSION_FROZEN feature flag** | Grep `app/config.py`, `app/middleware/`, `app/routers/admissions.py` — KHÔNG có `ADMISSION_FROZEN`/`MAINTENANCE_MODE`/feature flag system. Plan runbook reference flag không tồn tại. | Add `Settings.ADMISSION_FROZEN: bool = False` vào `app/config.py`. Tạo `app/middleware/admission_freeze.py` middleware (hoặc `Depends(check_admission_not_frozen)` dependency) raise 503 cho `POST/PUT/DELETE /api/admissions/*`. Verify env var update không cần container restart. | BE (small, 0.5d) |
| **OG-3: Nginx admission block** | `nginx/conf.d/default.conf.template:76-80` chỉ có generic `/api/` catch-all. KHÔNG có conditional block `/api/admissions/*` cho maintenance. | Add upstream condition trong template: nếu env `NGINX_ADMISSION_FROZEN=1` → `location ~ ^/api/admissions/ { return 503 ... }`. Defense-in-depth với OG-2 backend middleware. | Ops + BE (0.5d) |
| **OG-4: Outbox worker beat task** | `Backend_FastAPI/app/celery_app.py:108-150` beat schedule có consultation reminders/cache sync/KPI nhưng KHÔNG có `dispatch_pending_outbox` entry. | Add beat schedule entry: `"dispatch-pending-outbox": {"task": "app.tasks.notification_tasks.dispatch_pending_outbox_task", "schedule": 30.0}` (mỗi 30s). Implement task body theo plan v2.13.1 Phần 3.3.e (3-step claim/dispatch/finalize). | BE (1d, ship cùng D4 outbox model) |
| **OG-5: Casbin reload dedicated endpoint** | `app/routers/admin/roles.py` đã có `await enforcer.load_policy()` side-effect trong CRUD endpoint, nhưng KHÔNG có dedicated `POST /api/v2/admin/casbin/reload` cho cutover safety. | Add endpoint `POST /api/v2/admin/casbin/reload` admin-only gọi `await enforcer.load_policy()` + return policy count + audit log. Useful sau khi seed deny rules direct DB. | BE (small, 0.25d) |

**3 wording clarifications**:
- "CDN purge" trong runbook → **Frontend container restart** (Next.js standalone không có CDN layer; verified `frontend/next.config.ts:6-8` `output: "standalone"`).
- "System auto-create profile draft + issue submit token" trong smoke test → **verify hành vi mong đợi**: `lead_service.py:1405, 1825-1828` kiểm tra existing profile, KHÔNG có auto-create logic. MVP scope cần clarify: (a) implement auto-create-on-lead-creation HOẶC (b) officer manual create profile sau create lead (2-step flow). User chốt trước D3.
- `sync_notification_rules` script (`app/scripts/sync_notification_rules.py:123-225`) chỉ seed rule cho event có `notification_class="user"`. **12 ADMISSION_* events MUST có `notification_class="user"`** + `default_channels` trong EventDefinition entry — verify D4.

### D8-D11: Frontend (4 days)

| Day | Task | Owner |
|---|---|---|
| D8 | Zod schema `admissions.ts` + `lead.ts`: 14 status enum + plural `admission_profiles` + typed `available_actions: [{action, target, endpoint}]`. | FE |
| D8 | Status badge config 14 entry + i18n inline 25 keys. | FE |
| D9 | ConfirmAdmissionForm extend cho 4 action (submit/resubmit/confirm/withdraw) + CCCD verify. | FE |
| D10 | LeadDetailPanel + LeadInfoTab plural admission_profiles render. AdmissionsClient STATUS_TABS extend 14 status. | FE |
| D11 | E2E smoke test FE flow: public magic link 4 action + admin transition + candidate confirm. | FE + QA |

### D12-D14: Rehearsal (3 days)

| Day | Task | Owner |
|---|---|---|
| D12 | Migration rehearsal lần 1 trên staging clone: apply chain → verify count + sample data. | DBA + BE |
| D12 | E2E vận hành smoke test (Phần 2.5) lần 1 → identify issue. | QA |
| D13 | Fix issue identified D12. Update migration/code. | Team |
| D13 | Migration rehearsal lần 2 (idempotency): reset clone, re-apply → expect identical end state. | DBA |
| D14 | E2E lần 2 → expect zero issue. Document migration time + smoke time cho cutover window. | QA |
| D14 | Rollback rehearsal: restore from backup, verify recovery. | DBA |

### D15: Cutover Rehearsal Dry-run (1 day)

- [ ] Full cutover dry-run trên staging: freeze → backup → deploy → migrate → smoke → unlock.
- [ ] Time tracking từng step. Total estimate maintenance window.
- [ ] Issue identification + final fix.
- [ ] Stakeholder sign-off cho production deploy schedule.

### D16-D18: Production Deploy + Post-deploy Soak (3 days)

**D16: Production cutover (maintenance window 2-4h)**

| Step | Time estimate | Action |
|---|---|---|
| 1 | 0:00-0:15 | Communicate freeze: email + Slack + in-app banner. |
| 2 | 0:15-0:30 | Disable all admission endpoints (feature flag + reverse proxy block). |
| 3 | 0:30-1:00 | Final pg_dump production. Upload offsite. |
| 4 | 1:00-1:30 | Deploy new backend image (with MVP code). KHÔNG run migration yet. |
| 5 | 1:30-2:00 | Run migration chain. Monitor logs. Verify zero error. |
| 6 | 2:00-2:30 | Deploy new frontend image. CDN purge. |
| 7 | 2:30-3:00 | Smoke test: 5 critical user journey + 3 admin flow + Casbin matrix. |
| 8 | 3:00-3:15 | Re-enable admission endpoints. Communicate unlock. |
| 9 | 3:15-3:30 | Monitor error rate + outbox worker dispatch + lead sync. Standby for hotfix. |

**D17-D18: Post-deploy soak**

- [ ] Monitor 48h: error rate, outbox backlog, lead sync failure, Casbin deny hit count, status transition latency.
- [ ] Daily smoke test: 1 candidate end-to-end magic link flow + 1 admin transition flow.
- [ ] Rollback decision point: D17 EOD nếu issue critical → restore + revert. D18 nếu xanh → declare GA.

---

## Phần 4 — Consolidated Migration List (MVP)

**Total: 8 Alembic migrations + 2 backfill scripts** (so với 27 ở plan v2.13.1).

| # | Migration | Body |
|---|---|---|
| `mvp_01` | `relax_applied_rules_immutability_for_payment_keys` | Trigger function whitelist `fee_paid_at`, `fee_payment_data`, `fee_calculated_at`, `fee_invoice_id`. Was Phase 0b. |
| `mvp_02` | `create_status_history_table_with_role_split` | `admission_profile_status_history` với `actor_actual_role` + `effective_transition_role` tách + CHECK actor consistency + indexes. |
| `mvp_03` | `extend_profile_status_check_constraint` | Drop old CHECK + recreate với 14 state (10 legacy + 4 new: reviewing/result_published/admitted/waitlisted). |
| `mvp_04` | `create_notification_outbox_with_claim_columns` | `notification_outbox` table + claimed_at/claimed_until + UNIQUE idempotency_key + 2 partial index. |
| `mvp_05` | `create_system_config_table` | `system_config (key, value JSONB, description, updated_at, updated_by_user_id)` + seed `current_intake_year=2026`. |
| `mvp_06` | `extend_confirmation_token_for_multi_action` | ALTER ADD `action_type VARCHAR(20) DEFAULT 'confirm'` + drop UNIQUE profile_id + partial UNIQUE `(profile_id, action_type) WHERE confirmed_at IS NULL` + revoked_at/by audit columns. |
| `mvp_07` | `drop_lead_id_unique_add_composite_lead_year` | Drop `admission_profile.lead_id` UNIQUE + ADD UNIQUE `(lead_id, academic_year)`. |
| `mvp_08` | `backfill_casbin_eft_v3_and_seed_deny_rules` | `UPDATE casbin_rule SET v3='allow'` + INSERT 16 deny rules cho accountant. |

**Backfill scripts (D3 cùng wave migration):**
- `backfill_status_history_initial_and_scattered_scalar.py` — 1 row/profile + migrate 5 scattered scalar (approved_at/by, rejected_at/by, revision_requested_at/by, resubmitted_at/by, overridden_at/by).
- `backfill_token_action_type_default.py` — set `action_type='confirm'` cho token existing.

**Code task ship cùng wave (KHÔNG Alembic):**
- T1: Hot-fix `admission_config_repository.py:76,84` field name `admission_criteria_id → criteria_id`.
- T2: Casbin auth_model.conf rewrite + adapter v3 mapping verify.
- T3: EventDefinition extend + 12 ADMISSION_* enum (`notification_class="user"` + `default_channels` MANDATORY cho `sync_notification_rules` auto-seed) + dispatch_event wrapper.
- T4: AdmissionStateService implementation + 11 site refactor + lint rule.
- T5: lead_admission_sync 4 new state + caller audit + soft-fatal wrap.
- T6: system_config repository + Redis cache + admin endpoint + whitelist key registry.
- T7: Lead one-to-many model + schema + repository + service + 3 caller migrate.
- T8: Magic link 4 action + atomic claim + CCCD verify + attempt_count separate tx.
- T9: Frontend Zod + status badge + ConfirmAdmissionForm + LeadDetailPanel + AdmissionsClient.

**Operational gaps fill (5 task ship cùng wave per Phần 2.6):**
- T10 (OG-1): `docker-entrypoint-cutover.sh` HOẶC `RUN_MIGRATIONS_ON_STARTUP` env var.
- T11 (OG-2): `ADMISSION_FROZEN` config + middleware/dependency block admission writes.
- T12 (OG-3): Nginx conditional block `/api/admissions/*` cho maintenance window (env-driven).
- T13 (OG-4): Celery beat task `dispatch_pending_outbox_task` schedule 30s + 3-step claim/dispatch/finalize implementation.
- T14 (OG-5): Casbin reload endpoint `POST /api/v2/admin/casbin/reload` admin-only.

---

## Phần 5 — Cold Cutover Runbook

### 5.1. Pre-flight Checklist (D15 dry-run)

- [ ] Backup verified offsite + restore test PASS.
- [ ] Staging deploy identical với production target.
- [ ] Migration rehearsal 2 lần PASS.
- [ ] E2E vận hành smoke test PASS.
- [ ] Casbin matrix 4×14 PASS.
- [ ] Stakeholder sign-off (Product, Legal, DBA, FE Lead).
- [ ] Rollback playbook tested.
- [ ] Maintenance window communicated 48h trước.

### 5.2. Maintenance Window (D16, 2-4h estimate)

**Pre-window (T-30min):**
- [ ] Final stakeholder check-in.
- [ ] Standby team: 2 BE + 1 FE + 1 DBA + 1 Ops.
- [ ] Rollback path confirmed (backup file + commit hash).

**Cutover (T+0):**

⚠️ **Entrypoint topology** (verified 2026-05-01): `Backend_FastAPI/docker-entrypoint.sh:4-5` tự chạy `alembic upgrade head` mỗi container start. Cold cutover cần kiểm soát migration log/time/rollback rõ ràng → **Approach 2: tách migration khỏi container startup**.

**Pre-D16 implementation (ship trong D3-D7 backend wave)**:
- [ ] Tạo `Backend_FastAPI/docker-entrypoint-cutover.sh` (mới): KHÔNG chạy `alembic upgrade head`, chỉ `sync_notification_rules` + `exec "$@"`.
- [ ] `Backend_FastAPI/Dockerfile` thêm option `ENTRYPOINT_MODE=cutover` env hoặc build arg select entrypoint.
- [ ] HOẶC: thêm env var `RUN_MIGRATIONS_ON_STARTUP` (default `true`); entrypoint check `if [ "$RUN_MIGRATIONS_ON_STARTUP" = "true" ]; then alembic upgrade head; fi`.
- [ ] Document trong `Backend_FastAPI/CLAUDE.md` Common Commands.

**Cutover sequence với explicit migration step**:
```
T+0:00  Communicate freeze (email + Slack + banner)
T+0:15  Set ADMISSION_FROZEN=true env (backend container restart không cần — middleware đọc env runtime)
        + Nginx reload với admission block config (return 503 cho POST/PUT/DELETE /api/admissions/*)
T+0:30  Final pg_dump → upload S3
T+1:00  Deploy backend image với ENV `RUN_MIGRATIONS_ON_STARTUP=false`
        Container start → KHÔNG chạy alembic, chỉ sync_notification_rules + uvicorn ready
T+1:30  Manual run: `docker compose exec backend alembic upgrade head`
        Stream log realtime → verify zero error mỗi migration step
        Time tracking: nếu > 5 phút bất kỳ step → investigate trước tiếp.
T+2:00  Deploy frontend image (Next.js standalone — KHÔNG có CDN, chỉ container restart + browser cache header verify)
T+2:15  Manual run: `docker compose exec backend python -m app.scripts.sync_notification_rules` (nếu entrypoint cutover skip step này)
T+2:30  Smoke test (5 candidate journey + 3 admin flow + Casbin matrix) — xem Phần 5.3
T+3:00  Set ADMISSION_FROZEN=false + Nginx reload bỏ admission block
T+3:15  Communicate unlock
T+3:30  Monitor handoff to oncall (post-deploy soak D17-D18 dashboard)
T+24h   Switch backend container env back to `RUN_MIGRATIONS_ON_STARTUP=true` cho future routine deploys
        (cutover behavior chỉ áp dụng 1 lần, sau đó về default auto-migration)
```

**KHÔNG dùng wording "CDN purge"** — Next.js standalone build không có CDN layer. Frontend container restart đủ. Nếu có Cloudflare/Vercel edge cache layer, document riêng.

### 5.3. Smoke Test Script (T+2:30 — T+3:00)

**Candidate journey:**
1. Officer create lead → status pre-admission (verified existing flow).
2. **[VERIFY EXPECTED BEHAVIOR — pending product chốt]** Profile creation:
   - **Option A (auto-create)**: System auto-create draft profile + issue submit token (TTL 7d) khi lead created. **CHƯA IMPLEMENT** (verified `lead_service.py:1405, 1825-1828` chỉ check existing). MVP scope cần ship logic + test.
   - **Option B (manual 2-step)**: Officer create lead → riêng endpoint create profile draft → riêng endpoint issue submit token. Existing flow.
   - **Decision needed trước D3**: Product chốt A hay B. Smoke test step 2 update accordingly.
3. Candidate click magic link → CCCD verify → submit profile → status `submitted`.
4. Officer claim → status `reviewing`.
5. Officer approve → status `approved` (legacy flow) HOẶC admin publish-result + system distribute → status `admitted`.
6. Candidate magic link confirm → status `confirmed`.
7. System enroll → status `enrolled` + Student row created.

**Admin flow:**
1. Admin login → dashboard render 14 status filter.
2. Admin reject profile → status `rejected` + reason audit.
3. Admin override (admitted → confirmed) → reason mandatory + audit.

**Casbin matrix:**
1. Accountant call any admission transition → 403 (deny first).
2. Officer call publish-result → 403 (manager+ only).
3. Manager call T17 admin-rollback → 403 (admin only).

**Notification fanout:**
1. Admin publish-result → 12 candidate nhận event ADMISSION_DECISION_ADMITTED qua in-app + email (Zalo/SMS gated).
2. Outbox worker dispatch backlog = 0 sau 30s.

### 5.4. Rollback Plan

**Trigger conditions:**
- Smoke test fail bất kỳ critical step.
- Error rate > 5% trong 30 phút post-unlock.
- Critical bug data corruption.

**Rollback steps (T+1h từ trigger):**
1. Re-freeze admission endpoints.
2. `pg_restore` từ backup pre-cutover.
3. Deploy previous backend image (commit hash X).
4. Deploy previous frontend image.
5. Communicate revert + post-mortem schedule.
6. Standby team root cause + fix + reschedule cutover.

### 5.5. Post-deploy Monitoring (D17-D18)

| Metric | Threshold | Action if exceeded |
|---|---|---|
| Error rate | > 1% | Investigate, fix forward hoặc rollback |
| Outbox backlog | > 100 rows pending > 5 min | Worker scale up hoặc dispatch debug |
| Lead sync failure rate | > 0.5% | Audit ADMISSION_TO_LEAD_STATUS_MAP completeness |
| Casbin deny hit count cho accountant | > 0 | Verify intent — if intentional, OK; if officer routed nhầm, RBAC bug |
| Status transition latency p95 | > 2s | Investigate FOR UPDATE lock contention |
| Magic link CCCD verify failure rate | > 5% | Audit token issuance flow + lockout logic |

---

## Phần 6 — Frontend Deliverables (consolidated)

**14 status enum + STATUS_BADGE_CONFIG mapping (i18n inline 3 file existing per Q8):**

```typescript
// frontend/src/lib/zod/admissions.ts
status: z.enum([
  // 10 legacy
  "draft", "submitted", "approved", "rejected", "revision_requested",
  "resubmitted", "confirmed", "overridden", "enrolled", "withdrawn",
  // 4 new
  "reviewing", "result_published", "admitted", "waitlisted",
])

// available_actions typed structure
available_actions: z.array(z.object({
  action: z.string(),
  target: z.enum(["self", "override", "staff"]),
  endpoint: z.string(),
}))
```

**5 component update:**
1. `ConfirmAdmissionForm.tsx`: extend cho 4 action (submit/resubmit/confirm/withdraw) — single component với `action` prop.
2. `LeadDetailPanel.tsx`: render plural `admission_profiles` per year + tab switcher (default = `current_intake_year`).
3. `LeadInfoTab.tsx`: dual-read `profile.gpa_overall ?? lead.gpa`.
4. `AdmissionsClient.tsx`: STATUS_TABS extend 14 status (consolidated tab grouping).
5. `AdmissionActions.tsx`: render action button qua typed `available_actions` (KHÔNG suy luận từ status).

**OUT for MVP:**
- ChoiceListEditor (multi-NV)
- ChoiceScoreCard
- EligibilityResultViewer
- DecisionBadge
- AuditReasonDialog (ship vs MVP nếu T17 admin rollback critical, otherwise inline reason in existing dialog)

---

## Phần 7 — Carry-over Findings từ Plan/Risk Review (KHÔNG re-litigate)

**Schema verified 2026-05-01 (DON'T re-verify):**
- `AdmissionProfile.status` 10 enum legacy (`app/models/admission.py:43-55`).
- `confirmed_via` CHECK 3 giá trị (line 51-54).
- `admission_path.criteria_id` (NOT `admission_criteria_id`); 2 site repository drift đã track Phase 0c.
- 9 audit scalar fields scattered hiện có.
- `AdmissionProfileChoice` + `ProfileChoiceScore` + `AdmissionProfileStatusHistory` + `notification_outbox` + `system_config` table CHƯA TỒN TẠI — MVP ship.
- Student model KHÔNG có `deleted_at/reason/by` — Q1 strict reject T17, KHÔNG cần.
- Casbin `auth_model.conf` matcher dùng `keyMatch4` + effect allow-only — MVP rewrite.
- `casbin_rule.v0..v5` columns đã có — MVP backfill v3='allow' + seed deny.
- 11 direct `profile.status = '...'` site verified line numbers — MVP refactor.
- `safe_dispatch` KHÔNG có `strict` param; `dispatch` CÓ — worker dùng `dispatch(strict=True)`.
- `lead_admission_sync.py:115-121` return False unknown status — MVP raise + caller audit.

**Top failure modes vẫn applicable (MUST verify trong rehearsal D12-D14):**
1. Casbin deny silent ignored → accountant pass through.
2. dispatch_event wrapper TypeError on missing fields.
3. T17 từ enrolled cascade fail (MVP REJECT mitigates).
4. Lead pipeline projection fallback `False` break sync transaction.
5. 11 direct status writes bypass audit.
6. Magic link CCCD bruteforce qua tx rollback (MVP separate tx mitigates).
7. Outbox worker dispatch fail.
8. FE Zod parse fail trên state mới (MVP cold cutover deploy đồng thời mitigates).
9. cascade="delete-orphan" + uselist=True conflict (MVP drop delete-orphan).
10. Migration rollback impossible (MVP có backup pre-cutover).

---

## Phần 8 — Phase 2 Roadmap (Q3/2026+)

Sau MVP GA + soak 2-3 tháng, đánh giá nghiệp vụ thực tế và ship Phase 2 features có nhu cầu:

| Item | Trigger condition |
|---|---|
| Multi-NV (`AdmissionProfileChoice`) | Khi nghiệp vụ thực sự cần thí sinh đăng ký nhiều nguyện vọng. |
| `OfferingAdmissionRound` + multi-round | Khi mùa tuyển sinh có nhiều đợt cùng năm với chỉ tiêu khác. |
| `PathSubjectGroupConfig` + 3-tier scoring | Khi engine xét tuyển cần override path-level. |
| `applicable_to` audience filter | Khi nhiều education_level cùng path. |
| `subject_kind` mở rộng + score precision widen | Khi DGNL/V-ACT/IELTS thực dùng. |
| Demographics + extra thresholds | Phase 4 Q1/2027. |
| i18n next-intl | Q1/2027 sau khi locale infrastructure ổn định. |

---

## Phần 9 — Sign-off Required Before D1

- [ ] **Engineering Owner:** ____________ (sign-off MVP scope + 18-day timeline + cold cutover strategy).
- [ ] **Product Owner:** ____________ (sign-off OUT list defer + maintenance window communication).
- [ ] **DBA:** ____________ (sign-off backup/restore plan + migration rehearsal protocol).
- [ ] **Legal/Compliance:** ____________ (sign-off Q7 bypass consent in-app+email only; Zalo/SMS gated).
- [ ] **Frontend Lead:** ____________ (sign-off Q8 i18n inline + 14 status render contract).
- [ ] **Ops Lead:** ____________ (sign-off maintenance window 2-4h + rollback playbook).
- [ ] **QA Lead:** ____________ (sign-off E2E smoke test scope + rehearsal protocol).

---

## Phần 10 — Communication Plan

### 10.1. Pre-cutover (T-7d → T-0)

| Day | Audience | Channel | Message |
|---|---|---|---|
| T-7d | All staff | Email | "Maintenance window scheduled D16 ${HH:MM}. Admission frozen 2-4h. Plan attached." |
| T-3d | Admin/Officer | In-app banner | "Hệ thống tuyển sinh sẽ bảo trì ngày ${DATE} từ ${HH:MM}. Liên hệ ${CONTACT} nếu có hồ sơ urgent." |
| T-1d | Candidate (active) | Email + Zalo | "Hệ thống bảo trì nâng cấp ngày ${DATE}. Vui lòng hoàn tất hồ sơ trước ${HH:MM} hoặc sau bảo trì." |
| T-1h | All | Slack #ops + in-app | "Maintenance starting in 1 hour. Final reminder." |

### 10.2. During cutover (T+0 → T+3:30)

- Slack #ops live updates per step.
- In-app banner: "Hệ thống đang bảo trì. Vui lòng quay lại sau ${HH:MM}."
- Status page update: incident.io / statuspage.io nếu có.

### 10.3. Post-cutover (T+3:30 onwards)

- T+3:30: All-staff email "Maintenance complete. New features: ${LIST}. Issues? Contact ${CONTACT}."
- T+24h: Stakeholder briefing — error rate + smoke test summary + any issues.
- T+72h: Post-mortem if any rollback or significant issue.

---

**Source documents archived:**
- `Documents/ADMISSION_REFACTOR_PLAN.md` v2.13.1 — historical reference, KHÔNG dùng spec.
- `Documents/ADMISSION_REFACTOR_RISK_REVIEW.md` — findings carry-over (Phần 7).
- `Documents/PR_DRAFTS_2026-05-01.md` v3 — staged PR sequence không còn áp dụng.

**Pending product decision trước D3 (Q11)**:
- Profile creation flow: Option A (auto-create on lead creation) hay Option B (manual 2-step). Affects smoke test step 2 + lead_service implementation scope. Ship cùng D7 backend wave nếu chốt A.

**Changelog:**
- v1 (2026-05-01) — initial MVP cutover plan sau strategy decision.
- v2 (2026-05-01 EOD) — round 21 verify codebase + 5 operational gaps (OG-1 entrypoint cutover, OG-2 ADMISSION_FROZEN flag, OG-3 Nginx admission block, OG-4 outbox beat task, OG-5 Casbin reload endpoint) + 3 wording clarifications (CDN purge → container restart, auto-create profile pending product decision Q11, sync_notification_rules dependency on `notification_class="user"`). Phần 2.6 + 5 task T10-T14 + cutover sequence revised với manual migration step.

**Last updated:** 2026-05-01 EOD (round 21 verify operational mismatches, plan v2 ready cho sign-off).
