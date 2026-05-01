# ADMISSION REFACTOR — Implementation Risk Review (Round 19)

> 📌 **Role: Evidence / Risk Log — NOT implementation plan** (cleanup 2026-05-01)
>
> **Source of truth cho spec:** `Documents/ADMISSION_REFACTOR_PLAN.md` v2.13.1.
> **Production replacement runbook:** `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md`.
>
> File này được giữ làm:
> - 10 product decisions Q1-Q10 (Phần 0) — quyết định nghiệp vụ chốt 2026-05-01.
> - 7 P0 blocker findings (Phần 2) + 14 P1 + 11 P2 + 5 P3 issue (Phần 3).
> - Codebase verification evidence file:line (Phần 11).
> - Top failure modes (Phần 7).
>
> KHÔNG dùng làm spec implementation. Mọi schema/transition/migration content đọc PLAN.md.
> KHÔNG dùng làm cutover runbook. Mọi backup/freeze/cutover step đọc PRODUCTION_REPLACEMENT_RUNBOOK.md.

---

**Plan reviewed:** `ADMISSION_REFACTOR_PLAN.md` v2.12 (4222 dòng, baseline 2026-04-30)
**Review date:** 2026-05-01
**Reviewer:** Senior/Principal Engineer review pass
**Codebase baseline:** `main @ ddbca88d` (2026-05-01)
**Verdict (initial):** CONDITIONAL GO — proceed Phase 0 sau khi 8 P0 blocker đóng + 10 product decisions chốt.
**Verdict (final 2026-05-01 EOD):** **STRATEGY CHANGED** → full v2.13.1 cold cutover / production replacement thay thế staged rollout. (MVP rút scope đã bị revoked cùng ngày — giữ full scope multi-NV + multi-round + scoring engine + demographics đẩy lùi xuống Q1/2027 chỉ phần Q9 defer.)

---

## Phần 0 — Decision Log 2026-05-01 (production-safe lock)

10 quyết định product/business chốt 2026-05-01, áp dụng cho mùa 2026:

| # | Question | Decision | Rationale | Plan impact |
|---|---|---|---|---|
| Q1 | T17 cascade từ `enrolled` | **Strict reject** — bắt buộc dùng T16 admin-withdraw trước. KHÔNG soft-delete Student trong mùa 2026. | Tránh phải ADD 3 column `deleted_at/deleted_reason/deleted_by_user_id` trên Student model + cascade dependency (DormAssignment, ClassEnrollment...) → schema change nhỏ hơn, ít rủi ro mid-season. | Plan Phần 3.3.b T17 spec đổi từ "cascade SOFT DELETE Student" → "REJECT với guidance T16 trước". v2.12 fix #1 bỏ migration ADD column Student. State Service raise `BusinessRuleViolation("T17 from enrolled requires T16 admin-withdraw first")`. |
| Q2 | Late submit grace period | **Strict cutoff theo `end_date`**, `grace_period_hours = 0`. Grace là Phase sau. | Nghiệp vụ tuyển sinh có thể extend round qua admin endpoint (Phase 1 #08 Rule 2) — đủ cho edge case. Không cần grace_period field thêm complexity. | Plan Phần 2.1.a Rule 1 giữ nguyên strict cutoff. Bỏ wording "grace_period_hours field" khỏi spec late-submit. |
| Q3 | DOT_1 + DOT_2 cùng năm cho 1 thí sinh | **BLOCK cho 2026** — `AdmissionProfile.status` là scalar, chưa có per-round lifecycle. 1 lead → 1 profile/year → 1 round. | Multi-round per profile = phức tạp lifecycle (profile có thể đậu DOT_1 + apply DOT_2 cùng năm). Existing UNIQUE `(citizen_id, academic_year)` enforce naturally. Phase 4+ mới mở nếu nghiệp vụ yêu cầu. | Plan Phần 3.3.g.1 "Duplicate hồ sơ theo round/path" wording đổi: "1 profile/year only — multi-round per profile defer Phase 4+". Service guard reject create profile thứ 2 cùng `academic_year` cho cùng lead. |
| Q4 | Wave A/B staged launch | **Wave A single-NV chấp nhận**; KHÔNG ép multi-NV ngay nếu P0 chưa đóng. Wave B trượt OK. | Mùa 2026 hard deadline 2026-07-23 (Wave A). Wave B 2026-08-13 SLIP-able vì single-NV đủ cho most use case. Buffer thực tế cho engineering. | Plan Phần 7.1 timeline: Wave A 2026-07-23 commit; Wave B "best-effort 2026-08-13, slip-able". Document risk slip với product team trước Phase 1 start. |
| Q5 | Phase 4 timing (drop legacy) | **Q1/2027** — KHÔNG drop destructive trong Q4/2026 khi mùa còn nóng. | Avoid risk drop `Lead.gpa` / `AdmissionPath.academic_info_id` mid-season → caller cũ chưa migrate hết. Q1/2027 sau monitor 2 tháng prod confirm 0 caller. | Plan Phần 4 Phase 4 timeline đổi `Q4/2026 → Q1/2027`. Bỏ wording "After 1-2 months observation". |
| Q6 | `admit_quota` field | **Tách rõ** `submission_count` (đăng ký) và `admit_quota` (trúng tuyển). Nullable. | Nghiệp vụ phân biệt: round có thể nhận 200 đăng ký nhưng chỉ 100 admit slot. Engine cần guard riêng. | Plan Phần 2.1 `OfferingAdmissionRound` thêm field `admit_quota INT NULL`. Plan Phần 5.b thêm engine guard: T7 (`result_published → admitted`) check `count(admitted) < admit_quota`. Migration phase2_01 thêm column. |
| Q7 | Bypass consent (5 critical events) | **Chỉ bypass in-app + email** khi có legal basis. **Zalo + SMS cần legal sign-off + template approval riêng**. | In-app/email là channel hệ thống nội bộ, đủ legal cover. Zalo/SMS là third-party + có quota commercial → cần Bộ GD&ĐT compliance docs + ZNS template approval Zalo official. | Plan Phần 3.3.d cột "Bypass consent" đổi từ "Yes (all channels)" → "in-app + email only; Zalo/SMS gated by legal approval flag". `dispatch_event()` route Zalo/SMS cho 5 critical event qua `consent_check + zalo_template_approved` flag (False mặc định trước khi legal sign-off). |
| Q8 | i18n system | **Inline 3 file existing** cho 2026 (`admissions.ts`, `status-badge.config.ts`, `StatusBadge.tsx`). next-intl defer Q1/2027. | Effort xây i18n system mới = 1 sprint không cần thiết cho 25 keys. Inline + lint rule sync 3 file đủ cho mùa 2026. | Plan Phase 3 FE deliverables item #6 i18n đổi "25 keys system mới" → "25 keys inline 3 file existing với lint rule sync". Effort giảm từ 1.5 sprint → 0.5 sprint. |
| Q9 | Buffer 0 trade-off | **Drop scope**, KHÔNG cứu bằng tăng người trễ. | Tăng team mid-project = onboarding cost > productivity gain trong 15 tuần. Drop scope (defer 1 số migration Phase 1) realistic hơn. | Plan Phần 7.1 timeline thêm "Defer list" cho Phase 4: Phase 1 #04 extra thresholds, Phase 1 #07 demographics, Phase 1 #09 conduct/health admin UI. Mùa 2026 chỉ cần state machine extend + multi-NV core. |
| Q10 | Officer scope cho 4 new state | **Giữ nguyên** assigned + unit cho mọi state mới. Manager unit. Admin all. System internal only. | Không thay đổi RBAC scope = giảm test surface. 4 new state (reviewing/result_published/admitted/waitlisted) cùng IDOR boundary với legacy state. | Plan Phần 3.3.b RBAC matrix thêm note: "IDOR scope KHÔNG đổi cho 4 new state — reuse `get_admission_for_user()` (deps.py:2241) + `get_admission_for_manager()` (deps.py:2161)". |

**Carry-over impact:**
- Q1 + Q3 + Q9 → simplify Phase 1 schema scope (Student schema unchanged, multi-round per profile defer, demographics defer).
- Q4 + Q5 + Q9 → realistic timeline rebase: Wave A hard 2026-07-23, Wave B best-effort, Phase 4 Q1/2027.
- Q6 + Q7 + Q10 → additive infrastructure (admit_quota field, legal flag, RBAC scope unchanged).
- Q8 → FE effort reduction (-1 sprint).

---

## Phần 1 — Executive Summary

Plan v2.12 chốt **schema design** chắc chắn (model + constraint + index + backfill SQL hardened qua 19 round review), nhưng **chưa production-ready** ở mức **plumbing/infra/contract enforcement** vì **5 hệ thống phụ trợ là green-field code mới** — không phải refactor field nullable additive như plan claim:

1. **Casbin deny effect** (auth_model.conf rewrite) — chưa support deny rule
2. **EventDefinition extension** (`requires_outbox`, `bypass_consent_check` fields) — không tồn tại
3. **Outbox infrastructure** (`notification_outbox` table, worker beat task, dispatch routing) — green-field
4. **AdmissionStateService + effective_role_for_transition** — green-field
5. **system_config table + current_intake_year** — không tồn tại

Cộng với **11 direct** `profile.status = ...` assignments cần refactor (round 20 re-verify) + 23 file caller cần migrate sang `is_admitted_like()` helper + Lead one-to-many bundle PR (model + schema + repo + service + FE) → effort thực 22-26 tuần với 2 BE + 1 FE, KHÔNG phải 15 tuần buffer 0 như plan ước tính.

**Sau khi 10 product decisions chốt 2026-05-01:**
- T17 strict reject (Q1) bỏ Student schema migration → giảm 1 P0
- DOT_1+DOT_2 cùng năm BLOCK (Q3) → bỏ multi-round per profile complexity
- i18n inline (Q8) → giảm 1 sprint FE
- Drop scope (Q9) → defer Phase 1 #04/#07/#09 demographics

Còn lại **7 P0 blocker** phải đóng trước Phase 1 chain start. Wave A (single-NV) timeline 2026-07-23 còn realistic. Wave B (multi-NV) timeline 2026-08-13 high-risk slip — accept slip per Q4 chốt.

---

## Phần 2 — Blocker List (7 P0 sau khi 10 chốt)

⚠️ **Source of truth cho blocker ID = `ADMISSION_REFACTOR_PLAN.md` top blocker list (lines 57-65)**. Bảng dưới chỉ mirror — KHÔNG dùng làm authoritative reference. Nếu có drift giữa bảng này và PLAN, PLAN thắng.

| # | Blocker | Severity | Phase blocked | Status (post-decision-2026-05-01) |
|---|---|---|---|---|
| B1 | Casbin `auth_model.conf` không support deny | **P0** | Phase 1 #16 audit | OPEN — phải đóng trước Phase 1 W3 |
| B2 | `EventDefinition` thiếu 2 field; 12 SystemEvents enum mới chưa có | **P0** | Phase 1 #19 outbox | OPEN — phải đóng trước Phase 1 W3 |
| B3 | ~~Student model thiếu deleted_at/reason/by~~ | ~~P0~~ | ~~Phase 1 #11~~ | **CLOSED via Q1 chốt** (T17 strict reject) |
| B4 | `system_config` table + `current_intake_year` không tồn tại | **P0** | Phase 1 #15 lead one-to-many | OPEN — phải đóng cùng Phase 1 #15 |
| B5 | **11 direct** `profile.status = ...` (round 20 re-verify, KHÔNG phải 9) chưa refactor + lint rule chưa active | **P0** | Phase 1 #11 | OPEN — task #16 PR scope cập nhật cover 11 sites |
| B6 | `ADMISSION_TO_LEAD_STATUS_MAP` 4 new state chưa map; line 121 `return False` (KHÔNG `sts13` fallback per round 20 verify) | **P0** | Phase 1 #11 | OPEN — task #15 PR scope |
| B7 | ~~Effort 15w buffer 0~~ | ~~P0~~ | ~~Toàn bộ~~ | **CLOSED via Q4+Q9 chốt** (Wave B slip-able + drop scope) |
| B8 | Lead one-to-many bundle PR atomic risk | **P0** | Phase 1 #15 | OPEN — atomic local implementation per cold cutover (KHÔNG staged 3 PR + soak windows như plan v2.13.1 ban đầu đề xuất) |

**Tracker mapping**: xem `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` Section 11 cho mapping Plan Blocker → Tracker Task IDs đầy đủ.

---

## Phần 3 — Risk Matrix

### 3.1. P0 Issues (7 sau decision lock)

| ID | Module | Evidence | Plan ref | Problem | Production impact | Recommended fix/gate |
|---|---|---|---|---|---|---|
| **P0-01** | RBAC | `Backend_FastAPI/auth_model.conf:1-14` chỉ có `e = some(where (p.eft == allow))` | Plan v2.9 fix #3 (lines 115, 1294) | Plan ghi `policy entry deny accountant explicit` nhưng auth_model effect KHÔNG support deny. Mọi `p, role:accountant, ..., deny` rule plan đề xuất sẽ bị Casbin enforcer **bỏ qua**. Accountant inherit officer (line 44) → pass route guard cho `/claim`/`/request-revision`/`/publish-result`. | Accountant trigger transition T2/T3/T4/T6 qua direct API → lệch SoD compliance, audit trail ghi sai role. | Update `auth_model.conf` `e = !some(where p.eft == deny) && some(where p.eft == allow)` TRƯỚC khi seed deny policy. Test: accountant → `POST /api/admissions/{id}/claim` → 403 (không 200/500). Coverage script verify mọi route admin-only + manager-only có deny rule cho accountant. |
| **P0-02** | Notification | `app/core/event_catalog.py:53-86` `EventDefinition` chỉ có 15 field hiện có; KHÔNG có `requires_outbox`, `bypass_consent_check`, `audience_roles`, `template_codes_by_channel`. `app/core/events.py:258-1168` chỉ có 6 APPLICATION_* + 3 ADMISSION_CONFIRMATION_* — 12 milestone events plan ADMISSION_* chưa có. | Plan v2.9 fix #8 + Phần 3.3.f (line 2153-2158) | Plan code sample dùng `event_def.requires_outbox`, `event_def.bypass_consent_check`. KHÔNG TỒN TẠI. `dispatch_event()` wrapper plan đề xuất sẽ raise `AttributeError` runtime. | `transition()` service crash mọi transition → admission workflow chết. | Extend `EventDefinition` class thêm 2 field optional (`requires_outbox: bool = False`, `bypass_consent_check: bool = False`). Add 12 SystemEvents enum mới + 12 EVENT_CATALOG entries TRƯỚC service `transition()` deploy. PR scope: `events.py` + `event_catalog.py` + `notification_dispatcher.py` (dispatch_event wrapper) — **3-4 files, MERGE BEFORE Phase 1 #19**. Áp dụng Q7: Zalo/SMS bypass guard thêm `zalo_template_approved` flag. |
| **P0-04** | Lead projection | `app/models/config.py` không có `system_config` table hoặc `SystemConfig` model | Plan v2.5.b + v2.11 fix #4 (line 770-832) | Dependency `config.get('current_intake_year')` cho Lead pipeline projection multi-year. Không có table → KeyError hoặc default fallback → multi-year scenario sai. | Lead `consultation_status` projection sai sau Phase 1 #15 (drop lead_id UNIQUE → multi-profile/lead). 1000+ lead enrolled mùa 2025 đột ngột mất tracking khi lookup `current_intake_year=2026` → None fallback → KPI funnel giảm sai. | Phase 1 mới migration `phase1_XX_create_system_config_table.py` với `(key, value, description, updated_at, updated_by)` + admin endpoint UPDATE (RBAC admin-only). Seed default `current_intake_year=2026`. Bundle với Phase 1 #15 PR scope. |
| **P0-05** | Workflow contract | `app/services/admission_service.py:3918, 5014, 5317, 5517, 5708, 6085, 6284, 6862, 7786, 7994, 8214` — **11 direct** `profile.status = '...'` (round 20 re-verify, +2 sites bulk approve/reject) | Plan task #16 (line 206, 3031-3072) | 11 direct assignment KHÔNG đi qua `validate_transition()`. Sau Phase 1 #11 ALTER CHECK extend, caller cũ vẫn có thể set `'approved'` direct trong khi `transition()` ghi `'admitted'` → DB accept cả 2 → status mixed across `uses_choice_engine` boundary. | Audit trail lệch (status_history insert chỉ qua state_service, direct set không insert) → compliance fail. Frontend hiển thị sai badge. Lead pipeline projection sai. | Task #16 PR refactor 11 site cụ thể: `submit_and_evaluate (3918)`, `enroll_student (5014)`, `approve_profile (5317)`, `reject_profile (5517)`, `request_revision (5708)`, `resubmit_profile (6085)`, `override_profile (6284)`, `withdraw_profile (6862)`, `verify_and_confirm (7786)`, **`bulk_approve (7994)`, `bulk_reject (8214)`**. Lint rule custom AST check catch `profile.status = '...'` outside `state_service.py` body. CI gate. |
| **P0-06** | Lead sync | `app/services/lead_admission_sync.py:41-53` `ADMISSION_TO_LEAD_STATUS_MAP` 9 entries hard-code; **line 121 `return False`** cho unknown status (round 20 verify — KHÔNG phải `sts13` fallback như earlier doc claim) | Plan task #15 step 3 (line 3140-3158) | Plan task #15 dùng tên map `ADMISSION_TO_LEAD_STAGE_MAP` (DIFFERENT — code dùng `_STATUS_MAP`). 4 state mới không trong map → silent return `False` skip sync → lead pipeline lệch. | Lead pipeline funnel báo cáo KPI sai → manager báo cáo sai stake-holder. | Task #15 verify map name (`ADMISSION_TO_LEAD_STATUS_MAP`), thêm 4 entry mới, raise `BusinessRuleViolation` thay vì silent `False` return + soft-fatal caller wrap. Áp dụng Q10: scope IDOR giữ nguyên cho 4 state mới. |
| **P0-08** | Lead bundle PR | `app/models/lead.py:252-257` `relationship(uselist=False, cascade="delete-orphan")`; `app/schemas/lead.py:410` singular Optional; `app/repositories/admission_repository.py:482` singular | Plan #15 (line 3074-3110) | PR #15 scope: DB migration + model + schema + repository + service + FE schema + FE component. Bundle atomic merge = nếu fail giữa chừng → deploy state với DB đã drop unique nhưng code vẫn singular. cascade="delete-orphan" + uselist=False kết hợp = SQLAlchemy throws error khi setter assign list. | Lead detail page crash, FE timeline crash, KPI sai. Rollback DB migration FAIL nếu prod đã có lead với multi-year profile. | Tách 3 PR sequence: (1) PR-15a: DROP unique → ADD composite, KHÔNG đổi model relationship. Soak 1 tuần. (2) PR-15b: model `uselist=True` + repository thêm 2 method mới + schema dual response. Soak 1 tuần. (3) PR-15c: FE migrate component sang plural list. Áp dụng Q3: composite UNIQUE `(lead_id, academic_year)` enforce 1 profile/year only. |

### 3.2. P1 Issues (14)

| ID | Module | Evidence | Plan ref | Problem | Impact | Fix |
|---|---|---|---|---|---|---|
| **P1-01** | FE Zod | `frontend/src/lib/zod/admissions.ts:495` strict enum 10 status | Plan v2.10 fix #7 (line 2807-2829) | 3-stage permissive→strict deploy choreography phức tạp + status-badge.config (`status-badge.config.ts:96-196`) hard-code 11 entries → state lạ render fail. | User mở browser tab cũ → state mới về backend → Zod parse fail → page crash giờ cao điểm. | (a) FE Zod **strict enum 14 state ngay W3 deploy** (Wave A), KHÔNG permissive intermediate. BE migration #11 ship Wave A cùng wave. (b) Status badge config thêm 4 entry default fallback color/label TRƯỚC. (c) Bỏ 3-stage choreography phức tạp. |
| **P1-02** | Phase manager | `app/services/phase_manager.py:119` `if status in ("approved", "confirmed", "overridden")` | Plan task #15 row 2 | Hard-code tuple match cho FEE phase. Sau Phase 1 #11, profile choice-engine có `status='admitted'` → KHÔNG match → fee/commission downstream không trigger. | Choice-engine profile không enter FEE phase → fee invoice không issue → revenue impact. | Refactor sang `is_admitted_like(profile)` helper. Test cross 3 case: legacy approved, legacy overridden, choice-engine admitted. |
| **P1-03** | Finance | `app/routers/fees.py:81` `if profile.status not in ("approved", "confirmed", "enrolled")` | Plan task #15 row 6 | Same root cause P1-02. Choice-engine 'admitted' không match → fee gate trả False → candidate đậu nhưng không thấy invoice. | Drop-off rate tăng. | Refactor + cross case test. |
| **P1-04** | Commission | `app/services/commission_service.py:248, 296`; `commission_repository.py:246` | Plan task #15 row 9-10 | Commission record bound to admission status hard-code. Choice-engine admitted → commission không project. | Collaborator legal complaint, commission report sai. | Same — refactor `effective_status(profile)` + cross-case test. |
| **P1-05** | Outbox infra | Grep alembic/versions: KHÔNG có migration `notification_outbox` | Plan Phase 1 #19 (line 3225-3236) | Plan ship outbox table + worker beat + 12 EVENT_CATALOG entries + cron archive 90-day = 4 deliverable trong 1 migration. > 300 dòng. Risk: review miss bug, deploy fail roll-forward khó. | Outbox worker dispatch fail → silent notification loss. | Tách 4 migration con: (a) `phase1_19a_create_outbox_table.py` (b) `phase1_19b_seed_event_catalog_db_rows.py` (c) `phase1_19c_register_celery_beat_archive_task.py` (d) `phase1_19d_seed_notification_rules.py`. Down migration mỗi file độc lập. |
| **P1-06** | Outbox worker | Plan Phần 3.3.e (line 2034-2107) 3-step claim/dispatch/finalize pattern | Plan v2.11 fix #3 | Pattern phức tạp: `SELECT FOR UPDATE SKIP LOCKED` + 2-step CTE + adaptive `claimed_until` + `idempotency_key` UNIQUE. Memory `dispatch-bundle-strict-required` ghi `dispatch()` có 3 persistence branches gọi `db.rollback()` internal → conflict với worker tx. Existing `dispatch(db, event, payload, dedupe_key, skip_preference_check, strict, rooms)` (verified `notification_dispatcher.py:593`). Plan dispatch_event() wrapper KHÔNG pass `strict=True` → worker fail nuốt outer tx. | Worker dispatch fail → outbox row claim không release → backlog → 12 events không fanout. | Worker test rig với 100+ event mock fanout, scenarios: (a) external IO timeout, (b) worker crash sau Step 2 trước Step 3, (c) 2 worker concurrent claim, (d) dedupe key collision. PASS trước Phase 3 deploy. Worker `safe_dispatch(... strict=True, ...)` per memory `dispatch-bundle-strict-required`. |
| **P1-07** | T17 cleanup | Plan T17 wildcard rollback từ bất kỳ state | Plan Phần 3.3.b (line 1175-1196) | T17 BẮT BUỘC reason ≥10 chars. Nhưng `transition()` không có rollback semantics cho `applied_rules.fee_paid_at` (đã set qua Phase 0b whitelist). Profile rollback → draft với `applied_rules.fee_paid_at` còn nguyên → khi resubmit + re-approve → fee tracking lệch. Cộng Q1 chốt T17 từ enrolled REJECT → simplify nhưng vẫn cần document. | Data corruption fee tracking; refund flow trigger sai. | Áp dụng Q1: T17 từ enrolled raise `BusinessRuleViolation`. T17 từ state khác phải reset `applied_rules.fee_paid_at = NULL` hoặc raise nếu fee đã paid. Document Phần 3.3.b spec rõ. |
| **P1-08** | Public submit IDOR | Plan candidate route `/api/v2/public/admissions/{token}/{action}` | Plan Phần 3.3.g (line 1740-1965) v2.12 fix #2 | Atomic claim qua `UPDATE...RETURNING confirmed_at = NOW()` đặt token expired ngay. Nếu state transition sau đó fail → caller `db.rollback()` → `confirmed_at` revert. Pattern OK NHƯNG **`attempt_count` cũng revert** → CCCD bruteforce reset count mỗi fail. | Token CCCD bruteforce: attacker submit invalid form → tx rollback → attempt_count = 0 lại → unlimited retry. | Tách `attempt_count++` thành **separate short tx** (commit ngay sau check), KHÔNG gộp với main tx. Hoặc savepoint chỉ rollback business state, persist attempt_count. |
| **P1-09** | FE AdmissionPath | `frontend/src/lib/zod/admission-path.ts:215-248` thiếu `applicable_to`, `method_quota`, `admission_round_id` | Plan Phase 1 #03 (line 2402-2411) | Migration #03 ship cả backend + service + FE Zod cùng wave. Nếu BE migration ship trước FE → response field mới nhưng FE Zod strict reject. | Admin path management page crash sau migration #03 deploy. | CI gate: migration #03 alembic + `frontend/src/lib/zod/admission-path.ts` cùng PR atomic. |
| **P1-10** | i18n inline | Frontend KHÔNG có `messages/vi.json` | Plan Phase 3 i18n (line 3604-3633) + Q8 chốt | Inline 3 file existing (`admissions.ts:880-891`, `status-badge.config.ts:96-196`, `StatusBadge.tsx:110-122`). Drift bug nếu không sync. | Maintenance debt. | Q8 chốt: inline 3 file + lint rule custom check 25 keys present trong cả 3 file. Test: snapshot compare. |
| **P1-11** | EVENT_CATALOG worker | Memory `celery-worker-init-gap` (PR #101) | Plan v2.12 fix #3 (line 20-21) | Module-level Python dict pattern. Worker import `app.core.event_catalog` → catalog ready. NHƯNG cần verify Celery worker startup actually imports module. | Worker dispatch outbox 500. Backlog. | Pre-flight test: `celery -A worker inspect registered` + script verify `EVENT_CATALOG` import resolves. PR Phase 1 #19 ship cùng worker import explicit ở `app/tasks/notification_tasks.py` (top of file). |
| **P1-12** | Quota race backfill | Plan Phần 5.b atomic check-and-decrement | Plan v2.11 fix #5 | `submission_count` field MỚI ở `OfferingAdmissionRound`. Backfill set initial = COUNT profile WHERE round_id. Nhưng profile cũ trước Phase 2 KHÔNG có `applied_rules.admission_round_id` (verified) → JOIN sai → submission_count = 0 → quota check sai sau cutover → infinite submit. | Round quota không enforce → > admission target → manual cleanup. | Backfill conservative: `COUNT(profile JOIN admission_path on applied_rules.admission_path_id WHERE path.admission_round_id = round.id AND profile.status IN (active states))`. Verify count match expected mùa 2025. Áp Q6: thêm `admit_quota` backfill từ `annual_admission_quota / round_count` nếu admin không set explicit. |
| **P1-13** | Public storefront | `app/services/public_admissions_service.py:114, 145, 534` | Plan Phase 1 #17 code task | Storefront load path qua `academic_info_id` direct hiện tại — sau swap unique → `.first()` random path. Plan task #17 fix-closed nhưng KHÔNG list cụ thể caller endpoint cần update. | Sau Phase 2 #02b deploy: storefront path detail random → thí sinh đăng ký nhầm path. | Task #17 PR grep + update tất cả `public_admissions_service.py` references (line 114, 145, 534+). FE storefront page show round_code label rõ ràng. |
| **P1-14** | Score precision migration | `app/models/admission_config/criteria.py` `min_score Numeric(4,1)`, `max_possible_score Numeric(5,2)` | Plan Phase 2 #04 | ALTER COLUMN type yêu cầu SHARED ACCESS EXCLUSIVE LOCK. Production block tất cả admission API trong duration of ALTER. | Brief downtime mid-day → user 503. | Schedule migration off-peak (đêm). Pre-warm: `EXPLAIN ANALYZE` ALTER trên replica để measure time. |

### 3.3. P2 Issues (11)

| ID | Module | Evidence | Plan ref | Problem | Fix |
|---|---|---|---|---|---|
| **P2-01** | applied_rules trigger | `alembic/versions/b5c6d7e8f9a0_*.py` strict immutable | Plan Phase 0b (line 2320-2363) | Phase 0b whitelist 4 key. Memory `partial-update-loses-cross-field-invariants` cảnh báo cross-field invariant không address. | Future migration cần update applied_rules sẽ phải DROP→CREATE trigger pattern. Document. |
| **P2-02** | Casbin keyMatch4 | `auth_model.conf` matcher `keyMatch4` (verified) | Memory `lead-keymatch4-collision-followup` | `/api/v2/admissions/{id}` có thể ăn cả `/api/v2/admissions/bulk-publish-result`. | Tighten path matcher: `/{id:[0-9]+}` cho admission, hoặc đặt `bulk-*` trước `/{id}` trong policy ordering. |
| **P2-03** | Outbox archive failed | Plan Phần 1 #19 cron weekly archive 90-day | Plan v2.11 fix #8 | 90-day retention chỉ cho `dispatched_at IS NOT NULL`. Outbox `attempts >= 5` (DLQ) tích vĩnh viễn. | Add weekly cleanup `WHERE attempts >= 5 AND dispatched_at IS NULL AND created_at < NOW() - INTERVAL '180 days'` archive sang `_archived_outbox_failed`. |
| **P2-04** | Frontend socket debounce | `frontend/src/lib/socket/client.ts` KHÔNG implement 300ms debounce | Plan v2.10 fix #6 reference memory adm-032 | Memory `adm-032-doc-mutations-realtime` claim 300ms debounce. FE code KHÔNG có. Drift giữa memory và code. | Verify memory accuracy. Document handler thực tế hoặc implement 300ms debounce. |
| **P2-05** | StatusHistoryMetadataSchema | `extra='forbid'` strict | Plan v2.12 fix #8 | 8 keys cố định. Future feature thêm key → Pydantic load fail → 500. | Quy ước: schema additive only, monthly review. Hoặc `extra='ignore'` cho metadata write path, validate chỉ đọc. |
| **P2-06** | Wave B retroactive add NV | Plan Phần 4 Phase 3 Wave B + v2.12 fix #5 | Áp Q4: Wave B slip-able | Profile draft Wave A có 1 choice → Wave B button "Add NV" xuất hiện → race condition: user đã submit Wave A nhưng FE cache stale → button nhấn → BE reject → UX confusing. | FE force refresh sau Wave B deploy. Service worker cache invalidate. |
| **P2-07** | Magic link 4 actions | `app/models/admission.py:490-605` `AdmissionConfirmationToken` profile_id UNIQUE | Plan Phase 1 #18 | Migration drop UNIQUE profile_id + tạo partial unique `(profile_id, action_type) WHERE confirmed_at IS NULL`. Backfill default `'confirm'`. | Backfill rõ ràng: token existing chưa confirmed → action_type='confirm'. Token đã confirmed → giữ. Reminder logic test post-migration. |
| **P2-08** | Phase 1 #11 ALTER CHECK | Plan Phase 1 #11 | Postgres ALTER ADD CONSTRAINT block reads. Table 50k+ profile → ALTER vài giây. | Use `ADD CONSTRAINT ... NOT VALID` rồi `VALIDATE CONSTRAINT` cho full validation off-peak. |
| **P2-09** | Test debt | Memory `test-debt-admission-workflow-e2e` 6 pre-existing failures | Plan timeline KHÔNG include test debt cleanup | CI fail intermittent → block PR merge mid-Phase 1. | Phase 0 thêm test debt sweep PR (`test-debt/admission-workflow-e2e-fixture-fix` đã tracked). |
| **P2-10** | Coverage script | `app/scripts/check_notification_event_coverage.py` (memory) | Plan v2.9 fix #9 | Script check catalog/seed/dispatch site. Plan extend namespace collision check + outbox INSERT site. Chưa scope ngày. | Bundle với Phase 1 #19 PR. |
| **P2-11** | bulk_transition concurrency | Plan Suggestion #9 (line 1639-1671) | Plan bulk 1000 profile fanout < 5s. Mỗi profile hold FOR UPDATE → 1000 row lock → block other admin operations. | Chunk 50/batch + sleep 50ms giữa batch để release lock periodic. |

### 3.4. P3 Issues (5)

| ID | Module | Evidence | Plan ref | Problem | Fix |
|---|---|---|---|---|---|
| **P3-01** | Plan version sprawl | Plan có 12 version (v1.0 → v2.12) | Plan changelog | 19 round × 8-12 fix per round = 200+ line item — maintainability suffer. | Squash thành single document v3.0 sau khi P0 đóng. Lưu changelog tóm tắt 1 line per round. |
| **P3-02** | Cheat sheet drift | Plan Phần 8 line 4187 "Phase 1: 17"; line 4195 "Phase 1: 16" | Plan inconsistency | Drift số count migration. | Re-count + sync Phần 8. |
| **P3-03** | Field naming `path_id` vs `admission_path_id` | Plan code sample mix line 869, 870 (`path_id`) và 859 (`admission_path_id`) | Plan internal | Confusing. | Standardize on `admission_path_id` (verified DB schema). |
| **P3-04** | Archive table migration | `_archived_admission_profile` + `_archived_notification_outbox` | Plan v2.12 fix #6 | 2 archive table mới chưa có migration spec đầy đủ (chỉ pseudo-code). | Phase 1 add 2 migration tách: `phase1_XX_create_archived_admission_profile_table.py` + `phase1_XX_create_archived_outbox_table.py`. |
| **P3-05** | FE component path | Plan Phần 4 Phase 3 component table | Path không match Next.js App Router structure existing. | Adjust component path with FE team conventions (`app/(dashboard)/admissions/[id]/_components/...`). |

---

## Phần 4 — Cross-Module Impact Map

| Module | Impact level | Critical files modified | Risk |
|---|---|---|---|
| **Admission core** | **EXTREME** | `models/admission.py`, `services/admission_service.py` (**11 sites** direct status), `services/admission_state_machine.py` (extend), `services/admission_state_service.py` (NEW), `repositories/admission_repository.py` (3 method NEW), `routers/admissions.py` (~10 endpoint mới), `schemas/admission.py` (12+ schema mới) | EXTREME — engine xét tuyển + state machine + audit history |
| **Lead** | HIGH | `models/lead.py:252-257` (one-to-many flip), `schemas/lead.py:410`, `services/lead_admission_sync.py:41-53,57-59`, `core/admission_event_mapping.py` (15 status keys), `services/lead_service.py` effective_status | HIGH — pipeline projection multi-year, KPI funnel |
| **Finance** | MEDIUM | `routers/fees.py:81`, `services/admission_service.py:5904-5907` (fee_paid_at applied_rules), Phase 0b trigger | MEDIUM — fee gate dependency `is_admitted_like()` |
| **Commission/Collaborator** | MEDIUM | `services/commission_service.py:248,296`, `commission_repository.py:246`, `tasks/collaborator_tasks.py:71` | MEDIUM — projection bound to admission status |
| **Notification** | **EXTREME** | `core/event_catalog.py:53-86` (extend EventDefinition), `core/events.py` (12 enum mới), `services/notification_dispatcher.py` (dispatch_event wrapper), `models/notification.py` (NotificationOutbox NEW), `tasks/notification_tasks.py` (worker beat NEW) | EXTREME — outbox infra mới, 12 event mới, Q7 legal flag Zalo/SMS |
| **Frontend (admissions)** | HIGH | `lib/zod/admissions.ts:495,296-348`, `lib/zod/admission-path.ts:215-248`, `lib/ui-config/status-badge.config.ts:40-196`, `components/forms/ConfirmAdmissionForm.tsx`, 5 component mới (ChoiceListEditor, ChoiceScoreCard, EligibilityResultViewer, DecisionBadge, AuditReasonDialog) | HIGH — multi-NV UI + Q8 i18n inline 25 keys |
| **Public Storefront** | HIGH | `services/public_admissions_service.py:114,145,534` | HIGH — round + audience filter + 3-tier doc resolution |
| **KPI/Reports** | MEDIUM | `services/admission_service.py:309-312` (quota counting whitelist), `repositories/admission_repository.py:429` | MEDIUM — generic groupby OK; status_counts DTO sync FE |
| **RBAC/IDOR** | **EXTREME** | `auth_model.conf` (effect deny rewrite), `casbin_config/policy_templates.py` (deny rules), `core/deps.py:378` (CasbinAuth), `core/deps.py:2161-2316` (3-tier IDOR — Q10 unchanged) | EXTREME — deny rule infra mới |
| **Database/Migration** | **EXTREME** | 27 Alembic migration + 3 archive table + system_config table + admit_quota field | EXTREME — many one-way migration |
| **Operations** | HIGH | Cron beat, archive task, FE staged deploy choreography, monitoring outbox backlog, legal sign-off Zalo/SMS templates | HIGH — new infra to operate |

---

## Phần 5 — Migration/Rollback Review

### 5.1. Migration Safety Matrix

| Migration | Type | Down rollback | Risk |
|---|---|---|---|
| `phase0_add_selected_subject_group_id_to_profile` | ADDITIVE (ADD COLUMN nullable) | SAFE auto-revert | LOW |
| `phase0b_relax_applied_rules_immutability_for_payment_keys` | TRIGGER REPLACE | SAFE (revert to v1 strict) | LOW |
| `phase0c_fix_admission_config_repository_field_name` (code-only) | N/A code only | git revert | LOW |
| `phase1_01-08, 09a` (additive fields) | ADDITIVE | SAFE | LOW |
| `phase1_07b_create_backfill_exceptions_table` | ADDITIVE TABLE | SAFE | LOW |
| ~~`phase1_09b_create_eligibility_lock_trigger`~~ | TRIGGER + SCHEMA + ROLE + FUNCTION — **DEFERRED Q1/2027** per Q9 chốt 2026-05-01 (KHÔNG active 2026 chain). Lock-after-draft trigger không ship mùa 2026. | TRICKY — DBA role coord | MEDIUM |
| `phase1_10_create_status_history_table_and_backfill` | ADDITIVE + 5 backfill blocks scattered scalar | SAFE down (DROP TABLE) | LOW (data loss audit if rollback) |
| **`phase1_11_extend_profile_status_check_constraint`** | **ALTER CHECK CONSTRAINT (one-way nếu prod đã có 4 state mới)** | **MANUAL ROLLBACK PLAYBOOK 7.5 strategy B** | **HIGH** |
| `phase1_12_backfill_selected_subject_group_id` | DATA only + exception inserts | SAFE re-run idempotent | LOW |
| **`phase1_15_drop_lead_id_unique_constraint`** | **DROP UNIQUE + ADD COMPOSITE** | **MANUAL CLEANUP REQUIRED nếu prod đã có 2+ profile/lead** | **HIGH** |
| `phase1_18_extend_confirmation_token_for_multi_action` | ALTER ADD COLUMN + DROP/ADD UNIQUE | SAFE down | MEDIUM |
| `phase1_19a_create_outbox_table` | NEW TABLE | SAFE down (DROP TABLE) | LOW |
| `phase1_19b_seed_event_catalog_db_rows` | DATA seed | SAFE (DELETE seeded rows) | LOW |
| `phase1_19c_register_celery_beat_archive_task` | Beat task config | SAFE (UNREGISTER task) | LOW |
| `phase1_19d_seed_notification_rules` | DATA seed | SAFE | LOW |
| `phase1_XX_create_system_config_table` (NEW per Q4) | NEW TABLE | SAFE | LOW |
| `phase2_01_create_offering_admission_round` | ADDITIVE + backfill DOT_1 + admit_quota field per Q6 | SAFE | LOW |
| **`phase2_02b_admission_path_round_not_null_swap_unique`** | **ALTER NOT NULL + DROP/ADD UNIQUE one-way** | **MANUAL ROLLBACK + `_archive_admission_path_dup`** | **HIGH** |
| `phase2_03_create_path_subject_group_config_and_item` | NEW TABLES + backfill | SAFE | LOW |
| `phase2_04_widen_score_precision` | ALTER COLUMN type | SAFE if no overflow | MEDIUM |
| `phase3_01_create_admission_profile_choice_and_score` | NEW TABLES + 3-step backfill | SAFE | MEDIUM |
| ~~`phase3_02_seed_12_milestone_events_and_rules`~~ | DATA (catalog/rule/template) — **MOVED to Phase 1 #19a/b/c/d** per PLAN §8 cheat sheet line 4401 | SAFE | LOW |

### 5.2. Required Manual Rollback Playbook

3 migration ONE-WAY cần manual playbook + DBA approval trước rollback:

1. **`phase1_11` status CHECK extend** — strategy B remap (Plan 7.5 line 4079-4115)
2. **`phase1_15` drop lead_id UNIQUE** — manual cleanup duplicate profile-per-lead
3. **`phase2_02b` admission_round_id NOT NULL + unique swap** — `_archive_admission_path_dup` table

**Pre-flight bắt buộc trước Phase 3 deploy:**
- DB snapshot pre-deploy taken + verified offsite
- Status remap script dry-run trên replica
- FE read-only mode tested + togglable
- Runbook strategy A/B/C với contact list + escalation path

---

## Phần 6 — E2E/Regression Checklist Bắt Buộc

### 6.1. Pre-Phase 1 Deploy

- [ ] `auth_model.conf` updated to support deny effect + test 4 role × 14 action matrix (B1)
- [ ] `EventDefinition` extended với 2 field mới + 12 SystemEvents enum mới + EVENT_CATALOG seed (B2)
- [ ] ~~Student model deleted_at/reason/by~~ — **CLOSED via Q1 strict reject**
- [ ] `system_config` table + `current_intake_year` seeded (B4)
- [ ] All **11 direct** `profile.status = ...` refactored to `state_service.transition()`; lint rule active (B5)
- [ ] `is_admitted_like()` + `effective_status()` helpers shipped + 23 caller migrated
- [ ] Cross-case test (legacy approved + legacy overridden + choice-engine admitted) PASS for: fees, commission, phase_manager, lead sync, KPI, event projection
- [ ] Magic link 4 actions test: submit/resubmit/confirm/withdraw with CCCD verify + atomic claim + `attempt_count` persist sau tx rollback (P1-08)
- [ ] Outbox worker test rig: external IO timeout, worker crash, 2-worker concurrent, dedupe collision (P1-06)
- [ ] FE Zod 14 status enum + STATUS_BADGE_CONFIG mapping + i18n 25 keys inline 3 file + lint rule check sync (Q8)
- [ ] T17 strict reject test: rollback từ enrolled raise BusinessRuleViolation (Q1)
- [ ] Q3 1 profile/year UNIQUE: composite UNIQUE `(lead_id, academic_year)` enforce
- [ ] Q10 IDOR scope unchanged for 4 new state — verify `get_admission_for_user()` cover

### 6.2. Pre-Phase 2 Deploy

- [ ] phase2_02b dry-run on prod-replica — zero duplicate path detected
- [ ] Public storefront task #17 ship + tested 4 case (0/1/2 round + audience filter)
- [ ] Fail-closed strategy verified: 0 round → empty list, 1 round → auto-select, 2 round → picker
- [ ] Q6 `admit_quota` field migration ship + backfill conservative count + engine guard test

### 6.3. Pre-Phase 3 Deploy

- [ ] DB snapshot taken + verified
- [ ] Phase 3 backfill dry-run on replica × 2 (idempotency)
- [ ] Engine xét tuyển ≥80% coverage + 30+ case PASS
- [ ] 12 milestone events: catalog + rule + template seed verified zero silent fanout
- [ ] Bulk transition load test 1000 profile fanout < 5s; chunk pattern test (P2-11)
- [ ] FE staged Wave A deploy choreography rehearsed
- [ ] Q7 Zalo/SMS bypass guard `zalo_template_approved=False` mặc định; legal sign-off pending

### 6.4. Pre-2026 Mùa Mở (Wave A 2026-07-23)

- [ ] Admin set `applicable_to[]` cho 100% path active mùa 2026
- [ ] Admin set `default_bonus_rule` cho mọi `AdmissionMethod`
- [ ] Admin set `OfferingAdmissionRound` (DOT_1) với round_quota = annual; admit_quota = annual nếu 1 round
- [ ] FE đăng ký NV single-priority tested e2e (Wave A scope per Q4)
- [ ] Admin training: result_published + waitlist_promoted + rollback override workflow
- [ ] Q7 Zalo template approved Bộ GD&ĐT cho 5 critical event (HOẶC bypass tắt cho Zalo channel, chỉ in-app + email)

---

## Phần 7 — Top 10 Failure Modes

1. **Casbin deny silent ignored** → accountant trigger admin transition → audit lệch role → SoD compliance fail.
2. **dispatch_event() AttributeError trên `requires_outbox`** → mọi transition crash → admission workflow dead.
3. **T17 từ enrolled** raise đúng strict → KHÔNG cascade → admin force rollback enrolled fail → admin phải biết workflow T16 → training gap.
4. **Lead pipeline projection multi-year fallback `sts13`** → KPI funnel sai → manager báo cáo sai stake-holder.
5. **11 direct profile.status = '...'** chưa refactored → status_history audit lệch → compliance fail.
6. **Magic link CCCD bruteforce qua tx rollback** → attempt_count reset → token compromise.
7. **Outbox worker dispatch fail giữa Step 2-3** → claim không release → 12 events không fanout cho hàng nghìn thí sinh.
8. **Phase 2 #02b NOT NULL + unique swap** prod đã có duplicate `(academic_info_id, method_id)` → migration FAIL → manual cleanup required mid-deploy.
9. **FE Zod strict state mới chưa enum** → response parse fail → mass user crash giờ cao điểm.
10. **Phase 1 #15 lead_id UNIQUE drop bundle PR fail giữa chừng** → DB allow multi-profile/lead nhưng code SQLAlchemy `uselist=False` → relationship.append() crash → Lead detail page crash.

---

## Phần 8 — Plan v2.13 Patches Proposed

Dựa trên 10 chốt 2026-05-01 + 7 P0 còn open, đề xuất patches áp dụng vào `ADMISSION_REFACTOR_PLAN.md` v2.12 → v2.13:

| Patch | Plan section | Action | Source |
|---|---|---|---|
| **PATCH-01** | Phần 3.3.b T17 spec | Đổi T17 từ enrolled: từ "cascade SOFT DELETE Student" → "REJECT với guidance dùng T16 admin-withdraw trước". Bỏ pseudo-code Student.deleted_at. | Q1 |
| **PATCH-02** | Phần 2.1.a Rule 1 | Wording explicit: "grace_period_hours = 0 cho mùa 2026, defer Phase 4+". Bỏ optional grace period field. | Q2 |
| **PATCH-03** | Phần 3.3.g.1 | Thêm wording: "1 profile/academic_year per lead. Multi-round per profile defer Phase 4+". Composite UNIQUE `(lead_id, academic_year)` đã có ở Phase 1 #15. | Q3 |
| **PATCH-04** | Phần 7.1 timeline | Wave A 2026-07-23 hard commit; Wave B 2026-08-13 best-effort + slip-able. Document trade-off với product team. | Q4 |
| **PATCH-05** | Phần 4 Phase 4 | Đổi "Q4/2026" → "Q1/2027". Bỏ wording "After 1-2 months observation". | Q5 |
| **PATCH-06** | Phần 2.1 + Phase 2 #01 | `OfferingAdmissionRound` thêm field `admit_quota INT NULL` nullable + service guard T7 check `count(admitted) < admit_quota`. | Q6 |
| **PATCH-07** | Phần 3.3.d | Cột "Bypass consent" đổi từ "Yes (all channels)" → "in-app + email only; Zalo/SMS gated by `zalo_template_approved` legal flag". `dispatch_event()` route thêm consent check Zalo/SMS. | Q7 |
| **PATCH-08** | Phần 4 Phase 3 deliverable #6 | i18n đổi "25 keys system mới" → "25 keys inline 3 file existing với lint rule sync". Effort -1 sprint. | Q8 |
| **PATCH-09** | Phần 7.1 timeline | Defer list bổ sung: Phase 1 #04 (extra thresholds min_conduct/min_health), #07 (demographics area_code/priority_object_codes), #09 admin UI (conduct/health). Move sang Phase 4 Q1/2027. | Q9 |
| **PATCH-10** | Phần 3.3.b RBAC | Thêm note: "IDOR scope KHÔNG đổi cho 4 new state — reuse `get_admission_for_user()` (`deps.py:2241`) + `get_admission_for_manager()` (`deps.py:2161`). System internal transitions KHÔNG endpoint." | Q10 |
| **PATCH-11** | Phần 3.3.f dispatch_event() | Update sample dùng `safe_dispatch(... strict=True, ...)` per memory `dispatch-bundle-strict-required`. | P1-06 |
| **PATCH-12** | Phần 3.3.g token | Thêm spec: `attempt_count++` SEPARATE short tx (commit ngay trước main tx). Hoặc savepoint pattern. | P1-08 |
| **PATCH-13** | Phần 4 Phase 1 #19 | Tách thành 4 migration con (19a/19b/19c/19d). | P1-05 |
| **PATCH-14** | Phần 4 Phase 1 thêm migration | `phase1_XX_create_system_config_table.py` + admin endpoint UPDATE + seed `current_intake_year=2026`. Bundle với #15 PR. | B4 |
| **PATCH-15** | Phần 4 Phase 1 #15 | Tách thành 3 PR sequence (15a/15b/15c) với soak windows giữa. Document cascade="delete-orphan" + uselist=True conflict. | B8 + P0-08 |
| **PATCH-16** | Phần 4 Phase 1 thêm code task | "Code task B1 — Casbin auth_model.conf rewrite + deny effect + matcher update + 4 role × 14 action matrix test. GATE BEFORE phase1_11." | B1 + P0-01 |
| **PATCH-17** | Phần 4 Phase 1 thêm code task | "Code task B2 — EventDefinition extend (`requires_outbox`, `bypass_consent_check`) + 12 SystemEvents enum + EVENT_CATALOG seed module-level. GATE BEFORE phase1_19." | B2 + P0-02 |
| **PATCH-18** | Phần 8 cheat sheet | Re-count migration: Phase 0 = 2, Phase 1 = 18 (thêm 19a/19b/19c/19d/system_config; bỏ #04/#07/#09 admin UI defer per Q9), Phase 2 = 5, **Phase 3 = 1** (chỉ phase3_01; phase3_02 + phase3_03 SUPERSEDED → moved Phase 1 #19a-d). Tổng 26 migration + 6 code task. | P3-02 |
| **PATCH-19** | Phần 4 Phase 1 + Phase 2 | Chuẩn hóa naming `admission_path_id` (verified DB schema) toàn plan. | P3-03 |
| **PATCH-20** | Phần 4 Phase 1 thêm 2 migration | `phase1_XX_create_archived_admission_profile_table.py` + `phase1_XX_create_archived_outbox_table.py` (phụ thuộc của Phần 7.5 + outbox archive). | P3-04 |

---

## Phần 9 — Action Plan Sequence (gate ordering post-decision)

```
W1-W2 (2026-04-30 → 2026-05-14) — PHASE 0 + P0 PRE-WORK
  ├── Phase 0 (existing scope): selected_subject_group_id + applied_rules whitelist
  ├── Phase 0c: admission_config_repository field-name hot-fix
  ├── Code task B1: Casbin auth_model deny effect rewrite + 4 role test matrix
  ├── Code task B2: EventDefinition extend + 12 SystemEvents + EVENT_CATALOG seed
  └── Test debt sweep: PR test-debt/admission-workflow-e2e-fixture-fix

W3-W6 (2026-05-14 → 2026-06-11) — PHASE 1 (REVISED)
  ├── #01: degree_level_fk
  ├── #02: bonus_rule
  ├── #03: applicable_to + method_quota + admission_round_id (BE+FE Zod sync wave atomic)
  ├── #05: subject_kind + subject ảo seed
  ├── #06: doc_group path_id + 3-tier resolution
  ├── #08: uses_choice_engine flag (DEFER #07 demographics per Q9)
  ├── #07b: backfill_exceptions table
  ├── #10: status_history table + backfill scattered scalar (5 block)
  ├── PR Phase 1 #15a: DROP lead_id UNIQUE → ADD composite (lead_id, academic_year), giữ uselist=False
  ├── PR system_config table + admin endpoint
  ├── Code task #15: 23 file caller + is_admitted_like() helper
  ├── Code task #16: 11 direct profile.status assignment refactor + lint rule
  ├── #11: ALTER CHECK constraint (BE+FE Zod 14 state strict atomic deploy)
  ├── #12: backfill selected_subject_group_id
  ├── PR Phase 1 #15b: model uselist=True + repository 2 method mới + schema dual
  ├── #18: confirmation_token action_type
  ├── #19a: outbox table
  ├── #19b: 12 EVENT_CATALOG DB seed
  ├── #19c: Celery beat archive task
  └── #19d: notification_rule seed
  (DEFER per Q9: #04 extra thresholds, #09b lock trigger to Q1/2027)

W7-W10 (2026-06-11 → 2026-07-09) — PHASE 2
  ├── #01: offering_admission_round + admit_quota field per Q6
  ├── #02: admission_path admission_round_id Step 1-3 (nullable + backfill + shim)
  ├── Code task #17: public_admissions_service migrate
  ├── #02b: NOT NULL + unique swap (one-way; manual rollback _archive_admission_path_dup ready)
  ├── #03: path_subject_group_config + item
  ├── #04: widen score precision
  └── Engine test suite ≥30 case PASS

W11-W12 (2026-07-09 → 2026-07-23) — PHASE 3 WAVE A (single-NV)
  ├── #01: admission_profile_choice + profile_choice_score (chỉ migration active còn lại của Phase 3)
  ├── ~~#02: 12 milestone events catalog + rule + template seed~~ → **already completed in Phase 1 #19a-d** (SUPERSEDED 2026-05-01: phase3_02 moved Phase 1, KHÔNG còn task ở Phase 3)
  ├── PR Phase 1 #15c: FE migrate component plural list (cộng Phase 3 Wave A FE deliverables)
  ├── FE deliverables Wave A: 5 component mới + i18n inline 25 keys
  └── Hard deadline 2026-07-23: Wave A single-NV mở mùa 2026 ✓

W13-W17 (2026-07-23 → 2026-08-27) — PHASE 3 WAVE B (multi-NV; SLIP-ABLE per Q4)
  ├── Multi-NV UI mở
  ├── available_actions typed structure
  ├── Bulk transition endpoint
  ├── Add NV retroactive Wave B rule
  └── Best-effort 2026-08-13; slip OK

Q1/2027 — PHASE 4 (defer per Q5)
  ├── Drop AdmissionPath.academic_info_id
  ├── Deprecate CriteriaSubjectGroup
  ├── Drop Lead.gpa
  ├── Phase 1 #04 extra thresholds + #09 admin UI (deferred per Q9)
  └── i18n next-intl migration (deferred per Q8)
```

---

## Phần 10 — Sign-off Required

**Engineering Owner:** ____________ (cần sign-off plan v2.13 patches before Phase 0 PR start)
**Product Owner:** ____________ (cần sign-off Q1-Q10 decisions)
**DBA:** ____________ (cần sign-off DB role + manual rollback playbook)
**Legal/Compliance:** ____________ (cần sign-off Q7 bypass consent + Zalo/SMS template approval)
**Frontend Lead:** ____________ (cần sign-off Q4 Wave A/B + Q8 i18n inline)

**Pre-Phase 0 deploy gates:**
- [ ] 10 product decisions (Q1-Q10) approved + documented in this file ✓
- [ ] 7 P0 blocker (B1/B2/B4/B5/B6/B8) closed
- [ ] Plan v2.13 patches (PATCH-01 through PATCH-20) merged into ADMISSION_REFACTOR_PLAN.md
- [ ] DB snapshot pre-Phase-0 taken + verified offsite

---

## Phần 11 — Round 20 Verification Results (2026-05-01)

Sau khi v2.13 ship + 20 patches áp, tiếp tục có round 20 review verify codebase. **Verdict: NO GO Phase 1**, conditional GO Phase 0/pre-work. Các finding mới + correction:

### 11.1. Findings xác nhận VERIFIED (9/10 claim)

| Finding | Evidence (file:line) | Status |
|---|---|---|
| **B3 / P0-03 signature mismatch** — `safe_dispatch` KHÔNG có `strict` param | `notification_dispatcher.py:1853-1860` chỉ có `db, event, payload, dedupe_key, skip_preference_check, rooms`. PATCH-11 v2.13 SAI khi viết `safe_dispatch(... strict=True)`. | **VERIFIED** — fixed v2.13.1 (đổi sang `dispatch(...)` có strict + worker tự commit) |
| **B4 / P0-04 update count 9 → 11** — bulk approve/reject sót | `admission_service.py:7994` (bulk_approve), `:8214` (bulk_reject) cũng direct assign profile.status. | **VERIFIED** — fixed v2.13.1 plan changelog + Risk Review P0-05 |
| **B5 / P0-06 lead sync return False** — không phải fallback `sts13` | `lead_admission_sync.py:115-121`: `if not target_status_id: log.warning(...) return False`. | **VERIFIED** — Risk Review P0-06 wording cần fix (P3-01) |
| **P1-04 storefront** — 3 site, không 1 | `admission_path_repository.py:119-143`, `admission_service.py:2571`, `public_admissions_service.py:137-150,529-534`. | **VERIFIED** — Plan task #17 scope cập nhật |
| **P1-05 token + FE** — FE confirm endpoint vẫn legacy | `frontend/src/lib/zod/admissions.ts:1098-1137` dùng `/api/admissions/confirm/{token}` (legacy), không `/api/v2/public/admissions/{token}/confirm`. | **VERIFIED** — Plan Phase 1 #18 phải bundle FE migration |
| **P1-06 FE available_actions** — vẫn `string[]` | `admissions.ts:550`: `available_actions: z.array(z.string()).default([])`. v2.10 fix #5 spec typed `[{action, target, endpoint}]` chưa apply. | **VERIFIED** — Plan FE deliverables thêm migration row |
| **P1-08 FE filter tabs** — hard-code 7 status | `AdmissionsClient.tsx:156-164` `STATUS_TABS` const list `[draft, submitted/resubmitted, approved/overridden, confirmed, enrolled, rejected]`. | **VERIFIED** — Plan task #15 thêm AdmissionsClient.tsx |
| **P1-10 plan stale sample** — `event_code`/`idempotency_key` thay vì `event`/`dedupe_key` | Plan line 1592-1600, 2152-2163, 2401-2403 có 3 sample stale. | **VERIFIED** — fixed v2.13.1 cả 3 sample |
| **P2-01/02/03 cross-module** — sync_lead_profile + survey + fee_calc miss new states | `lead_profile_sync.py:93-105` lock/editable sets; `admission_tasks.py:112` survey filter `"approved"`; `fee_calculation_service.py:805` reads `applied_rules["academic_info_id"]`. | **VERIFIED** — Plan task #15 list cập nhật 23 file → ~26 file |

### 11.2. False positive (1/10)

- **P3-01 wording fallback** — Risk Review viết "fallback `sts13`" theo plan companion, nhưng code thật trả `False`. Đây là drift trong RISK_REVIEW.md, không phải drift codebase. Fix wording trong file này (P3-01 đã track).

### 11.3. v2.13.1 hot-fix applied (in-place, no version bump)

| Hot-fix | Plan line | Action |
|---|---|---|
| HF-1 | 2235-2251 | Worker dispatch dùng `dispatch(... strict=True)` không `safe_dispatch(... strict=True)` (signature mismatch). Worker tự commit explicit. |
| HF-2 | 1592-1600 | Sample `transition()` body align signature: `event=event_def.code` (enum) + `dedupe_key=` (không `idempotency_key`). |
| HF-3 | 2152-2163 | Sample Phần 3.3.e align tương tự + comment giải thích outbox column `idempotency_key` (DB) khác arg name `dedupe_key` (API). |
| HF-4 | 2392-2403 | Sample Phần 3.3.f service caller pattern align signature + `event_def.code.value` cho serialization. |
| HF-5 | Changelog v2.13 entry B5 | Update count 9 → 11 + list 7994 + 8214 (bulk approve/reject sót). |
| HF-6 | Schema verified section | Update count 9 → 11 với line numbers chính xác. |

### 11.4. Updated Blocker Status (post round 20)

| ID | Status | Detail |
|---|---|---|
| B1 | OPEN | Casbin auth_model deny effect chưa rewrite |
| B2 | OPEN | EventDefinition extend chưa ship |
| B3 | OPEN | Signature mismatch confirmed → plan fixed, code wrapper chưa ship |
| B4 | OPEN | 11 sites direct status confirmed; task #16 scope cập nhật |
| B5 | OPEN | 4 new state mapping chưa add; fallback `False` confirmed (không `sts13`) |
| B6 | ~~CLOSED~~ → **REOPEN** | Round 20 phát hiện thêm 3 site `lead_service.py` (1405, 1827, 2792) cần plural API; PR #15 split chưa đủ — phải bundle FE filter component (P1-06/P1-08) |
| B7 | OPEN | system_config table chưa ship |
| B8 | OPEN | Quota wording vẫn stale ở Phần 5.b "phân biệt 2 loại quota" — admit_quota chỉ ship Phần 2.1 + cheat sheet, body sample backfill SQL chưa cập nhật |

### 11.5. Top 10 Failure Modes — Updated

Cộng vào danh sách:
11. **dispatch_event() wrapper TypeError** vì worker code dùng sai API (`safe_dispatch(strict)` thay vì `dispatch(strict)`) → outbox queue đầy không drain → mass notification loss.
12. **Plan sample dev copy-paste** (`event_code`/`idempotency_key`) → service body raise `TypeError: dispatch() got unexpected keyword argument 'event_code'` runtime.

### 11.6. Recommended Mode Change — Task-based execution

Plan đã có 13 version (v1.0 → v2.13.1) trong 1 ngày. Tiếp tục patch v2.14/v2.15 = **plan rotting anti-pattern** (memory `feedback_audit_report_accuracy`). Đề xuất:

1. **FREEZE plan v2.13.1** — chỉ accept hot-fix nếu finding chứng minh code-verified drift (như round 20).
2. **Open 8 GitHub issue** cho 8 P0 blocker, mỗi issue:
   - Title: `[P0-XX] <module> — <summary>`
   - Body: link section trong PLAN.md + RISK_REVIEW.md
   - File:line evidence
   - Acceptance criteria + test
   - Linked PR
3. **Daily standup tracker**: status trong `Phần 2 Blocker List` của file này. Mỗi P0 close → mark CLOSED với commit hash + PR link.
4. **Khi 8 P0 close + Phase 0 deploy thành công** → bump plan v2.14 với "GA-ready" status; archive RISK_REVIEW.md sang `Documents/archive/`.
5. **KHÔNG patch plan thêm** cho đến milestone 4. Round review tiếp theo (round 21+) chỉ ship qua RISK_REVIEW.md update Phần 11+.

**Recommended first PR sequence (W1-W2 2026-04-30 → 2026-05-14):**

| PR # | Title | P0 | Effort | Owner |
|---|---|---|---|---|
| 1 | `chore(rbac): rewrite Casbin auth_model.conf with deny-first effect` | B1 | 2-3 days | Senior BE |
| 2 | `feat(notification): extend EventDefinition + add 12 ADMISSION_* SystemEvents enum` | B2 | 1 day | BE |
| 3 | `chore(notification): align dispatch_event wrapper signature (event/dedupe_key)` | B3 | 0.5 day | BE (small) |
| 4 | `chore(workflow): refactor 11 direct profile.status assignments to state_service.transition()` | B4 | 3-4 days | Senior BE |
| 5 | `feat(lead): add 4 new state mappings to ADMISSION_TO_LEAD_STATUS_MAP + remove silent False fallback` | B5 | 0.5 day | BE |
| 6 | `feat(config): add system_config table + admin endpoint + seed current_intake_year` | B7 | 1 day | BE |
| 7 | `chore(quota): normalize submission_count + admit_quota in plan body + executable migration test` | B8 | 1 day | BE + tech writer |
| 8 | `refactor(lead): tách 3 PR sequence cho lead one-to-many (15a/15b/15c)` | B6 | 5-6 days (tách PR) | Senior BE |

**Tổng effort PR 1-8: 14-18 days.** Phase 0 P1 fix (3 score/submit bug) song song. Hard deadline 2026-05-14 cho Phase 1 unblock.

---

**Review file location:** `Documents/ADMISSION_REFACTOR_RISK_REVIEW.md`
**Plan reference:** `Documents/ADMISSION_REFACTOR_PLAN.md` v2.13.1 (post round 20 hot-fix, FROZEN)
**Memory reference:** `admission-refactor-2026` (project memory snapshot)
**Last updated:** 2026-05-01 (round 20 verification + v2.13.1 hot-fix + mode change recommendation)
