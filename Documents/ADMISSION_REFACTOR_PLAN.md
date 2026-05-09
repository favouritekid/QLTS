# Admission Module Refactor Plan

> 📌 **Source of truth duy nhất cho spec nghiệp vụ Admission** (cleanup 2026-05-01)
>
> **Phạm vi document này:** schema, migration, business rules, transition matrix T1-T17, scoring engine, RBAC/IDOR contract, notification + outbox, FE contract, multi-NV, multi-round, audit history.
>
> **Companion documents:**
> - `Documents/ADMISSION_REFACTOR_RISK_REVIEW.md` — evidence / risk log + 10 product decisions Q1-Q10 + 7 P0 blocker tracker.
> - `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md` — operations runbook cho cold cutover production (KHÔNG copy spec).
> - `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` — daily progress tracker (task status, owner, branch/PR, test result, blocker). KHÔNG copy spec, chỉ tiến độ code.
>
> **Event/pipeline projection source of truth = code, KHÔNG documentation:**
> - `Backend_FastAPI/app/core/admission_event_mapping.py` — `ADMISSION_TO_LEAD_STATUS_MAP` + `ADMISSION_EVENT_PROJECTIONS` dict.
> - `Backend_FastAPI/app/services/lead_admission_sync.py` — projection logic + sync function.
> - `Backend_FastAPI/scripts/data/consultation_status_v3.csv` — lead consultation_status seed data.
> - `Backend_FastAPI/scripts/data/allowed_transitions_v3.csv` — allowed transitions seed data.
> - `Documents/archive/ADMISSION_MATRIX_MAPPING.md` — historical only (last updated 2026-01-15, stale vs code), DO NOT implement from this file.
>
> **KHÔNG tạo full refactor plan thứ hai.** Mọi đề xuất scope mở rộng → patch vào file này (bump version), KHÔNG tạo file song song.
>
> **Strategy deployment:** cold cutover trên production clone (xem RUNBOOK). KHÔNG staged rollout. KHÔNG MVP rút scope (decision reverted 2026-05-01).

---

**Phiên bản:** 2.13.1 (production-safe; 10 decisions + 20 patches v2.13 + 6 hot-fix round 20 verify; full v2.13 scope ACTIVE — deployment qua cold cutover per ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md)
**Ngày chốt baseline:** 2026-04-30
**Phạm vi:** Mở rộng module tuyển sinh QLTS để hỗ trợ engine xét tuyển đầy đủ — multi-đợt, multi-phương thức, multi-tổ hợp, multi-nguyện vọng, đa loại điểm, ưu tiên KV/đối tượng.

**Companion document:** `Documents/ADMISSION_REFACTOR_RISK_REVIEW.md` — Risk Review round 19 (2026-05-01) với 7 P0 blocker open + 14 P1 + 11 P2 + 5 P3 + cross-module impact map + manual rollback playbook + E2E checklist + top 10 failure modes. Đọc trước khi start Phase 0 PR.

**Nguyên tắc xuyên suốt:**
1. **Dual-write, additive trước — breaking sau**. **Rollback-safe cho additive phases (Phase 0, 1 phần lớn);** destructive/constraint-swap migrations (Phase 1 #11 status CHECK extend, Phase 2 #2 unique swap) có **manual rollback playbook** trong Phần 7.5 — KHÔNG auto-revert.
2. **Không tạo entity song song** với entity đã có (giữ `AdmissionProfile`, không tạo `Application`).
3. **Không sửa cấu trúc** `SubjectGroup` + `SubjectGroupSubject` (giữ nguyên field hiện có). `Subject` mở rộng **additive** (thêm field nullable `subject_kind/max_score/min_possible_score`, KHÔNG đổi field hiện có).
4. **Override ở edge entity** (path-level), không ở catalog.
5. **Field name align với DB thực tế**, alias ở serializer/API nếu cần đổi semantic.
6. **Idempotent backfill** + **transition guard centralized** + **notification AFTER COMMIT**.

## Changelog

### v2.13.2 — 2026-05-05 (solo cold cutover SOP — formal soak waiver)

**1 amendment**: Phần 4 Phase 1 cheat sheet line 3473-3478 ~~Soak 1 tuần~~ between sub-PRs `phase1_15a` / `15b` / `15c` is formally **WAIVED** for the solo cold cutover deploy model documented in memory `solo-cutover-simple-data-import` (saved 2026-05-05 pivot).

**Rationale**: the original 1-week soak windows assume a team gradual-rollout deploy pattern with concurrent production traffic to monitor for query-pattern regressions, edge-case telemetry, and alert noise. The QLTS deploy model is a single-maintenance-window cold cutover (frozen prod → drop database → restore from snapshot → run alembic upgrade → resume traffic). During the cutover window:

- 0 concurrent production traffic between sub-PRs.
- 0 production telemetry to monitor.
- Soak windows yield empty signal.

→ Honoring soak = ceremonial 14-day delay with 0 functional benefit.

**Substitute evidence required** (replaces soak gate):

| Gate | Evidence |
|---|---|
| Multi-year regression coverage | unit test `test_create_profile_allows_same_lead_different_year` (or equivalent year-aware contract) |
| Same-year duplicate enforcement | unit test `test_create_profile_blocks_same_year_duplicate` |
| Live alembic + DB INSERT verify | dev DB rehearsal post prod-data import per memory `solo-cutover-simple-data-import` |
| FE smoke (dual-read pattern) | `LeadDetailPanel` render with multi-year profiles |
| FE wrapper checks | `scripts/fe-check.sh type-check` + `test` PASS |
| Tracker / issue / memory sync | M-1-15-model + M-1-15-fe TESTED + Wave 4 closure banner |

**Affected sub-PRs**:

- `phase1_15a` (Wave 3-E PR #223 squash `15f52c8e`): shipped without soak — substitute evidence verified by Wave 3-E live alembic roundtrip.
- Wave 4 `#15b` (PR #224 squash `966d5f5f`) + hotfix (PR #226 squash `e5b0a411`): shipped without soak — multi-year regression test added in hotfix.
- Wave 4 `#15c` (PR #225 OPEN): ships without soak — FE dual-read pattern preserves backward compat regardless of deploy ordering.

**Process precedent**: this waiver applies to all solo cold cutover sub-PR sequences in `feat/admission-full-cutover` and any future branches operating under the same deploy model. Future team-mode rollouts MUST re-evaluate the substitute-evidence gate.

### v2.13 — 2026-05-01 (production-safe lock, 10 product decisions + 20 patches áp risk review round 19)

**Companion:** `Documents/ADMISSION_REFACTOR_RISK_REVIEW.md` (Phần 0 decision log + Phần 8 patches detail).

**10 product decisions chốt 2026-05-01:**
1. **Q1 — T17 từ enrolled: strict reject** (dùng T16 trước; KHÔNG soft-delete Student trong mùa 2026). PATCH-01 áp Phần 3.3.b.
2. **Q2 — Late submit: strict cutoff `end_date`**, `grace_period_hours = 0`. PATCH-02 áp Phần 2.1.a Rule 1.
3. **Q3 — DOT_1 + DOT_2 cùng năm: BLOCK** cho 2026 — 1 profile/academic_year per lead. Composite UNIQUE `(lead_id, academic_year)` đã có ở Phase 1 #15 enforce naturally. Multi-round per profile defer Phase 4+. PATCH-03 áp Phần 3.3.g.1.
4. **Q4 — Wave A single-NV** 2026-07-23 hard commit; **Wave B 2026-08-13 best-effort + slip-able**. Buffer thực tế cho engineering. PATCH-04 áp Phần 7.1.
5. **Q5 — Phase 4: Q1/2027** (KHÔNG drop destructive Q4/2026 khi mùa còn nóng). PATCH-05 áp Phần 4 Phase 4.
6. **Q6 — Quota tách rõ: `submission_count` (đăng ký) + `admit_quota` (trúng tuyển) nullable**. Engine T7 (`result_published → admitted`) check `count(admitted) < admit_quota`. PATCH-06 áp Phần 2.1 + Phase 2 #01.
7. **Q7 — Bypass consent CHỈ in-app + email** khi có legal basis. **Zalo/SMS gated bằng `zalo_template_approved` legal flag (False mặc định)**. PATCH-07 áp Phần 3.3.d.
8. **Q8 — i18n inline 3 file existing** (`admissions.ts`, `status-badge.config.ts`, `StatusBadge.tsx`) cho 2026; next-intl defer Q1/2027. Effort -1 sprint. PATCH-08 áp Phần 4 Phase 3 deliverable #6.
9. **Q9 — Buffer 0: drop scope, KHÔNG tăng người**. Defer Phase 1 #04 (extra thresholds), #07 (demographics), #09 admin UI sang Q1/2027. PATCH-09 áp Phần 7.1.
10. **Q10 — Officer scope giữ nguyên** assigned + unit cho mọi state mới. Manager unit, admin all, system internal only. PATCH-10 áp Phần 3.3.b RBAC matrix.

**7 P0 blocker still open** (phải đóng trước Phase 1 chain start, xem risk review Phần 2):
- **B1** — Casbin `auth_model.conf` không support deny effect (verified `auth_model.conf:1-14` chỉ có `e = some(where (p.eft == allow))`). PATCH-16 thêm code task GATE BEFORE phase1_11.
- **B2** — `EventDefinition` thiếu `requires_outbox`/`bypass_consent_check` field (verified `app/core/event_catalog.py:53-86`); 12 SystemEvents enum `ADMISSION_*` chưa có (verified `app/core/events.py`). PATCH-17 thêm code task GATE BEFORE phase1_19.
- ~~B3~~ — **CLOSED** via Q1 chốt T17 strict reject (Student schema unchanged).
- **B4** — `system_config` table + `current_intake_year` không tồn tại (verified `app/models/config.py`). PATCH-14 thêm `phase1_XX_create_system_config_table.py` migration.
- **B5** — **11 direct** `profile.status = '...'` (round 20 re-verify, không phải 9 như v2.13 viết ban đầu) ở `admission_service.py:3918, 5014, 5317, 5517, 5708, 6085, 6284, 6862, 7786, 7994, 8214` chưa refactor sang `state_service.transition()`. Line 7994 + 8214 là **bulk approve/reject** path (sót trong audit ban đầu). Lint rule custom AST check phải active. Task #16 PR scope cập nhật cover 11 sites.
- **B6** — `ADMISSION_TO_LEAD_STATUS_MAP` (`lead_admission_sync.py:41-53`) thiếu 4 new state mapping; fallback `sts13` (line 57-59) silent break. Task #15 PR scope.
- ~~B7~~ — **CLOSED** via Q4+Q9 chốt (Wave B slip-able + drop scope).
- **B8** — PR Phase 1 #15 lead one-to-many bundle scope quá lớn. PATCH-15 tách 3 PR sequence (15a/15b/15c) với soak windows giữa.

**20 patches list (chi tiết tại risk review Phần 8):**

| # | Plan section | Action | Source decision |
|---|---|---|---|
| PATCH-01 | Phần 3.3.b T17 spec | T17 từ enrolled REJECT (KHÔNG cascade Student); raise `BusinessRuleViolation` với guidance T16 trước. Bỏ pseudo-code Student.deleted_at. | Q1 |
| PATCH-02 | Phần 2.1.a Rule 1 | grace_period_hours = 0 cho mùa 2026; defer Phase 4+. Bỏ optional grace period field. | Q2 |
| PATCH-03 | Phần 3.3.g.1 | "1 profile/academic_year per lead. Multi-round per profile defer Phase 4+". | Q3 |
| PATCH-04 | Phần 7.1 timeline | Wave A 2026-07-23 hard commit; Wave B 2026-08-13 best-effort + slip-able. | Q4 |
| PATCH-05 | Phần 4 Phase 4 | "Q4/2026" → "Q1/2027". Bỏ "After 1-2 months observation". | Q5 |
| PATCH-06 | Phần 2.1 + Phase 2 #01 | `OfferingAdmissionRound` thêm `admit_quota INT NULL` + service guard T7. | Q6 |
| PATCH-07 | Phần 3.3.d + 3.3.f | Bypass consent column đổi "Yes (all channels)" → "in-app + email only; Zalo/SMS gated by `zalo_template_approved` legal flag". `dispatch_event()` route thêm consent check Zalo/SMS riêng. | Q7 |
| PATCH-08 | Phần 4 Phase 3 deliverable #6 | i18n "25 keys system mới" → "25 keys inline 3 file existing với lint rule sync". Effort -1 sprint. | Q8 |
| PATCH-09 | Phần 7.1 timeline | Defer list Phase 1 #04 + #07 + #09 admin UI sang Q1/2027. | Q9 |
| PATCH-10 | Phần 3.3.b RBAC | "IDOR scope KHÔNG đổi cho 4 new state — reuse `get_admission_for_user()` + `get_admission_for_manager()`". | Q10 |
| PATCH-11 | Phần 3.3.f dispatch_event | Worker `safe_dispatch(... strict=True, ...)` per memory `dispatch-bundle-strict-required`. | P1-06 |
| PATCH-12 | Phần 3.3.g token | `attempt_count++` SEPARATE short tx (commit ngay trước main tx) hoặc savepoint pattern, chống bruteforce reset qua tx rollback. | P1-08 |
| PATCH-13 | Phần 4 Phase 1 #19 | Tách thành 4 migration con (19a outbox table / 19b catalog seed / 19c beat task / 19d notification_rule seed). | P1-05 |
| PATCH-14 | Phần 4 Phase 1 thêm migration | `phase1_XX_create_system_config_table.py` + admin endpoint UPDATE + seed `current_intake_year=2026`. | B4 |
| PATCH-15 | Phần 4 Phase 1 #15 | Tách 3 PR sequence (15a DROP unique giữ uselist=False / 15b model uselist=True + repo / 15c FE migrate) với soak windows. | B8 + P0-08 |
| PATCH-16 | Phần 4 Phase 1 thêm code task | Code task **B1** — Casbin auth_model.conf rewrite + deny effect + matcher update + 4 role × 14 action matrix test. **GATE BEFORE phase1_11**. | B1 |
| PATCH-17 | Phần 4 Phase 1 thêm code task | Code task **B2** — EventDefinition extend + 12 SystemEvents enum + EVENT_CATALOG seed module-level. **GATE BEFORE phase1_19**. | B2 |
| PATCH-18 | Phần 8 cheat sheet | Re-count migration: Phase 0 = 2, Phase 1 = 18 (thêm 19a/19b/19c/19d/system_config; bỏ #04/#07/#09 admin UI defer per Q9), Phase 2 = 5, **Phase 3 = 1** (chỉ còn `phase3_01_create_admission_profile_choice_and_score`; phase3_02 + phase3_03 đã SUPERSEDED → moved Phase 1 #19a-d). Tổng 26 migration + 6 code task. | P3-02 |
| PATCH-19 | Phần 4 Phase 1 + Phase 2 | Chuẩn hóa naming `admission_path_id` (verified DB schema) toàn plan. | P3-03 |
| PATCH-20 | Phần 4 Phase 1 thêm 2 migration | `phase1_XX_create_archived_admission_profile_table.py` + `phase1_XX_create_archived_outbox_table.py`. | P3-04 |

**Schema verified 2026-05-01 (tham chiếu trước mọi PR):**
- `AdmissionProfile.status` 10 enum giá trị legacy hiện có (verified `app/models/admission.py:47-50`).
- `confirmed_via` CHECK 3 giá trị: `magic_link/admin_override/officer` (line 51-54).
- `admission_path.criteria_id` (NOT `admission_criteria_id`); 2 site repository drift đã track Phase 0c hot-fix.
- 9 audit scalar fields scattered hiện có trên `AdmissionProfile`: approved_at/by_id, rejected_at/by_id, revision_requested_at/by_id, resubmitted_at/by_id, overridden_at/by_id, dropped_at/by_id, confirmed_at/by_id/via.
- `AdmissionProfileChoice` + `ProfileChoiceScore` + `AdmissionProfileStatusHistory` **CHƯA TỒN TẠI** (Phase 1+3 ship).
- `notification_outbox` table **CHƯA TỒN TẠI** (Phase 1 #19a ship).
- `system_config` table **CHƯA TỒN TẠI** (PATCH-14 ship).
- `Student` model **KHÔNG CÓ** `deleted_at/deleted_reason/deleted_by_user_id` (verified `app/models/student.py:26-199`); Q1 chốt strict reject T17 → KHÔNG cần thêm.
- Casbin `auth_model.conf` matcher dùng `keyMatch4` + `e = some(where (p.eft == allow))` — KHÔNG support deny.
- **11** direct `profile.status = '...'` site verified line numbers ở `admission_service.py` (round 20 re-grep): 3918, 5014, 5317, 5517, 5708, 6085, 6284, 6862, 7786, 7994 (bulk approve), 8214 (bulk reject).

### v2.12 — 2026-05-01 (round 19 review, 8 P1 — 2 security + 2 integrity + 4 implementation)
- **P1 fix #1 — T17 rollback cascade Student record**: T17 wildcard cho phép admin rollback profile từ enrolled → 'draft' nhưng KHÔNG cascade Student record (memory `confirmed-state-wave-closed` ghi T13 enrollment tạo Student row). Profile draft + Student tồn tại = orphan row. Sửa Phần 3.3.b: T17 từ enrolled → BẮT BUỘC reason + cascade SOFT DELETE Student (`deleted_at = NOW()`, `deleted_reason = 'admission_rollback_T17'`); status_history metadata thêm `student_id_cascaded`. Hoặc reject T17 từ enrolled với gợi ý "dùng T16 admin-withdraw trước".
- **P1 fix #2 — Public submit/resubmit/withdraw thiếu CCCD verification (security)**: existing confirm flow có CCCD verify (memory `adm-023-028-magic-link`), 3 action mới (submit/resubmit/withdraw) KHÔNG có. URL token leak qua email forward → người khác submit thay candidate. Lệch security model. Sửa Phần 3.3.g: extend tất cả 4 action với CCCD verification — token landing endpoint trả form yêu cầu nhập 4 chữ cuối CCCD; backend validate `lead.citizen_id[-4:] == request.cccd_last_4` trước atomic UPDATE...RETURNING; `attempt_count` + lockout reuse logic existing confirm flow.
- **P1 fix #3 — Celery worker `EVENT_CATALOG` init strategy chốt module-level**: memory `celery-worker-init-gap`: worker không run FastAPI startup. Plan v2.9 fix #8 reference catalog ở `app/core/event_catalog.py` nhưng KHÔNG verify init strategy. Chốt strategy (a) module-level Python dict — catalog hardcode trong code, migration `phase1_19` seed CHỈ DB rows (`notification_rule` + `notification_template` tables) cho admin UI. Worker import module → catalog ready. KHÔNG dùng DB-backed lazy lookup (tránh worker lazy-init pattern phức tạp như PR #101).
- **P1 fix #4 — Admin reduce `round_quota` mid-mùa cần warning + audit**: atomic UPDATE pattern v2.11 fix #5 silent reject submit mới khi `submission_count > new_quota`. Sửa: admin endpoint update quota validate trước:
  ```python
  if payload.new_quota < round.submission_count:
      if not payload.override:
          return {"status": "warning",
                  "message": f"Quota mới ({payload.new_quota}) thấp hơn submission_count ({round.submission_count}). Override=true để confirm.",
                  "current_submission_count": round.submission_count, "delta": payload.new_quota - round.submission_count}
      # Override → audit log mandatory
      audit_log("quota_reduced_with_oversubscribed", reason=payload.reason)
  ```
  Cron job alert hàng ngày nếu round có `submission_count > round_quota` (oversubscribed state).
- **P1 fix #5 — Wave B retroactive add NV timing rule**: profile tạo Wave A có 1 choice → Wave B deploy hiển thị "Add NV" button. Plan KHÔNG spec timing rule → candidate có thể add NV2 cho profile đã submitted/reviewing → break "applied_rules immutable after submit". Sửa Phần 4 Phase 3 Wave B: add NV retroactive cho phép CHỈ KHI:
  - `profile.status IN ('draft', 'revision_requested')` AND
  - `round.end_date >= NOW()` (round chưa hết hạn)
  - Profile submitted/reviewing → button disabled với tooltip "Chỉ thêm NV trước khi submit hoặc khi tư vấn viên yêu cầu sửa"
  - Wave B FE gate qua `available_actions` typed entry `{action: 'add_choice', target: 'self'}`
- **P1 fix #6 — `current_admission_profile()` query archive table fallback**: v2.10 archive cron move profile end_date+6 months → `_archived_admission_profile`. Helper Lead.current_admission_profile() chỉ query active table → archive invisible. Officer mất truy cập hồ sơ cũ. Sửa: helper UNION query active + archive với index `(lead_id, academic_year)` trên archive table:
  ```python
  def current_admission_profile(self, year):
      active = next((p for p in self.admission_profiles if p.academic_year == year), None)
      if active: return active
      return db.execute(select(ArchivedAdmissionProfile)
                        .where(lead_id=self.id, academic_year=year)).scalar_one_or_none()
  ```
- **P1 fix #7 — WebSocket `notification_received` channel authorization (security)**: v2.10 fix #6 spec channel mới nhưng KHÔNG spec auth → broadcast all 12 events tất cả connected client → PII leak (e.g., user A nhận event ADMITTED của user B với total_score). Sửa Phần 3.3.d:
  - User-scoped channel `notification_received_user_{user_id}` cho staff (officer/admin/manager).
  - Lead-scoped channel `notification_received_lead_{lead_id}` cho candidate qua magic_link.
  - Role-scoped broadcast `notification_received_role_admin` + `_role_manager` cho operations rộng.
  - Backend dispatcher emit vào multiple channels theo audience của event.
  - Authorize subscription qua existing socket auth (JWT staff, magic_link cookie candidate).
- **P1 fix #8 — `StatusHistoryMetadataSchema` Pydantic strict drift với v2.11 fix #1 backfill keys**: Suggestion #10 v2.8 spec `extra='forbid'` + 5 key cố định. v2.11 fix #1 backfill SQL insert metadata với 2 key mới `source`, `transition` → Pydantic load fail → 500. Sửa schema:
  ```python
  class StatusHistoryMetadataSchema(BaseModel):
      model_config = ConfigDict(extra='forbid')
      # Existing
      computed_total_score: Optional[float] = None
      decision_rule: Optional[str] = None
      choice_priority: Optional[int] = Field(None, ge=1, le=10)
      trigger_source: Optional[str] = None
      backfill: Optional[bool] = None
      # v2.11 fix #1 scattered scalar backfill
      source: Optional[Literal['scattered_scalar_backfill', 'phase1_10_initial']] = None
      transition: Optional[Literal['approved','rejected','revision_requested',
                                   'resubmitted','overridden']] = None
      # v2.12 fix #1 T17 cascade audit
      student_id_cascaded: Optional[int] = None
  ```

### v2.11 — 2026-05-01 (round 18 review, 8 P1 lifecycle gaps)
Round 18 soi sâu hơn vào lifecycle/timing/retention edges, không lặp 17 round trước:
- **P1 fix #1 — Phase 1 #10 backfill migrate scattered scalar audit lịch sử**: verified `app/models/admission.py:221-303` có `approved_at/by`, `rejected_at/by`, `revision_requested_at/by`, `resubmitted_at/by`, `overridden_at/by` với data audit thật. Backfill v2.10 chỉ INSERT 1 row generic system → mất audit truth lịch sử (compliance Bộ GD&ĐT). Sửa: backfill thêm SQL migrate 5 scattered scalar → status_history rows per profile (5+ row/profile thay vì 1).
- **P1 fix #2 — Event catalog register window: move seed lên Phase 1 cùng outbox**: v2.9 fix #9 chỉ move outbox TABLE lên Phase 1 nhưng `EVENT_CATALOG` register 12 event vẫn ở Phase 3 (`phase3_02_seed_12_milestone_events_and_rules`). Phase 1 transition() emit event → `EVENT_CATALOG[event]` KeyError → service 500. Sửa: rename `phase1_19` thành `phase1_19_create_outbox_and_seed_events.py` — gộp outbox table + 12 event catalog seed + Celery beat task vào 1 migration. Phase 3 chỉ ship FE Wave A/B.
- **P1 fix #3 — Outbox worker `claimed_until` adaptive theo batch size**: v2.10 fix #2 ship worker beat ở Phase 1 với hard-coded `claimed_until = NOW() + 60s`. Batch 100 row × external IO 2-5s = 200-500s > 60s → worker khác pick up duplicate dispatch → email duplicate user-facing (Zalo/SMS có dedupe key OK, email không có). Sửa: dynamic timeout `claimed_until = NOW() + LEAST(batch_size * 5s, 600s)` — adaptive cap 10 phút. Hoặc giảm batch size xuống 20 row/lần.
- **P1 fix #4 — `current_intake_year` flip orphan lead enrolled cũ**: v2.10 fix #3 spec `current_intake_year` config-based projection. Khi admin flip 2026→2027 sau mùa close → 1000 lead enrolled mùa 2026 mất tracking (lookup year=2027 → None). Sửa Phần 2.5.b thêm fallback chain: priority 1 = current_intake_year profile; priority 2 = last terminal profile (enrolled/withdrawn/rejected) làm anchor; priority 3 = pre-admission stage. Hoặc tách 2 field: `current_intake_status` + `lifetime_status`.
- **P1 fix #5 — Quota race condition candidate submit (admit slot exhaust)**: Phần 5.a concurrency CHỈ cover admin mutate quota. Candidate submit không có lock → 2 candidate submit cùng lúc khi count=99 quota=100 → cả 2 pass → 101 profile cho 100 quota. Sửa: public submit endpoint dùng `pg_advisory_xact_lock(round_id)` HOẶC atomic `UPDATE round SET submission_count = submission_count + 1 WHERE submission_count < round_quota RETURNING submission_count` (reject nếu RETURNING NULL). Bổ sung column `OfferingAdmissionRound.submission_count` ở phase2_01.
- **P1 fix #6 — Wave B drop `available_actions_legacy` soft cutoff thay vì hard**: v2.10 fix #5 spec hard drop legacy field ở Wave B → user mở browser tab cũ trước Wave B (FE bundle cached service worker) → undefined access → mass crash mùa cao điểm. Sửa: 3-step soft cutoff:
  - Wave B+0: backend keep both, FE Wave B push update + service worker cache invalidate.
  - Wave B+30 days: backend trả `available_actions_legacy` + header `X-API-Deprecation: 30 days`.
  - Wave B+90 days: backend drop legacy field. Header `X-API-Schema-Version: 2` cho FE detect.
- **P1 fix #7 — 308 redirect explicit + Nginx body preserve**: v2.7 fix #7 chỉ nói "308 Redirect" abstract. FastAPI default `RedirectResponse` trả 307; Nginx default có thể strip POST body khi forward 308; mobile webview cũ có thể không follow 308. Sửa: 2 lựa chọn — (a) explicit `RedirectResponse(url, status_code=308)` + Nginx `proxy_pass_request_body on;` + e2e test curl POST verify; (b) **KHÔNG redirect**, mount cả 2 routes `/api/{unversioned}/*` và `/api/v1/*` cùng handler → tránh redirect entirely. Chốt (b) — đơn giản hơn, FE migrate sang `/api/v2/` subprefix mà không break legacy.
- **P1 fix #8 — Outbox retention 90-day archive policy**: phase1_19 outbox table không có archive/partition. Sau 5 năm production → 60k-180k row → worker SELECT FOR UPDATE SKIP LOCKED scan slow + coverage script DB query slow. Sửa: thêm cron weekly task `archive_outbox_dispatched_task`:
  ```sql
  WITH archived AS (
      DELETE FROM notification_outbox
      WHERE dispatched_at IS NOT NULL
        AND dispatched_at < NOW() - INTERVAL '90 days'
      RETURNING *
  )
  INSERT INTO _archived_notification_outbox SELECT * FROM archived;
  ```
  Bổ sung table `_archived_notification_outbox` cùng schema. Phase 1 #19 ship table + cron task.

### v2.10 — 2026-05-01 (round 17 review, 8 P1 second-order issues)
Đã đóng surface bug 16 round; round 17 soi tương tác giữa fix:
- **P1 fix #1 — Audit backfill populate 2 column mới (`actor_actual_role`/`effective_transition_role`)**: v2.9 thêm 2 column NOT NULL ENUM với CHECK constraint role-actor consistency. Nhưng `phase1_10_create_status_history_table_and_backfill.py` backfill row cũ chỉ set `transitioned_by_role='system'` → CHECK fail trên prod data. Sửa migration body: backfill SQL populate cả 3 column với `actor_actual_role='system'` + `effective_transition_role='system'`.
- **P1 fix #2 — Outbox worker beat ship cùng phase1_19**: outbox table tạo Phase 1 nhưng worker beat ở Phase 3 → window W3-W11 transition() INSERT outbox row vô tận, KHÔNG có dispatch → 12 milestone fan out 0. Sửa: ship Celery beat task `dispatch_pending_outbox` cùng `phase1_19` (KHÔNG tách Phase 3). Phase 3 chỉ ship event seed + frontend.
- **P1 fix #3 — Lead.consultation_status projection rule cho multi-year**: Lead có nhiều profile/year nhưng `consultation_status` projection chỉ map 1 stage. Spec rule: project từ profile của `current_intake_year` config; multi-year display tab per-year ở Lead detail; KPI count 1 lead × N year = N funnel entries.
- **P1 fix #4 — Admin token revocation atomic chống race với candidate consume**: admin revoke endpoint `SELECT tokens` rồi `UPDATE expires_at` không atomic — candidate có thể `UPDATE...RETURNING claim` ở giữa. Sửa: admin revoke dùng atomic compound `UPDATE expires_at=NOW() WHERE id IN (...) AND confirmed_at IS NULL RETURNING id` — chỉ revoke token còn active, return list cho admin verify đã revoke thật sự N token.
- **P1 fix #5 — `available_actions[]` typed structure phân biệt T12 endpoint**: FE check `'confirm' in available_actions` không biết gọi `/public/{token}/confirm` hay `/staff-confirm`. Sửa: `available_actions` đổi sang typed `[{action, target: 'self'|'override', endpoint}]`. FE branch theo `target` + auth context.
- **P1 fix #6 — Socket emit vs outbox event tách kênh**: PR #172 (memory `adm-032-doc-mutations-realtime`) đã ship `data_updated` cross-tab realtime. Plan 12 milestone events outbox + in-app notification → duplicate fanout. Sửa Phần 3.3.d thêm rule: outbox events fan qua Zalo/email + socket channel `notification_received` (riêng); `data_updated` channel CHỈ cho document mutations, KHÔNG cho status transition.
- **P1 fix #7 — FE-BE deploy 2-stage choreography cho mono-repo split**: backend container + frontend container build/deploy độc lập → window 1-3 phút mỗi deploy strict Zod parse fail → user crash. Sửa Phần 4 Phase 1 #11 FE Zod sync wave: 3-stage deploy:
  - Stage 1 (W3 deploy 1): FE Zod permissive enum (catchall passthrough state lạ → fallback render generic badge). Deploy FE only.
  - Stage 2 (W3 deploy 2, sau soak 24h): BE migration #11 + service trả state mới. Deploy BE.
  - Stage 3 (W3 deploy 3): FE Zod strict enum lock 4 state mới + STATUS_BADGE_CONFIG mapping đầy đủ.
- **P1 fix #8 — Round lifecycle in-flight profile khi end_date qua**: round end_date chỉ filter storefront query, không có rule cho profile lifecycle khi round đã hết hạn. Bổ sung Phần 2.1 sub-section "Round lifecycle":
  - **Cutoff**: candidate magic_link submit endpoint check `round.end_date >= NOW()` → 410 Gone nếu hết hạn (token vẫn valid nhưng round đã đóng).
  - **Admin extension**: endpoint `/api/v2/admin/rounds/{id}/extend` audit log mandatory + reason required.
  - **Cleanup policy**: round end_date + 6 months → cron job archive profile sang `_archived_admission_profile` table (không xoá, giữ audit).
  - **Engine xét tuyển**: chỉ chạy cho profile của round có `is_active=true` AND `end_date >= NOW() - 30 days` (cho phép retroactive review trong 30 ngày). Sau 30 ngày → admin override only.

### v2.9 — 2026-05-01 (round 16 review, 9 P1 contract cleanup)
Dọn stale sample + chốt 1 contract duy nhất + thêm gate test cho RBAC/token/outbox lifecycle:
- **P1 fix #1 — Xoá stale `_resolve_role(actor)` sample**: line 1142 còn sample cũ. Dev copy → manager bị deny sai/T17 lọt. Thay bằng entrypoint duy nhất `transition(db, profile_id, actor, to_status, ...)` với FOR UPDATE + can_transition gọi effective_role_for_transition() internal.
- **P1 fix #2 — Audit role tách actual vs effective**: status_history hiện chỉ có `transitioned_by_role` enum 4 giá trị. Manager actor map sang officer/admin tùy transition → mất sự thật. Sửa schema status_history thêm 2 column: `actor_actual_role` (CHECK in admin/manager/accountant/officer/system + role candidate=NULL khi qua lead_id) + `effective_transition_role` (resolved per-transition). CHECK constraint cũ `transitioned_by_role` deprecate, query report theo `actor_actual_role` cho audit thật, theo `effective_transition_role` cho RBAC trace.
- **P1 fix #3 — Casbin auth_model.conf phải đổi để support deny**: verified existing `auth_model.conf` chỉ có `p = sub, obj, act` — KHÔNG có effect field. Plan policy `eft=allow/deny` không có hiệu lực. Sửa: Phase 1 #16 audit task scope mở rộng — update `auth_model.conf` thêm `p_eft` + matcher "deny first match wins", update policy adapter/seed/sync, test matcher accountant deny pass-through. KHÔNG ship deny policy nếu auth_model chưa update.
- **P1 fix #4 — Xoá stale `AdmissionMagicLinkToken` dependency block**: line 1466-1480 còn block cũ `AdmissionMagicLinkToken/token_id/used_at/parse_uuid` sau section đã chốt reuse `AdmissionConfirmationToken`. Xoá hoàn toàn — chỉ giữ 1 dependency dùng `token` field + `confirmed_at` mark used + `attempt_count` lockout (verified schema thực tế).
- **P1 fix #5 — Token consume atomic chống double-submit**: dependency hiện SELECT token rồi service insert transition → 2 request song song cùng pass `confirmed_at IS NULL` → 2 transition lọt. Sửa: dependency dùng `UPDATE admission_confirmation_token SET confirmed_at = NOW() WHERE token = :raw AND action_type = :action AND confirmed_at IS NULL AND expires_at > NOW() AND attempt_count < 5 RETURNING profile_id` — atomic claim. Caller second nhận NULL → 404. Hoặc `SELECT ... FOR UPDATE` lock token row trong cùng transaction với state transition.
- **P1 fix #6 — Public submit contract chốt**: plan có endpoint `/api/v2/public/admissions/{token}/submit` nhưng KHÔNG mô tả ai tạo draft profile + ai phát submit token + idempotency CCCD/email/phone/year + anti-bot/rate-limit + duplicate hồ sơ theo round/path. Bổ sung Phần 3.3.g.1 (mới) — Public submit lifecycle:
  - **Bước 1**: Officer/admin tạo lead qua internal route `/api/v2/leads`. Hệ thống auto-create draft profile + auto-issue submit token (TTL 7 ngày) gửi qua email/SMS.
  - **Bước 2**: Candidate click link → endpoint `/api/v2/public/admissions/{token}/submit` validate token + render form.
  - **Idempotency**: composite UNIQUE `(citizen_id, academic_year)` đã có ở model. Backend reject 409 nếu duplicate.
  - **Anti-bot**: rate limit 5/min/token + 30/min/IP (đã spec) + reCAPTCHA v3 ở public endpoint (FE add).
  - **Duplicate per round/path**: same profile có thể submit nhiều choice cho cùng round, nhưng UNIQUE `(profile_id, path_id, config_id)` ở `AdmissionProfileChoice` chặn duplicate config.
- **P1 fix #7 — API versioning topology align với router hiện tại**: plan đề xuất `/api/v1/`+`/api/v2/` nhưng existing router unversioned mount `/api` xen với `/api/public`/`/api/admin`/`/api/meta`. Sửa Phần 3.3.h Suggestion #11:
  - Phase 0 thêm router migration: rename existing `/api/admissions/*` → `/api/v1/admissions/*` (alias backward-compat).
  - Phase 1 mount `/api/v2/admissions/*` + `/api/v2/public/admissions/*` song song.
  - FE client (Zod schema) target `/api/v2/` cho choice-engine; legacy FE giữ `/api/v1/`.
  - Nginx config update routing prefix nếu có.
  - Route alias test: `/api/admissions/123/confirm` (no version) → 308 Redirect → `/api/v1/admissions/123/confirm`. Phase 4 drop alias.
- **P1 fix #8 — Event catalog drift `app/core/event_catalog.py` (KHÔNG `notification_events.py`)**: verified module thực tế ở `app/core/event_catalog.py` + `app/core/events.py`. Plan reference `app/core/event_catalog.py` không tồn tại. Sửa toàn bộ reference: `EventDefinition` trong `app/core/event_catalog.py`. KHÔNG tạo module song song.
- **P1 fix #9 — Outbox lifecycle gate trước transition service deploy**: plan #16 audit task GATE phase1_11, transition service ship sau #16 (W3-W6). Nhưng `notification_outbox` table ở `phase3_03` (W11+). Nếu transition() gọi nhánh outbox trước Phase 3 → fail "table does not exist" hoặc silently skip. Sửa 2 phương án:
  - (a) Move `phase3_03_create_notification_outbox.py` lên Phase 1 (chèn trước phase1_11) → outbox table có sẵn từ Phase 1, transition service dispatch_event() chạy được ngay. Worker beat task vẫn ở Phase 3.
  - (b) Feature flag `FLAG_OUTBOX_ENABLED=False` cho Phase 1-2, dispatch_event() fall back direct safe_dispatch nếu flag off. Phase 3 flip flag.
  - Chốt (a) — đơn giản hơn, không cần feature flag thêm. Migration chain update: `phase3_03` rename thành `phase1_19_create_notification_outbox` chèn trước phase1_11.

### v2.8 — 2026-05-01 (round 15 + /review, 12 fix — 8 P1 + 4 P1 suggestion)
**Round 15 review (8 fix):**
- **P1 fix #1 — `effective_role_for_transition` wiring vào transition flow**: v2.7 thêm resolver nhưng `transition()` sample vẫn `self._resolve_role(actor)` + `can_transition()` không nhận `transition_code`. Fix nằm ngoài luồng. Sửa: `can_transition(actor, profile, from_status, to_status, transition_code)` BẮT BUỘC nhận `transition_code`; gọi `effective_role_for_transition(actor, transition_code)` ở đầu. Service entry pass `transition_code` từ endpoint.
- **P1 fix #2 — Candidate public route tách prefix**: endpoint `/api/admissions/{id}/submit` cho cả candidate + officer là contract IDOR mơ hồ. Sửa: tách public route prefix `/api/public/admissions/{token}/{action}` (token + action_type ở Path, KHÔNG cần `id` direct). Profile resolve qua token. Officer/admin route giữ `/api/admissions/{id}/{action}` với `Depends(CasbinAuth)`. 2 hệ route riêng biệt, không lẫn.
- **P1 fix #3 — `AdmissionConfirmationToken` schema reuse correct**: verified model `profile_id unique=True`, field tên `token` (không `token_id`), `confirmed_at` (không `used_at`), KHÔNG có `action_type`. Sửa Phần 3.3.g + migration `phase1_18`:
  - ALTER ADD `action_type VARCHAR(20) NOT NULL DEFAULT 'confirm'`.
  - DROP unique cũ trên `profile_id`, tạo partial unique `(profile_id, action_type) WHERE confirmed_at IS NULL` (1 active token per profile per action; nhiều token đã confirmed cho audit OK).
  - Field reference thực tế: `token` (string), `confirmed_at` (mark used), `expires_at`, `attempt_count`. KHÔNG dùng `used_at`/`token_id`.
  - Dependency `get_profile_by_magic_link_token()` query: `where(token == :raw) AND action_type == :action AND expires_at > now() AND confirmed_at IS NULL`.
- **P1 fix #4 — Casbin diamond inheritance accountant deny-early**: Casbin `g, role:accountant, role:officer` (line 44) → accountant inherit officer policy → accountant pass route guard cho `/admissions/*/claim, /request-revision`. Service guard chặn nhưng RBAC fail-late. Sửa: 2 lựa chọn — (a) policy entry deny accountant explicit `p, role:accountant, /api/admissions/*/{transition_action}, !` (Casbin priority deny rule), (b) effect "deny first match" — accountant entry ở top với deny. Chốt (a) — explicit hơn. Test bắt buộc: `accountant_user → /api/admissions/{id}/claim → 403`, không 200.
- **P1 fix #5 — Notification API chốt 1 sample duy nhất**: Phần 3.3.f vẫn còn sample cũ dùng `event_code`/`idempotency_key` lẫn `event: SystemEvents`/`dedupe_key`. Sửa: xoá toàn bộ sample cũ, giữ 1 signature. `post_commit_callback` capture `db` qua closure rõ ràng (functools.partial hoặc nested function bind).
- **P1 fix #6 — Outbox worker pass `bypass_consent_check` vào dispatcher**: worker gọi `safe_dispatch(db, event, payload, dedupe_key)` chỉ 4 arg → mặc định `skip_preference_check=False` → ADMITTED/WAITLISTED/REJECTED/RESULT_PUBLISHED/ENROLLED bị consent revoke chặn → vi phạm bypass policy. Verified dispatcher có `skip_preference_check: bool = False` param ở line 598/1858. Sửa worker: lookup `EVENT_CATALOG[event].bypass_consent_check` + pass `skip_preference_check=event_def.bypass_consent_check`.
- **P1 fix #7 — Migration `phase1_18` orphan khỏi chain**: cheat sheet liệt kê 16 migration Phase 1 nhưng chain ordering line 2090-2099 KHÔNG có `phase1_18`. Sửa: chèn `phase1_18_extend_confirmation_token_for_multi_action` vào chain SAU `phase1_15` (drop lead_id unique) và TRƯỚC bất kỳ candidate route deploy. Recount: Phase 1 = 16 migration thực sự.
- **P2 fix #8 — Cheat sheet/timeline drift cuối file**: line 3192-3193 vẫn ghi "25 + 1" trong khi đầu cheat sheet ghi "26 + 4". Line 3166 nói "11 file" workflow remap (cũ v1.x), body chốt 23 file. Timeline summary 2026-08-01/07-30 stale, body chốt 2026-08-13 full mở. Sửa toàn bộ stale numbers + sync với body.

**/review suggestion (4 P1 mới):**
- **Suggestion #9 — Bulk transition API cho `RESULT_PUBLISHED` fanout**: hiện `transition()` per-profile call ~5 query (lookup catalog + audit check + status_history INSERT + outbox INSERT). Fanout 1000 profile = 5000 query. Bổ sung `bulk_transition()` service method: 1 single query INSERT N status_history rows + N outbox rows trong transaction. Endpoint `POST /api/admissions/bulk-publish-result` admin only. Test: 1000 profile fanout < 5s.
- **Suggestion #10 — JSONB payload Pydantic strict (chống injection)**: `applied_rules`, `eligibility_check_result`, outbox `payload`, status_history `metadata` đều JSONB. Service nhận user input có thể craft pathologic shape. Bổ sung Pydantic model strict cho mỗi: `AppliedRulesSchema`, `EligibilityCheckResultSchema`, `OutboxPayloadSchema`, `StatusHistoryMetadataSchema`. Service validate qua `model_validate()` trước serialize JSONB. Endpoint reject 400 nếu shape sai.
- **Suggestion #11 — API versioning strategy**: Phase 4 drop `Lead.gpa` + endpoint singular `/leads/{id}/admission-profile`. Plan KHÔNG mention version. Chốt: URL prefix `/api/v1/` cho legacy + `/api/v2/` cho choice-engine. Phase 1 thêm v2 alias endpoint cho Lead profiles list. Phase 4 drop `/api/v1/leads/{id}/admission-profile` singular sau monitor 0 caller. Header `X-API-Deprecation-Date` cho client migration.
- **Suggestion #12 — `FOR UPDATE` service entry transition()**: race condition khi 2 admin concurrent `publish_result` + `waitlist_promote` cùng profile → cả 2 call `transition()` đọc cùng `from_status`, write conflict ở status_history. Bổ sung `AdmissionStateService.transition()` SELECT profile `with_for_update()` ở entry. Hold lock đến cuối transaction. Pattern symmetric với existing `bulk_assign` (PR #156).

### v2.7 — 2026-05-01 (round 14 review, 7 fix — 1 P0 + 5 P1 + 1 P2)
- **P0 fix #1 — Timeline gate alignment với chain ordering**: timeline (Phần 7.1) vẫn ghi "Code task #15 workflow audit ở W10 (sau Phase 1+2)", mâu thuẫn chain ordering v2.6 đã chốt #15/#16 GATE BEFORE phase1_11. Sửa timeline: kéo #15+#16 lên W3 (đầu Phase 1), chạy song song với Phase 1 migration #01-#10; chốt phải merge TRƯỚC khi push migration #11. Phase 1 stretch nhẹ thành W3-W6.
- **P1 fix #2 — Manager role effective resolution**: Manager map sang Admin subset nhưng `_resolve_role(manager) → 'admin'` thì manager rollback T17 được (nguy hiểm), `→ 'manager'` thì matrix không match → fail mọi action. Sửa: thêm `effective_role_for_transition(user, transition)` resolver — return role per-transition: T17 chỉ resolve 'admin' nếu `user.role == 'admin'` thực; T6/T10/T11 resolve 'admin' cho cả admin và manager; T3/T4 resolve 'officer' cho officer + manager. KHÔNG generic mapping.
- **P1 fix #3 — Casbin per-action policy align deps existing**: verified `app/core/deps.py:378` `check_permission` dùng `request.url.path + method` matcher. Plan `action='admission:transition:<name>'` không match. Sửa: 2 lựa chọn — (a) tách route per-action: `POST /admissions/{id}/submit`, `POST /admissions/{id}/confirm`, `POST /admissions/{id}/withdraw` (existing pattern), `POST /admissions/{id}/admin-rollback`, ... (path-level Casbin work as-is); (b) giữ generic `/transition` + extend `check_permission` matcher đọc `request.json()['action_type']`. Chốt (a) — symmetric với existing endpoint pattern, audit log rõ.
- **P1 fix #4 — Outbox worker sample align dispatcher signature**: line 1255-1257 worker Step 2 dùng `safe_dispatch(event=event_code, payload=payload, idempotency_key=idem_key)` — mâu thuẫn signature align ở Fix #4 v2.6. Sửa: outbox row column tên `event_code` (string lưu DB) nhưng worker resolve về `SystemEvents` enum trước khi gọi: `safe_dispatch(db=db_conn, event=SystemEvents(event_code), payload=payload, dedupe_key=idem_key)`. Thêm `db` arg + enum cast + rename `idempotency_key → dedupe_key` cho consistency.
- **P1 fix #5 — Magic link reuse `AdmissionConfirmationToken` existing**: verified `app/models/admission.py:490 AdmissionConfirmationToken` đã có với `attempt_count`, lockout/cooldown, CCCD verification, reminder metadata (memory: adm-023-028 đã ship 2026-04-29). Plan tạo `admission_magic_link_token` song song sẽ duplicate + lệch flow confirm. Sửa Phần 3.3.g: REUSE existing table cho confirm action (dùng `confirmation_token` field hiện có); 3 action mới (`submit`, `resubmit`, `withdraw`) extend existing table thêm `action_type ENUM` column hoặc tạo bảng mới chỉ cho 3 action mới (KHÔNG đụng confirm). Migration plan rõ: ALTER existing add `action_type` default 'confirm' cho row cũ.
- **P1 fix #6 — Public storefront fail-closed thay vì DOT_1 silent default**: plan v2.5 fix #6 ghi public service "default DOT_1 nếu env chưa configure rõ" — silent fallback nguy hiểm khi prod có DOT_1 + DOT_2 active đồng thời. Sửa Phần 1 #17: storefront query active rounds qua `WHERE NOW() BETWEEN start_date AND end_date AND is_active=true`; nếu = 0 round → fail-closed empty list + log warning; nếu > 1 round → render dropdown picker BẮT BUỘC, KHÔNG default. URL param `?round_code=DOT_1` cho deep-link.
- **P2 fix #7 — Cheat sheet stale numbers**: line 3100 area cần verify code task count vs body. v2.6 chốt 4 code task (#15 + #16 + #17 + Phase 0c hot-fix), transition matrix T1-T17. Cheat sheet sync số chính xác.

### v2.6 — 2026-05-01 (round 13 review, 9 fix — 2 P0 + 6 P1 + 1 P2)
- **P0 fix #1 — Workflow gate stale narrative**: line 2149 vẫn ghi "Bundle change Step 1-5 vào PR riêng sau Phase 1 migration #11/#12" — mâu thuẫn với gate table v2.5 đã chốt #15/#16 GATE BEFORE phase1_11. Sửa stale wording: "Bundle change Step 1-5 vào PR riêng MERGE BEFORE phase1_11 (gate cứng theo Migration ordering chain)".
- **P0 fix #2 — `create_profile` path lookup ambiguous sau multi-round**: verified `admission_path_repository.py:119` `get_path_by_offering_and_method(academic_info_id, admission_method_id)` dùng `.first()`. Sau Phase 2 swap unique sang `(round_id, method_id)`, cùng method có DOT_1 + DOT_2 → `.first()` random → snapshot path sai → applied_rules sai. Bổ sung Phase 2 #02 PR scope: deprecate `get_path_by_offering_and_method` + thêm `get_path_by_round_and_method(admission_round_id, admission_method_id)` + `create_profile` API/service nhận `admission_path_id` direct (không lookup nữa) hoặc `admission_round_id` explicit.
- **P1 fix #3 — Notification timing narrative stale**: line 1062-1065 vẫn ghi service trả `event_payload: dict | None` + router gọi `safe_dispatch(**event_payload)` — contract CŨ. Phần 3.3.e/f đã chốt callback API mới. Sửa Phần 3.3.d Notification timing wording về callback API duy nhất.
- **P1 fix #4 — `dispatch_event` signature align với existing dispatcher**: verified existing `app/services/notification_dispatcher.py:593` `dispatch(db, ...)` + `:1853 safe_dispatch(...)` dùng `dedupe_key` param + `SystemEvents` enum (không string). Plan pseudo-code `safe_dispatch(event=event_code, payload=payload)` thiếu `db`, dùng string event_code, dùng `idempotency_key` thay `dedupe_key`. Sửa: `dispatch_event()` wrapper align signature existing — input `event: SystemEvents` enum + `dedupe_key: str` (rename idempotency_key → dedupe_key cho consistency) + pass `db` cho dispatch path internal.
- **P1 fix #5 — RBAC matrix nối Casbin/deps**: verified `casbin_config/policy_templates.py:44-46` có 4 role `admin/manager/accountant/officer` (KHÔNG chỉ admin/officer). Plan transition matrix bỏ qua `manager` — manager hiện có quyền approve/reject/request-revision. Bổ sung Phần 3.3.b mapping table: `manager` map sang plan role `admin` (full transition power) hoặc `officer` (request-revision/claim only) tùy operation. Update `policy_templates.py` thêm policy entry cho 17 transition mới + route dependency check.
- **P1 fix #6 — Candidate actions IDOR contract spec**: plan candidate submit/resubmit/confirm/withdraw qua magic_link nhưng KHÔNG spec token shape, expiry, rate limit, IDOR check. Bổ sung Phần 3.3.g (mới) — Candidate auth contract: token format (UUID v7 + HMAC), expiry (configurable per action), rate limit (5 req/min/token), IDOR via `get_profile_by_magic_link_token()` dependency raise 404 nếu token invalid/expired/wrong profile.
- **P1 fix #7 — Lead one-to-many repository scope**: v2.5 fix #5 list model + schema + service nhưng KHÔNG list repository `admission_repository.py:482 get_profile_by_lead_id` singular. Caller existing rely on singular trả 1 profile. Sau drop unique → repository raise hoặc trả random. Bổ sung Phase 1 #15 PR scope: deprecate `get_profile_by_lead_id` + thêm `list_profiles_by_lead_id(lead_id)` + `get_profile_by_lead_year(lead_id, academic_year)`. Caller migrate sang 2 API mới.
- **P1 fix #8 — FE action gate giữ thin-client**: v2.5 fix #6 ghi "FE dùng `is_admitted_like()` helper FE" — vi phạm thin-client principle. FE phải gate qua `available_actions[]` từ backend response (verified `permission-adapter.ts:45`). Sửa: backend `_populate_response_fields()` populate `available_actions` đầy đủ cho cả legacy approved + choice-engine admitted profile. FE chỉ check `'confirm' in available_actions`, KHÔNG suy luận từ status.
- **P2 fix #9 — Catalog principle wording**: nguyên tắc #3 line 10 "Không sửa catalog dùng chung (`Subject`, `SubjectGroup`, `SubjectGroupSubject`)" mâu thuẫn với migration thêm `Subject.subject_kind/max_score/min_possible_score`. Sửa: "Không sửa cấu trúc `SubjectGroup`/`SubjectGroupSubject`; `Subject` mở rộng additive (thêm field nullable, KHÔNG đổi field hiện có)".

### v2.5 — 2026-05-01 (round 12 review, 8 fix — 1 P0 + 5 P1 + 2 P2)
- **P0 fix #1 — Workflow audit gate self-conflict**: v2.3 fix #2 nói "Phase 1 #11 chỉ merge sau #16 audit ship", nhưng body chain ordering line 2090-2099 KHÔNG list #16 task → đọc body sẽ thấy `phase1_11 → phase1_12` direct, không gate. Sửa: chain ordering thêm explicit `[code task #16 audit] PR-merge → phase1_11 → ...`. Bổ sung note đầu chain: "code task không phải Alembic migration, ship PR riêng, MERGE TRƯỚC migration #11 (gate cứng)".
- **P1 fix #2 — Alembic chain missing migrations**: chain ordering thiếu `phase0b_relax_applied_rules_immutability_for_payment_keys` (Phase 0) + `phase1_15_drop_lead_id_unique_constraint` (Phase 1). Phase 2 numbering phải `01 → 02 → 02b → 03 → 04` (NOT-NULL gate giữa unique swap, widen score precision sau cùng). Chain đầy đủ + `down_revision` rõ ràng.
- **P1 fix #3 — Notification contract pattern duy nhất**: Phần 3.3.e service pattern line 1075-1082 vẫn dùng cũ "INSERT outbox row trực tiếp service body". v2.4 đã chốt API `dispatch_event()` ở Phần 3.3.f. Sửa Phần 3.3.e service pattern dùng `dispatch_event()` API duy nhất, KHÔNG INSERT outbox direct.
- **P1 fix #4 — PL/pgSQL FOREACH variable declaration**: function `prevent_applied_rules_update()` Phase 0b dùng `FOREACH key IN ARRAY allowed_keys` nhưng KHÔNG declare biến `key` trong block `DECLARE`. Migration sẽ fail compile. Thêm `v_key TEXT;` declaration + đổi `FOREACH v_key IN ARRAY...`.
- **P1 fix #5 — Lead one-to-many relationship contract**: Phase 1 #15 drop `lead_id UNIQUE` chỉ đổi DB constraint. Verified hiện tại `app/models/lead.py:252` `admission_profile = relationship(uselist=False)` (one-to-one), `app/schemas/lead.py:410` `admission_profile: Optional[AdmissionProfileShallow]` singular, `app/services/admission_service.py:1183` block tạo profile nếu lead đã có. Bổ sung Phase 1 #15 PR scope:
  - `Lead.admission_profile` → `Lead.admission_profiles` plural list (`uselist=True`).
  - Schema `LeadResponse.admission_profile` → `admission_profiles: list[AdmissionProfileShallow]` + helper `current_admission_profile()` resolve theo academic_year.
  - Service `create_profile`: thay block "lead đã có profile" → block "lead đã có profile cho academic_year này".
  - FE schema/component: hiển thị multi-profile per lead theo year.
- **P1 fix #6 — Public admissions storefront missing**: verified `app/services/public_admissions_service.py:114,145` load path qua `academic_info_id` direct + `:534` resolve document theo `offering_type/method`. KHÔNG biết `admission_round_id`, `applicable_to`, path-level `DocumentGroup`. Sau Phase 2 swap unique + Phase 1 doc_group path override, public storefront sẽ hiển thị sai. Bổ sung Phase 1 #17 code task: migrate `public_admissions_service.py` qua round + audience filter + 3-tier doc resolution. Ship cùng wave Phase 2 #2 unique swap.
- **P2 fix #7 — DB role preflight cho admission_admin/audit_reader**: verified `docker-compose.yml:27` chỉ tạo role `qlts`. Plan grant cho `admission_admin` + `audit_reader` sẽ fail nếu role chưa tồn tại ở dev/staging. Sửa migration Phase 1 #9b: preflight `DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='admission_admin') THEN CREATE ROLE admission_admin; END IF; END $$;`. Conditional grant cho cả 2 role.
- **P2 fix #8 — Backfill SQL alias drift `rec` không có `(value)`**: line 1592 vẫn dùng `jsonb_array_elements(p.academic_history) rec` rồi `rec->>` — cú pháp sai (rec là record column). Đổi `AS rec(value)` + `rec.value->>`.

### v2.4 — 2026-05-01 (plan-review verification, 4 fix)
Plan-review qua 2 Explore agent verify 12 finding. 6/12 false positive (code đã đúng), 4/12 confirmed:
- **Fix #1 — Outbox count math (Phần 3.3.d line 1028)**: ghi "6 outbox-required events (4/5/6/7/8/10/12)" + "6 best-effort còn lại". Đếm `(4/5/6/7/8/10/12)` = 7 events. 12 - 7 = 5 best-effort. Sửa 2 chỗ: "6 outbox-required" → "7 outbox-required", "6 best-effort" → "5 best-effort". Đồng bộ với Phần 3.3.e line 1176.
- **Fix #2 — Cheat sheet code task count (Phần 8 line 2837)**: ghi "~25 file Alembic + 1 code task". v2.3 đã thêm 2 code-only task ngoài Alembic: Phase 0c hot-fix (`admission_config_repository.py`) + Phase 1 #16 audit task (workflow contract boundary). Sửa "1 code task" → "3 code task" (#15 workflow audit + #16 contract boundary + Phase 0c hot-fix).
- **Fix #3 — Phần 9 verification log thêm `criteria_id` drift**: log hiện list 13 field name fix nhưng missing `admission_criteria_id` (sai trong code repository) → `criteria_id` (model thực tế). Thêm row + ghi rõ context "code-level drift, không phải proposal".
- **Fix #4 — i18n keys enumerate explicit (Phần 4 Phase 3 Frontend deliverables)**: Item BLOCK #6 ghi tổng "25+ keys" nhưng KHÔNG list cụ thể. Bổ sung sub-table 25 key path để FE dev pickup không phải tự suy.

**False positive đã verify (KHÔNG fix)**:
- Notification contract code sample đã consistent callback pattern (Phần 3.3.c line 985-990, 994-1002). Sample code đúng, narrative text v2.3 đã clear.
- Router pattern comment đã có "outbox events đã INSERT trong commit" ở line 1000.
- Phần 7 title đã có sub-heading 7.1 "(absolute dates, baseline 2026-04-30)" line 2683.
- Phase 1 #11 migration body đã có inline SQL ALTER CHECK constraint full DDL line 1738-1750.

### v2.3 — 2026-05-01 (round 11 review, 8 fix — 2 P0 blockers)
- **P0 fix #1 — Outbox worker claim đúng batch semantics**: pattern v2.2 `UPDATE ... RETURNING ... fetchmany(100)` UPDATE TOÀN BỘ pending rows rồi mới fetch 100 → các row sau cap 100 vẫn bị `attempts++` mà không dispatch → chạm retry cap 5 mà chưa gửi. Sửa: 2-step CTE — (1) `SELECT id FROM ... ORDER BY created_at LIMIT 100 FOR UPDATE SKIP LOCKED`, (2) `UPDATE ... WHERE id IN (selected_ids)` set claim. Chỉ N row được claim đúng.
- **P0 fix #2 — Workflow contract compatibility boundary**: state service v2.2 chốt mọi transition đi qua `AdmissionStateService`, nhưng codebase hiện set `profile.status` trực tiếp ở nhiều endpoint (`admission_service.py:3918` legacy approve/reject, multiple confirm/enroll endpoints). Audit mở rộng: KHÔNG ship CHECK constraint extend (Phase 1 #11) trước khi 100% caller được chuyển qua state service. Bổ sung **Phase 1 #16 audit task** — grep + refactor mọi `profile.status = '...'` site (BE) + FE Zod/status/action map + notification mapping + status-count DTO + finance/commission projections. Gate Phase 1 #11 sau khi #16 ship.
- **P1 fix #3 — Notification contract chốt 1 API duy nhất**: v2.2 mâu thuẫn — Phần 3.3.c service trả `event_payload` + router gọi `safe_dispatch`, nhưng Phần 3.3.f dispatcher route theo `requires_outbox` flag → 2 contract khác nhau. Sửa: chốt **1 API duy nhất** — service luôn gọi `dispatch_event(db, event_code, payload, idempotency_key)`. Function tự route: `requires_outbox=True` → INSERT outbox cùng tx; `requires_outbox=False` → trả `(payload, callback)` cho router safe_dispatch sau commit. Service KHÔNG có discretion. Router pattern đơn giản: `await dispatch_event(...)` rồi `commit` rồi `await callback() if callback`.
- **P1 fix #4 — `graduation_year` LATERAL alias syntax**: v2.2 dùng `LATERAL jsonb_array_elements(...) AS rec` rồi `rec->>'year_to'` — sai cú pháp Postgres. `jsonb_array_elements` trả set của `value` column → cần `AS rec(value)` rồi `rec.value->>'year_to'`. Migration sẽ fail. Đã sửa GPA staging dùng đúng cú pháp `WITH ORDINALITY AS rec(value, ord)`, nhưng graduation_year staging quên áp dụng pattern.
- **P1 fix #5 — Score >10 bridge contract**: legacy CHECK `ck_profile_subject_score_range (score 0..10)` (verified `profile_data.py:69`) + Pydantic validate `score 0..10` (`schemas/admission.py:174`) + FE Zod cap 0..10 (`admissions.ts:137`). Plan thêm ABILITY_TEST max=150, V-ACT max=1200, IELTS max=9 — nhưng KHÔNG drop legacy CHECK. Nếu Phase 1 #5 seed subject ảo `DGNL_DHQGHN max=150` mà existing path dùng nó → CHECK reject. Bổ sung gate: subject_kind ∈ (TERM_AVERAGE, ABILITY_TEST, CERTIFICATE) chỉ enable cho `ProfileChoiceScore` (Phase 3) — KHÔNG expose qua legacy `ProfileSubjectScore` API. Phase 4 deprecate legacy CHECK + Pydantic + FE cap.
- **P1 fix #6 — `AdmissionPath` schema/service drift end-to-end**: Plan thêm fields `applicable_to`, `method_quota`, `bonus_rule_override`, `admission_round_id` ở model nhưng:
  - BE create schema `app/schemas/admission_path.py:133` chưa nhận.
  - Service create `app/services/admission_path_service.py:145` còn duplicate check theo `(academic_info_id, admission_method_id)` — sẽ break sau swap unique.
  - FE Zod `frontend/src/lib/zod/admission-path.ts:117` chưa có.
  Bổ sung Phase 1 #03 ship cùng PR: API request/response schema update + service create logic update + applied_rules snapshot bao gồm new fields + FE Zod cập nhật. KHÔNG được merge migration #03 trước khi schema/service/FE wave xong.
- **P1 fix #7 — FE Zod strict enum reject new states trước fallback**: response schema `admissions.ts:494` strict enum legacy → parse fail trước render → status badge fallback không kịp chạy. Bổ sung Phase 3 Wave A: FE Zod update enum + new schema fields PHẢI deploy CÙNG WAVE với BE Phase 1 #11 CHECK extend, KHÔNG thể stagger. Update Phần 4 Phase 3 Wave A scope.
- **P2 fix #8 — Field-name drift `admission_criteria_id`**: verified `admission_config_repository.py:76,84` dùng `admission_criteria_id` nhưng model thực tế là `criteria_id` (xác nhận Phần 9 verification log + `admission_path.py:82` `criteria_id`). 2 query này silent broken — `select(...).where(.admission_criteria_id == ...)` raise `AttributeError` runtime. Pre-existing bug, KHÔNG phải refactor task — bổ sung Phase 0 hot-fix migration `phase0c_fix_admission_config_repository_field_name.py` (code-only PR, không Alembic): sửa 2 line về `criteria_id`.

### v2.2 — 2026-05-01 (cross-module hard review, 10 update)
- **Update #1 — Lead.gpa deprecation timeline (Phần 2.5)**: bổ sung subsection rõ ràng. Phase 1: dual-read fallback Lead.gpa nếu Profile.gpa_overall null. Phase 2: dual-write service layer. Phase 3: lead pipeline filter chuyển qua relationship `lead.profile.gpa_overall`. Phase 4: drop Lead.gpa.
- **Update #2 — Event namespace collision audit (Phần 3.3.d)**: thêm cột "Existing event mapping" cho 12 events. Verified `APPLICATION_*` namespace đã có ở `notification_events.py`. Quyết định: KHÔNG reuse `APPLICATION_*` (giữ legacy backward-compat); tạo 12 event mới `ADMISSION_*` namespace, deprecate APPLICATION_* sau Phase 4. Coverage script extend check namespace collision.
- **Update #3 — Outbox routing flags (Phần 3.3.e)**: `EventDefinition.requires_outbox: bool` + `bypass_consent_check: bool` flags. Dispatcher phân nhánh: `if event.requires_outbox → INSERT outbox; else safe_dispatch()`. Critical events bypass Zalo consent (5 events: ADMITTED/WAITLISTED/REJECTED/RESULT_PUBLISHED/ENROLLED) — system-critical thông báo, không phải marketing.
- **Update #4 — Phase 0 `applied_rules` partial-update bypass**: code production update `applied_rules["fee_paid_at"]` ở `admission_service.py:5904-5907`. Trigger `b5c6d7e8f9a0` raise. Phase 0 thêm migration update trigger function: whitelist key `fee_paid_at`, `fee_payment_data`, `fee_calculated_at` — chỉ những key này được phép thêm/update sau create.
- **Update #5 — Phase 1 #15 drop `lead_id` UNIQUE**: `AdmissionProfile.lead_id UNIQUE` chặn cùng lead apply nhiều season. Phase 1 thêm `phase1_15_drop_lead_id_unique_constraint.py` — DROP unique, giữ index thường + `(citizen_id, academic_year)` UNIQUE đã có.
- **Update #6 — Phase 3 Frontend deliverables subsection**: 5 component mới (choice editor, score card per choice, decision badge, eligibility result viewer, audit reason dialog) + 9 Zod field + 4 enum + i18n 22 keys. FE effort revise: 2-3 sprint thay vì 1 sprint.
- **Update #7 — Task #14 file list 11 → 23**: bổ sung 12 file ngoài: `admission_repository.py:429`, `commission_service.py:251,296`, `commission_repository.py:246`, `phase_manager.py:119`, `admission_state_machine.py:44,61`, `event_catalog.py`, `admission_event_mapping.py:154,187`, `routers/fees.py:81`, `routers/collaborators.py:205`, `tasks/collaborator_tasks.py:71`, `templates/emails/admission_*.html`, `lead_service.py` effective_status.
- **Update #8 — Task #14 step "Update state machine FIRST"**: trước normalize layer, phải update `AdmissionStatus` enum (`admission_state_machine.py:44`) + `ALLOWED_TRANSITIONS` dict (line 61). State machine là source of truth — không update sẽ block mọi transition mới ngay khi deploy.
- **Update #9 — Task #14 lead_admission_sync mapping cho 4 new states**: bổ sung 4 entry mapping trong `admission_event_mapping.py`: `reviewing → giữ stage`, `result_published → mapping mới`, `admitted → sts09 (giống approved)`, `waitlisted → mapping mới`. Choice-engine fanout LEAD_STATUS_PROJECTED.
- **Update #10 — Phần 6 test strategy thêm cross-module regression**: fee payment + commission khi profile ở `admitted` (choice-engine state). Verify `is_admitted_like(profile)` helper trả `True` cho cả `approved` (legacy) và `admitted` (choice-engine). Regression suite cho phase_manager + reports cũng phải test cả 2 state.

### v2.1 — 2026-05-01 (round 9 review, 12 fix)
- **P1 fix #1 — Phase 2 NOT NULL không phá caller cũ**: ALTER `admission_round_id SET NOT NULL` ở Phase 2 sẽ reject path tạo bằng caller cũ (chưa migrate sang round). Sửa: Phase 2 ship **service-layer shim** TRƯỚC NOT NULL — endpoint create path nhận `academic_info_id` thiếu round → auto-resolve `DOT_1` của academic_info đó. Gate kiểm: 100% endpoint create path đã set round trong 1 tuần monitor → mới ALTER NOT NULL ở migration sau.
- **P1 fix #2 — `AdmissionStateService` guard `uses_choice_engine`**: `can_transition()` không check flag → legacy profile có thể đi qua flow mới, tạo `status_history`/outbox với state UI legacy không hiểu. Thêm pre-check: nếu `profile.uses_choice_engine = false` AND `to_status` thuộc {reviewing, result_published, admitted, waitlisted} → reject `BusinessRuleViolation("Legacy profile cannot enter choice-engine state")`. Ngược lại nếu `uses_choice_engine = true` AND `to_status` thuộc legacy {approved, resubmitted, overridden} → tương tự reject.
- **P1 fix #3 — Malformed `applied_rules` guard NULL/non-object**: `BACKFILL_MALFORMED_PATH_ID` insert query không bắt `applied_rules IS NULL` (operator JSON trả NULL → WHERE không true) + `jsonb_object_keys` fail nếu không phải object. Thêm guard `applied_rules IS NULL OR jsonb_typeof(applied_rules) <> 'object'` trước nhánh malformed; CASE bao quanh `jsonb_object_keys` chỉ gọi khi jsonb type = object.
- **P1 fix #4 — Rollback strategy B map về legacy state thật**: `result_published → reviewing` sai vì `reviewing` cũng là state mới (CHECK cũ reject sau downgrade). Map trực tiếp về legacy: `result_published → submitted`, `admitted → approved`, `waitlisted → submitted`, `reviewing → submitted`. Sau remap, assert `0 row` ở 4 state mới trước khi run downgrade CHECK migration.
- **P1 fix #5 — Score precision widening**: verified `AdmissionCriteria.min_score = Numeric(4,1)` (max 999.9), `max_possible_score = Numeric(5,2)` (max 999.99). V-ACT max 1200 sẽ overflow. Phase 2 thêm migration `phase2_04_widen_score_precision.py`: ALTER `min_score` → `Numeric(8,2)`, `min_subject_score` → `Numeric(8,2)`, `max_possible_score` → `Numeric(8,2)`. `PathSubjectGroupConfig.min_score`/`min_subject_score` định nghĩa `Numeric(8,2)` ngay từ đầu (Phase 2 #3).
- **P2 fix #6 — Outbox worker không hold DB tx khi gọi external IO**: pattern v2.0 vẫn lock row + `safe_dispatch` trong cùng transaction → giữ connection + row lock suốt thời gian gọi Zalo/email. Sửa 3-step: (1) short tx claim row (set `dispatched_at = NULL` + `attempts++` + commit), (2) external dispatch ngoài tx, (3) short tx mark success (`dispatched_at = now()`) hoặc failure (`last_error`).
- **P2 fix #7 — `applicable_to` query preserve legacy NULL**: nullable allow path cũ KHÔNG break, nhưng query `@>` không match NULL → bật filter audience ẩn toàn bộ path chưa backfill. Query contract sửa: `(applicable_to IS NULL OR applicable_to @> ARRAY[:audience]::admission_audience[])` trong Phase 1+2. Phase 3 trước enable filter ở FE: validator gate "X path null applicable_to → admin set trước"; sau gate, query bỏ NULL branch.
- **P2 fix #8 — `DocumentGroup.admission_path_id` index + invariant**: thêm partial index `CREATE INDEX ix_doc_group_path ON document_group (admission_path_id) WHERE admission_path_id IS NOT NULL`. Service invariant: `DocumentGroup.offering_type_id` + `admission_method_id` phải khớp với `admission_path` đang ref (qua AdmissionPath → ProgramOffering.offering_type_id + path.admission_method_id).
- **P2 fix #9 — Composite FK target UNIQUE**: composite FK `(admission_path_id, path_subject_group_config_id) → path_subject_group_config(admission_path_id, id)` cần UNIQUE `(admission_path_id, id)` trên target. PK trên id riêng KHÔNG đủ. 2 lựa chọn: (a) thêm `UNIQUE(admission_path_id, id)` trên `path_subject_group_config`, hoặc (b) bỏ composite FK, giữ chỉ service-layer invariant. Chốt: (b) — service invariant đủ defense, tránh redundant unique.
- **P2 fix #10 — Cheat sheet conduct/health backfill mâu thuẫn body**: cheat sheet ghi 4 scalar field backfill từ JSON, body chốt `conduct`/`health_category` không có nguồn → để NULL. Sửa cheat sheet: chỉ `gpa_overall` + `graduation_year` backfill from JSON; `conduct`/`health_category` admin manual review qua UI.
- **P2 fix #11 — Migration count stale** (HISTORICAL note v2.1; superseded by v2.13.1 cheat sheet count): tổng ghi Phase 1: 13, Phase 3: 2 nhưng chain thực có 07b + 09a/09b split + Phase 2 thêm `phase2_04_widen_precision` + ~~Phase 3 thêm `phase3_03_outbox`~~ (SUPERSEDED 2026-05-01 — phase3_03 moved Phase 1 #19a). Recount v2.1: Phase 0: 1, Phase 1: 14, Phase 2: 4, Phase 3: 3 (01, 02, 03). **Active count v2.13.1 (post Q9 defer + Phase 3 supersede): Phase 0 = 2, Phase 1 = 18, Phase 2 = 5, Phase 3 = 1 (chỉ còn phase3_01). Tổng 26 migration + 6 code task.**
- **P2 fix #12 — Rule (c) ambiguous scope**: insert `AMBIGUOUS_SELECTED_GROUP` cho mọi profile null sau rule a/b → flood exception cho draft/data lịch sử thiếu. Scope lại: chỉ áp dụng cho `status NOT IN ('draft','withdrawn')` AND `applied_rules ? 'admission_path_id'` AND `(applied_rules->>'admission_path_id') ~ '^[0-9]+$'`. Profile thiếu path data → exception type khác `INSUFFICIENT_DATA_FOR_BACKFILL`, không phải AMBIGUOUS.

### v2.0 — 2026-05-01 (round 8 review, 8 fix)
- **P1 fix #1 — Alembic chain wording chốt 1 nguồn**: migration #13 body v1.9 vẫn ghi `down_revision = Phase 0 revision id` (sai), trong khi ordering chính ghi `phase1_12 ← phase1_11`. Sửa toàn bộ wording về 1 chain duy nhất: `<head> → phase0 → phase1_01 → ... → phase1_11 → phase1_12_backfill_selected_subject_group_id`. Migration #13 `down_revision = phase1_11` (KHÔNG phải Phase 0). Phase 0 là ancestor của phase1_01, không trỏ trực tiếp.
- **P1 fix #2 — Phase 3 choice INSERT cast guard**: CTE `eligible_for_choice_creation` cast `(applied_rules->>'admission_path_id')::int` cùng JOIN với regex guard ở WHERE. Tách 2-step: CTE 1 filter key + regex, CTE 2 expose `admission_path_id_int` đã cast, rồi mới JOIN `path_subject_group_config`.
- **P1 fix #3 — Outbox table có migration chính thức** (HISTORICAL v2.0; SUPERSEDED 2026-05-01 — phase3_03 moved Phase 1 #19a-d, owner duy nhất cho outbox table giờ là `phase1_19a_create_outbox_table`): `notification_outbox` v1.9 chỉ define ở Phần 3.3.e nhưng KHÔNG có Alembic migration. ~~Thêm `phase3_03_create_notification_outbox.py` vào Phase 3 migration list (sau `phase3_02` seed events). Owner duy nhất cho table + index + UNIQUE constraint.~~ → Active: phase1_19a là owner.
- **P1 fix #4 — Staging cast overflow guard**: GPA staging cast `numeric(8,4)` sau regex format → `999999999999` pass regex nhưng overflow numeric(8,4). graduation_year cast `::int` có cùng lỗi với `99999999999`. Sửa: (a) regex thêm length guard `^[0-9]{1,3}(\.[0-9]+)?$` cho GPA, `^[0-9]{4}$` cho year; (b) staging cast vào unconstrained `numeric`/`bigint` để tránh overflow trước range check.
- **P2 fix #5 — Outbox worker commit-per-row vỡ lock**: worker `FOR UPDATE SKIP LOCKED` lock batch nhưng `commit()` trong loop → commit đầu release lock toàn batch → worker khác pick up duplicate. Sửa: 1 transaction per row (BEGIN-process-COMMIT loop) thay vì batch lock + per-row commit. Hoặc giữ batch + commit sau cả loop.
- **P2 fix #6 — Phase 3 exception order phải trước choice creation**: text nói "Step 1 INSERT exception trước, Step 2 INSERT choice", nhưng code SQL exception đặt sau score backfill (đoạn `BACKFILL_PATH_CONFIG_MISMATCH` nằm cuối). Sửa: di chuyển exception SQL block lên đầu, trước CTE `eligible_for_choice_creation`. CTE eligible anti-join `_admission_backfill_exceptions` đảm bảo profile flagged không tạo choice.
- **P2 fix #7 — GIN index query contract**: GIN array index không được dùng cho `:val = ANY(arr)` operator → query phổ biến không hit index. Spec rõ query contract: dùng `applicable_to @> ARRAY[:audience]::admission_audience[]` hoặc `applicable_to && ARRAY[:audiences]::admission_audience[]`. Service repository PHẢI dùng operator indexable, có `EXPLAIN ANALYZE` smoke test.
- **P2 fix #8 — Score backfill snapshot full**: SQL backfill `profile_choice_score` chỉ insert `max_score_snapshot` + `weight_snapshot`, thiếu `min_possible_score_snapshot`. Nếu schema NOT NULL hoặc engine validate range, profile cũ thiếu data. Thêm `min_possible_score_snapshot` từ `Subject.min_possible_score` (default 0 cho legacy).

### v1.9 — 2026-05-01 (round 7 review, 8 fix)
- **P1 fix #1 — CTE scope per-statement**: GPA + graduation_year backfill v1.8 dùng CTE qua 2 statement (UPDATE rồi INSERT exception) → CTE chỉ tồn tại trong 1 statement → INSERT fail `relation does not exist`. Sửa: dùng **temp table staging** trong migration (`CREATE TEMP TABLE _gpa_staging AS SELECT ...`) sau đó UPDATE từ staging + INSERT exception cùng staging. Drop temp tự động cuối transaction.
- **P1 fix #2 — Alembic linear chain**: Phase 0 + Phase 1 #13 down_revision mâu thuẫn (text nói #13 trỏ Phase 0, nhưng ordering ghi `01 → ... → 12`). Chốt **linear chain**: `<current head> → phase0 → phase1_01 → phase1_02 → ... → phase1_12 (backfill_selected_group) → phase1_14_workflow_audit_marker`. Phase 0 thành ancestor của phase1_01. Phase1_12 ngay sau phase1_11 (CHECK extend), không phải branch.
- **P1 fix #3 — Rule (a) cast guard tách CTE**: Rule (a) v1.7 vẫn cast `(applied_rules->>'admission_path_id')::int` cùng WHERE với regex guard. Sửa symmetric với Rule (b): tách `eligible_profiles_a` CTE filter key + regex TRƯỚC, expose cast int sau.
- **P1 fix #4 — Null semantics validation engine**: 6 rule v1.7 không spec rõ behavior khi threshold null hoặc profile scalar null. Bổ sung **Phần 3.1.a — Null semantics rules** chốt: (a) threshold null → SKIP rule; (b) threshold có giá trị + profile null → FAIL với code `MISSING_<FIELD>`; (c) enum conduct map ordinal `TB=1, KHA=2, TOT=3` cho compare; (d) health_category nhỏ hơn = tốt hơn; (e) Python compare None → wrap qua `Optional` checker, không direct compare.
- **P1 fix #5 — Quota guard concurrency**: service-layer sum check không an toàn under concurrent update (2 admin đồng thời tạo path/group). Bổ sung **Phần 5.a — Concurrency strategy**: (a) `SELECT ... FOR UPDATE` parent row trước khi compute sum, hoặc (b) advisory lock `pg_advisory_xact_lock(<academic_info_id>)` per academic_info, hoặc (c) `SERIALIZABLE` isolation cho endpoint quota-mutate. Chốt lựa chọn: pattern (a) + (b) (FOR UPDATE academic_info row + advisory lock cho round/path operations).
- **P1 fix #6 — Phase 3 choice backfill INSERT path**: v1.8 chỉ ghi exception SQL, KHÔNG có INSERT choice chính thức. Bổ sung INSERT path: CTE `eligible_for_choice_creation` (profile có `selected_subject_group_id` + path/config khớp + KHÔNG nằm trong exceptions) → `INSERT INTO admission_profile_choice ... SELECT ... ON CONFLICT DO NOTHING`. Score backfill cùng pattern. Thứ tự rõ: exception INSERT trước → choice INSERT sau (chỉ INSERT cho rows không vào exception).
- **P2 fix #7 — Lock trigger BEFORE UPDATE OF cols**: trigger `BEFORE UPDATE ON admission_profile` v1.8 fires mọi UPDATE (kể cả phone/email/status), query audit table redundant. Sửa thành `BEFORE UPDATE OF gpa_overall, conduct, health_category, graduation_year ON admission_profile`. Postgres bind trigger chỉ với 4 column này.
- **P2 fix #8 — Notification transactional outbox**: post-commit `safe_dispatch` vẫn gap (process crash sau commit → event lost). Bổ sung **Phần 3.3.e — Transactional outbox pattern**: tạo bảng `notification_outbox` (id, event_code, payload, created_at, dispatched_at NULL, attempts INT). Service `transition()` INSERT outbox row CÙNG transaction với status update. Worker scan outbox + dispatch + mark `dispatched_at` với retry/idempotency key. Direct `safe_dispatch` chỉ giữ cho non-critical events.

### v1.8 — 2026-05-01 (round 6 review, 5 fix)
- **P1 fix #1 — Maintenance bypass scope theo profile_ids**: trigger v1.7 chỉ check audit row cùng txid → 1 lần gọi `set_maintenance_mode([1,2])` cho phép update mọi `admission_profile` trong transaction (KHÔNG chỉ profile [1,2]). Sửa: trigger thêm guard `(audit.profile_ids IS NULL OR NEW.id = ANY(audit.profile_ids))`. NULL profile_ids = bypass toàn cục (chỉ DBA emergency); dùng explicit array cho normal admin maintenance.
- **P2 fix #2 — SECURITY DEFINER hardening search_path + revoke audit table writes**: function `set_maintenance_mode` thêm `SECURITY DEFINER SET search_path = admission_maint, pg_catalog`. Audit table `bypass_audit` REVOKE UPDATE, DELETE FROM PUBLIC + grant SELECT cho audit role. Tránh object shadowing + bảo vệ audit trail immutable.
- **P2 fix #3 — GPA backfill range guard**: regex chỉ check numeric format → `100`, `999.9` pass nhưng overflow `numeric(4,2)` hoặc sai nghiệp vụ. Cast trong CTE trung gian + filter `gpa_value BETWEEN 0 AND 10` trước UPDATE; out-of-range → `_admission_backfill_exceptions` với type `INVALID_GPA_VALUE`.
- **P2 fix #4 — graduation_year range guard**: regex `^[0-9]+$` cho phép `999999` overflow smallint. Filter `year_value BETWEEN 1900 AND 2100` (smallint range an toàn cho năm thực tế); out-of-range → exception `INVALID_GRADUATION_YEAR`.
- **P2 fix #5 — `selected_subject_group_id` single owner migration**: Phase 0 tạo column, Phase 1 #13 reference nó. Sửa rõ: Phase 0 revision là `down_revision` chính thức của Phase 1 #13. Phase 1 #13 chỉ backfill + exception (decision tree 3 rule), KHÔNG re-define column. Pre-flight verify column exists trước khi chạy migration #13.

### v1.7 — 2026-05-01 (round 5 review, 8 fix)
- **P1 fix #1 — Maintenance bypass txid token**: GUC `admission.maintenance_mode='on'` vẫn có thể `SET` trực tiếp qua psql, vô hiệu trigger. Đổi sang **txid-bound token**: function `admission_maint.set_maintenance_mode()` insert audit row với `txid_current()` + return token. Trigger check `EXISTS (SELECT 1 FROM admission_maint.bypass_audit WHERE txid = txid_current())`. SQL trực tiếp không gọi function → không có audit row cùng txid → trigger raise. SET GUC trực tiếp vô tác dụng.
- **P1 fix #2 — Cast guard tách CTE**: Rule (b) cast `(p.applied_rules->>'admission_path_id')::int` trong JOIN — Postgres không đảm bảo regex guard chạy trước cast. Tách `eligible_profiles` CTE: filter key + regex TRƯỚC, rồi cast sang `admission_path_id_int` riêng. Apply cho cả Phase 3 mismatch query.
- **P1 fix #3 — `jsonb_build_object` set-returning scalar fail**: `(SELECT jsonb_object_keys(...))` trả nhiều row → scalar subquery raise. Đổi sang `(SELECT jsonb_agg(k) FROM jsonb_object_keys(p.applied_rules) AS k)` hoặc lưu nguyên `p.applied_rules`.
- **P2 fix #4 — DISTINCT ON deterministic ORDER**: `SELECT DISTINCT ON (profile_id)` cần explicit `ORDER BY profile_id, ord DESC` — thứ tự từ CTE không phải contract. Apply cho GPA backfill.
- **P2 fix #5 — SECURITY DEFINER audit caller**: `current_user` trong SECURITY DEFINER là function owner, không phải caller thật. Đổi sang `session_user` + truyền explicit `reviewed_by_user_id` qua function param + lưu vào audit table.
- **P2 fix #6 — `ProfileChoiceScore` UNIQUE per-item**: thiếu `UNIQUE(profile_choice_id, path_subject_group_item_id)` — backfill/duplicate có thể tạo 2 score cho cùng môn cùng NV → engine tính sai. Thêm constraint.
- **P2 fix #7 — `AdmissionPath.admission_round_id` nullable schema lệch migration**: schema chính ghi nullable dual-write, migration Phase 2 ALTER NOT NULL. Schema cập nhật: nullable trong bước add/backfill, final NOT NULL sau Phase 2 #2 Step 3.
- **P3 fix #8 — Pattern C example unsafe**: ví dụ GPA backfill ở Phần 5b dùng `academic_history->-1->>'gpa'` (cũ, đã fix ở v1.6 migration 9a). Đổi pattern C ví dụ sang shape đã hardened, hoặc bỏ ví dụ GPA khỏi phụ lục để tránh copy-paste nhầm.

### v1.6 — 2026-05-01 (round 4 review, 9 fix)
- **P1 fix #1 — Exception table lifecycle chốt**: migration #12 sửa wording "Tạo bảng `_admission_backfill_exceptions`" thành "Reuse table đã tạo ở 7b". Dependency chain bổ sung 7b vào ordering chính thức.
- **P1 fix #2 — Rule (b) infer group-completeness**: SQL hiện chỉ count distinct groups có ít nhất 1 môn match. Sửa thành: profile match group X iff không có subject thuộc group X mà profile thiếu score (group-complete check). Ưu tiên match đúng count = required group size.
- **P1 fix #3 — Phase 3 backfill cast guard**: query `BACKFILL_PATH_CONFIG_MISMATCH` cast `applied_rules->>'admission_path_id'` thiếu key/numeric guard. Thêm `applied_rules ? 'admission_path_id' AND ... ~ '^[0-9]+$'` symmetric với rule (a)/(b).
- **P1 fix #4 — Path config table unique**: `path_subject_group_config` thêm `UNIQUE(admission_path_id, subject_group_id)`. `path_subject_group_item` thêm `UNIQUE(path_subject_group_config_id, subject_group_subject_id)`. Backfill dùng `ON CONFLICT DO NOTHING`.
- **P1 fix #5 — Round table unique trong migration**: Phase 2 #1 schema + migration phải có `UNIQUE(academic_info_id, round_code)` (đã reference trong pattern idempotent nhưng chưa trong migration body). Bổ sung vào schema `OfferingAdmissionRound`.
- **P2 fix #6 — GUC bypass tăng cường defense**: maintenance bypass đổi từ public GUC sang DB function `admission_set_maintenance_mode(reason text)` trong schema riêng `admission_maint`, GRANT EXECUTE chỉ cho role `admission_admin`. Trigger check qua function call (function set GUC + insert audit row trong cùng transaction). Người sửa SQL trực tiếp cần GRANT EXECUTE từ DBA — defense-in-depth.
- **P2 fix #7 — Backfill GPA filter rỗng**: SQL hiện `academic_history->-1->>'gpa'` lấy phần tử cuối bất kể có GPA. Sửa: `jsonb_array_elements(...) WITH ORDINALITY`, filter GPA numeric, order desc by ordinality, lấy first.
- **P2 fix #8 — graduation_year cast guard**: tương tự GPA, subquery cast `year_to::int` thiếu numeric check. Thêm regex `~ '^[0-9]+$'` filter trước khi cast. Row không suy được → exception `MISSING_GRADUATION_YEAR`.
- **P2 fix #9 — Role summary T12 align matrix**: Quy tắc role ở Phần 3.3.b vẫn chỉ liệt kê Candidate có T12. Sửa: T12 candidate/officer/admin, reason bắt buộc cho non-candidate.
- **P3 fix #10 — Timeline absolute baseline**: đổi "Tổng từ today" sang "Tổng từ baseline 2026-04-30 = 13 tuần". Buffer 0 unchanged.

### v1.5 — 2026-04-30 (round 3 review, 10 fix)
- **P1 fix #1 — Exception table tạo trước khi insert**: tách `_admission_backfill_exceptions` thành migration riêng `phase1_07b_create_backfill_exceptions_table.py` chạy sau #07 (demographics) và TRƯỚC #09a. Migration 9a + 12 + 13 chỉ insert vào table này, không tạo lại.
- **P1 fix #2 — Lock trigger không chặn admin review**: trigger 9b dùng pattern session GUC `current_setting('admission.maintenance_mode', true) = 'on'` để cho phép privileged maintenance. Service `AdmissionMaintenanceService.bulk_review_eligibility(...)` set GUC + audit log + reset, dùng cho UI admin nhập conduct/health/year cho hồ sơ submitted/approved.
- **P1 fix #3 — Backfill key đúng `admission_path_id`**: verified snapshot dùng key `admission_path_id` (KHÔNG phải `path_id`). Sửa rule (a) JOIN: `(p.applied_rules->>'admission_path_id')::int` + cast safe `WHERE applied_rules ? 'admission_path_id' AND (applied_rules->>'admission_path_id') ~ '^[0-9]+$'`.
- **P1 fix #4 — Inference scope theo path**: rule (b) sửa lại — JOIN với `CriteriaSubjectGroup` của chính path profile đang dùng, chỉ infer khi scores match đúng 1 group TRONG path. Tránh nhiễu do môn Toán xuất hiện ở nhiều group toàn hệ thống.
- **P1 fix #5 — Phase 3 backfill skip exceptions**: Phase 3 #1 sửa wording "mỗi profile → 1 choice" → "mỗi profile có `selected_subject_group_id IS NOT NULL` → 1 choice". Profile trong `_admission_backfill_exceptions` skip — admin review qua UI mới ship Phase 1+2.
- **P1 fix #6 — Unique mới không bảo vệ NULL round**: Phase 2 #2 add migration step: backfill `admission_round_id` cho 100% path → ALTER COLUMN SET NOT NULL → DROP unique cũ → CREATE unique mới. Service guard reject `admission_round_id IS NULL` ở mọi create/update path. NOT NULL phải áp trước khi drop unique cũ để chặn race window.
- **P1 fix #7 — Transition matrix T12 actor mismatch**: code sample `TRANSITION_MATRIX[("admitted","confirmed")]` chỉ có `{"candidate"}` nhưng bảng spec ghi candidate/officer/admin. Sửa code: `{"candidate", "officer", "admin"}`. Officer/admin confirm phải pass reason; candidate optional reason.
- **P2 fix #8 — Down CHECK constraint manual rollback**: migration #11 down ALTER CHECK về legacy chỉ chạy được nếu 0 row ở `reviewing/result_published/admitted/waitlisted`. Thêm pre-check raise `Exception("Manual rollback required - run status remap script first")` nếu detect new states. Symmetric với Phase 2 #2 unique swap.
- **P2 fix #9 — Service contract chốt 1 kiểu**: service trả `(profile, event_payload: dict | None)`, KHÔNG trả callback. Router commit DB xong gọi `safe_dispatch(**event_payload)`. Sửa toàn bộ wording còn nói "post_commit_callback" trong Phần 3.3.c thành event_payload.
- **P2 fix #10 — Nguyên tắc rollback-safe wording**: nguyên tắc #1 sửa wording để phân biệt rollback-safe (additive) vs manual rollback playbook (destructive). Tránh người implement hiểu nhầm rằng mọi migration auto-revert được.

### v1.4 — 2026-04-30 (round 2 review, 9 fix)
- **P1 fix #1 — Unique swap one-way**: Phase 2 #2 (drop `(academic_info_id, method_id)` + tạo `(round_id, method_id)`) là **one-way migration**. Sau khi prod đã tạo DOT_1/HB và DOT_2/HB cùng năm, down migration sẽ fail. Bổ sung rollback procedure: archive duplicate paths vào table `_archive_admission_path_dup` trước khi recreate constraint cũ. Xem Phần 4 Phase 2 #2.
- **P1 fix #2 — Backfill `selected_subject_group_id` decision tree**: snapshot `applied_rules` hiện không có `selected_group_code` (chỉ `allowed_subject_codes`, `subject_groups`, `subject_weights`). Backfill rule: (a) path có 1 group → auto-map. (b) path có nhiều group + hồ sơ chỉ có scores của 1 group → infer từ scores. (c) ambiguous → insert vào table `_admission_backfill_exceptions` cho admin manual review, KHÔNG tạo choice mơ hồ.
- **P1 fix #3 — Rollback playbook cho in-flight choice-engine profile**: tắt `FLAG_MULTI_NV_ENABLED` chỉ block profile mới. Profile đã `uses_choice_engine=true` ở `result_published/admitted/waitlisted` không tự về legacy. Bổ sung Phần 7.5 rollback playbook 3 chiến lược: freeze + read-only, status remap có kiểm soát, hoặc full DB restore từ snapshot pre-Phase-3.
- **P1 fix #4 — `approved → admitted` workflow audit task**: 11 file dùng `status='approved'` (admission_event_mapping, phase_manager, fees, commission, collaborator, state_machine, tasks, routers). Bổ sung Phase 1 task #14 audit + update toàn bộ workflow phụ thuộc, mapping `approved` (legacy) ↔ `admitted` (new) ở event_mapping layer trước khi flip choice-engine.
- **P2 fix #5 — `confirmed_via=manual` vi phạm CHECK**: model có `CHECK confirmed_via IN ('magic_link','admin_override','officer')`. T12 spec ghi "magic_link/manual" sai. Đổi wording về `magic_link / officer / admin_override` (đúng CHECK hiện có), KHÔNG thêm migration extend.
- **P2 fix #6 — Scalar backfill 9a chỉ backfill được `gpa_overall` + `graduation_year`**: `academic_history` JSON chỉ có `school_name/year_from/year_to/gpa/graduation_type`. `conduct` + `health_category` KHÔNG có nguồn — để NULL, admin review qua UI mới ở Phase 1+2. Migration 9a ghi rõ scope.
- **P2 fix #7 — Service guard sample dispatch trước commit**: code sample trong Phần 3.3.c gọi `await dispatch(db, ...)` trong service body — vi phạm "AFTER COMMIT" rule. Đổi sample: service chỉ build `event_payload: dict | None`, return `(profile, event_payload)`; router commit DB xong mới `await safe_dispatch(**event_payload)`.
- **P2 fix #8 — `ProfileChoiceScore.raw_score` precision**: model hiện `ProfileSubjectScore.score = Numeric(3,1)` (max 9.9). Plan mở rộng ABILITY_TEST max=150, V-ACT max=1200, IELTS max=9.0. Thay bằng `raw_score Numeric(8,2)` + service-layer validate `min_possible_score_snapshot ≤ raw_score ≤ max_score_snapshot`.
- **P3 fix #9 — Schema label `DegreeLevel` → `ConfigDegreeLevel`**: Phần 2.4 schema diagram update label cho khớp với migration text.

### v1.3 — 2026-04-30 (post-review hardened, 7 fix)
- **P1 fix #1 — ConfigDegreeLevel**: Bỏ tạo `degree_level` mới. Repo đã có `ConfigDegreeLevel` tại `app/models/config.py:53` (table `config_degree_level`). FK `MajorProgram.degree_level_id → config_degree_level.id`. Thêm `duration_default_semesters` vào catalog hiện có nếu cần (Phần 2.4).
- **P1 fix #2 — Status CHECK constraint + bỏ `admitted` state**: Phase 1 thêm migration ALTER CHECK constraint `ck_admission_profile_status` để bao gồm states mới (`reviewing`, `result_published`, `waitlisted`, `admitted` — không có `admitted` nữa). `admitted` đổi thành `status='admitted'` + `choice_priority` lưu ở `AdmissionProfileChoice` + status_history metadata (Phần 3.3.a + 3.3.b updated).
- **P1 fix #3 — AdmissionPath unique constraint**: Phase 2 phải drop unique `(academic_info_id, admission_method_id)` (constraint name `uq_admission_path_offering_method`) và thay bằng `(admission_round_id, admission_method_id)` để hỗ trợ multi-round trong cùng năm. Thêm vào migration #2 Phase 2.
- **P1 fix #4 — Choice constraints**: Thêm `UNIQUE(admission_profile_id, display_order)` trên `admission_profile_choice` (chặn 2 NV cùng priority). Service invariant: `path_subject_group_config.admission_path_id == admission_profile_choice.admission_path_id` (chặn config trỏ sai path).
- **P2 fix #5 — Idempotency per-row**: Pattern A "skip nếu table có row" lỗ — partial backfill fail giữa chừng → re-run skip → thiếu data. Đổi sang `INSERT ... SELECT ... WHERE NOT EXISTS` hoặc `ON CONFLICT (natural_key) DO NOTHING` per-source-row (Phần 5b updated).
- **P2 fix #6 — Status history actor model**: `transitioned_by` không thể là FK User cho mọi case (candidate qua magic_link không có User row). Tách thành `transitioned_by_user_id` (officer/admin/system caller có User) + `transitioned_by_lead_id` (candidate qua magic_link có Lead). Nullable cả 2 — system actor cả hai NULL (Phần 2.7 updated).
- **P2 fix #7 — Timeline re-anchor absolute dates**: Baseline 2026-04-30, Q1/2026 đã qua. Đổi sang mốc tuần tuyệt đối: Phase 0 (W1-W2 = 04-30 → 05-14), Phase 1 (W3-W5 = 05-14 → 06-04), Phase 2 (W6-W9 = 06-04 → 07-02), Phase 3 (W10-W13 = 07-02 → 07-30), mùa 2026 mở từ ~08-01 (Phần 7 updated).
- **Phase 0 hardening**: P1-3 fix `selected_group` BẮT BUỘC persist vào DB column `AdmissionProfile.selected_subject_group_id` (FK → `subject_group.id` nullable), không chỉ schema/request. Lý do: Phase 3 backfill `AdmissionProfileChoice` cần biết group thí sinh đã chọn — nếu chỉ trong request thì backfill phải đoán.

### v1.2 — 2026-04-30 (decision locked)
- **Phần 7**: chốt **multi-NV BẮT BUỘC cho mùa tuyển sinh 2026**. Timeline lock: Phase 0 start tuần này, Phase 1 cuối Q1/2026, Phase 2 giữa Q2/2026, Phase 3 cuối Q2/2026 (critical path). Bổ sung 5 điểm risk mitigation cho Phase 3 + pre-mùa 2026 checklist 8 mục.

### v1.1 — 2026-04-30
- **Phần 2.5**: thêm `AdmissionProfile.uses_choice_engine` boolean flag (thay thế logic count-of-choices để chọn state machine).
- **Phần 2.6**: thêm bảng `admission_profile_status_history` cho audit trail mọi transition.
- **Phần 2.3**: chốt Pydantic `ScoreFormulaConfig` discriminated union validate khi save `PathSubjectGroupConfig`; whitelist formula type theo phase.
- **Phần 3.3**: thay thế hoàn toàn — bổ sung 17 transition matrix (4 actor: thí sinh/officer/admin/system), 12 milestone events (gộp `admitted` về 1 event với `choice_priority` payload), service guard `can_transition()`. Manual claim workflow giữ nguyên (KHÔNG auto `submitted → reviewing`). `result_published` yêu cầu admin trigger trước khi system fanout decisions.
- **Phần 4 Phase 1**: tách migration #8 thành `8a (add fields + backfill JSON → scalar)` → `8b (create lock trigger)`. Thêm migration #9 cho `admission_profile_status_history`. Thêm "Migration ordering & dependencies" subsection với `depends_on` chain rõ ràng.
- **Phần 4 Phase 3**: 12 events seed (thay vì 4); 3 feature flags rõ ràng (`FLAG_MULTI_NV_ENABLED`, `FLAG_USE_PATH_CONFIG`, `FLAG_USE_BONUS_RULE`).
- **Phần 5b** (mới): idempotency pattern cho mọi backfill script.
- **Phần 8**: cheat sheet update theo các thay đổi trên.

### v1.0 — 2026-04-30
- Baseline implementation-ready sau khi align field name với DB thực tế.

---

## Phần 1 — Mục tiêu nghiệp vụ

Hệ thống QLTS hiện đã quản trị tốt mức "cấu hình tuyển sinh cơ bản + hồ sơ đơn nguyện vọng". Mục tiêu refactor: nâng lên mức "engine xét tuyển thực sự", giải quyết 7 nhóm yêu cầu:

1. **Đa đợt tuyển sinh trong một năm** (đợt 1, đợt 2, bổ sung) với chỉ tiêu và mốc thời gian riêng.
2. **Chia chỉ tiêu theo phương thức** (60% học bạ, 40% TN THPT...) — hiện chỉ có quota tổng năm.
3. **Filter phương thức theo đối tượng thí sinh** (post-THCS không thấy phương thức TN THPT).
4. **Đa loại điểm xét** trong tổ hợp: môn học truyền thống, TB học kỳ, ĐGNL, chứng chỉ.
5. **Override ngưỡng theo path** mà không phá catalog tổ hợp dùng chung.
6. **Cộng điểm ưu tiên** khu vực và đối tượng theo Quy chế Bộ GD&ĐT.
7. **Đăng ký đa nguyện vọng** với thứ tự ưu tiên, mỗi NV xét độc lập.

---

## Phần 2 — Schema cuối (đã verify trên model thực tế 2026-04-30)

Field/bảng bổ sung đánh dấu **`(MỚI)`**. Field giữ nguyên không có nhãn.

### 2.1. Cây cấu hình tuyển sinh

```
MajorProgram
├── id
├── name                                    [hiện có]
├── degree_level                            text — giữ
├── degree_level_id                         (MỚI) FK → ConfigDegreeLevel
│                                              (config_degree_level.id), dual-write
├── code                                    UNIQUE
├── is_active
├── is_heavy
└── unit_id                                 FK → organization_unit

ProgramOffering
├── id
├── program_id                              FK → MajorProgram   ← TÊN ĐÚNG
├── offering_type_id                        FK → ConfigOfferingType
├── duration_semesters
├── scoring_rules                           JSON
├── is_active                               ← KHÔNG đổi sang status
│
├── DocumentGroup[]                         bảng đã có, mở rộng
│   ├── id
│   ├── offering_type_id
│   ├── admission_method_id                 nullable
│   ├── admission_path_id                   (MỚI) nullable, override sâu hơn
│   ├── code                                UNIQUE bắt buộc
│   ├── name
│   ├── description
│   ├── is_active
│   └── DocumentGroupItem[]
│       ├── group_id                        ← TÊN ĐÚNG (không phải document_group_id)
│       ├── document_type_id                FK → ConfigDocumentType   ← TÊN ĐÚNG
│       ├── is_mandatory
│       ├── requires_upload
│       ├── submission_format
│       └── display_order
│
└── OfferingAcademicInfo[]
    ├── id
    ├── offering_id                         FK → ProgramOffering   ← TÊN ĐÚNG
    ├── academic_year                       UNIQUE (offering_id, academic_year)
    ├── annual_admission_quota
    ├── is_published, is_deleted
    │
    ├── OfferingSemesterTuition[]
    │   ├── academic_info_id
    │   ├── semester_no
    │   ├── amount
    │   └── notes                           ← TÊN ĐÚNG (không phải note)
    │
    └── OfferingAdmissionRound[]            (MỚI)
        ├── id
        ├── academic_info_id
        ├── round_code                      DOT_1 / DOT_2 / BO_SUNG
        ├── round_name
        ├── start_date, end_date
        ├── round_quota                     nullable; sum ≤ annual ở SERVICE
        │                                              Số slot ĐĂNG KÝ tối đa cho round.
        ├── admit_quota                     (MỚI v2.13 Q6) INT NULL
        │                                              Số slot TRÚNG TUYỂN tối đa cho round
        │                                              (có thể < round_quota — round nhận 200
        │                                               đăng ký nhưng chỉ admit 100).
        │                                              Nullable: NULL = không giới hạn admit
        │                                              (admit_quota = round_quota mặc định).
        │                                              Engine T7 (result_published → admitted)
        │                                              guard: count(admitted in round) < admit_quota.
        ├── submission_count                (MỚI v2.11) INT NOT NULL DEFAULT 0
        │                                              Atomic increment khi candidate submit
        │                                              (P1 fix #5 — chống race candidate submit)
        ├── is_active
        ├── archived_at                     (MỚI v2.10) TIMESTAMPTZ NULL
        │                                              Set khi round end_date + 6 months;
        │                                              cron job `archive_expired_rounds_task`
        │                                              move profile sang archive table
        ├── extended_at, extended_by_user_id, extension_reason  (MỚI v2.10)
        │                                              Audit cho admin extend end_date
        └── UNIQUE (academic_info_id, round_code)
                                              ← chặn duplicate round; cho phép
                                                INSERT ON CONFLICT idempotent

#### 2.1.a. Round lifecycle — in-flight profile khi end_date qua (P1 fix #8 v2.10)

`OfferingAdmissionRound.end_date` không chỉ filter storefront mà còn governs profile lifecycle. 4 rule bắt buộc:

**Rule 1 — Cutoff submit khi end_date hết hạn**:
Candidate magic_link `/api/v2/public/admissions/{token}/submit` validate `round.end_date >= NOW()`. Nếu hết hạn → 410 Gone:
```python
async def submit_endpoint(profile: AdmissionProfile = Depends(get_profile_by_magic_link_token)):
    round = await db.get(OfferingAdmissionRound, profile.applied_rules['admission_round_id'])
    if round.end_date < datetime.now(timezone.utc):
        raise HTTPGone("Đợt tuyển sinh đã đóng. Liên hệ tư vấn viên để được hỗ trợ.")
    # ... continue submit logic
```
Token vẫn valid (chưa `confirmed_at`) — KHÔNG revoke. Officer có thể extend round (Rule 2) → token reuse được.

**Rule 2 — Admin extension** với audit log mandatory:
Endpoint `/api/v2/admin/rounds/{id}/extend` admin only:
```sql
UPDATE offering_admission_round
SET end_date = :new_end_date,
    extended_at = NOW(),
    extended_by_user_id = :admin_id,
    extension_reason = :reason
WHERE id = :round_id;
```
Phase 1 #19 thêm 3 column audit `extended_at`, `extended_by_user_id`, `extension_reason`. Reason ≥10 chars mandatory.

**Rule 3 — Cleanup policy 6-month archive**:
Cron job `archive_expired_rounds_task` chạy hàng tuần:
```sql
-- Archive profile của round đã end_date + 6 months
INSERT INTO _archived_admission_profile (...)
SELECT * FROM admission_profile p
JOIN offering_admission_round r ON r.id = (p.applied_rules->>'admission_round_id')::int
WHERE r.end_date < NOW() - INTERVAL '6 months'
  AND r.archived_at IS NULL;

UPDATE offering_admission_round
SET archived_at = NOW()
WHERE end_date < NOW() - INTERVAL '6 months' AND archived_at IS NULL;
```
KHÔNG xoá profile gốc (audit trail giữ); chỉ move sang archive table cho query report nhanh hơn.

**Rule 4 — Engine xét tuyển scope**:
Engine chỉ chạy cho profile của round có `is_active=true AND end_date >= NOW() - INTERVAL '30 days'` (cho phép retroactive review trong 30 ngày sau end_date). Sau 30 ngày → admin override only (T17 rollback hoặc admin manual force).

**Late submit business rule (Q2 chốt 2026-05-01 v2.13)**:
- ✅ **Strict cutoff theo `end_date`**, `grace_period_hours = 0` cho mùa 2026.
- ❌ KHÔNG thêm `grace_period_hours` field — defer Phase 4+ (Q1/2027) nếu nghiệp vụ thực tế phát sinh need.
- Workflow extend round: nếu cần kéo dài, dùng admin endpoint `/api/v2/admin/rounds/{id}/extend` (Rule 2 ở trên) với audit log mandatory + reason ≥10 chars.
```

### 2.2. AdmissionPath

```
AdmissionPath
├── id
├── academic_info_id                        GIỮ Phase 1-2-3, drop Phase 4
├── admission_round_id                      (MỚI) Phase 2 #2 Step 1: nullable
│                                              Phase 2 #2 Step 3: ALTER NOT NULL
│                                              Final: NOT NULL + service guard reject NULL
├── admission_method_id                     FK → AdmissionMethod
├── criteria_id                             FK → AdmissionCriteria (1-1)
├── display_order                           ← DÙNG field hiện có
├── status                                  ← TÊN ĐÚNG: draft/active/inactive/archived
├── display_name
├── visibility
├── application_fee
├── allow_unverified_submission             ← đã có
├── minor_correction_allowed_fields         ← đã có
├── activated_at, activated_by
├── created_at, updated_at
│
├── applicable_to[]                         (MỚI) ARRAY ENUM, GIN INDEX
│                                              POST_THCS / POST_THPT / LIEN_THONG_TC /
│                                              LIEN_THONG_CD / VLVH
├── method_quota                            (MỚI) nullable
└── bonus_rule_override                     (MỚI) JSONB nullable, hiếm dùng
                                               (default lấy từ AdmissionMethod)
```

**Service-layer invariant:**
```
path.academic_info_id == path.admission_round.academic_info_id
```
Validate ở mọi tạo/sửa path. Lệch → raise integrity error.

**Resolution rule cho `DocumentGroup` (chốt rõ trong service):**
```
1. WHERE admission_path_id = X                         → match → dùng bộ này
2. WHERE admission_method_id = Y AND admission_path_id IS NULL  → fallback method
3. WHERE offering_type_id = Z AND admission_method_id IS NULL   → default offering type
```

### 2.3. AdmissionCriteria + PathSubjectGroupConfig + Item

```
AdmissionCriteria
├── id
├── min_gpa
├── min_score
├── min_subject_score
├── conditions                              ← TÊN ĐÚNG (không phải note)
├── min_conduct                             (MỚI) ENUM: TB / KHA / TOT
├── min_health_category                     (MỚI) smallint 1-4
├── required_graduation_year_min            (MỚI) nullable
└── required_graduation_year_max            (MỚI) nullable

CriteriaSubjectGroup[]                      bảng cũ, GIỮ Phase 1-2-3, deprecate Phase 4

PathSubjectGroupConfig[]                    (MỚI) thay thế CriteriaSubjectGroup
├── id
├── admission_path_id
├── subject_group_id                        FK → SubjectGroup catalog (KHÔNG phá)
├── min_score                               Numeric(8,2) — override ngưỡng tổng tổ hợp ở path này
│                                              Đủ chứa scale DGNL=150, V-ACT=1200, IELTS=9.0
├── min_subject_score                       Numeric(8,2) — override điểm liệt ở path này
├── group_quota                             nullable; sum ≤ method_quota ở SERVICE
├── score_formula                           JSONB optional, validate qua Pydantic
│                                              ScoreFormulaConfig (xem 2.3.a)
│     {"type": "weighted_sum", "rounding": 2}
│
├── UNIQUE (admission_path_id, subject_group_id)  ← chặn duplicate config
│                                                   cho cùng path-group
│
└── PathSubjectGroupItem[]                  (MỚI) override item-level
    ├── id
    ├── path_subject_group_config_id
    ├── subject_group_subject_id            FK → catalog item gốc
    ├── weight_override                     nullable, fallback catalog weight
    ├── is_principal                        (MỚI) môn chính, dùng tie-break
    ├── min_score_override                  nullable
    └── UNIQUE (path_subject_group_config_id, subject_group_subject_id)
                                              ← chặn duplicate item override
                                                cho cùng config-catalog-item
```

**Composite invariant cho `PathSubjectGroupItem`:**
```
subject_group_subject.subject_group_id
    == path_subject_group_config.subject_group_id
```
Enforce ở service layer (tạo/sửa item). Tùy chọn: composite FK
`(subject_group_subject_id, subject_group_id) → subject_group_subject(id, subject_group_id)`
nếu cần defense-in-depth ở DB level.

#### 2.3.a. `score_formula` schema validation (Pydantic discriminated union)

`PathSubjectGroupConfig.score_formula` là JSONB raw → footgun runtime nếu admin nhập sai shape. Validate qua Pydantic `ScoreFormulaConfig` trong service `save/update PathSubjectGroupConfig`, KHÔNG để engine load runtime mới phát hiện.

```python
# app/schemas/admission_scoring.py (Phase 2)

from typing import Literal, Annotated, Union
from pydantic import BaseModel, Field

class WeightedSumFormula(BaseModel):
    type: Literal["weighted_sum"]
    rounding: int = Field(ge=0, le=4, default=2)
    scale: float = Field(gt=0, default=1.0)

class CustomFormula(BaseModel):
    """Phase 3+ — chỉ enable khi engine register handler."""
    type: Literal["custom"]
    handler_code: str  # registered handler key
    params: dict = Field(default_factory=dict)

ScoreFormulaConfig = Annotated[
    Union[WeightedSumFormula, CustomFormula],
    Field(discriminator="type")
]
```

**Whitelist formula type theo phase:**
- Phase 2: chỉ `weighted_sum`. Mọi config có `type` khác → reject ở save endpoint.
- Phase 3+: thêm `custom` (handler-based) khi đã có handler registry.
- Mỗi formula type phải có ≥3 unit test riêng (Phần 6 test strategy).

### 2.4. Catalog dùng chung (mở rộng pragmatic, không phá)

```
SubjectGroup (KHÔNG đổi cấu trúc)
├── id
├── code                                    A00, B00, C00, D01, custom_HB12...
├── name
├── display_order                           ← đã có
└── is_active

SubjectGroupSubject (catalog item — KHÔNG sửa weight)
├── id
├── subject_group_id
├── subject_id
├── position                                ← TÊN ĐÚNG (không phải display_order)
└── weight                                  Numeric(3,2) default 1.0 — đã có

Subject (mở rộng)
├── id
├── code                                    TOAN, LY, HOA, ..., TB_HK1_L12,
│                                              TB_CN_L12, DGNL_DHQGHN, V_ACT, IELTS, ...
├── name_vi                                 ← TÊN ĐÚNG (không phải name)
├── display_order
├── is_active
├── subject_kind                            (MỚI) ENUM:
│                                              ACADEMIC_SUBJECT — môn học (Toán, Lý, ...)
│                                              TERM_AVERAGE     — TB học kỳ / TB cả năm
│                                              ABILITY_TEST     — bài thi đánh giá năng lực
│                                              CERTIFICATE      — chứng chỉ (IELTS, nghề...)
├── max_score                               (MỚI) 10 / 150 / 1200 / 9.0
└── min_possible_score                      (MỚI)

⚠️ **Score >10 BRIDGE CONTRACT (P1 fix v2.3):**
Legacy `ProfileSubjectScore.score` có CHECK constraint `(score >= 0 AND score <= 10)` ở `app/models/admission_config/profile_data.py:69`. Pydantic schema `app/schemas/admission.py:174` validate `0..10`. FE Zod `frontend/src/lib/zod/admissions.ts:137` cap `0..10`. 3 layer constraint trên CHỈ áp dụng cho legacy `ProfileSubjectScore` (single-NV).

**Gate cho subject_kind > ACADEMIC_SUBJECT:**
- Phase 1 #5 seed các subject ảo (TB_HK1_L12, DGNL_DHQGHN, V_ACT, IELTS...) với `subject_kind != ACADEMIC_SUBJECT` + `max_score > 10`.
- Phase 1+2: KHÔNG expose subject này qua legacy API/UI (single-NV `ProfileSubjectScore` flow). Nếu admin tạo `CriteriaSubjectGroup` ref subject_kind != ACADEMIC_SUBJECT → service raise "Use Phase 3 multi-NV API for non-academic subjects".
- Phase 3: `ProfileChoiceScore.raw_score Numeric(8,2)` KHÔNG có CHECK 0..10 (xem Phần 2.6) → cho phép DGNL/V-ACT/IELTS qua choice flow.
- Phase 4: deprecate legacy `ProfileSubjectScore` CHECK + Pydantic + FE cap khi 0 caller dùng legacy single-NV.

Service guard ship cùng Phase 1 #5:
```python
def validate_subject_kind_for_path_config(subject_id, path_config):
    subject = db.get(Subject, subject_id)
    if subject.subject_kind != 'ACADEMIC_SUBJECT' and not path_config.path.uses_choice_engine:
        raise BusinessRuleViolation(
            f"Subject kind {subject.subject_kind} only allowed via choice-engine API"
        )
```

AdmissionMethod (catalog)
├── id
├── code                                    HB / TN_THPT / DGNL / XT_KET_HOP / TUYEN_THANG
├── name
├── description
├── requires_gpa, requires_subject_scores
├── display_order
├── is_active
└── default_bonus_rule                      (MỚI) JSONB ở method level
                                               {
                                                 "apply_area_bonus": true,
                                                 "apply_subject_bonus": true,
                                                 "max_total_bonus": 2.75
                                               }

ConfigDegreeLevel                           (đã có tại app/models/config.py:53,
│                                            table `config_degree_level`)
├── id
├── code                                    cao_dang / dai_hoc / thac_si / tien_si
├── name                                    UNIQUE
└── duration_default_semesters              (MỚI nếu chưa có — verify trước migration)
                                              FK target: MajorProgram.degree_level_id
                                              → config_degree_level.id
```

**Bonus rule resolution:**
```
effective_bonus_rule = path.bonus_rule_override
                       ?? path.admission_method.default_bonus_rule
                       ?? {"apply_area_bonus": false, "apply_subject_bonus": false}
```

### 2.5. Bên Application — mở rộng `AdmissionProfile` (KHÔNG tạo song song)

```
AdmissionProfile                            (gốc đã có, mở rộng field)
├── id
├── lead_id                                 FK → Lead, GIỮ NGUYÊN
├── academic_year
├── status                                  state machine đã có (draft/submitted/approved/
│                                              rejected/confirmed/enrolled/resubmitted/
│                                              overridden/revision_requested/withdrawn)
├── applied_rules                           JSONB ← TÊN ĐÚNG, immutability trigger active
├── version                                 optimistic locking
├── (full_name, dob, gender, citizen_id, ...)
├── permanent_province, permanent_district, permanent_ward
├── disability_type, ethnicity, religion
│
├── area_code                               (MỚI) KV1 / KV2_NT / KV2 / KV3
│                                              auto-compute từ permanent_province/district/ward
│                                              admin override được
├── priority_object_codes[]                 (MỚI) ARRAY: ["01", "06"]
│                                              auto-suggest 04 nếu disability_type IS NOT NULL
├── candidate_education_level               (MỚI) POST_THCS / POST_THPT / LIEN_THONG_TC / ...
│                                              snapshot tại thời điểm tạo profile
│                                              (KHÔNG share live với Lead.education_level)
│
├── gpa_overall                             (MỚI) Numeric(4,2), nullable, lock-after-draft
├── conduct                                 (MỚI) ENUM TB/KHA/TOT, nullable, lock-after-draft
├── health_category                         (MỚI) smallint 1-4, nullable, lock-after-draft
├── graduation_year                         (MỚI) smallint, nullable, lock-after-draft
└── uses_choice_engine                      (MỚI) Boolean, default false, NOT NULL
                                               false → state machine cũ (legacy)
                                               true  → state machine mới (multi-NV)
                                               KHÔNG dựa vào count(choices) — backfill Phase 3
                                               sẽ tạo 1 choice cho mọi profile cũ → count
                                               không còn distinguish được legacy vs new.
```

**Lock-after-draft:** DB trigger block UPDATE 4 field trên khi `status NOT IN ('draft', 'revision_requested')`. Lý do dùng trigger thay vì service guard: QLTS có history admin sửa data trực tiếp qua SQL (memory: officers enable `lead.zalo_bot` qua SQL; backfill scripts `zbaudit001`/`leadexp001`...). Service guard bypass được; trigger không.

```sql
CREATE TRIGGER trg_lock_profile_eligibility_fields
  BEFORE UPDATE OF gpa_overall, conduct, health_category, graduation_year
  ON admission_profile
  FOR EACH ROW
  WHEN (OLD.status NOT IN ('draft', 'revision_requested'))
  EXECUTE FUNCTION raise_locked_field_error();
```

`revision_requested` được mở để tích hợp với cơ chế `allow_unverified_submission` + `minor_correction_allowed_fields` đã có ở `AdmissionPath` (officer xin chỉnh sửa hồ sơ sau submit hợp lệ).

### 2.5.a. `Lead.gpa` deprecation timeline (cross-module sync)

`Lead.gpa Float` (verified `app/models/lead.py:111`) hiện được read 4+ sites: `admission_service.py:3430,3520,3718` + `lead_service.py:618` (export). Plan thêm `AdmissionProfile.gpa_overall` cần spec dual-write/read strategy rõ để không drift giữa Lead và Profile.

| Phase | Lead.gpa | Profile.gpa_overall | Reader strategy |
|---|---|---|---|
| Phase 1 (W3-W5) | Giữ nguyên, write cũ | Thêm field + backfill từ JSON | **Dual-read fallback**: service đọc Profile.gpa_overall trước; null → fallback Lead.gpa. Helper `effective_gpa(profile)` ở `app/services/admission_compat.py`. |
| Phase 2 (W6-W9) | Giữ + dual-write từ service layer | Source of truth cho engine | **Dual-write**: mọi endpoint update Lead.gpa cũng write Profile.gpa_overall. Lead pipeline filter vẫn dùng Lead.gpa (chưa migrate). |
| Phase 3 (W10-W13) | Read-only, deprecated | Source of truth | Lead pipeline filter migrate qua relationship `lead.profile.gpa_overall` (selectinload eager-load). Endpoint update Lead.gpa raise deprecation warning + still dual-write. |
| Phase 4 (Q4/2026+) | DROP COLUMN | Sole storage | Migration phase4_drop_lead_gpa.py sau khi grep codebase + log production xác nhận 0 caller cũ. |

**Code task ship cùng Phase 1**: helper `effective_gpa(profile)` trong `admission_compat.py`:
```python
def effective_gpa(profile: AdmissionProfile) -> Optional[Decimal]:
    """Phase 1 dual-read fallback. Profile source first, Lead fallback."""
    if profile.gpa_overall is not None:
        return profile.gpa_overall
    if profile.lead and profile.lead.gpa is not None:
        return Decimal(str(profile.lead.gpa))
    return None
```
Tất cả 4 read site (admission_service.py:3430/3520/3718, lead_service.py:618) update qua helper này.

#### 2.5.b. Lead pipeline projection rule cho multi-year multi-profile

`Lead.consultation_status` reflect lead pipeline stage projected từ profile state. Multi-year (Phase 1 #15) → 1 lead có nhiều profile → projection ambiguous. Spec rule:

**System config `current_intake_year`**: chốt 1 năm là "intake hiện tại" (2026 cho mùa 2026). Stored ở `system_config` table, admin update qua admin panel.

**Projection rule với fallback chain (P1 fix #4 v2.11 — chống orphan khi `current_intake_year` flip)**:

```python
# app/services/lead_admission_sync.py — fallback chain priority
TERMINAL_ADMISSION_STATUSES = {'enrolled', 'rejected', 'withdrawn', 'overridden'}

def project_lead_consultation_status(lead) -> str:
    """Multi-year aware projection với 3-tier fallback chain.

    Tránh scenario: admin flip current_intake_year=2026→2027 sau mùa close →
    1000 lead enrolled mùa 2026 không có profile 2027 → status reset → mất tracking.
    """
    current_year = config.get('current_intake_year')  # e.g. 2026

    # Priority 1: profile của current_intake_year (active recruitment)
    current = lead.current_admission_profile(current_year)
    if current is not None:
        return ADMISSION_TO_LEAD_STAGE_MAP[current.status]

    # Priority 2: profile năm gần nhất với status TERMINAL → giữ làm anchor
    # Lead enrolled mùa cũ vẫn có stage 'sts11' (đã ghi danh) cho dashboard tracking.
    last_terminal = lead.last_terminal_admission_profile()  # ORDER BY academic_year DESC LIMIT 1
    if last_terminal is not None and last_terminal.status in TERMINAL_ADMISSION_STATUSES:
        return ADMISSION_TO_LEAD_STAGE_MAP[last_terminal.status]

    # Priority 3: pre-admission stage (lead chưa apply mùa nào)
    return lead.consultation_status_pre_admission or 'sts_new'
```

**Helper mới ở Lead model**:
```python
class Lead(Base):
    def last_terminal_admission_profile(self) -> Optional[AdmissionProfile]:
        """Profile gần nhất có status TERMINAL — anchor cho lifetime tracking."""
        terminal_profiles = [
            p for p in self.admission_profiles
            if p.status in TERMINAL_ADMISSION_STATUSES
        ]
        return max(terminal_profiles, key=lambda p: p.academic_year, default=None)

    async def current_admission_profile(self, year: int, db) -> Optional[AdmissionProfile]:
        """Resolve profile theo year. UNION query active + archive (P1 fix #6 v2.12).

        v2.10 archive cron move profile end_date+6 months → _archived_admission_profile.
        Helper PHẢI query cả 2 table để officer thấy lead history đầy đủ.
        """
        # Priority 1: active table
        active = next((p for p in self.admission_profiles if p.academic_year == year), None)
        if active is not None:
            return active

        # Priority 2: archive table — index `(lead_id, academic_year)` cho query nhanh
        archived = await db.execute(
            select(ArchivedAdmissionProfile)
            .where(ArchivedAdmissionProfile.lead_id == self.id)
            .where(ArchivedAdmissionProfile.academic_year == year)
        ).scalar_one_or_none()
        return archived  # None nếu không có
```

**Migration `_archived_admission_profile` table** (Phần 7.5 archive cron) thêm index:
```sql
CREATE INDEX ix_archived_profile_lead_year
    ON _archived_admission_profile (lead_id, academic_year);
```

**UI display strategy**:
- Officer dashboard hiển thị `current_intake_status` (project current_year) + badge nhỏ "Lifetime: enrolled 2026" nếu có terminal anchor năm cũ.
- Lead detail tab `Lịch sử tuyển sinh` liệt kê toàn bộ profiles per year với status terminal.

**KPI count rule**: 1 lead × N year = N funnel entries (mỗi profile/year là 1 entry). Lead với year history `{2025: enrolled, 2026: reviewing}` count vào 2 funnel khác nhau (mùa 2025 + mùa 2026), không gộp.

**Lead detail UI**: tab per-year switcher; default tab = `current_intake_year`; tab cũ hiển thị read-only history (không cho thao tác trừ admin override).

**Officer dashboard**: filter lead theo year → query `WHERE EXISTS (SELECT 1 FROM admission_profile WHERE lead_id = lead.id AND academic_year = :year)`.

### 2.6. Multi-NV: AdmissionProfileChoice + ProfileChoiceScore (Phase 3)

```
AdmissionProfileChoice                      (MỚI) các nguyện vọng
├── id
├── admission_profile_id                    FK → AdmissionProfile
├── display_order                           thứ tự NV (1, 2, 3...)
├── admission_path_id                       FK → AdmissionPath
├── path_subject_group_config_id            FK → PathSubjectGroupConfig (KHÔNG FK catalog
│                                              trực tiếp — giữ override path-level)
├── computed_raw_score                      cache
├── computed_bonus                          cache
├── computed_total_score                    cache
├── eligibility_check_result                JSONB chi tiết pass/fail từng rule
├── bonus_rule_snapshot                     JSONB — effective bonus rule lúc xét
├── decision                                eligible / ineligible / admitted /
│                                              waitlisted / rejected
└── decision_at

UNIQUE (admission_profile_id, admission_path_id, path_subject_group_config_id)
  — không cho phép NV trùng tổ hợp y hệt
UNIQUE (admission_profile_id, display_order)
  — không cho phép 2 NV cùng priority (NV1 chỉ có 1 choice, NV2 chỉ có 1 choice...)

Service-layer invariant (composite consistency):
  path_subject_group_config.admission_path_id == admission_profile_choice.admission_path_id
  Validate ở mọi tạo/sửa choice. Lệch → raise integrity error.

  **Chốt: Service-layer invariant ONLY, KHÔNG composite FK ở DB**. Lý do:
  Composite FK `(admission_path_id, path_subject_group_config_id) → path_subject_group_config(admission_path_id, id)`
  đòi hỏi UNIQUE `(admission_path_id, id)` trên target table. PK riêng trên `id`
  + UNIQUE `(admission_path_id, subject_group_id)` đã có KHÔNG đủ. Thêm UNIQUE
  redundant `(admission_path_id, id)` chỉ để hỗ trợ composite FK là noise.
  Service guard đủ defense vì mọi caller phải đi qua service (router không trực tiếp insert).

ProfileChoiceScore                          (MỚI) điểm từng môn
├── id
├── profile_choice_id                       FK → AdmissionProfileChoice
├── path_subject_group_item_id              FK → PathSubjectGroupItem
│                                              ON DELETE SET NULL
│                                              (snapshot fields giữ truth)
│
├── subject_code_snapshot                   snapshot tại thời điểm nộp
├── subject_name_snapshot
├── max_score_snapshot                      Numeric(8,2) — chứa được 1200 (V-ACT)
├── min_possible_score_snapshot             Numeric(8,2)
├── weight_snapshot                         effective weight đã resolve override
│
├── raw_score                               Numeric(8,2) NOT NULL — đủ chứa
│                                              ACADEMIC max 10.0, ABILITY_TEST max 150 hoặc
│                                              1200 (V-ACT), CERTIFICATE max 9.0 (IELTS)
│                                              KHÔNG dùng Numeric(3,1) như ProfileSubjectScore
│                                              hiện có (max 9.9 — sẽ overflow cho DGNL/V-ACT)
│                                            Service-layer validate:
│                                              min_possible_score_snapshot ≤ raw_score ≤ max_score_snapshot
├── source                                  SELF_DECLARED / VERIFIED_BY_DOCUMENT /
│                                              FETCHED_FROM_MOET
├── verified_at, verified_by
├── document_url                            link scan học bạ / phiếu điểm
└── UNIQUE (profile_choice_id, path_subject_group_item_id)
                                              ← chặn duplicate score cho cùng môn
                                                trong cùng NV. Cần thiết vì engine
                                                sum theo môn — duplicate sẽ tính 2x.
```

**Vì sao snapshot:** khi catalog thay đổi tên môn / weight (rare nhưng có thể) hoặc admin xóa item config, điểm thí sinh đã chốt vẫn giữ giá trị tại thời điểm nộp. Pattern audit chuẩn.

**Vì sao `bonus_rule_snapshot` ở `AdmissionProfileChoice` thay vì nhét vào `applied_rules`:** giữ `applied_rules` immutable trigger ở scope hiện tại (rule-level), tách choice-level snapshot riêng. Sạch hơn, không phải disable/re-enable trigger trên prod.

### 2.7. Status history (audit trail mọi transition)

`AdmissionProfile.status` là scalar field — mỗi transition mất history. Hiện có scattered scalar (`approved_at/by`, `rejected_at/by`, `revision_requested_at/by`, `overridden_at/by`) — không scale với 17 transition mới (T1-T17).

```
admission_profile_status_history            (MỚI) — tạo trong Phase 1 (migration #10)
├── id
├── profile_id                              FK → AdmissionProfile, ON DELETE CASCADE
├── from_status                             nullable (lần đầu tạo profile: NULL)
├── to_status                               NOT NULL
├── transitioned_by_user_id                 FK → User, nullable
│                                              SET khi actor = officer/admin (có User row)
├── transitioned_by_lead_id                 FK → Lead, nullable
│                                              SET khi actor = candidate qua magic_link
│                                              (candidate KHÔNG có User row, dùng Lead làm
│                                               actor reference)
├── transitioned_by_role                    DEPRECATED — giữ cho backward-compat 1 release
│                                              (sẽ drop ở Phase 4 sau khi report migrate qua 2 column dưới)
├── actor_actual_role                       (MỚI v2.9) ENUM:
│                                              candidate / officer / manager / accountant / admin / system
│                                              Ghi trung thực role THẬT của actor (manager khi gọi
│                                              T6/T10/T11 ghi 'manager', không phải 'admin' resolved).
│                                              Audit/report theo cột này cho sự thật.
├── effective_transition_role               (MỚI v2.9) ENUM:
│                                              candidate / officer / admin / system
│                                              Role sau khi resolve qua effective_role_for_transition().
│                                              Manager sang T6 → 'admin'; manager sang T2 → 'officer'.
│                                              Dùng cho RBAC trace + matrix verification.
├── transition_reason                       Text nullable (bắt buộc cho admin override + reject)
├── occurred_at                             timestamp NOT NULL, default now()
└── metadata                                JSONB
                                              {
                                                "computed_total_score": 22.5,
                                                "decision_rule": "rule_5_pass",
                                                "choice_priority": 1,
                                                "trigger_source": "submit_endpoint"
                                              }

INDEX ix_status_history_profile_occurred ON (profile_id, occurred_at DESC)
INDEX ix_status_history_to_status ON (to_status)  -- cho report aggregate

CHECK constraint:
  ck_status_history_actor_consistency:
    (transitioned_by_role = 'system' AND transitioned_by_user_id IS NULL
       AND transitioned_by_lead_id IS NULL)
    OR (transitioned_by_role IN ('officer', 'admin') AND transitioned_by_user_id IS NOT NULL
       AND transitioned_by_lead_id IS NULL)
    OR (transitioned_by_role = 'candidate' AND transitioned_by_lead_id IS NOT NULL
       AND transitioned_by_user_id IS NULL)
```

**Service contract:** mỗi endpoint đổi `AdmissionProfile.status` MUST insert 1 row vào `status_history` cùng transaction frame. Không có row history → giả định bug, raise alert.

**Backfill Phase 1**: với mọi profile hiện có, tạo 1 row `(NULL → current_status, transitioned_by=NULL, occurred_at=created_at, metadata={"backfill": true})`. Idempotent guard (xem Phần 5b).

---

## Phần 3 — Validation engine

Chạy khi thí sinh submit hoặc khi tư vấn viên review. Per-choice (mỗi NV độc lập), trả về `eligibility_check_result` JSONB chi tiết.

### 3.1. Resolution ngưỡng (3 tầng override)

Khi cần biết "điểm liệt môn Toán trong NV này", engine resolve specific → general:

```
PathSubjectGroupItem.min_score_override     (cụ thể nhất — môn này, config này)
        ↓ nếu null
PathSubjectGroupConfig.min_subject_score    (mặc định cho config)
        ↓ nếu null
AdmissionCriteria.min_subject_score         (mặc định cho path)
```

Tương tự cho `min_score` (ngưỡng tổng tổ hợp): `PathSubjectGroupConfig.min_score → AdmissionCriteria.min_score`.

### 3.1.a. Null semantics — chốt rõ behavior cho mọi rule

Engine không direct compare `None` (Python crash) hoặc silent pass/fail (sai nghiệp vụ). 5 quy ước bắt buộc:

| Case | Behavior | Lý do |
|---|---|---|
| Threshold null (criteria.min_X = NULL) | **SKIP rule** với log `RULE_SKIPPED_NO_THRESHOLD` | Admin chưa cấu hình ngưỡng → chưa enforce. Không fail vì lý do hệ thống, không pass vì nghiệp vụ. |
| Threshold có giá trị + Profile scalar null | **FAIL** với code `MISSING_<FIELD>` | Hồ sơ thiếu data bắt buộc. Lỗi rõ ràng cho thí sinh khắc phục. |
| Conduct enum compare | Map ordinal `TB=1, KHA=2, TOT=3`. So sánh integer. | String compare "TB" < "TOT" về lexical sai. Map ordinal cho phép `profile.conduct_ord >= criteria.min_conduct_ord`. |
| Health category direction | Number nhỏ hơn = sức khỏe tốt hơn. So `profile.health_category <= criteria.min_health_category`. | Theo phân loại y tế VN: Loại 1 (tốt nhất) → Loại 4 (kém nhất). |
| Year range threshold (only one bound set) | NULL bound = unbounded ở phía đó. `[NULL, 2024]` = year ≤ 2024; `[2020, NULL]` = year ≥ 2020. | Cho phép criteria một-phía. |

```python
# Pattern engine an toàn (Python pseudocode)
def check_min_threshold(profile_value, threshold, *, field_name):
    if threshold is None:
        return RuleResult(passed=True, skipped=True, reason="no_threshold")
    if profile_value is None:
        return RuleResult(passed=False, code=f"MISSING_{field_name}")
    return RuleResult(passed=profile_value >= threshold)

CONDUCT_ORDINAL = {"TB": 1, "KHA": 2, "TOT": 3}

def check_conduct(profile_conduct, min_conduct):
    if min_conduct is None:
        return RuleResult(passed=True, skipped=True)
    if profile_conduct is None:
        return RuleResult(passed=False, code="MISSING_CONDUCT")
    return RuleResult(
        passed=CONDUCT_ORDINAL[profile_conduct] >= CONDUCT_ORDINAL[min_conduct]
    )
```

### 3.2. 6 rule chạy tuần tự

```
Rule 1 — Đủ môn?
  Mọi PathSubjectGroupItem của config đã chọn phải có ProfileChoiceScore tương ứng.

Rule 2 — Học lực, hạnh kiểm, sức khỏe đạt?
  AdmissionProfile.gpa_overall ≥ AdmissionCriteria.min_gpa
  AdmissionProfile.conduct ≥ AdmissionCriteria.min_conduct
  AdmissionProfile.health_category ≤ AdmissionCriteria.min_health_category
  (so sánh enum theo thứ tự định nghĩa, không string)

Rule 3 — Năm tốt nghiệp hợp lệ?
  AdmissionProfile.graduation_year ∈ [min, max] nếu criteria có set.

Rule 4 — Mỗi môn ≥ điểm liệt?
  Với mỗi ProfileChoiceScore, raw_score ≥ resolved_min_subject_score (3 tầng).

Rule 5 — Tính computed_raw_score theo score_formula
  Engine load score_formula → parse qua Pydantic ScoreFormulaConfig (Phần 2.3.a).
  - WeightedSumFormula (Phase 2): Σ(raw_score × effective_weight) × scale, round theo
    rounding param.
  - CustomFormula (Phase 3+): dispatch theo handler_code đã register.
  Parse fail → raise ngay, không fall back default — config sai phải sửa, không silent.

Rule 6 — Cộng ưu tiên + so ngưỡng tổng
  resolved_bonus_rule = path.bonus_rule_override ?? method.default_bonus_rule
  computed_bonus = area_bonus + subject_bonus (theo resolved_bonus_rule)
  computed_total_score = computed_raw_score + computed_bonus
  computed_total_score ≥ resolved_min_score → eligible
  Snapshot resolved_bonus_rule vào bonus_rule_snapshot.
```

Mỗi rule fail trả lỗi cụ thể (không "hồ sơ không hợp lệ" chung chung). Format:
```json
{
  "rules_passed": ["rule_1_subject_completeness", "rule_3_graduation_year"],
  "rules_failed": [
    {
      "rule": "rule_2_min_gpa",
      "expected": 6.5,
      "actual": 6.2,
      "message": "GPA chưa đạt ngưỡng tối thiểu"
    }
  ],
  "decision": "ineligible"
}
```

### 3.3. State machine của AdmissionProfile (mở rộng)

State machine mới chỉ active khi `AdmissionProfile.uses_choice_engine = true`. Profile cũ giữ state machine legacy (`approved/rejected/enrolled/...`) — KHÔNG phá behavior cũ.

#### 3.3.a. Sơ đồ trạng thái

```
                              ┌─────────┐
                              │  DRAFT  │ ←──── (12) ROLLED_BACK ◄─ * (admin only)
                              └────┬────┘
                                   │ (1) PROFILE_SUBMITTED  [Thí sinh]
                                   ▼
                            ┌────────────┐
              ┌────────────►│ SUBMITTED  │
              │             └─────┬──────┘
              │                   │ [Officer claim — manual, no event]
              │                   ▼
              │            ┌────────────┐
              │            │ REVIEWING  │
              │            └──┬────────┬┘
              │  (2) REVISION_REQUESTED │
              │  [Officer]              │
              │               ▼         │
              │   ┌────────────────┐    │
              │   │ REVISION_      │    │
              │   │ REQUESTED      │    │
              │   └────────┬───────┘    │
              │  (3) RESUBMITTED        │
              │  [Thí sinh] │           │
              └─────────────┘           │
                                        │ (4) RESULT_PUBLISHED
                                        │ [Admin trigger publish — system fanout decisions]
                                        ▼
                          ┌────────────────────┐
                          │ RESULT_PUBLISHED   │
                          └──┬──────┬───────┬──┘
                  (5) ADMITTED  (6) WAITLISTED  (7) REJECTED
                  [System distribute by ranking + quota]
                             │      │       │
                             ▼      ▼       ▼
                       ┌─────────┐ ┌──────┐ ┌──────────┐
                       │ADMITTED │ │WAIT- │ │ REJECTED │
                       │ (status)│ │LISTED│ │          │
                       └────┬────┘ └──┬───┘ └──────────┘
                            │ (8) WAITLIST_PROMOTED [Admin]
                            │◄────────┘
                            │ (9) CONFIRMED [Thí sinh, magic_link/officer/admin_override]
                            ▼
                       ┌──────────┐
                       │CONFIRMED │
                       └────┬─────┘
                            │ (10) ENROLLED [System — tạo Student record]
                            ▼
                       ┌──────────┐
                       │ ENROLLED │
                       └──────────┘

  Cross-state:
  (11) WITHDRAWN  — From: ADMITTED | CONFIRMED → bởi thí sinh
                    From: ENROLLED              → bởi admin only
                    To:   WITHDRAWN
  (12) ROLLED_BACK — From: bất kỳ state nào, bắt buộc reason
                    To:   DRAFT (admin only)
```

**Lưu ý quan trọng — `admitted` KHÔNG phải state động:**
- `AdmissionProfile.status = 'admitted'` (scalar, single value).
- `choice_priority` (1, 2, 3...) lưu ở 2 chỗ: (a) `AdmissionProfileChoice.display_order` của choice được admit, (b) `status_history.metadata.choice_priority`.
- Lý do: status enum hữu hạn cho CHECK constraint + index. Choice priority động (1..N) không phù hợp làm enum value.

**Status enum mới (Phase 1 migration ALTER CHECK):**
```
draft, submitted, reviewing, revision_requested,
result_published, admitted, waitlisted, rejected,
confirmed, enrolled, withdrawn,
-- legacy giữ để backward compat khi uses_choice_engine=false:
approved, resubmitted, overridden
```

#### 3.3.b. 17 transition matrix (actor + permission)

| # | From | To | Actor | Trigger | Audit reason |
|---|---|---|---|---|---|
| T1 | draft | submitted | candidate | submit endpoint | optional |
| T2 | submitted | reviewing | officer | claim endpoint | optional (no event) |
| T3 | reviewing | revision_requested | officer | request_revision endpoint | **required** |
| T4 | submitted | revision_requested | officer | shortcut khi thấy thiếu hồ sơ ngay | **required** |
| T5 | revision_requested | submitted | candidate | resubmit endpoint | optional |
| T6 | reviewing | result_published | admin | publish endpoint (broadcast) | optional |
| T7 | result_published | admitted | system | engine distribute | metadata: choice_priority, total_score |
| T8 | result_published | waitlisted | system | engine distribute | metadata: waitlist_rank |
| T9 | result_published | rejected | system | engine distribute | metadata: reject_codes[] |
| T10 | waitlisted | admitted | admin | promote endpoint | **required** |
| T11 | waitlisted | rejected | admin | finalize_waitlist endpoint | **required** |
| T12 | admitted | confirmed | candidate / officer / admin | confirm endpoint, set `confirmed_via` ∈ {`magic_link`, `officer`, `admin_override`} | optional |
| T13 | confirmed | enrolled | system | enrollment job | metadata: student_id |
| T14 | admitted | withdrawn | candidate | withdraw endpoint | **required** |
| T15 | confirmed | withdrawn | candidate | withdraw endpoint | **required** |
| T16 | enrolled | withdrawn | admin only | admin_withdraw endpoint | **required** (legal/registrar) |
| T17 | * | draft | admin only | rollback endpoint | **required** ("thoát hiểm") + **cascade Student nếu from=enrolled** |

**T17 cascade rule (Q1 chốt 2026-05-01 v2.13 — STRICT REJECT)**:
- ⚠️ **Quyết định cuối cùng**: T17 từ `enrolled` → **REJECT**. KHÔNG soft-delete Student trong mùa 2026.
- Lý do: Student model verified KHÔNG có `deleted_at/deleted_reason/deleted_by_user_id` (xem `app/models/student.py:26-199`). Soft delete đòi schema migration + cascade dependency (DormAssignment, ClassEnrollment, Commission record có thể đã issue) — risk mid-season cao.
- Service implementation:
  ```python
  if from_status == 'enrolled':
      raise BusinessRuleViolation(
          "Cannot rollback enrolled profile via T17. "
          "Use T16 admin-withdraw first to handle Student record + dependencies, "
          "then T17 from withdrawn state if needed."
      )
  ```
- Workflow thay thế: admin muốn rollback enrolled → T16 admin-withdraw (`enrolled → withdrawn`, cleanup Student + dependencies in withdraw flow) → T17 (`withdrawn → draft`) nếu thực sự cần re-process.
- T17 từ state khác (admitted/confirmed/waitlisted/rejected) vẫn cho phép theo wildcard rule, BẮT BUỘC reason ≥10 chars + audit log.
- **Defer Phase 4+ (Q1/2027 trở lên)**: nếu nghiệp vụ thực tế phát sinh need cascade, implement Student soft-delete + 3 column schema migration + dependency cascade trong release riêng.

**Quy tắc role:**
- Candidate: T1, T5, T12, T14, T15. T12 candidate qua magic_link — reason optional.
- Officer: T2, T3, T4, **T12 (override với reason bắt buộc)**. KHÔNG có quyền `result_published` — boundary security.
- Admin: T6, T10, T11, **T12 (override với reason bắt buộc)**, T16, T17. Mọi action override phải có audit reason.
- System: T7, T8, T9, T13. Tự động dựa trên engine + cron.

**Mapping với Casbin role hiện tại** (verified `app/casbin_config/policy_templates.py:44-46` có 4 role `admin/manager/accountant/officer`):

| Plan role | Casbin role hiện tại | Transition quyền |
|---|---|---|
| Candidate | (không có User row) | T1, T5, T12, T14, T15 qua magic_link token (xem Phần 3.3.g) |
| Officer | `officer` | T2, T3, T4, T12 |
| Manager | `manager` | T3, T4, T6, T10, T11, T12 (publish + waitlist actions). KHÔNG T17 rollback. |
| Admin | `admin` | Full toàn bộ T1-T17 (kể cả T17 rollback). |
| System | (không qua Casbin) | T7, T8, T9, T13 — service-internal, không endpoint |

**IDOR scope cho 4 new state (Q10 chốt 2026-05-01 v2.13 — UNCHANGED)**:

KHÔNG thay đổi RBAC scope cho `reviewing/result_published/admitted/waitlisted`. Tái sử dụng dependency hiện tại:
- **Officer**: assigned (`lead.assigned_officer_id == user.id`) + cùng unit (`lead.unit_id == user.unit_id`) qua `get_admission_for_user()` (`app/core/deps.py:2241-2316`).
- **Manager**: cùng unit qua `get_admission_for_manager()` (`deps.py:2161-2238`).
- **Admin**: all access.
- **System** (T7/T8/T9/T13): service-internal — KHÔNG endpoint, KHÔNG qua Casbin.

Lý do giữ nguyên: 4 new state cùng IDOR boundary với legacy state — không có nghiệp vụ phân scope khác. Giữ nguyên = giảm test surface + giảm regression risk. Phase 1 #16 audit task SCOPE: verify dependency `get_admission_for_user/manager` trả đúng cho profile có 4 state mới (không filter by status — chỉ filter by lead_id + unit + assignment).

**Effective role resolver (per-transition, KHÔNG generic mapping)**:
```python
# app/services/admission_state_service.py
def effective_role_for_transition(user, transition_code) -> str:
    """Resolve role per transition. KHÔNG map manager → admin generic vì sẽ
    cấp T17 rollback cho manager (nguy hiểm). KHÔNG map manager → manager
    nếu matrix không có entry (manager bị deny mọi action).
    """
    actual_role = user.role  # 'admin'/'manager'/'accountant'/'officer'

    # T17 rollback CHỈ admin thực — KHÔNG cấp cho manager dù manager có nhiều quyền khác
    if transition_code == 'T17':
        if actual_role == 'admin':
            return 'admin'
        raise BusinessRuleViolation("T17 rollback chỉ admin có quyền")

    # T6/T10/T11 — admin + manager đều được; resolve về 'admin' để khớp matrix
    if transition_code in ('T6', 'T10', 'T11'):
        if actual_role in ('admin', 'manager'):
            return 'admin'
        raise BusinessRuleViolation(f"{transition_code} chỉ admin/manager có quyền")

    # T2/T3/T4 — officer + manager đều được; resolve về 'officer' để khớp matrix
    if transition_code in ('T2', 'T3', 'T4'):
        if actual_role in ('admin', 'manager', 'officer'):
            return 'officer'
        raise BusinessRuleViolation(f"{transition_code} không cho phép role {actual_role}")

    # Default: dùng actual_role
    return actual_role
```

**Route split per-action (KHÔNG generic `/transition` endpoint)** — verified `app/core/deps.py:378 check_permission(request)` dùng `request.url.path + method` matcher. Generic `/transition` endpoint không thể per-action RBAC qua existing pattern.

**Endpoint design — 2 hệ route TÁCH BIỆT (public candidate vs internal staff)**:

```
# Public candidate routes — token-resolve profile, KHÔNG expose profile_id direct
POST /api/v2/public/admissions/{token}/submit       # T1 candidate
POST /api/v2/public/admissions/{token}/resubmit     # T5 candidate
POST /api/v2/public/admissions/{token}/confirm      # T12 candidate (magic_link path)
POST /api/v2/public/admissions/{token}/withdraw     # T14, T15 candidate

# Internal staff routes — Casbin guard, profile_id explicit
POST /api/v2/admissions/{id}/claim                  # T2 officer
POST /api/v2/admissions/{id}/request-revision       # T3, T4 officer/manager
POST /api/v2/admissions/{id}/publish-result         # T6 admin/manager
POST /api/v2/admissions/{id}/waitlist-promote       # T10 admin/manager
POST /api/v2/admissions/{id}/waitlist-reject        # T11 admin/manager
POST /api/v2/admissions/{id}/staff-confirm          # T12 officer/admin override
POST /api/v2/admissions/{id}/staff-withdraw         # T16 admin (post-enrollment)
POST /api/v2/admissions/{id}/admin-rollback         # T17 admin only
POST /api/v2/admissions/bulk-publish-result         # T6 batch (xem Fix #9)
```

**Lý do tách**:
- Candidate route resolve `profile` từ `token` (validate token + action_type → 404 nếu không match) — KHÔNG cần `id` trong URL → chống IDOR enumerate.
- Internal staff route dùng `id` direct + `Depends(CasbinAuth)` — symmetric existing pattern.
- T12 confirm có 2 endpoint (candidate vs staff override) tách rõ audit trail.

System transitions (T7/T8/T9/T13) chạy service-internal, KHÔNG endpoint.

**Service entry FOR UPDATE (fix race condition concurrent admin)**:
```python
async def transition(self, *, db, profile_id, actor, to_status, reason=None, metadata=None):
    # Lock profile row đầu transaction — prevent 2 admin concurrent publish + promote
    profile = await db.execute(
        select(AdmissionProfile)
        .where(AdmissionProfile.id == profile_id)
        .with_for_update()  # row-level lock đến cuối transaction
    ).scalar_one_or_none()
    if profile is None:
        raise ResourceNotFoundError("Profile not found")
    # ... can_transition check + insert status_history + dispatch_event ...
```

System transitions (T7/T8/T9/T13) chạy service-internal, KHÔNG endpoint.

**`policy_templates.py` update bắt buộc** (Phase 1 #16 audit task scope mở rộng):

⚠️ **Diamond inheritance gotcha** (verified `policy_templates.py:44 g, role:accountant, role:officer`): accountant inherit officer policy → accountant pass route guard cho `/admissions/*/claim` route. Service guard chặn nhưng RBAC fail-late. Phải explicit DENY accountant ở Casbin level.

```
# Casbin policy entries — per route path + method
# Allow rules
p, role:officer, /api/v2/admissions/*/claim, POST, allow
p, role:officer, /api/v2/admissions/*/request-revision, POST, allow
p, role:manager, /api/v2/admissions/*/request-revision, POST, allow
p, role:manager, /api/v2/admissions/*/publish-result, POST, allow
p, role:manager, /api/v2/admissions/*/waitlist-promote, POST, allow
p, role:manager, /api/v2/admissions/*/waitlist-reject, POST, allow
p, role:admin, /api/v2/admissions/*/admin-rollback, POST, allow
p, role:admin, /api/v2/admissions/bulk-publish-result, POST, allow

# DENY rules — accountant deny early (priority cao hơn inherit)
p, role:accountant, /api/v2/admissions/*/claim, POST, deny
p, role:accountant, /api/v2/admissions/*/request-revision, POST, deny
p, role:accountant, /api/v2/admissions/*/publish-result, POST, deny
p, role:accountant, /api/v2/admissions/*/waitlist-*, POST, deny
p, role:accountant, /api/v2/admissions/*/admin-rollback, POST, deny

# admin inherits manager → có hết quyền manager
# (g, role:admin, role:manager đã có ở line 46 policy_templates.py)

# Casbin matcher: priority deny first
# m = g(r.sub, p.sub) && keyMatch4(r.obj, p.obj) && r.act == p.act && p.eft == "allow" \
#   && !some((p2 in policies | p2.sub == r.sub && p2.obj == r.obj && p2.eft == "deny"))
```

Test bắt buộc: `accountant_user → POST /api/v2/admissions/{id}/claim → 403 Forbidden`, KHÔNG 200/500.

Mỗi endpoint dùng `Depends(CasbinAuth)` (check_permission existing) — KHÔNG cần thêm matcher mới. Symmetric với endpoint pattern hiện tại. Audit log mỗi endpoint riêng → query rõ.

**T12 đa actor lý do:** thí sinh tự confirm qua magic_link là happy path; officer/admin confirm thay khi thí sinh không có magic_link (đến trực tiếp trường, gọi điện), hoặc admin override khi xử lý case ngoại lệ. Tách qua `REASON_REQUIRED_FOR_NON_CANDIDATE_TRANSITIONS` trong service guard.

#### 3.3.c. Service guard `can_transition()`

Đặt ở `app/services/admission_state_service.py`. Mọi endpoint đổi status MUST gọi guard này trước:

```python
class AdmissionStateService:
    TRANSITION_MATRIX = {
        ("draft", "submitted"):                  {"candidate"},
        ("submitted", "reviewing"):              {"officer"},
        ("reviewing", "revision_requested"):     {"officer"},
        ("submitted", "revision_requested"):     {"officer"},
        ("revision_requested", "submitted"):     {"candidate"},
        ("reviewing", "result_published"):       {"admin"},
        ("result_published", "admitted"):        {"system"},
        ("result_published", "waitlisted"):      {"system"},
        ("result_published", "rejected"):        {"system"},
        ("waitlisted", "admitted"):              {"admin"},
        ("waitlisted", "rejected"):              {"admin"},
        ("admitted", "confirmed"):               {"candidate", "officer", "admin"},  # T12 — officer/admin override với reason; candidate optional reason
        ("confirmed", "enrolled"):               {"system"},
        ("admitted", "withdrawn"):               {"candidate"},
        ("confirmed", "withdrawn"):              {"candidate"},
        ("enrolled", "withdrawn"):               {"admin"},
        # T17: rollback — wildcard handled separately
    }

    REASON_REQUIRED_TRANSITIONS = {
        ("reviewing", "revision_requested"),
        ("submitted", "revision_requested"),
        ("waitlisted", "admitted"),
        ("waitlisted", "rejected"),
        ("admitted", "withdrawn"),
        ("confirmed", "withdrawn"),
        ("enrolled", "withdrawn"),
        # rollback always requires reason
    }

    # Reason required ONLY khi actor là officer/admin override (không phải candidate self-service).
    # T12 (admitted → confirmed): candidate confirm bằng magic_link không cần reason;
    # officer/admin confirm phải ghi reason.
    REASON_REQUIRED_FOR_NON_CANDIDATE_TRANSITIONS = {
        ("admitted", "confirmed"),
    }

    NEW_STATES = {"reviewing", "result_published", "admitted", "waitlisted"}
    LEGACY_STATES = {"approved", "resubmitted", "overridden"}

    # transition_code resolution map — matrix entry → T1-T17 code
    TRANSITION_CODE_MAP = {
        ("draft", "submitted"): "T1",
        ("submitted", "reviewing"): "T2",
        ("reviewing", "revision_requested"): "T3",
        ("submitted", "revision_requested"): "T4",
        ("revision_requested", "submitted"): "T5",
        ("reviewing", "result_published"): "T6",
        ("result_published", "admitted"): "T7",
        ("result_published", "waitlisted"): "T8",
        ("result_published", "rejected"): "T9",
        ("waitlisted", "admitted"): "T10",
        ("waitlisted", "rejected"): "T11",
        ("admitted", "confirmed"): "T12",
        ("confirmed", "enrolled"): "T13",
        ("admitted", "withdrawn"): "T14",
        ("confirmed", "withdrawn"): "T15",
        ("enrolled", "withdrawn"): "T16",
        # T17 wildcard handled separately
    }

    async def can_transition(
        self, *, actor, profile, from_status: str, to_status: str,
    ) -> tuple[bool, str]:
        """Return (allowed, effective_role). transition_code resolved internal.

        Effective role là output từ effective_role_for_transition() —
        đường duy nhất để tránh manager bypass T17 hoặc bị deny generic.
        """
        # Resolve transition_code TRƯỚC mọi check
        transition_code = self.TRANSITION_CODE_MAP.get((from_status, to_status))
        if to_status == "draft":
            transition_code = "T17"  # rollback wildcard
        if transition_code is None:
            return False, ""

        # Effective role per-transition (không generic mapping)
        try:
            effective_role = effective_role_for_transition(actor, transition_code)
        except BusinessRuleViolation:
            return False, ""

        # Engine guard — chặn cross-flow leak
        if not profile.uses_choice_engine and to_status in self.NEW_STATES:
            return False, ""
        if profile.uses_choice_engine and to_status in self.LEGACY_STATES:
            return False, ""

        # Matrix check với effective_role đã resolved
        if transition_code == "T17":
            return effective_role == "admin", effective_role
        allowed_roles = self.TRANSITION_MATRIX.get((from_status, to_status), set())
        return effective_role in allowed_roles, effective_role

    async def transition(
        self, *, db, profile_id: int, actor, to_status, reason=None, metadata=None
    ):
        """ENTRYPOINT DUY NHẤT cho mọi transition. KHÔNG có code path khác.

        Flow:
        1. SELECT profile FOR UPDATE (lock row toàn transaction)
        2. can_transition() resolved transition_code internal + effective_role_for_transition()
        3. Validate reason requirements
        4. INSERT status_history (actual + effective role tách)
        5. UPDATE profile.status
        6. dispatch_event() → outbox INSERT or callback
        """
        # Step 1 — FOR UPDATE lock
        profile = (await db.execute(
            select(AdmissionProfile)
            .where(AdmissionProfile.id == profile_id)
            .with_for_update()
        )).scalar_one_or_none()
        if profile is None:
            raise ResourceNotFoundError("Profile not found")
        from_status = profile.status

        # Step 2 — can_transition tự resolve transition_code + effective_role internal
        allowed, effective_role = await self.can_transition(
            actor=actor, profile=profile,
            from_status=from_status, to_status=to_status,
        )
        if not allowed:
            raise BusinessRuleViolation(
                f"Transition {from_status} → {to_status} not allowed"
            )

        # Step 3 — reason validation
        if (from_status, to_status) in self.REASON_REQUIRED_TRANSITIONS and not reason:
            raise ValidationError(f"Reason required for {from_status} → {to_status}")
        if (from_status, to_status) in self.REASON_REQUIRED_FOR_NON_CANDIDATE_TRANSITIONS \
                and effective_role != "candidate" and not reason:
            raise ValidationError(
                f"Reason required for {effective_role} performing {from_status} → {to_status}"
            )
        if to_status == "draft" and not reason:
            raise ValidationError("Rollback to draft requires reason")

        # Step 4 — INSERT status_history với actor TÁCH actual vs effective role
        # actor_actual_role: ghi trung thực ai gọi (admin/manager/accountant/officer/candidate/system)
        # effective_transition_role: role đã resolve cho RBAC matrix (admin/officer/candidate/system)
        actor_actual_role = self._resolve_actual_role(actor)  # role thật trên User
        actor_user_id = None
        actor_lead_id = None
        if actor_actual_role in ("officer", "admin", "manager", "accountant"):
            actor_user_id = actor.id  # User instance
        elif actor_actual_role == "candidate":
            actor_lead_id = actor.id  # Lead instance từ magic_link token

        history_row = AdmissionProfileStatusHistory(
            profile_id=profile.id,
            from_status=from_status,
            to_status=to_status,
            transitioned_by_user_id=actor_user_id,
            transitioned_by_lead_id=actor_lead_id,
            actor_actual_role=actor_actual_role,         # MỚI — sự thật actor
            effective_transition_role=effective_role,    # MỚI — role đã resolve cho RBAC
            transition_reason=reason,
            metadata=metadata or {},
        )
        db.add(history_row)
        profile.status = to_status
        await db.flush()

        # Notification dispatch qua API duy nhất `dispatch_event()` — service
        # KHÔNG quyết định outbox vs direct. dispatch_event() tự route theo
        # event_def.requires_outbox flag. Xem Phần 3.3.f.
        event_def = self._resolve_event(from_status, to_status, metadata)
        notif_callback = None
        if event_def:
            payload = {
                "profile_id": profile.id,
                "from_status": from_status,
                "to_status": to_status,
                "metadata": metadata or {},
            }
            # ⚠️ v2.13.1 fix (round 20 verify): align với existing dispatcher signature
            # (verified `notification_dispatcher.py:593,1853`): `dedupe_key` (không phải
            # `idempotency_key`); `event: SystemEvents` enum (không phải `event_code` string).
            dedupe_key = (
                f"{event_def.code.value}:{profile.id}:{(metadata or {}).get('choice_priority', 0)}"
            )
            # dispatch_event INSERT outbox nếu requires_outbox=True (return None),
            # hoặc trả post_commit_callback cho router await sau commit.
            notif_callback = await dispatch_event(
                db, event=event_def.code, payload=payload,  # event là SystemEvents enum
                dedupe_key=dedupe_key,
            )
        return profile, notif_callback
```

**Router pattern (chuẩn duy nhất):**
```python
@router.post("/admissions/{id}/transition")
async def transition_endpoint(...):
    profile, notif_callback = await state_service.transition(...)
    await db.commit()  # Commit DB FIRST
    if notif_callback is not None:
        await notif_callback()  # Best-effort post-commit; outbox events đã INSERT trong commit
    return profile
```

Mọi router transition: gọi `state_service.transition(...)` thay vì set `profile.status` trực tiếp.

#### 3.3.d. 12 milestone events + dispatch rules

| # | Event | Existing event mapping | Transition(s) | Actor | Audience | Outbox | Bypass consent | Payload chính |
|---|---|---|---|---|---|---|---|---|
| 1 | `ADMISSION_PROFILE_SUBMITTED` | `APPLICATION_SUBMITTED` (legacy, giữ + alias) | T1 | candidate | officer + candidate | No | No | `profile_id`, `submitted_at` |
| 2 | `ADMISSION_REVISION_REQUESTED` | KHÔNG có legacy | T3, T4 | officer | candidate | No | No | `profile_id`, `revision_reason`, `allowed_fields[]` |
| 3 | `ADMISSION_RESUBMITTED` | KHÔNG có legacy | T5 | candidate | officer | No | No | `profile_id`, `resubmit_notes` |
| 4 | `ADMISSION_RESULT_PUBLISHED` | KHÔNG có legacy (broadcast batch mới) | T6 | admin | officer + candidate | **Yes** | **Yes** | `profile_id`, `published_at`, `decision_summary` |
| 5 | `ADMISSION_DECISION_ADMITTED` | `APPLICATION_STATUS_CHANGED` partial overlap | T7 | system | candidate | **Yes** | **Yes** | `profile_id`, `choice_priority`, `path_id`, `total_score` |
| 6 | `ADMISSION_DECISION_WAITLISTED` | KHÔNG có legacy | T8 | system | candidate | **Yes** | **Yes** | `profile_id`, `waitlist_rank` |
| 7 | `ADMISSION_DECISION_REJECTED` | `APPLICATION_STATUS_CHANGED` partial overlap | T9 | system | candidate | **Yes** | **Yes** | `profile_id`, `reject_reason_codes[]` |
| 8 | `ADMISSION_WAITLIST_PROMOTED` | KHÔNG có legacy | T10 | admin | candidate | **Yes** | No | `profile_id`, `promoted_at`, `path_id` |
| 9 | `ADMISSION_CONFIRMED` | `ADMISSION_CONFIRMATION_*` (3 event hardening đã có) | T12 | candidate / officer / admin | officer | No | No | `profile_id`, `confirmed_via` (`magic_link`/`officer`/`admin_override` — đúng CHECK hiện có) |
| 10 | `ADMISSION_ENROLLED` | `APPLICATION_STATUS_CHANGED` partial overlap | T13 | system | officer + candidate | **Yes** | **Yes** | `profile_id`, `student_id`, `enrolled_at` |
| 11 | `ADMISSION_WITHDRAWN` | KHÔNG có legacy | T14, T15, T16 | varies | officer | No | No | `profile_id`, `from_status`, `withdrawn_by_role`, `reason` |
| 12 | `ADMISSION_ROLLED_BACK` | KHÔNG có legacy (admin-only override) | T17 | admin | officer + candidate | **Yes** | No | `profile_id`, `from_status`, `override_reason` |

**Namespace strategy chốt:**
- `ADMISSION_*` namespace mới cho 12 event ở plan này. KHÔNG reuse `APPLICATION_*` legacy.
- `APPLICATION_*` (6 event hiện có: SUBMITTED/STATUS_CHANGED/DELETED/FEE_PAID/SURVEY_DUE/MINOR_CORRECTED) giữ backward-compat trong Phase 1-3 cho payload key `application_id` (per `Backend_FastAPI/CLAUDE.md`).
- Phase 4 deprecate `APPLICATION_*` qua coverage script gate khi 0 caller production còn dùng.
- Coverage script extend check namespace collision (xem Phần 6 test strategy).
- 7 outbox-required events (4/5/6/7/8/10/12) bắt buộc INSERT outbox row trong service `transition()`. 5 best-effort còn lại (1/2/3/9/11) dùng `safe_dispatch()` post-commit.
- 5 bypass-consent events (4/5/6/7/10) — system-critical thông báo kết quả tuyển sinh.

**Bypass consent scope (Q7 chốt 2026-05-01 v2.13 — channel-tiered)**:

| Channel | Bypass for 5 critical events | Pre-condition | Mặc định |
|---|---|---|---|
| **In-app notification** | ✅ Bypass | Legal basis: thông báo bắt buộc theo Quy chế Bộ GD&ĐT | Active mọi lúc |
| **Email** | ✅ Bypass | Legal basis: same | Active mọi lúc |
| **Zalo ZNS** | ⚠️ **Gated bằng `zalo_template_approved` flag** | Bộ GD&ĐT compliance docs + Zalo OA template approval cho từng event template | **False** (tắt) cho đến khi legal sign-off |
| **SMS** | ⚠️ **Gated bằng `sms_template_approved` flag** | Telco template approval (Brand Name) + legal sign-off | **False** (tắt) cho đến khi approve |

**Lý do tách**: In-app + email là channel hệ thống nội bộ, đủ legal cover cho thông báo bắt buộc. Zalo + SMS là third-party có quota commercial + template approval Bộ chặt → phải có legal sign-off riêng. Nếu enable bypass cho Zalo/SMS không có template approval → violate ZNS policy (account ban) hoặc violate telco contract (rate limit).

**Implementation in dispatcher**:
```python
# app/services/zalo_dispatcher.py
async def send_zns(db, profile, message, *, event_def):
    if event_def.bypass_consent_check and not config.zalo_template_approved.get(event_def.code, False):
        log.info(f"Zalo skip — template not legal-approved for bypass, event={event_def.code}")
        # Fallback: vẫn check user consent thường
        consent = await get_zalo_consent(db, profile.lead_id)
        if consent.status != 'granted':
            return  # Skip nếu consent revoked
    # ... continue normal send flow
```

Pre-mùa 2026 checklist (Phần 7.3) thêm: legal team approve 5 ZNS template + admin set `zalo_template_approved[event_code]=True` per event.

**Transition KHÔNG phát event riêng (chỉ ghi `status_history`):**
- T2 (`submitted → reviewing` officer claim): internal workflow, dashboard tự update qua socket.
- T11 (`waitlisted → rejected`): gộp về event 7 với metadata `from_waitlist=true`.

**Socket emit vs outbox event — tách kênh tránh duplicate fanout** (P1 fix #6 v2.10):

PR #172 (memory `adm-032-doc-mutations-realtime`) đã ship `data_updated` cross-tab realtime cho document mutations. Plan thêm 12 milestone events qua outbox + in-app notification. Nếu cùng dùng channel `data_updated` → FE nhận 2 message cho 1 transition → race condition cache invalidate.

**Channel routing chốt:**

| Channel | Trigger | Mục đích | FE handler |
|---|---|---|---|
| `data_updated` | Document mutations (PR #172) | Cross-tab cache invalidate | Reload data, debounce 300ms |
| `notification_received` (MỚI) | 12 milestone events qua outbox | In-app toast notification | Render toast, không reload data |
| Email/Zalo/SMS | 12 milestone events qua outbox | External notification | N/A (out-of-band) |

**Rule bắt buộc:**
- Outbox events fanout qua: Email + Zalo + SMS + socket channel `notification_received_*` (scoped, KHÔNG broadcast). KHÔNG emit `data_updated` từ status transition.
- Existing `data_updated` channel CHỈ cho document mutations (admission_document CRUD), KHÔNG cho profile.status change.
- Status transition KHÔNG cần realtime cross-tab (admin/officer dashboard auto-poll mỗi 30s đủ). Nếu user mở 2 tab cùng profile → tab khác sẽ thấy state mới sau poll, không cần socket push.

**Channel authorization (P1 fix #7 v2.12 — chống PII leak across users)**:

⚠️ Anti-pattern v2.10: broadcast `notification_received` channel — user A connected nhận event ADMITTED của user B với total_score → PII leak.

Channel routing scoped:

| Channel name | Audience | Auth |
|---|---|---|
| `notification_received_user_{user_id}` | Staff (officer/admin/manager) — nhận event của profile họ assigned hoặc trong unit scope | JWT auth (existing) — verify subscriber.user_id == channel_user_id |
| `notification_received_lead_{lead_id}` | Candidate qua magic_link cookie — nhận event của profile thuộc lead | Magic_link cookie verify — subscriber có valid token cho lead_id |
| `notification_received_role_admin` | Broadcast vai trò admin — operations tổng | JWT verify role == 'admin' |
| `notification_received_role_manager` | Broadcast manager — operations unit | JWT verify role == 'manager' |

**Backend dispatcher fanout** (cùng outbox event → multiple channel):
```python
async def fanout_socket_event(event_payload):
    profile = await get_profile(event_payload['profile_id'])
    # Candidate channel
    await socket.emit(f'notification_received_lead_{profile.lead_id}', event_payload)
    # Officer assigned
    if profile.lead.assigned_officer_id:
        await socket.emit(f'notification_received_user_{profile.lead.assigned_officer_id}', event_payload)
    # Manager broadcast (operations)
    await socket.emit('notification_received_role_manager', event_payload)
    # Admin broadcast (oversight)
    await socket.emit('notification_received_role_admin', event_payload)
```

**FE subscription auth**:
```typescript
// Staff
socket.emit('subscribe', `notification_received_user_${currentUser.id}`);
// Candidate
socket.emit('subscribe', `notification_received_lead_${magicLinkLead.id}`);
// Backend handler verify subscriber.token authorization match channel suffix
```

**Notification timing — AFTER COMMIT (bắt buộc theo `Backend_FastAPI/CLAUDE.md` Part 7):**
- Service `transition()` gọi `dispatch_event()` API duy nhất (xem Phần 3.3.f). Function tự route:
  - `requires_outbox=True` → INSERT outbox row CÙNG transaction → return `None`.
  - `requires_outbox=False` → return `Optional[Callable]` callback cho router gọi sau commit.
- Service trả `(profile, notif_callback)`. Router pattern: `await db.commit()` → `if notif_callback is not None: await notif_callback()`.
- Atomic pair (event 4 + 5/6/7 cho cùng profile): wrap trong `async with db.begin_nested()` ở service.
- KHÔNG dispatch trong service body trước khi router commit (best-effort callback chạy SAU commit).
- KHÔNG có route service tự gọi `safe_dispatch`/`dispatch` raw — chỉ qua `dispatch_event()`.

**Catalog + rule + template seed bắt buộc** (Phase 3 migration): 12 events × audience × channel = ~36 template entries. Coverage script verify zero silent fanout.

#### 3.3.h. Bulk transition API + JSONB schema validation + API versioning + service FOR UPDATE

**Suggestion #9 — Bulk transition API cho `RESULT_PUBLISHED` fanout**:

Per-profile `transition()` ~5 query (catalog lookup + audit check + status_history INSERT + outbox INSERT + flush). Fanout 1000 profile cho `RESULT_PUBLISHED` broadcast = 5000 query → blocking endpoint vài phút.

```python
# app/services/admission_state_service.py
async def bulk_transition(
    self, *, db, profile_ids: list[int], to_status: str, actor, reason=None
):
    """Bulk transition cho admin publish_result fanout. 1 transaction, batch INSERT."""
    # Lock toàn bộ profile rows trong 1 query
    profiles = (await db.execute(
        select(AdmissionProfile)
        .where(AdmissionProfile.id.in_(profile_ids))
        .with_for_update()
    )).scalars().all()

    # Validate transition cho từng profile (parallel logic)
    history_rows = []
    outbox_rows = []
    for profile in profiles:
        allowed, effective_role = await self.can_transition(
            actor=actor, profile=profile,
            from_status=profile.status, to_status=to_status,
        )
        if not allowed:
            raise BusinessRuleViolation(f"Profile {profile.id} cannot transition")
        # Build history + outbox row (in-memory)
        history_rows.append(AdmissionProfileStatusHistory(...))
        event_def = self._resolve_event(profile.status, to_status, ...)
        if event_def and event_def.requires_outbox:
            outbox_rows.append(NotificationOutbox(...))
        profile.status = to_status

    # Batch INSERT
    db.add_all(history_rows)
    db.add_all(outbox_rows)
    await db.flush()
    return profiles
```

Endpoint `POST /api/v2/admissions/bulk-publish-result` admin only. Test: 1000 profile fanout < 5s.

**Suggestion #10 — JSONB payload Pydantic strict (chống injection)**:

`applied_rules`, `eligibility_check_result`, outbox `payload`, status_history `metadata` đều JSONB. Service nhận user input có thể craft pathologic shape (deeply nested, oversized). Bổ sung Pydantic models:

```python
# app/schemas/admission_jsonb.py — strict validation cho mọi JSONB write site
class AppliedRulesSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')  # reject unknown keys
    admission_path_id: int = Field(ge=1)
    allowed_subject_codes: list[str] = Field(max_length=20)
    subject_groups: list[dict] = Field(max_length=10)
    subject_weights: dict[str, float] = Field(max_length=20)
    fee_paid_at: Optional[datetime] = None
    fee_payment_data: Optional[dict] = None
    fee_calculated_at: Optional[datetime] = None
    fee_invoice_id: Optional[int] = None

class EligibilityCheckResultSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rules_passed: list[str] = Field(max_length=10)
    rules_failed: list[RuleFailureItem] = Field(max_length=10)
    decision: Literal['eligible', 'ineligible', 'admitted', 'waitlisted', 'rejected']

class OutboxPayloadSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: int
    from_status: str
    to_status: str
    metadata: dict = Field(default_factory=dict, max_length=20)

class StatusHistoryMetadataSchema(BaseModel):
    model_config = ConfigDict(extra='forbid')
    # Existing metadata keys
    computed_total_score: Optional[float] = None
    decision_rule: Optional[str] = None
    choice_priority: Optional[int] = Field(None, ge=1, le=10)
    trigger_source: Optional[str] = None
    backfill: Optional[bool] = None
    # v2.11 fix #1 scattered scalar backfill keys
    source: Optional[Literal['scattered_scalar_backfill', 'phase1_10_initial']] = None
    transition: Optional[Literal['approved', 'rejected', 'revision_requested',
                                 'resubmitted', 'overridden']] = None
    # v2.12 fix #1 T17 cascade audit
    student_id_cascaded: Optional[int] = None
```

Service validate qua `model_validate()` trước serialize JSONB. Endpoint reject 400 nếu shape sai. Coverage script verify mọi JSONB INSERT site qua Pydantic schema.

**Suggestion #11 — API versioning strategy**:

Phase 4 drop `Lead.gpa` + endpoint singular `/leads/{id}/admission-profile`. Cần versioning để client migrate dần:

- **URL prefix**: `/api/v1/` cho legacy + `/api/v2/` cho choice-engine.
- Phase 1: thêm v2 alias endpoint song song với v1 cho mọi endpoint affected (lead admission profiles, admission paths, admission profile choice).
- Phase 2-3: client mới dùng v2; v1 giữ backward-compat.
- Phase 4: drop v1 endpoint sau monitor 0 caller production trong 1 tháng.
- Header `X-API-Deprecation-Date: 2026-12-31` thêm vào response v1 cho client biết schedule migration.
- Document v1/v2 difference ở `Backend_FastAPI/docs/api_versioning.md` (mới).

**Suggestion #12 — `FOR UPDATE` service entry transition()**:

Đã apply ở Fix #2 service entry sample (xem ở trên). Mọi `transition()` call mở đầu bằng `with_for_update()` lock profile row → hold đến cuối transaction. Symmetric với existing `bulk_assign` PR #156 pattern.

#### 3.3.g. Candidate auth contract (magic_link IDOR protection)

Candidate KHÔNG có User row, KHÔNG đi qua `get_current_active_user`. Plan có 5 candidate transition (T1, T5, T12, T14, T15) — bề mặt IDOR công khai mới. Spec chặt:

**Token storage strategy — REUSE existing `AdmissionConfirmationToken`**:

Verified `app/models/admission.py:490 AdmissionConfirmationToken` đã có với `attempt_count`, lockout/cooldown, CCCD verification, reminder metadata (memory: adm-023-028 đã ship 2026-04-29). KHÔNG tạo bảng `admission_magic_link_token` song song.

**Migration plan — verified schema thực tế** (`admission.py:490-549`):
- Field hiện có: `id`, `profile_id` (UNIQUE single-token-per-profile), `token` (string, không phải `token_id`), `expires_at`, `confirmed_at` (mark used, không phải `used_at`), `attempt_count`, lockout fields. KHÔNG có `action_type`.
- Phase 1 thêm migration `phase1_18_extend_confirmation_token_for_multi_action.py`:
  ```sql
  -- Step 1: ADD COLUMN action_type
  ALTER TABLE admission_confirmation_token
      ADD COLUMN action_type VARCHAR(20) NOT NULL DEFAULT 'confirm';
  ALTER TABLE admission_confirmation_token
      ADD CONSTRAINT ck_token_action_type
      CHECK (action_type IN ('submit', 'resubmit', 'confirm', 'withdraw'));

  -- Step 2: DROP unique cũ trên profile_id (chỉ cho phép 1 token per profile)
  ALTER TABLE admission_confirmation_token
      DROP CONSTRAINT IF EXISTS admission_confirmation_token_profile_id_key;

  -- Step 3: Tạo partial unique — 1 active token per (profile, action_type)
  -- Cho phép nhiều token đã confirmed (audit trail) nhưng chỉ 1 active.
  CREATE UNIQUE INDEX uq_active_token_per_profile_action
      ON admission_confirmation_token (profile_id, action_type)
      WHERE confirmed_at IS NULL;

  -- Step 4: Index cho lookup theo token + action_type
  CREATE INDEX ix_token_action_type ON admission_confirmation_token (token, action_type);
  ```
- 3 action mới (`submit`, `resubmit`, `withdraw`) reuse hết logic existing: `attempt_count`, lockout, cooldown, CCCD verification, reminder metadata.
- KHÔNG rename table — giữ `admission_confirmation_token` để backward-compat existing reference.
- Code update: model `AdmissionConfirmationToken` thêm `action_type` field + relationship `Lead.admission_profile.confirmation_tokens` (plural, list[]) thay vì singular `confirmation_token`.

**Dependency get_profile_by_magic_link_token() correct với schema thực tế**:
```python
async def get_profile_by_magic_link_token(
    token: str = Path(...),       # raw token string từ URL
    action: str = Path(...),       # action_type
    db: AsyncSession = Depends(get_db),
) -> AdmissionProfile:
    record = await db.execute(
        select(AdmissionConfirmationToken)
        .where(AdmissionConfirmationToken.token == token)
        .where(AdmissionConfirmationToken.action_type == action)
        .where(AdmissionConfirmationToken.expires_at > func.now())
        .where(AdmissionConfirmationToken.confirmed_at.is_(None))  # 1-time
        .where(AdmissionConfirmationToken.attempt_count < 5)        # not locked
    ).scalar_one_or_none()
    if record is None:
        raise ResourceNotFoundError("Token invalid or expired")
    profile = await db.get(AdmissionProfile, record.profile_id)
    if profile is None:
        raise ResourceNotFoundError("Profile not found")
    return profile
```

**Token format** (verified existing schema):
- Field `token` String(64) — URL-safe random (256-bit entropy) như existing implementation. KHÔNG dùng UUID v7 + HMAC để giảm phức tạp + tận dụng existing token generator.
- Existing fields reused: `token`, `profile_id`, `expires_at`, `confirmed_at` (mark used), `attempt_count`, lockout fields. KHÔNG có `token_id`/`used_at`.
- Field thêm: `action_type` VARCHAR(20) ENUM (như migration phase1_18 ở trên).

**Expiry per action:**
| Action | TTL |
|---|---|
| `submit` | 7 ngày (initial form submission link) |
| `resubmit` | 3 ngày sau revision_requested |
| `confirm` | 24h-30 ngày tùy config (đã có ở memory `adm-023-028-magic-link`) |
| `withdraw` | 24h sau request |

**Rate limit:**
- 5 request/phút/token (chống brute-force).
- 1 token chỉ dùng 1 lần (`confirmed_at` set atomic sau lần đầu) cho `submit/confirm/withdraw`. `resubmit` cho phép retry trong TTL.
- IP-level limit: 30 request/phút/IP cho mọi magic_link endpoint.

**CCCD verification cho TẤT CẢ 4 action (P1 fix #2 v2.12 — security parity)**:

Existing confirm flow đã có CCCD last-4-digits verification (memory `adm-023-028-magic-link`). Plan reuse `AdmissionConfirmationToken` cho 3 action mới (`submit/resubmit/withdraw`) PHẢI extend CCCD verification — tránh URL token leak attack:
- Candidate forward email vô tình → người khác mở URL → atomic claim token → submit form thay candidate.
- Audit ghi `transitioned_by_lead_id = candidate.id` (sai sự thật).

**Implementation**:
```python
# Token landing endpoint (GET) — render form yêu cầu nhập 4 chữ cuối CCCD
@router.get("/api/v2/public/admissions/{token}/{action}/landing")
async def landing(token: str, action: str, db):
    record = await db.execute(
        select(AdmissionConfirmationToken)
        .where(token=token, action_type=action,
               confirmed_at=None, expires_at__gt=func.now(),
               attempt_count__lt=5)
    ).scalar_one_or_none()
    if record is None: raise ResourceNotFoundError("Token invalid/expired")
    return {"token": token, "action": action,
            "instruction": "Nhập 4 chữ số cuối CCCD để xác thực"}

# Action endpoint (POST) — verify CCCD trước atomic claim
@router.post("/api/v2/public/admissions/{token}/{action}")
async def execute_action(token: str, action: str, payload: PublicActionPayload, db):
    # Step 1: Lookup token + lead (chưa claim)
    record = await db.execute(
        select(AdmissionConfirmationToken, Lead)
        .join(AdmissionProfile).join(Lead)
        .where(token=token, action_type=action,
               confirmed_at=None, expires_at__gt=func.now())
        .with_for_update()  # lock token row
    ).first()
    if record is None: raise ResourceNotFoundError("Token invalid/expired")
    token_row, lead = record

    # Step 2: Verify CCCD last 4 digits
    if lead.citizen_id is None or len(lead.citizen_id) < 4:
        raise BusinessRuleViolation("Lead missing CCCD for verification")
    expected_last_4 = lead.citizen_id[-4:]
    if payload.cccd_last_4 != expected_last_4:
        token_row.attempt_count += 1
        await db.flush()
        if token_row.attempt_count >= 5:
            raise BusinessRuleViolation("Token locked sau 5 lần CCCD sai")
        raise ValidationError(f"CCCD không khớp ({token_row.attempt_count}/5)")

    # Step 3: Atomic claim + transition (verified CCCD OK)
    token_row.confirmed_at = func.now()
    await transition(...)
```

**Atomic token consumption (chống double-submit, P1 fix #5)**:
Dependency v2.8 SELECT trả token rồi service insert transition → 2 request song song cùng pass `confirmed_at IS NULL` → 2 transition lọt. Sửa: dùng atomic UPDATE...RETURNING để claim token + state transition trong cùng transaction:

```python
# app/core/deps.py — dependency atomic claim
async def get_profile_by_magic_link_token(
    token: str = Path(...),
    action: str = Path(...),
    db: AsyncSession = Depends(get_db),
) -> AdmissionProfile:
    """Atomic claim token + return profile. 2 request song song chỉ 1 thắng."""
    # UPDATE...RETURNING atomic: chỉ row đầu match WHERE clause được claim
    result = await db.execute(text("""
        UPDATE admission_confirmation_token
        SET confirmed_at = NOW()
        WHERE token = :raw_token
          AND action_type = :action_type
          AND confirmed_at IS NULL
          AND expires_at > NOW()
          AND attempt_count < 5
        RETURNING profile_id
    """), {"raw_token": token, "action_type": action})
    row = result.scalar_one_or_none()
    if row is None:
        # Token invalid/expired/already-used/locked — cùng error tránh leak
        raise ResourceNotFoundError("Token invalid or expired")
    profile = await db.get(AdmissionProfile, row)
    if profile is None:
        raise ResourceNotFoundError("Profile not found")
    return profile
```

**Lưu ý**: token đã `confirmed_at = NOW()` ngay khi dependency resolve. Nếu state transition sau đó fail → caller phải rollback transaction → `confirmed_at` revert. KHÔNG dùng nested transaction cho token claim (cần atomic với main tx).

**⚠️ PATCH-12 v2.13 — `attempt_count` SEPARATE short tx (chống bruteforce reset qua tx rollback)**:

Verified anti-pattern: nếu dependency increment `attempt_count` trong cùng main tx với state transition → main tx rollback → `attempt_count` revert về 0 → attacker reset count mỗi fail → unlimited bruteforce.

Pattern đúng: `attempt_count++` qua **savepoint** hoặc **separate short tx commit ngay** trước main tx:

```python
async def get_profile_by_magic_link_token(
    token: str, action: str, db: AsyncSession,
):
    # PATCH-12: attempt_count tracking SEPARATE short tx — chống bruteforce reset
    # Step 1: Lookup token (no claim yet) — read-only
    record = await db.execute(
        select(AdmissionConfirmationToken)
        .where(AdmissionConfirmationToken.token == token)
        .where(AdmissionConfirmationToken.action_type == action)
    ).scalar_one_or_none()
    if record is None:
        raise ResourceNotFoundError("Token invalid")
    if record.confirmed_at is not None or record.expires_at < func.now():
        raise ResourceNotFoundError("Token expired or used")
    if record.attempt_count >= 5:
        raise BusinessRuleViolation("Token locked sau 5 lần thử")

    # Step 2 sẽ check CCCD ở endpoint body. Nếu CCCD sai, endpoint phải:
    #   2a. Increment attempt_count trong SHORT TX RIÊNG (commit ngay):
    #       async with db.begin():  # nested or new tx
    #           await db.execute(
    #               update(AdmissionConfirmationToken)
    #               .where(id=record.id)
    #               .values(attempt_count=record.attempt_count + 1)
    #           )
    #           # commit này INDEPENDENT với main tx — không revert qua main rollback
    #   2b. Raise ValidationError("CCCD không khớp")

    # Step 3: CCCD OK → atomic claim (UPDATE...RETURNING confirmed_at = NOW)
    # Trong main tx — nếu state transition sau fail, rollback main → confirmed_at revert (OK,
    # token vẫn có thể claim lại). Nhưng attempt_count đã commit ở Step 2a (không revert).
    return profile
```

Hoặc dùng savepoint: `async with db.begin_nested(): increment + commit savepoint` → main tx rollback giữ nguyên savepoint commits.

**Test bắt buộc**: 5 CCCD wrong attempts với mỗi attempt main tx rollback → token attempt_count phải = 5 (không reset về 0). Lockout active sau attempt thứ 5.

**Audit chain**:
- Mọi action qua magic_link insert `admission_profile_status_history` row với `transitioned_by_lead_id = profile.lead_id`, `transitioned_by_user_id = NULL`, `actor_actual_role = 'candidate'`, `effective_transition_role = 'candidate'`.
- Token `confirmed_at` set atomic trong dependency UPDATE...RETURNING (cùng transaction với state transition).

#### 3.3.g.1. Public submit lifecycle (token issuance + idempotency + anti-bot)

Plan v2.8 thiếu spec ai tạo draft profile + ai phát submit token. Public surface mới — phải chốt rõ:

**Lifecycle**:

```
1. Officer/admin tạo Lead qua /api/v2/leads (internal route)
   ↓
2. System auto-create draft AdmissionProfile (status='draft', uses_choice_engine=true)
   + auto-issue submit token (action_type='submit', TTL 7 ngày)
   ↓
3. System gửi email/SMS với link /api/v2/public/admissions/{token}/submit
   ↓
4. Candidate click → atomic claim token + render form
   ↓
5. Candidate submit form → atomic transition draft → submitted + confirmed_at set
```

**Idempotency rules**:
- `AdmissionProfile` UNIQUE `(citizen_id, academic_year)` đã có ở model — backend reject 409 Conflict nếu duplicate.
- `Lead` lookup đầu tiên bằng `(citizen_id, academic_year)` — nếu đã có → reuse lead, recreate profile.
- Email/phone không phải UNIQUE key — chỉ contact info.

**Anti-bot + rate limit**:
- Endpoint `/api/v2/public/admissions/{token}/submit`: rate limit 5/min/token + 30/min/IP (đã spec).
- reCAPTCHA v3 ở FE form (score < 0.5 → reject + log).
- IP allowlist cho campus computer (officer hỗ trợ thí sinh) — config ở Nginx.

**Duplicate hồ sơ theo round/path (Q3 chốt 2026-05-01 v2.13 — 1 profile/year only)**:
- ✅ Same profile có thể có nhiều `AdmissionProfileChoice` cho cùng round (multi-NV — NV1/NV2/NV3 trong cùng round).
- ✅ UNIQUE `(profile_id, path_id, config_id)` chặn 2 NV trùng tổ hợp y hệt.
- ❌ **BLOCK multi-round per profile cho 2026**: 1 lead → 1 profile/academic_year → 1 round. Composite UNIQUE `(lead_id, academic_year)` ở Phase 1 #15 enforce naturally.
- Lý do BLOCK: `AdmissionProfile.status` là scalar field — 1 profile chỉ có 1 status tại 1 thời điểm. Multi-round per profile = phức tạp lifecycle (profile có thể đậu DOT_1 + apply DOT_2 cùng năm = 2 status đồng thời). `applied_rules.admission_round_id` immutable sau create + service guard.
- **Defer Phase 4+ (Q1/2027 trở lên)**: nếu nghiệp vụ thực tế yêu cầu multi-round per profile, design lại lifecycle (mỗi choice có per-round status thay vì profile-level status).

**Token revocation (atomic chống race với candidate consume)**:

Officer hủy lead/profile → mọi token chưa `confirmed_at` revoke. KHÔNG dùng pattern `SELECT tokens` rồi `UPDATE expires_at` (race window: candidate có thể atomic claim ở giữa).

Endpoint `/api/v2/admissions/{id}/revoke-tokens` admin only — atomic compound:
```sql
-- Atomic: chỉ revoke token còn ACTIVE (confirmed_at IS NULL).
-- RETURNING list cho admin verify N token đã thực sự revoke.
UPDATE admission_confirmation_token
SET expires_at = NOW(),
    revoked_at = NOW(),  -- field mới (Phase 1 #18 thêm cùng action_type)
    revoked_by_user_id = :admin_id
WHERE profile_id = :profile_id
  AND confirmed_at IS NULL
  AND expires_at > NOW()  -- chỉ revoke token chưa expire (đã expire không cần revoke lại)
RETURNING id, action_type, expires_at;
```

Admin response trả `revoked_count: int + revoked_tokens: list[{id, action_type}]`. Nếu candidate đã consume token ở giữa (atomic UPDATE...RETURNING claim ở dependency) → token row có `confirmed_at != NULL` → admin revoke không match WHERE → KHÔNG return → admin biết "token đã được dùng trước revoke" + audit log lưu lại.

**Phase 1 #18 migration update**: ngoài `action_type`, thêm 2 column nữa cho audit revocation:
```sql
ALTER TABLE admission_confirmation_token
    ADD COLUMN revoked_at TIMESTAMPTZ NULL,
    ADD COLUMN revoked_by_user_id INT NULL REFERENCES "user"(id) ON DELETE SET NULL;
CREATE INDEX ix_token_revoked ON admission_confirmation_token (revoked_at)
    WHERE revoked_at IS NOT NULL;
```

#### 3.3.e. Transactional outbox cho critical events

`safe_dispatch` post-commit vẫn còn gap: process crash hoặc dispatcher lỗi sau commit → status đã đổi DB nhưng event không fanout. 12 milestone events nhiều cái critical (admit/reject decision); broadcast batch của `RESULT_PUBLISHED` impact hàng nghìn thí sinh — cần guarantee delivery.

**Outbox table (Phase 3 migration):**
```sql
CREATE TABLE notification_outbox (
    id BIGSERIAL PRIMARY KEY,
    event_code VARCHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,  -- e.g. "ADMITTED:profile_42:choice_1"
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    dispatched_at TIMESTAMPTZ NULL,
    attempts INT NOT NULL DEFAULT 0,
    last_error TEXT NULL
);
CREATE INDEX ix_outbox_pending ON notification_outbox (created_at)
    WHERE dispatched_at IS NULL;
```

**Service pattern — gọi qua API duy nhất `dispatch_event()` (KHÔNG INSERT outbox direct):**

⚠️ **Anti-pattern v2.4**: service body INSERT outbox row direct. Sửa: dùng API `dispatch_event()` (Phần 3.3.f) — function tự route theo `event_def.requires_outbox` flag. Service KHÔNG có discretion.

```python
async def transition(...):
    # ... update profile.status + insert status_history
    await db.flush()
    # Notification dispatch qua API duy nhất — function tự route outbox vs direct.
    # ⚠️ v2.13.1 fix (round 20 verify): align với existing dispatcher signature.
    # Verified `notification_dispatcher.py:593,1853`: `dispatch(db, event: SystemEvents, payload, dedupe_key, skip_preference_check, strict, rooms)`
    # + `safe_dispatch(db, event, payload, dedupe_key, skip_preference_check, rooms)`.
    # KHÔNG dùng `event_code=...` (string), KHÔNG dùng `idempotency_key=...` — code thật dùng
    # `event=` (enum) + `dedupe_key=`. Outbox COLUMN `idempotency_key` (DB) là OK — chỉ wrapper
    # API arg name phải align.
    notif_callback = None
    if event_def:
        dedupe_key = f"{event_def.code.value}:{profile.id}:{metadata.get('choice_priority', 0)}"
        # dispatch_event INSERT outbox cùng tx nếu requires_outbox=True (return None),
        # hoặc trả callback cho router gọi sau commit (best-effort).
        notif_callback = await dispatch_event(
            db,
            event=event_def.code,  # SystemEvents enum, KHÔNG string
            payload={"profile_id": profile.id, "from_status": from_status, "to_status": to_status},
            dedupe_key=dedupe_key,  # KHÔNG `idempotency_key`
        )
    return profile, notif_callback  # router: commit → await callback nếu khác None
```

**Worker dispatch (Celery beat task, chạy mỗi 10s):**

⚠️ **Anti-pattern**: Lock batch + `commit()` trong loop → commit đầu release lock toàn batch → worker khác pick up duplicate. KHÔNG dùng pattern này.

**Pattern đúng — 3-step claim/dispatch/finalize (KHÔNG hold tx khi gọi external IO):**

⚠️ **Anti-pattern bổ sung**: lock row bằng `FOR UPDATE` rồi gọi `safe_dispatch` (Zalo/email/SMS) trong cùng tx → giữ DB connection + row lock 5-30s mỗi external call. Throughput chết. Crash post-dispatch trước commit → row vẫn `dispatched_at IS NULL` → re-dispatch duplicate.

Cần thêm 2 column outbox: `claimed_at TIMESTAMPTZ NULL`, `claimed_until TIMESTAMPTZ NULL`. Body migration apply ở `phase1_19a_create_outbox_table` (active owner — phase3_03 đã SUPERSEDED 2026-05-01). DDL cụ thể:
```sql
ALTER TABLE notification_outbox
    ADD COLUMN claimed_at TIMESTAMPTZ NULL,
    ADD COLUMN claimed_until TIMESTAMPTZ NULL;
CREATE INDEX ix_outbox_claim ON notification_outbox (claimed_until)
    WHERE dispatched_at IS NULL;
```

**Worker pattern (FIXED v2.3):**

⚠️ **Anti-pattern v2.2**: `UPDATE ... RETURNING ... fetchmany(100)` UPDATE TOÀN BỘ pending rows trước khi `fetchmany` cap. Postgres execute UPDATE atomically trên all-matching rows; client `fetchmany` chỉ hạn chế số row trả về, KHÔNG hạn chế số row UPDATE. Kết quả: rows ngoài 100 đầu vẫn `attempts++` + `claimed_until` set mà không dispatch → chạm cap 5 → DLQ mà không gửi.

**Pattern đúng — 2-step CTE: SELECT ID có LIMIT + lock, UPDATE WHERE id IN (...):**

```python
@celery.task
async def dispatch_pending_outbox():
    pending_rows = []
    # STEP 1 — Short tx claim với 2-step CTE
    async with db.begin() as conn:
        # Sub-step 1a: SELECT 100 IDs với FOR UPDATE SKIP LOCKED
        # → atomic claim, không 2 worker cùng pick
        candidate_ids = (await conn.execute(text("""
            SELECT id FROM notification_outbox
            WHERE dispatched_at IS NULL
              AND attempts < 5
              AND (claimed_until IS NULL OR claimed_until < NOW())
            ORDER BY created_at
            LIMIT 100
            FOR UPDATE SKIP LOCKED
        """))).scalars().all()

        if not candidate_ids:
            return

        # Sub-step 1b: UPDATE chỉ các IDs đã claim (KHÔNG full-table UPDATE)
        # Adaptive claimed_until: batch size × 5s/external IO call, cap 600s.
        # Tránh worker timeout < dispatch time → row sau bị worker khác duplicate (P1 fix #3 v2.11).
        # Email không có dedupe key honor → user nhận email duplicate.
        batch_size = len(candidate_ids)
        timeout_seconds = min(batch_size * 5, 600)  # cap 10 phút
        rows = (await conn.execute(text(f"""
            UPDATE notification_outbox
            SET claimed_at = NOW(),
                claimed_until = NOW() + interval '{timeout_seconds} seconds',
                attempts = attempts + 1
            WHERE id = ANY(:ids)
            RETURNING id, event_code, payload, idempotency_key
        """), {"ids": candidate_ids})).fetchall()
        pending_rows = [(r.id, r.event_code, r.payload, r.idempotency_key) for r in rows]
        # Tx commit ở cuối async with — release FOR UPDATE lock

    # STEP 2 — External dispatch NGOÀI DB tx (no connection held).
    # Outbox column `event_code` lưu string (enum.value); resolve về SystemEvents enum
    # trước khi gọi `dispatch(db, event: SystemEvents, payload, dedupe_key, skip_preference_check, strict)`.
    # ⚠️ v2.13.1 fix (round 20 verify): worker dùng `dispatch()` (CÓ `strict` param), KHÔNG dùng
    # `safe_dispatch()` (KHÔNG có `strict`). Worker tự manage commit.
    # bypass_consent_check lookup từ EVENT_CATALOG cho 5 critical event.
    results = []
    async with get_async_db() as worker_db:  # session riêng cho dispatch — không hold lock tx Step 1
        for row_id, event_code, payload, idem_key in pending_rows:
            try:
                event = SystemEvents(event_code)  # cast string column → enum
                event_def = EVENT_CATALOG[event]   # lookup metadata
                # PATCH-11 v2.13.1 fix (round 20 verify): safe_dispatch() KHÔNG nhận `strict`
                # (verified `notification_dispatcher.py:1853-1860`: chỉ có db, event, payload,
                # dedupe_key, skip_preference_check, rooms).
                # `dispatch()` (line 593-601) CÓ `strict: bool = False` — đúng API cần dùng.
                # Per memory `dispatch-bundle-strict-required`: dispatch() có 3 persistence
                # branches gọi db.rollback() internal → KHÔNG strict=True → worker fail nuốt
                # outer tx → claim không release → backlog.
                notif_ids, _cb = await dispatch(
                    db=worker_db,
                    event=event,
                    payload=payload,
                    dedupe_key=idem_key,
                    skip_preference_check=event_def.bypass_consent_check,  # 5 critical bypass
                    strict=True,  # required: rollback savepoint thay vì outer tx
                )
                # Worker tự manage commit (KHÔNG dùng safe_dispatch fire-and-forget pattern)
                await worker_db.commit()
                results.append((row_id, "ok", None))
            except Exception as e:
                results.append((row_id, "error", str(e)[:1000]))

    # STEP 3 — Short tx mark final state:
    async with db.begin() as conn:
        for row_id, status, error in results:
            if status == "ok":
                await conn.execute(
                    update(NotificationOutbox)
                    .where(NotificationOutbox.id == row_id)
                    .values(dispatched_at=func.now(), claimed_until=None)
                )
            else:
                await conn.execute(
                    update(NotificationOutbox)
                    .where(NotificationOutbox.id == row_id)
                    .values(last_error=error, claimed_until=None)  # release claim cho retry sau
                )
```

**Tại sao 3-step an toàn:**
- Step 1 atomic UPDATE với `claimed_until` → 2 worker concurrent KHÔNG cùng claim (claim đầu set `claimed_until = now()+60s`, claim sau filter `claimed_until < now()` không match).
- Step 2 chạy ngoài tx → connection trả pool, không hold lock.
- Worker crash giữa Step 2-3 → `claimed_until` expire sau 60s, worker khác pick up. `attempts` đã tăng ở Step 1 → cap 5 vẫn enforce.
- `idempotency_key` UNIQUE bảo vệ end-to-end: dispatcher SDK (Zalo/email) honor key → re-send không duplicate fanout end-user.

**Recovery & guarantees:**
- Process crash sau DB commit nhưng trước outbox dispatch → worker pick up + dispatch.
- Dispatcher crash → `attempts` tăng + retry cap 5 → manual review nếu > 5.
- `idempotency_key` UNIQUE → re-run worker không duplicate fanout (SDK Zalo/email phải honor key).
- Direct `safe_dispatch` (non-outbox) chỉ giữ cho non-critical events (e.g. internal log/socket update) — khi mất event không sai nghiệp vụ.

#### 3.3.f. Dispatcher routing logic (KHÔNG accidental call)

Plan có 7 outbox-critical events + 5 best-effort. Dev có thể accidental call `safe_dispatch()` cho critical event → silent fail guarantee. Dispatcher PHẢI route theo flag, KHÔNG để service tự chọn:

**API duy nhất `dispatch_event()`** — service KHÔNG gọi `safe_dispatch` hoặc `dispatch` raw, KHÔNG quyết định outbox vs direct. Function tự route + return contract rõ ràng.

**Verified existing dispatcher signature** (`app/services/notification_dispatcher.py:593,1853`): `dispatch(db, event: SystemEvents, ...)` + `safe_dispatch(...)` dùng `dedupe_key: Optional[str]` (không phải `idempotency_key`). `dispatch_event()` wrapper PHẢI align để không runtime TypeError:

**EVENT_CATALOG init strategy chốt module-level dict (P1 fix #3 v2.12)**:

Memory `celery-worker-init-gap`: Celery worker không run FastAPI `main.py` startup → DB-backed lazy catalog risk worker miss. Chốt strategy:

- **Module-level Python dict** ở `app/core/event_catalog.py`:
  ```python
  # app/core/event_catalog.py
  EVENT_CATALOG: dict[SystemEvents, EventDefinition] = {
      SystemEvents.ADMISSION_PROFILE_SUBMITTED: EventDefinition(
          code=SystemEvents.ADMISSION_PROFILE_SUBMITTED,
          requires_outbox=False, bypass_consent_check=False,
          audience_roles=['officer', 'candidate'],
          template_codes_by_channel={'email': 'tpl_admission_submitted_v1', ...},
      ),
      # ... 11 events còn lại
  }
  ```
- Worker process import `app.core.event_catalog` → catalog ready ở module load. KHÔNG cần DB query startup.
- Migration `phase1_19` seed CHỈ DB rows phục vụ admin UI (`notification_rule` + `notification_template` tables) — KHÔNG là source of truth cho dispatcher.
- Coverage script `check_notification_event_coverage.py` verify EVENT_CATALOG dict keys khớp với DB seed entries (consistency check), KHÔNG load runtime.

```python
# app/core/event_catalog.py — extend EventDefinition
class EventDefinition(BaseModel):
    code: SystemEvents                    # ENUM, không string
    requires_outbox: bool = False         # Critical → outbox guarantee
    bypass_consent_check: bool = False    # System-critical → ignore consent revoke
    audience_roles: list[str]
    template_codes_by_channel: dict

# app/services/notification_dispatcher.py — chốt API duy nhất
async def dispatch_event(
    db, *, event: SystemEvents, payload: dict, dedupe_key: Optional[str] = None
) -> Optional[Callable[[], Awaitable[None]]]:
    """
    Chốt 1 API duy nhất cho notification trong admission domain.

    Returns:
        - None: nếu event requires_outbox=True (đã INSERT outbox cùng tx).
                Worker beat sẽ dispatch sau commit. Caller KHÔNG cần làm gì thêm.
        - Callable[[], Awaitable[None]]: best-effort callback cho router gọi
          SAU db.commit(). Caller PHẢI await callback nếu khác None.

    Service contract:
        - Service luôn gọi dispatch_event() trong service body (cùng transaction).
        - Service trả callback về router cùng `(result, callback)` tuple.
        - Router commit DB → await callback nếu không None.
    """
    event_def = EVENT_CATALOG[event]  # event là SystemEvents enum, không string

    if event_def.requires_outbox:
        if dedupe_key is None:
            raise ValueError(
                f"Event {event.name} requires_outbox=True needs dedupe_key"
            )
        # INSERT outbox row CÙNG transaction service đang gọi (atomic)
        # idempotency_key column tên giữ trong outbox table cho rõ ngữ nghĩa,
        # nhưng API arg dùng dedupe_key align dispatcher existing.
        db.add(NotificationOutbox(
            event_code=event.value,           # enum.value để serialize
            payload=payload,
            idempotency_key=dedupe_key,       # column name khác arg name OK
        ))
        return None  # Worker beat sẽ dispatch sau
    else:
        # Best-effort path — return callback cho router safe_dispatch sau commit.
        # Capture db session qua closure — router bind session active sau commit.
        # safe_dispatch signature existing: (db, event: SystemEvents, payload, dedupe_key, skip_preference_check)
        captured_db = db   # closure capture
        captured_skip = event_def.bypass_consent_check  # cho 5 critical event
        async def post_commit_callback():
            await safe_dispatch(
                db=captured_db,
                event=event,
                payload=payload,
                dedupe_key=dedupe_key,
                skip_preference_check=captured_skip,
            )
        return post_commit_callback
```

**Service caller pattern** (cập nhật theo signature mới):
```python
notif_callback = await dispatch_event(
    db,
    event=SystemEvents.ADMISSION_DECISION_ADMITTED,  # enum, không string
    payload={"profile_id": profile.id, "choice_priority": 1, ...},
    dedupe_key=f"ADMITTED:{profile.id}:1",
)
```

**Service pattern (chuẩn duy nhất, v2.13.1 fix align signature thật):**
```python
async def transition(...):
    # ... build event_payload, dedupe_key (KHÔNG idempotency_key)
    notif_callback = await dispatch_event(
        db,
        event=event_def.code,  # SystemEvents enum
        payload=event_payload,
        dedupe_key=f"{event_def.code.value}:{profile.id}:{choice_priority}",
    )
    return profile, notif_callback  # callback có thể là None hoặc awaitable
```

**Router pattern (chuẩn duy nhất):**
```python
@router.post("/admissions/{id}/transition")
async def transition_endpoint(...):
    profile, notif_callback = await state_service.transition(...)
    await db.commit()
    if notif_callback is not None:
        await notif_callback()
    return profile
```

**Tránh mâu thuẫn v2.2:**
- KHÔNG có route nào service tự `safe_dispatch` trong service body.
- KHÔNG có route nào service quyết định outbox vs direct — chỉ event_def.requires_outbox quyết định.
- Coverage script verify mọi `safe_dispatch` call ngoài `dispatch_event` body raise error.

**Coverage script extend** (`app/scripts/check_notification_event_coverage.py`):
```python
def check_outbox_consistency(event_def):
    """Verify event với requires_outbox=True có dispatch site INSERT outbox,
       KHÔNG phải safe_dispatch trực tiếp."""
    if event_def.requires_outbox:
        sites = grep(f"event_code.*{event_def.code}|EventCode\\.{event_def.code}")
        for site in sites:
            if "safe_dispatch" in surrounding_lines(site, 10):
                raise CoverageError(
                    f"{event_def.code} requires_outbox=True but found "
                    f"safe_dispatch call at {site}. Use dispatch_event() instead."
                )
```

**Bypass consent rule** (cho 5 events: ADMITTED/WAITLISTED/REJECTED/RESULT_PUBLISHED/ENROLLED):
```python
# app/services/zalo_dispatcher.py — extend
async def send_zns(db, profile, message, *, event_def):
    if not event_def.bypass_consent_check:
        consent = await get_zalo_consent(db, profile.lead_id)
        if consent.status != 'granted':
            log.info(f"Skip ZNS — consent revoked, event={event_def.code}")
            return
    # System-critical events bypass consent — vẫn gửi
    await zns_send(message)
```

Document compliance: bypass áp dụng cho thông báo BẮT BUỘC theo Quy chế Bộ GD&ĐT (kết quả tuyển sinh, danh sách đậu/rớt/dự bị, ghi danh chính thức). Best-effort events (REVISION_REQUESTED, CONFIRMED, WITHDRAWN, etc.) vẫn respect consent revoke.

**12 events apply outbox (chốt từ table 3.3.d):**
- Critical (outbox bắt buộc, 6 events): `RESULT_PUBLISHED`, `DECISION_ADMITTED`, `DECISION_WAITLISTED`, `DECISION_REJECTED`, `WAITLIST_PROMOTED`, `ENROLLED`, `ROLLED_BACK`.
- Best-effort (direct dispatch OK, 5 events): `PROFILE_SUBMITTED`, `REVISION_REQUESTED`, `RESUBMITTED`, `CONFIRMED`, `WITHDRAWN`.

---

## Phần 4 — Migration plan (4 phase)

### Phase 0 — P1 score/submit fixes (1 sprint, không phụ thuộc refactor)

3 bug đã verify ở `app/services/admission_service.py:3712-3825` và `admission_scoring_service.py:246-345`:

1. **P1-1**: `submit_and_evaluate` subject_based branch không check `score_result.passed` → fix: reject nếu `passed=False`.
2. **P1-2**: `min_gpa` không apply cho subject_based path → fix: so avg(selected scores) với `min_gpa` trong subject_based branch.
3. **P1-3**: `Profile.selected_group` chưa persist + chưa enforce subject restriction.
   - **Fix Phase 0** (migration + service):
     - Migration `phase0_add_selected_subject_group_id_to_profile.py`: thêm `AdmissionProfile.selected_subject_group_id INT NULL FK → subject_group.id`. **Phase 0 chỉ persist forward (profile mới submit sau Phase 0).** Backfill data lịch sử dùng decision tree 3 rule ở Phase 1 #13 (verified `applied_rules` KHÔNG có `selected_group_code` nguồn).
     - Service: lưu vào column khi submit, validate scores chỉ thuộc group đã chọn.
   - **Lý do persist**: Phase 3 backfill `AdmissionProfileChoice` cần biết group thí sinh đã chọn. Nếu chỉ trong request/schema, backfill phải đoán → high risk.

**Lý do tách Phase 0:** stop bleeding scoring bugs, đồng thời chuẩn bị data cho Phase 3 backfill choice (persist `selected_subject_group_id`). Có thể ship song song khi user đang finalize Phase 1 design.

**Phase 0c — Hot-fix pre-existing field-name drift** (code-only PR, KHÔNG Alembic):

Verified bug: `app/repositories/admission_config_repository.py:76,84` dùng `OfferingAdmissionConfig.admission_criteria_id` và `AdmissionPath.admission_criteria_id`. Model thực tế là `criteria_id` (xem `app/models/admission_config/admission_path.py:82`). Hai query này silent broken — `select(...).where(.admission_criteria_id == ...)` raise `AttributeError` runtime khi gọi `check_criteria_usage()`.

Pre-existing bug, KHÔNG phải scope refactor. Phải fix TRƯỚC khi Phase 1 dựa vào repository này:
```python
# app/repositories/admission_config_repository.py
# Line 76 (old): .where(OfferingAdmissionConfig.admission_criteria_id == criteria_id)
# Line 76 (new):
.where(OfferingAdmissionConfig.criteria_id == criteria_id)

# Line 84 (old): .where(AdmissionPath.admission_criteria_id == criteria_id)
# Line 84 (new):
.where(AdmissionPath.criteria_id == criteria_id)
```

Ship cùng Phase 0 wave (W1-W2). Bug lâu nay silent vì caller `check_criteria_usage()` chỉ chạy ở admin delete criteria endpoint hiếm gọi. Phase 1 dependency check sẽ rely on repository này → must fix.

**Phase 0 thêm migration `phase0b_relax_applied_rules_immutability_for_payment_keys.py`** (CRITICAL — chặn fee endpoint break sau khi extend status CHECK):

Code production hiện UPDATE 3 key trong `applied_rules` ở `admission_service.py:5904-5906` (`record_application_fee_payment`) sau khi profile approved:

* `applied_rules["fee_status"]` — flip từ `"pending"`/`"exempt"` (init line 2745) sang `"paid"`.
* `applied_rules["fee_paid_at"]` — ISO timestamp.
* `applied_rules["fee_payment_data"]` — JSONB blob từ gateway.

Trigger `b5c6d7e8f9a0` `prevent_applied_rules_update` raise nếu `OLD.applied_rules IS DISTINCT FROM NEW.applied_rules` — block toàn bộ change. Existing test `tests/services/test_admission_application_fee.py:340-341` assert cả `fee_status == "paid"` lẫn `fee_paid_at` is not None — chỉ pass vì trigger chưa được apply trong test fixtures hiện tại; deploy Phase 1 → trigger active prod → fee endpoint break.

```sql
-- Replace trigger function: classify per-key change.
-- Whitelist 5 key ADD/UPDATE được; deletion bị reject ngay cả với whitelisted keys
-- (PLAN nói "thêm/update", không nói xóa — strip-and-compare tham khảo bên dưới
-- có blind spot với deletion).
CREATE OR REPLACE FUNCTION prevent_applied_rules_update()
RETURNS TRIGGER AS $$
DECLARE
    allowed_keys TEXT[] := ARRAY[
        'fee_status',
        'fee_paid_at',
        'fee_payment_data',
        'fee_calculated_at',
        'fee_invoice_id'
    ];
    v_key TEXT;
    v_all_keys TEXT[];
    v_old_value JSONB;
    v_new_value JSONB;
    v_old_has BOOLEAN;
    v_new_has BOOLEAN;
BEGIN
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.applied_rules IS NULL THEN
            RETURN NEW;
        END IF;
        IF OLD.applied_rules IS NOT DISTINCT FROM NEW.applied_rules THEN
            RETURN NEW;
        END IF;
        IF NEW.applied_rules IS NULL THEN
            RAISE EXCEPTION 'applied_rules is immutable; cannot wipe entire object';
        END IF;

        SELECT ARRAY(
            SELECT DISTINCT k FROM (
                SELECT jsonb_object_keys(OLD.applied_rules) AS k
                UNION
                SELECT jsonb_object_keys(NEW.applied_rules) AS k
            ) sub
        ) INTO v_all_keys;

        FOREACH v_key IN ARRAY v_all_keys LOOP
            v_old_has := OLD.applied_rules ? v_key;
            v_new_has := NEW.applied_rules ? v_key;
            v_old_value := OLD.applied_rules -> v_key;
            v_new_value := NEW.applied_rules -> v_key;
            IF v_old_value IS DISTINCT FROM v_new_value
               OR v_old_has <> v_new_has THEN
                IF NOT (v_key = ANY(allowed_keys)) THEN
                    RAISE EXCEPTION 'applied_rules: key % is immutable', v_key;
                END IF;
                IF v_old_has AND NOT v_new_has THEN
                    RAISE EXCEPTION 'applied_rules: deletion of key % is not allowed', v_key;
                END IF;
            END IF;
        END LOOP;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

Down migration: revert về function v1 strict (literal-for-literal từ `b5c6d7e8f9a0`).

**Drift fix (round 24 — chốt 2026-05-02 trong M-P0b PR):**
- Whitelist mở rộng từ 4 key → 5 key. PLAN v2.13.1 đề xuất `fee_paid_at` + `fee_payment_data` + `fee_calculated_at` + `fee_invoice_id` (4 key) miss `fee_status`. Code thực tế ở `admission_service.py:5904` ghi `fee_status = "paid"`; nếu thiếu, fee endpoint vẫn break sau Phase 1 #11. Verified-from-code 2026-05-02 trong cùng PR.
- Logic trigger thay từ strip-and-compare → per-key classification. Strip pattern đã tham khảo trong bản v2.13.1 có blind spot với deletion (strip allowed key khỏi cả OLD lẫn NEW khiến delete equal add equal update — tất cả silent allow). Per-key classification phân biệt rõ add/update (allow nếu whitelisted) vs delete (reject ngay cả khi whitelisted).

**Lý do Phase 0**: Migration này độc lập với choice-engine refactor, NHƯNG phải chạy TRƯỚC Phase 1 status CHECK extend. Nếu để sang Phase 1, fee payment endpoint break ngay khi profile có `applied_rules.fee_paid_at` được update (mọi profile post-payment).

**Lưu ý — Single owner column**: Phase 0 migration là **owner duy nhất** của column `selected_subject_group_id` (DDL ADD COLUMN). Phase 1 #13 KHÔNG re-define column — chỉ làm 2 việc:
- Pre-flight verify column exists (raise nếu không, hint chạy Phase 0 trước).
- Backfill data lịch sử qua decision tree 3 rule + insert exception rows.

Phase 0 là **ancestor của `phase1_01`**, KHÔNG trỏ trực tiếp tới `phase1_12`. Linear chain: `<head> → phase0 → phase1_01 → ... → phase1_11 → phase1_12`. `phase1_12.down_revision = phase1_11` (CHECK constraint extend). Pre-flight check trong `phase1_12` verify column tồn tại — nếu không, raise hint user áp Phase 0 trước. Môi trường staging/dev chạy full chain tự động đúng thứ tự; môi trường prod đã ship Phase 0 → áp Phase 1 chain bình thường.

### Phase 1 — Additive, zero breaking (1-2 sprint)

Thêm field nullable, không phá schema, không breaking change.

**Pre-flight task (1 ngày, BẮT BUỘC trước khi viết migration đầu tiên):**
- Audit `applied_rules` immutability trigger DDL: `alembic/versions/b5c6d7e8f9a0_add_applied_rules_immutability_trigger.py`. Confirm pattern DROP → backfill → CREATE. Trigger dùng `IS DISTINCT FROM` strict — bất kỳ update nào với value khác sẽ raise.

**Migrations (~10 file). Mỗi file ghi rõ `down_revision` để Alembic enforce thứ tự:**

⚠️ **Q9 deferred items (chốt 2026-05-01)**: 3 migration dưới đây (`phase1_04`, `phase1_07`, `phase1_09b`) ĐƯỢC GIỮ LẠI CHỈ ĐỂ THAM KHẢO Phase 4 Q1/2027. **KHÔNG implement trong active 2026 cutover chain.** Body đầy đủ giữ nguyên cho Phase 4 reactivate; mỗi mục có nhãn DEFERRED inline. Active count Phase 1 = 18 migration (xem cheat sheet Phần 8). Phase 1 #09a chỉ backfill `gpa_overall` + `graduation_year` (KHÔNG conduct/health_category vì threshold tương ứng ở phase1_04 đã defer).

1. `phase1_01_add_degree_level_fk_to_major_program.py`
   - **KHÔNG tạo bảng mới** — `config_degree_level` đã có tại
     `app/models/config.py:53`. Verify bằng `\d config_degree_level` trước migration.
   - `MajorProgram.degree_level_id INT NULL FK → config_degree_level.id`
   - (Tùy chọn) thêm `config_degree_level.duration_default_semesters INT NULL` nếu
     chưa có — verify column hiện có trước, không tự ý add.
   - Backfill `degree_level_id` từ `degree_level` text bằng JOIN tên:
     ```sql
     UPDATE major_program mp
     SET degree_level_id = cdl.id
     FROM config_degree_level cdl
     WHERE mp.degree_level_id IS NULL
       AND lower(trim(mp.degree_level)) = lower(trim(cdl.name));
     ```
   - Idempotent: `WHERE degree_level_id IS NULL` per-row guard.

2. `phase1_02_add_bonus_rule_to_method_and_path.py`
   - `AdmissionMethod.default_bonus_rule` JSONB nullable
   - `AdmissionPath.bonus_rule_override` JSONB nullable

3. `phase1_03_add_applicable_to_method_quota_to_path.py` + **end-to-end PR**
   - `applicable_to ARRAY(Enum)` nullable
   - `method_quota` nullable
   - GIN index: `CREATE INDEX ix_admission_path_applicable_to ON admission_path USING GIN (applicable_to)`
   - **PR ship cùng phải bao gồm** (verified drift hiện tại — KHÔNG được merge migration trước layer này):
     - `app/schemas/admission_path.py:133` — extend `AdmissionPathCreate`/`AdmissionPathUpdate` request schema thêm 4 fields mới (`applicable_to`, `method_quota`, `bonus_rule_override`, `admission_round_id`).
     - `app/services/admission_path_service.py:145` — service create logic update: bỏ duplicate check `(academic_info_id, admission_method_id)` (sẽ break sau Phase 2 #2 swap unique), thay bằng check `(admission_round_id, admission_method_id)` nếu round đã set; service auto-resolve `DOT_1` nếu round null (xem Phase 2 #2 shim).
     - `app/services/admission_path_service.py` — `applied_rules` snapshot bao gồm 4 fields mới khi create profile từ path mới.
     - `frontend/src/lib/zod/admission-path.ts:117` — extend Zod schema cho path create/update + response.
     - FE form path admin update + UI cho 4 field mới (audience filter dropdown, method quota input, bonus rule override JSON editor).
   - **Query contract bắt buộc cho service repository** — GIN array index KHÔNG dùng được cho `:val = ANY(arr)` operator (Postgres planner không pick GIN cho `=ANY`). PHẢI dùng:
     - **Containment**: `applicable_to @> ARRAY[:audience]::admission_audience[]` (single value match)
     - **Overlap**: `applicable_to && ARRAY[:audiences]::admission_audience[]` (any-of-multiple match)
   - **NULL handling cho legacy path** (Phase 1+2, trước khi 100% backfill xong):
     ```sql
     -- Path chưa backfill applicable_to → NULL → @> không match → ẩn khỏi list.
     -- Trong Phase 1+2 phải preserve legacy với OR NULL branch:
     WHERE (applicable_to IS NULL OR applicable_to @> ARRAY[:audience]::admission_audience[])
     ```
   - **Phase 3 trước enable filter ở FE**: validator gate "X path có `applicable_to IS NULL` → admin set trước khi enable filter audience". Sau gate, query có thể bỏ NULL branch (chỉ dùng `@>`).
   - Smoke test bắt buộc: `EXPLAIN ANALYZE` cho endpoint filter audience phải show `Bitmap Index Scan on ix_admission_path_applicable_to`. Nếu thấy `Seq Scan`, query đã viết sai operator.
   - Anti-pattern (KHÔNG dùng): `WHERE :audience = ANY(applicable_to)` — đúng kết quả nhưng không hit index, scan full table.

4. ~~`phase1_04_add_extra_thresholds_to_criteria.py`~~ — **DEFERRED Q1/2027** (Q9 chốt 2026-05-01; KHÔNG ship 2026 cutover chain)
   - ~~`min_conduct`, `min_health_category`, `required_graduation_year_min/max` nullable~~ — body giữ tham khảo Phase 4.

5. `phase1_05_add_subject_kind_and_score_bounds.py`
   - `subject_kind` ENUM default `ACADEMIC_SUBJECT` cho backfill
   - `max_score`, `min_possible_score` nullable
   - Seed các subject ảo: `TB_HK1_L12`, `TB_HK2_L12`, `TB_CN_L12`, `DGNL_DHQGHN`, `V_ACT`, `IELTS`
   - Idempotent: `INSERT ... ON CONFLICT (code) DO NOTHING`

6. `phase1_06_add_path_id_to_document_group.py`
   - `admission_path_id` nullable + FK → `admission_path(id)` ON DELETE SET NULL
   - Partial index: `CREATE INDEX ix_doc_group_path ON document_group (admission_path_id) WHERE admission_path_id IS NOT NULL` — resolution rule query `WHERE admission_path_id = X` cần index FK-side.
   - **Service invariant** (validate khi tạo/sửa DocumentGroup ref path): `DocumentGroup.offering_type_id` + `admission_method_id` phải khớp với path đang ref:
     ```python
     if doc_group.admission_path_id:
         path = await db.get(AdmissionPath, doc_group.admission_path_id)
         offering = await db.get(ProgramOffering,
             (await db.get(OfferingAcademicInfo, path.academic_info_id)).offering_id)
         if doc_group.offering_type_id != offering.offering_type_id:
             raise BusinessRuleViolation("DocumentGroup.offering_type lệch path")
         if doc_group.admission_method_id and doc_group.admission_method_id != path.admission_method_id:
             raise BusinessRuleViolation("DocumentGroup.method lệch path")
     ```
     Lý do: resolution rule chọn DocumentGroup theo path TRƯỚC offering_type/method. Nếu path-level group có offering_type/method lệch, sẽ chọn group sai cho profile.
   - Service: implement resolution rule 3 tầng

7. ~~`phase1_07_add_demographics_to_profile.py`~~ — **DEFERRED Q1/2027** (Q9 chốt 2026-05-01; KHÔNG ship 2026 cutover chain)
   - ~~`area_code`, `priority_object_codes[]`, `candidate_education_level` nullable~~ — body giữ tham khảo Phase 4.
   - ~~Service: auto-compute `area_code` từ địa chỉ; auto-suggest `priority_object_codes` từ `disability_type`~~

7b. `phase1_07b_create_backfill_exceptions_table.py` ← **CHẠY TRƯỚC mọi migration insert exception** (active — required cho M-1-12 + M-3-01 backfill exception inserts)
   - Tạo `_admission_backfill_exceptions` (id, profile_id, exception_type, details JSONB, created_at, resolved_at, resolved_by_user_id, resolution_notes).
   - UNIQUE (profile_id, exception_type) — chặn duplicate.
   - INDEX (exception_type) cho admin filter.
   - Migration 9a, 12, 13 sau đó insert vào table này — KHÔNG tự tạo lại.

8. `phase1_08_add_uses_choice_engine_flag_to_profile.py`
   - `uses_choice_engine BOOLEAN NOT NULL DEFAULT false`
   - Backfill: `UPDATE admission_profile SET uses_choice_engine = false` (no-op nhờ default)

9. `phase1_09a_add_eligibility_scalars_and_backfill.py` ← **TÁCH 9a/9b**
   - `gpa_overall`, `conduct`, `health_category`, `graduation_year` nullable
   - **Verified `academic_history` JSON schema**: chỉ chứa `school_name`, `year_from`, `year_to`, `gpa`, `graduation_type`. KHÔNG có conduct/health_category.
   - **Backfill scope phân tách:**
     - `gpa_overall`: backfill từ record có ordinality cao nhất CÓ gpa numeric (không phải record cuối bất kỳ — record cuối có thể thiếu gpa nhưng record trước có):
       ```sql
       -- TEMP TABLE staging — CTE chỉ scope 1 statement; cần chia 2 statement
       -- (UPDATE valid + INSERT exception out-of-range), staging table giải quyết.
       -- TEMP tables auto-drop cuối transaction.
       -- Regex thêm length guard: GPA tối đa 3 chữ số nguyên + decimal optional.
       -- Tránh value '999999999999' pass regex format nhưng overflow numeric(8,4).
       -- Cast staging vào unconstrained `numeric` (không precision) để chứa edge case.
       CREATE TEMP TABLE _gpa_staging ON COMMIT DROP AS
       SELECT
           p.id AS profile_id,
           rec.ord AS ord,
           rec.value->>'gpa' AS gpa_text,
           (rec.value->>'gpa')::numeric AS gpa_value_wide  -- unconstrained numeric
       FROM admission_profile p,
            LATERAL jsonb_array_elements(p.academic_history) WITH ORDINALITY AS rec(value, ord)
       WHERE p.gpa_overall IS NULL
         AND p.academic_history IS NOT NULL
         AND rec.value->>'gpa' ~ '^[0-9]{1,3}(\.[0-9]{1,4})?$';  -- length-bounded regex

       CREATE INDEX ON _gpa_staging (profile_id, ord DESC);

       -- UPDATE: chỉ row trong range [0, 10] — cast vào numeric(4,2) sau khi đã filter range
       -- nên không có overflow risk.
       WITH gpa_in_range AS (
           SELECT profile_id, ord,
                  gpa_value_wide::numeric(4,2) AS gpa_value
           FROM _gpa_staging
           WHERE gpa_value_wide >= 0 AND gpa_value_wide <= 10
       ),
       latest_gpa AS (
           SELECT DISTINCT ON (profile_id) profile_id, gpa_value
           FROM gpa_in_range
           ORDER BY profile_id, ord DESC  -- explicit deterministic
       )
       UPDATE admission_profile p
       SET gpa_overall = lg.gpa_value
       FROM latest_gpa lg
       WHERE lg.profile_id = p.id
         AND p.gpa_overall IS NULL;

       -- INSERT exception: row out-of-range — dùng staging table, KHÔNG dùng CTE từ UPDATE
       INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
       SELECT profile_id, 'INVALID_GPA_VALUE',
              jsonb_build_object(
                  'out_of_range_values',
                  jsonb_agg(jsonb_build_object('text', gpa_text, 'numeric', gpa_value_wide))
              )
       FROM _gpa_staging
       WHERE gpa_value_wide NOT BETWEEN 0 AND 10
       GROUP BY profile_id
       ON CONFLICT (profile_id, exception_type) DO NOTHING;
       ```
     - `graduation_year`: backfill từ `year_to` của record có `graduation_type IS NOT NULL` + numeric + range thực tế [1900, 2100]:
       ```sql
       -- TEMP TABLE staging — chia 2 statement (UPDATE + INSERT exception)
       -- Regex length-bounded: year tối đa 4 chữ số. Cast staging sang bigint
       -- (unconstrained int phạm vi rộng) để không overflow trước range filter.
       -- LATERAL jsonb_array_elements(...) trả set có column tên `value` —
       -- alias bắt buộc dạng `AS rec(value)` rồi truy cập `rec.value->>'k'`.
       -- Dạng `AS rec` + `rec->>'k'` là SAI cú pháp Postgres → migration fail.
       CREATE TEMP TABLE _grad_year_staging ON COMMIT DROP AS
       SELECT
           p.id AS profile_id,
           rec.value->>'year_to' AS year_text,
           (rec.value->>'year_to')::bigint AS year_value  -- bigint chứa được 99999999999
       FROM admission_profile p,
            LATERAL jsonb_array_elements(p.academic_history) AS rec(value)
       WHERE p.graduation_year IS NULL
         AND rec.value->>'graduation_type' IS NOT NULL
         AND rec.value->>'year_to' ~ '^[0-9]{4}$';  -- length 4 — chặn overflow ngay regex

       CREATE INDEX ON _grad_year_staging (profile_id, year_value DESC);

       -- UPDATE: chỉ row trong range [1900, 2100]
       WITH latest_grad AS (
           SELECT DISTINCT ON (profile_id) profile_id, year_value
           FROM _grad_year_staging
           WHERE year_value BETWEEN 1900 AND 2100
           ORDER BY profile_id, year_value DESC
       )
       UPDATE admission_profile p
       SET graduation_year = lg.year_value
       FROM latest_grad lg
       WHERE lg.profile_id = p.id
         AND p.graduation_year IS NULL;

       -- INSERT exception: row out-of-range — dùng staging table
       INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
       SELECT profile_id, 'INVALID_GRADUATION_YEAR',
              jsonb_build_object('out_of_range_years', array_agg(year_value))
       FROM _grad_year_staging
       WHERE year_value NOT BETWEEN 1900 AND 2100
       GROUP BY profile_id
       ON CONFLICT (profile_id, exception_type) DO NOTHING;

       -- Profile có graduation_type nhưng year_to malformed/missing → exception
       -- Alias `AS rec(value)` bắt buộc cho jsonb_array_elements (set-returning với column `value`).
       INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
       SELECT p.id, 'MISSING_GRADUATION_YEAR',
              jsonb_build_object('academic_history', p.academic_history)
       FROM admission_profile p
       WHERE p.graduation_year IS NULL
         AND p.academic_history IS NOT NULL
         AND EXISTS (
             SELECT 1 FROM jsonb_array_elements(p.academic_history) AS rec(value)
             WHERE rec.value->>'graduation_type' IS NOT NULL
         )
       ON CONFLICT (profile_id, exception_type) DO NOTHING;
       ```
     - `conduct`: **để NULL** — không có nguồn trong JSON. Admin review qua UI Phase 1+2 (UI thêm field cho hồ sơ existing để admin nhập).
     - `health_category`: **để NULL** — không có nguồn. Admin review qua UI tương tự.
   - Insert exception row cho profile có `gpa_overall IS NULL` sau backfill (data nguồn lỗi):
     ```sql
     INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
     SELECT id, 'MISSING_GPA_OVERALL', jsonb_build_object('academic_history', academic_history)
     FROM admission_profile
     WHERE gpa_overall IS NULL AND status NOT IN ('draft', 'revision_requested')
     ON CONFLICT DO NOTHING;
     ```
   - **CHƯA tạo lock trigger** — backfill cần UPDATE mọi state, trigger sẽ block.
   - Idempotent: mỗi rule guard `WHERE <field> IS NULL`.

10. ~~`phase1_09b_create_eligibility_lock_trigger.py`~~ — **DEFERRED Q1/2027** (Q9 chốt 2026-05-01; KHÔNG chạy trong 2026 cutover chain)

    Lý do defer: lock-after-draft trigger là defense-in-depth cho admin-side data mutation; thiếu nó trong 2026 chỉ làm giảm guarantee (service guard đã đủ basic), KHÔNG block multi-NV/multi-round/scoring engine core. Reactivate ở Phase 4 Q1/2027 khi compliance audit + DB role coordination sẵn sàng.

    Body đầy đủ giữ tham khảo Phase 4:

    Defense-in-depth: maintenance bypass dùng **txid-bound audit token**. GUC chỉ là escape valve, KHÔNG phải authorization mechanism.

    Lý do bỏ GUC bypass: bất kỳ DB role nào cũng có thể `SET admission.maintenance_mode='on'` qua psql trực tiếp → bypass trigger mà không qua function/audit. Token-based check khắc phục: function `admission_maint.set_maintenance_mode()` insert audit row với `txid_current()`, trigger check `EXISTS audit row cùng txid`. SQL trực tiếp không gọi function → không có row cùng txid → trigger raise. SET GUC trực tiếp vô tác dụng.

    ```sql
    -- Schema riêng cho maintenance — separation of concern
    CREATE SCHEMA IF NOT EXISTS admission_maint;

    -- Audit table — txid là token cho trigger check, NOT NULL.
    -- Immutable: REVOKE UPDATE/DELETE để không sửa được trail.
    CREATE TABLE admission_maint.bypass_audit (
        id BIGSERIAL PRIMARY KEY,
        txid BIGINT NOT NULL,                        -- txid_current() khi gọi function
        called_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        session_user_name NAME NOT NULL,             -- ghi caller thật, không phải owner
        reviewed_by_user_id INT NULL,                -- app-level user id (truyền explicit)
        application_name TEXT NULL,
        reason TEXT NOT NULL,
        profile_ids INT[] NULL                       -- NULL = global bypass (DBA emergency)
    );
    CREATE INDEX ix_bypass_audit_txid ON admission_maint.bypass_audit (txid);

    -- Lock down audit table: chỉ INSERT (qua SECURITY DEFINER function), không UPDATE/DELETE
    REVOKE ALL ON admission_maint.bypass_audit FROM PUBLIC;

    -- Preflight: tạo role nếu chưa có (dev/staging mặc định chỉ có role `qlts`).
    -- Production DBA setup roles trước khi deploy migration; dev/CI tạo qua DO block.
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admission_admin') THEN
            CREATE ROLE admission_admin NOLOGIN;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'audit_reader') THEN
            CREATE ROLE audit_reader NOLOGIN;
        END IF;
    END $$;

    GRANT SELECT ON admission_maint.bypass_audit TO admission_admin;
    GRANT SELECT ON admission_maint.bypass_audit TO audit_reader;
    -- INSERT chỉ qua function SECURITY DEFINER — không direct GRANT INSERT.
    -- Tuyệt đối KHÔNG GRANT UPDATE/DELETE cho bất kỳ role nào (kể cả admission_admin).
    -- Production DBA grant cho user app/admin tương ứng:
    --   GRANT admission_admin TO qlts_admin_user;
    --   GRANT audit_reader TO qlts_audit_user;

    -- Function set maintenance token + ghi audit. SECURITY DEFINER chạy với
    -- quyền của owner; chỉ role được GRANT EXECUTE mới gọi được.
    -- Lưu ý: dùng session_user (caller thật) thay vì current_user (owner).
    CREATE OR REPLACE FUNCTION admission_maint.set_maintenance_mode(
        p_reason TEXT,
        p_reviewed_by_user_id INT,
        p_profile_ids INT[] DEFAULT NULL
    )
    RETURNS VOID AS $$
    BEGIN
        IF p_reason IS NULL OR length(trim(p_reason)) < 10 THEN
            RAISE EXCEPTION 'Maintenance bypass requires meaningful reason (>=10 chars)';
        END IF;
        IF p_reviewed_by_user_id IS NULL THEN
            RAISE EXCEPTION 'Maintenance bypass requires explicit reviewed_by_user_id';
        END IF;
        INSERT INTO admission_maint.bypass_audit
            (txid, session_user_name, reviewed_by_user_id, application_name, reason, profile_ids)
        VALUES
            (txid_current(), session_user, p_reviewed_by_user_id,
             current_setting('application_name', true), p_reason, p_profile_ids);
    END;
    $$ LANGUAGE plpgsql
       SECURITY DEFINER
       SET search_path = admission_maint, pg_catalog;
    -- SET search_path: tránh object shadowing nếu caller có schema riêng cùng tên
    -- với admission_maint (ví dụ schema test). Function bind đúng objects của
    -- admission_maint + pg_catalog, không phụ thuộc search_path session.

    REVOKE ALL ON FUNCTION admission_maint.set_maintenance_mode(TEXT, INT, INT[]) FROM PUBLIC;
    -- DBA grant cho role admin riêng, KHÔNG grant cho app role thông thường:
    -- GRANT EXECUTE ON FUNCTION admission_maint.set_maintenance_mode TO admission_admin;

    -- Trigger function — check audit row TỒN TẠI cùng txid + scope theo profile_ids
    -- KHÔNG đọc GUC. SET GUC trực tiếp không bypass được.
    -- Bypass chỉ hợp lệ cho profile nằm trong profile_ids đã audit; NULL = global bypass
    -- (chỉ DBA emergency, ghi rõ trong audit reason).
    CREATE OR REPLACE FUNCTION raise_locked_field_error()
    RETURNS TRIGGER AS $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM admission_maint.bypass_audit
            WHERE txid = txid_current()
              AND (profile_ids IS NULL OR NEW.id = ANY(profile_ids))
        ) THEN
            RETURN NEW;  -- Bypass hợp lệ — function đã audit cùng txid + đúng scope
        END IF;
        IF OLD.status NOT IN ('draft', 'revision_requested') THEN
            IF (NEW.gpa_overall IS DISTINCT FROM OLD.gpa_overall
                OR NEW.conduct IS DISTINCT FROM OLD.conduct
                OR NEW.health_category IS DISTINCT FROM OLD.health_category
                OR NEW.graduation_year IS DISTINCT FROM OLD.graduation_year) THEN
                RAISE EXCEPTION 'Eligibility scalar fields locked after submit (profile_id=%)',
                    NEW.id;
            END IF;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    -- BEFORE UPDATE OF specific columns: trigger CHỈ fire khi 1 trong 4 column đổi.
    -- Update phone/email/status không touch audit table query.
    CREATE TRIGGER trg_lock_profile_eligibility_fields
        BEFORE UPDATE OF gpa_overall, conduct, health_category, graduation_year
        ON admission_profile
        FOR EACH ROW
        EXECUTE FUNCTION raise_locked_field_error();
    ```

    **Tại sao txid-bound audit là defense-in-depth:**
    - `txid_current()` chỉ tăng khi transaction mới. SQL trực tiếp không gọi `set_maintenance_mode()` → không có row cùng txid → trigger raise.
    - GRANT EXECUTE chỉ cho role admin riêng. App role không có GRANT → kể cả gọi function cũng fail permission.
    - SECURITY DEFINER + REVOKE FROM PUBLIC ngăn user thông thường hijack function.
    - `session_user` ghi nhận caller thật, audit table immutable (không UPDATE policy).

    - `down_revision = 'phase1_09a'` — bắt buộc 9a hoàn tất trước.
    - **Service `AdmissionMaintenanceService` ship cùng PR**:
      ```python
      async def bulk_review_eligibility(db, profile_ids, updates_by_id, reviewed_by_user_id, reason):
          """Cho phép admin nhập conduct/health_category cho profile đã submitted."""
          # Function ghi audit row với txid_current() — token cho trigger check
          await db.execute(
              text("""
                  SELECT admission_maint.set_maintenance_mode(
                      :reason, :reviewed_by, :pids
                  )
              """),
              {"reason": reason, "reviewed_by": reviewed_by_user_id, "pids": profile_ids},
          )
          for pid in profile_ids:
              # update + audit log app-level (separate from DB-level audit)
              ...
          # Audit row giữ vĩnh viễn cho compliance; trigger chỉ active trong cùng txn.
      ```
    - **Pháp lý DB role**: app role (vd: `qlts_app`) KHÔNG có GRANT EXECUTE. Role admin riêng (vd: `admission_admin`) được GRANT bởi DBA, dùng cho service `AdmissionMaintenanceService` với credential khác. Người sửa SQL trực tiếp qua psql cần xin GRANT từ DBA, để lại audit row + session_user trong `admission_maint.bypass_audit`.

11. `phase1_10_create_status_history_table_and_backfill.py`
    - Tạo `admission_profile_status_history` (xem Phần 2.7) với đầy đủ cả 3 column role: `transitioned_by_role` (deprecated 1 release), `actor_actual_role`, `effective_transition_role`. Tất cả NOT NULL ENUM với CHECK constraint.
    - Backfill: với mọi profile hiện có, insert 1 row populate cả 3 column:
      ```sql
      INSERT INTO admission_profile_status_history
          (profile_id, from_status, to_status,
           transitioned_by_role, actor_actual_role, effective_transition_role,
           metadata, occurred_at)
      SELECT
          p.id, NULL, p.status,
          'system',                    -- legacy column
          'system',                    -- v2.9 actor_actual_role
          'system',                    -- v2.9 effective_transition_role
          jsonb_build_object('backfill', true, 'source', 'phase1_10_initial'),
          p.created_at
      FROM admission_profile p
      WHERE NOT EXISTS (
          SELECT 1 FROM admission_profile_status_history h
          WHERE h.profile_id = p.id
      );
      ```
    - Idempotent: `WHERE NOT EXISTS` per-profile.
    - **Lưu ý**: backfill row có `from_status=NULL` (lần đầu tạo profile) — CHECK constraint role-actor consistency phải allow `(actor_actual_role='system', user_id IS NULL, lead_id IS NULL)` cho backfill case.

    - **Backfill scattered scalar audit lịch sử (P1 fix #1 v2.11)**: profile hiện có 5 scattered scalar set `(approved_at/by, rejected_at/by, revision_requested_at/by, resubmitted_at/by, overridden_at/by)` chứa data audit thật. Backfill thêm 5 SQL block (mỗi block 1 transition type) để migrate vào status_history. KHÔNG bỏ qua — sau Phase 4 drop scattered scalar fields, audit data mất vĩnh viễn (compliance Bộ GD&ĐT yêu cầu trace mọi quyết định approve/reject):
      ```sql
      -- Block 1: Approved transitions
      INSERT INTO admission_profile_status_history
          (profile_id, from_status, to_status,
           transitioned_by_user_id, actor_actual_role, effective_transition_role,
           transition_reason, occurred_at, metadata)
      SELECT
          p.id, 'submitted', 'approved',
          p.approved_by_id,
          COALESCE(u.role, 'admin'),       -- actual role lookup từ User; fallback 'admin'
          'admin',                          -- effective resolve
          p.approval_notes,
          p.approved_at,
          jsonb_build_object('source', 'scattered_scalar_backfill', 'transition', 'approved')
      FROM admission_profile p
      LEFT JOIN "user" u ON u.id = p.approved_by_id
      WHERE p.approved_at IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM admission_profile_status_history h
            WHERE h.profile_id = p.id
              AND h.to_status = 'approved'
              AND h.metadata->>'source' = 'scattered_scalar_backfill'
        );

      -- Block 2: Rejected transitions
      INSERT INTO admission_profile_status_history
          (profile_id, from_status, to_status, transitioned_by_user_id,
           actor_actual_role, effective_transition_role, transition_reason,
           occurred_at, metadata)
      SELECT p.id, 'submitted', 'rejected', p.rejected_by_id,
             COALESCE(u.role, 'admin'), 'admin', p.rejection_reason, p.rejected_at,
             jsonb_build_object('source', 'scattered_scalar_backfill', 'transition', 'rejected')
      FROM admission_profile p
      LEFT JOIN "user" u ON u.id = p.rejected_by_id
      WHERE p.rejected_at IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM admission_profile_status_history h
                        WHERE h.profile_id = p.id AND h.to_status = 'rejected'
                          AND h.metadata->>'source' = 'scattered_scalar_backfill');

      -- Block 3: Revision requested, Block 4: Resubmitted, Block 5: Overridden — pattern tương tự
      ```
    - Backfill order theo `occurred_at ASC` để status_history giữ chronological order.

12. `phase1_11_extend_profile_status_check_constraint.py` + **FE Zod sync wave (BLOCKER)**

    **Cảnh báo deploy ordering:** FE response Zod schema `frontend/src/lib/zod/admissions.ts:494` strict enum legacy. Nếu BE deploy migration #11 (CHECK extend) + service trả profile với `status='reviewing'/'admitted'` TRƯỚC khi FE Zod update → response parse fail → FE crash hoặc fallback render không kịp.

    PR migration #11 BẮT BUỘC bundle với FE Zod update theo **3-stage deploy choreography** (P1 fix #7 v2.10):

    QLTS có `Backend_FastAPI/` + `frontend/` riêng folder cùng repo nhưng deploy 2 container độc lập (verified `docker-compose.yml`). Window 1-3 phút giữa BE migration apply và FE container build → strict Zod parse fail → user crash. Cần 3-stage deploy:

    **Stage 1 (Day 1) — FE Zod permissive deploy ONLY**:
    - FE Zod đổi enum strict thành catchall: `z.union([z.enum([...legacy_states]), z.string()])` — passthrough state lạ.
    - Status badge fallback render generic gray badge cho state lạ.
    - KHÔNG đổi BE.
    - Deploy FE container only.
    - Soak 24h verify FE không crash trên state legacy.

    **Stage 2 (Day 2) — BE migration #11 + service trả state mới**:
    - Deploy BE container: migration apply + service start trả `status='reviewing'/'admitted'`.
    - FE catchall enum chấp nhận → render generic badge tạm thời.
    - User thấy badge "Trạng thái: reviewing" (raw string) thay vì label đẹp — acceptable tạm 24-48h.

    **Stage 3 (Day 4 sau Stage 2 soak) — FE Zod strict + label đẹp**:
    - FE Zod strict enum lock 4 state mới.
    - `STATUS_BADGE_CONFIG` mapping đầy đủ 4 entry với i18n key + color.
    - Deploy FE container.
    - User thấy badge "Đang xét duyệt" tiếng Việt.

    **Tránh**: deploy 1 wave atomic → window 1-3 phút crash. Coordinate với QA staging trước khi BE migration ship prod.
    - Drop CHECK constraint `ck_admission_profile_status` (hiện chỉ chứa legacy states)
    - Recreate CHECK với union states cũ + mới:
      ```sql
      ALTER TABLE admission_profile DROP CONSTRAINT ck_admission_profile_status;
      ALTER TABLE admission_profile ADD CONSTRAINT ck_admission_profile_status CHECK (
        status IN (
          'draft', 'submitted', 'reviewing', 'revision_requested',
          'result_published', 'admitted', 'waitlisted', 'rejected',
          'confirmed', 'enrolled', 'withdrawn',
          'approved', 'resubmitted', 'overridden'  -- legacy backward compat
        )
      );
      ```
    - **CHẠY TRƯỚC khi Phase 3 ship** — nếu không, mọi transition Phase 3 sẽ fail DB.
    - **Down migration KHÔNG auto-revert** (one-way pattern giống Phase 2 #2):
      ```python
      def downgrade():
          bind = op.get_bind()
          new_state_count = bind.execute(text("""
              SELECT COUNT(*) FROM admission_profile
              WHERE status IN ('reviewing', 'result_published', 'admitted', 'waitlisted')
          """)).scalar()
          if new_state_count > 0:
              raise Exception(
                  f"Manual rollback required: {new_state_count} profiles in new states. "
                  "Run status remap script (Phần 7.5 strategy B) before downgrade."
              )
          # Safe to revert
          op.execute(text("ALTER TABLE admission_profile DROP CONSTRAINT ..."))
          op.execute(text("ALTER TABLE admission_profile ADD CONSTRAINT ... CHECK (status IN ('draft','submitted','approved',...))"))
      ```

13. `phase1_12_backfill_selected_subject_group_id.py` ← **chỉ backfill, KHÔNG re-add column**
    - **Pre-flight check**: column `selected_subject_group_id` PHẢI đã tồn tại (do Phase 0 migration tạo). Nếu không tồn tại → raise hint "Run Phase 0 migration first".
      ```python
      def upgrade():
          bind = op.get_bind()
          column_exists = bind.execute(text("""
              SELECT 1 FROM information_schema.columns
              WHERE table_name = 'admission_profile'
                AND column_name = 'selected_subject_group_id'
          """)).scalar()
          if not column_exists:
              raise Exception(
                  "Column selected_subject_group_id not found. Run Phase 0 "
                  "migration phase0_add_selected_subject_group_id_to_profile.py first."
              )
          # ... backfill logic
      ```
    - `down_revision = phase1_11_extend_profile_status_check_constraint` (linear chain). Phase 0 là ancestor của `phase1_01`, không trỏ trực tiếp.
    - **KHÔNG ADD COLUMN** — Phase 0 là owner duy nhất.
    - **Reuse `_admission_backfill_exceptions`** đã tạo ở migration 7b (KHÔNG tạo lại).
    - **Verified**: snapshot `applied_rules` hiện KHÔNG có `selected_group_code` (chỉ có `allowed_subject_codes`/`subject_groups`/`subject_weights`). Backfill phải dùng decision tree 3 rule:

      **Rule (a) — path có 1 group → auto-map:**
      Verified: snapshot dùng key `admission_path_id` (NOT `path_id`).
      Cast guard tách CTE symmetric với Rule (b) — Postgres không đảm bảo regex predicate chạy trước cast trong cùng WHERE.
      ```sql
      WITH eligible_profiles_a AS (
          -- Filter key + numeric guard TRƯỚC cast
          SELECT p.id AS profile_id,
                 (p.applied_rules->>'admission_path_id')::int AS admission_path_id_int
          FROM admission_profile p
          WHERE p.selected_subject_group_id IS NULL
            AND p.applied_rules ? 'admission_path_id'
            AND (p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'
      ),
      single_group_paths AS (
          SELECT ap.id AS path_id, MAX(csg.subject_group_id) AS group_id
          FROM admission_path ap
          JOIN criteria_subject_group csg ON csg.criteria_id = ap.criteria_id
          GROUP BY ap.id
          HAVING COUNT(*) = 1
      )
      UPDATE admission_profile p
      SET selected_subject_group_id = sgp.group_id
      FROM eligible_profiles_a ep
      JOIN single_group_paths sgp ON sgp.path_id = ep.admission_path_id_int
      WHERE p.id = ep.profile_id
        AND p.selected_subject_group_id IS NULL;
      ```

      **Rule (b) — infer SCOPED theo path + group-completeness check:**
      Lý do scope: môn Toán/Lý xuất hiện ở nhiều group toàn hệ thống (A00, A01, A02...). Nếu count toàn cục, profile có 3 môn Toán-Lý-Hóa sẽ match cả A00 toàn hệ thống thay vì chỉ A00 thuộc path đăng ký.
      Lý do group-complete: rule cũ chỉ check "có ít nhất 1 môn match" → profile chỉ có Toán cũng match A00. Phải check "tất cả môn của group có score". Match group X iff (a) profile có score cho mọi subject thuộc X, AND (b) đúng 1 group thoả trong path's allowed groups.
      ```sql
      WITH eligible_profiles AS (
          -- Filter key + numeric guard TRƯỚC khi cast — Postgres không đảm bảo
          -- WHERE chạy trước CAST trong cùng SELECT.
          SELECT p.id AS profile_id,
                 (p.applied_rules->>'admission_path_id')::int AS admission_path_id_int
          FROM admission_profile p
          WHERE p.selected_subject_group_id IS NULL
            AND p.applied_rules ? 'admission_path_id'
            AND (p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'
      ),
      path_allowed_groups AS (
          -- Groups được path cho phép (qua CriteriaSubjectGroup)
          SELECT ep.profile_id, csg.subject_group_id
          FROM eligible_profiles ep
          JOIN admission_path ap ON ap.id = ep.admission_path_id_int
          JOIN criteria_subject_group csg ON csg.criteria_id = ap.criteria_id
      ),
      group_completeness AS (
          -- Mỗi (profile, group) thuộc path's allowed: kiểm group có complete scores không
          SELECT pag.profile_id,
                 pag.subject_group_id,
                 (SELECT COUNT(*) FROM subject_group_subject sgs
                  WHERE sgs.subject_group_id = pag.subject_group_id) AS required_count,
                 (SELECT COUNT(*) FROM subject_group_subject sgs
                  JOIN profile_subject_score pss
                    ON pss.subject_id = sgs.subject_id
                    AND pss.profile_id = pag.profile_id
                  WHERE sgs.subject_group_id = pag.subject_group_id) AS matched_count
          FROM path_allowed_groups pag
      ),
      complete_groups_per_profile AS (
          -- Chỉ giữ groups mà profile có ĐỦ scores
          SELECT profile_id, subject_group_id
          FROM group_completeness
          WHERE matched_count = required_count
            AND required_count > 0
      ),
      unique_complete_groups AS (
          -- Profile match đúng 1 complete group
          SELECT profile_id,
                 MAX(subject_group_id) AS sole_group_id,
                 COUNT(*) AS complete_group_count
          FROM complete_groups_per_profile
          GROUP BY profile_id
          HAVING COUNT(*) = 1
      )
      UPDATE admission_profile p
      SET selected_subject_group_id = ucg.sole_group_id
      FROM unique_complete_groups ucg
      WHERE ucg.profile_id = p.id
        AND p.selected_subject_group_id IS NULL;
      ```

      **Rule (c) — ambiguous → exception report, KHÔNG auto-create choice. Scope chặt:**
      Chỉ áp dụng cho profile có data đầy đủ — tránh flood exception cho draft hoặc data lịch sử thiếu. Tách thành 2 exception type khác nhau:
      ```sql
      -- Exception 1: AMBIGUOUS — profile có data đủ nhưng nhiều group thoả
      INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
      SELECT p.id, 'AMBIGUOUS_SELECTED_GROUP',
             jsonb_build_object(
                 'applied_rules_groups', p.applied_rules->'subject_groups',
                 'score_count', (SELECT count(*) FROM profile_subject_score WHERE profile_id = p.id)
             )
      FROM admission_profile p
      WHERE p.selected_subject_group_id IS NULL
        AND p.status NOT IN ('draft', 'withdrawn')             -- scope: chỉ active profile
        AND p.applied_rules ? 'admission_path_id'              -- có path id
        AND (p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'  -- numeric
        AND EXISTS (SELECT 1 FROM profile_subject_score WHERE profile_id = p.id)  -- có scores
      ON CONFLICT (profile_id, exception_type) DO NOTHING;

      -- Exception 2: INSUFFICIENT_DATA_FOR_BACKFILL — profile thiếu path/scores
      INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
      SELECT p.id, 'INSUFFICIENT_DATA_FOR_BACKFILL',
             jsonb_build_object(
                 'has_path_id', p.applied_rules ? 'admission_path_id',
                 'has_scores', EXISTS (SELECT 1 FROM profile_subject_score WHERE profile_id = p.id),
                 'status', p.status
             )
      FROM admission_profile p
      WHERE p.selected_subject_group_id IS NULL
        AND p.status NOT IN ('draft', 'withdrawn')
        AND (
            NOT (p.applied_rules ? 'admission_path_id')
            OR (p.applied_rules->>'admission_path_id') !~ '^[0-9]+$'
            OR NOT EXISTS (SELECT 1 FROM profile_subject_score WHERE profile_id = p.id)
        )
      ON CONFLICT (profile_id, exception_type) DO NOTHING;
      ```
      Lý do tách: AMBIGUOUS đòi admin chọn group (action rõ ràng). INSUFFICIENT_DATA cần data fix khác (bổ sung scores, sửa applied_rules) — workflow riêng. Profile draft/withdrawn skip vì không cần backfill choice.

    - **Phase 3 backfill rule**: chỉ tạo `AdmissionProfileChoice` cho profile có `selected_subject_group_id IS NOT NULL`. Profile trong `_admission_backfill_exceptions` skip — admin manual review qua UI mới (Phase 1+2 ship trước).
    - Idempotent: mỗi rule guard `WHERE selected_subject_group_id IS NULL`.
    - **Lý do bắt buộc**: Phase 3 cần biết group profile cũ đã chọn. Không có nguồn truth → quyết định KHÔNG đoán, mà flag exception cho admin review.

14b. **Phase 1 #17 — Public admissions storefront migration (CODE TASK, GATE Phase 2 #02b):**

    Verified hiện tại `app/services/public_admissions_service.py` chưa biết về `admission_round_id`/`applicable_to`/path-level `DocumentGroup`:
    - Line 114, 145: load path qua `academic_info_id` direct, dùng set `academic_info_ids`.
    - Line 534: resolve document theo `offering_type_id/admission_method_id` 2-tier, không có path-level override.

    Sau Phase 2 #02b NOT NULL `admission_round_id` + swap unique → storefront sẽ:
    - Hiển thị path không filter audience → thí sinh post-THCS thấy path TN THPT.
    - Resolve document chỉ theo offering_type/method, không pickup admin custom path-level docs (Phase 1 #06).

    **Code task scope (PR riêng, GATE Phase 2 #02b)**:
    - `public_admissions_service.py:114-145`: load paths via `admission_round_id`. Query active rounds `WHERE is_active=true AND NOW() BETWEEN start_date AND end_date`. **Fail-closed strategy** (KHÔNG silent default DOT_1):
      - 0 round active → trả empty path list + log warning admin (storefront hiển thị "Hiện tại chưa có đợt tuyển sinh đang mở").
      - 1 round active → auto-select.
      - >1 round active → render dropdown picker BẮT BUỘC, KHÔNG default. URL deep-link `?round_code=DOT_2` cho thí sinh đến từ campaign cụ thể.
    - Filter audience: nếu request có `candidate_education_level` query param → apply `applicable_to @> ARRAY[:audience]` query (NULL fallback per Phần 1 #03 query contract).
    - `:534` resolve document: 3-tier như service-internal (path → method → offering_type). Reuse helper từ service-internal (DRY).
    - Frontend public storefront: dropdown audience filter (POST_THCS/POST_THPT/...). Dropdown round picker khi >1 round active. Empty state UI khi 0 round active.
    - Test: regression suite cho public storefront với 4 case: 0 round, 1 round, 2 round (picker), audience filter applied.

15b. **Phase 1 #16 — Workflow contract audit task (CODE TASK, GATE Phase 1 #11):**

    Verified hiện tại nhiều endpoint set `profile.status` trực tiếp KHÔNG qua state service:
    - `app/services/admission_service.py:3918` — legacy approve/reject
    - Multiple confirm endpoints
    - Enroll endpoint
    - Resubmit endpoint
    - Override endpoint

    Plan v2.2 chốt mọi transition đi qua `AdmissionStateService.transition()`. Nếu ship Phase 1 #11 (CHECK constraint extend thêm 4 new states) trước khi 100% caller migrate → contract lệch ngay, có endpoint vẫn set `'approved'` direct, có endpoint set `'admitted'` qua service.

    **Audit task scope (PR riêng, GATE Phase 1 #11):**

    Step 1 — Grep + list mọi `profile.status = '...'` site:
    ```bash
    grep -rn "profile\.status\s*=" Backend_FastAPI/app/
    grep -rn "\.status\s*=\s*['\"]" Backend_FastAPI/app/services/admission*.py
    grep -rn "\.status\s*=\s*['\"]" Backend_FastAPI/app/routers/admissions.py
    ```

    Step 2 — Refactor mỗi site:
    - Backend: thay direct set → `await state_service.transition(profile, to_status='...', actor=current_user, reason=...)`.
    - Notification mapping: verify mỗi caller cũ đã có event_def trong catalog.
    - Status-count DTO (`admission_repository.py:429` analytics): switch sang `effective_status()` helper.
    - Finance projection (`fees.py:81`): switch sang `is_admitted_like()`.
    - Commission projection (`commission_service.py:251,296`): xem có cần state-aware logic không.

    Step 3 — Frontend audit:
    - FE Zod status enum (`frontend/src/lib/zod/admissions.ts:494`).
    - Status badge config (`status-badge.config.ts:40`).
    - Action gates (`AdmissionActions.tsx:89,141`) check `is_admitted_like()` helper FE.

    Step 4 — Verify gate:
    - Test suite: 100% transition đi qua state service (không có direct set).
    - Lint rule (custom AST check) catch `profile.status = '...'` outside state service body.
    - Manual review checklist: 23 file caller (xem task #15).

    **Gate ordering:**
    - Phase 1 migration #11 (status CHECK extend) CHỈ merge sau khi #16 audit task ship + verify gate pass.
    - Lý do: nếu caller cũ vẫn set `'approved'` direct trong khi CHECK đã extend → DB accept nhưng state machine không update history_log → audit trail lệch.

    Bundle change vào PR riêng: 1 PR audit + refactor cho mọi caller, 1 PR migration #11. PR audit merge first.

14. `phase1_15_drop_lead_id_unique_constraint.py` ← **multi-season re-apply + one-to-many contract**

    **Verified scope hiện tại** — KHÔNG chỉ DB constraint:
    - `app/models/admission.py:65` — `lead_id unique=True`
    - `app/models/lead.py:252` — `admission_profile = relationship(uselist=False)` (one-to-one)
    - `app/schemas/lead.py:410` — `admission_profile: Optional[AdmissionProfileShallow]` singular
    - `app/services/admission_service.py:1183` — block tạo profile nếu lead đã có profile

    **PR scope BẮT BUỘC bundle (KHÔNG chỉ migration DB)**:
    - DB migration: drop unique trên `lead_id`, tạo `(lead_id, academic_year)` UNIQUE.
    - Model: `Lead.admission_profile` → `Lead.admission_profiles` plural list, `uselist=True`. Thêm helper `current_admission_profile(academic_year)` resolve theo year.
    - Schema: `LeadResponse.admission_profile` (singular Optional) → `admission_profiles: list[AdmissionProfileShallow]`. Backward-compat: thêm property computed `admission_profile` trả profile của academic_year hiện tại để FE chưa migrate vẫn work.
    - **Repository** (verified `app/repositories/admission_repository.py:482` `get_profile_by_lead_id` singular — caller existing rely on 1 profile):
      - Deprecate `get_profile_by_lead_id` (raise warning hoặc giữ + warn nếu lead có >1 profile, trả profile mới nhất).
      - Thêm `list_profiles_by_lead_id(lead_id)` trả `list[AdmissionProfile]` order by `academic_year DESC`.
      - Thêm `get_profile_by_lead_year(lead_id, academic_year)` cho lookup chính xác.
      - Caller existing migrate: lead pipeline phase tracker, KPI projection, audit log — list rõ caller bằng `grep -rn "get_profile_by_lead_id"` trước PR.
    - Service: `create_profile` block "lead đã có profile" → block "lead đã có profile cho academic_year này" (composite check).
    - FE: schema/component hiển thị multi-profile per lead theo year. Tab/list switcher giữa các năm.
    - API endpoint version: nếu có `/leads/{id}/admission-profile` (singular) → keep + add `/leads/{id}/admission-profiles` (list); deprecate singular ở Phase 4.
    - Migration:
      ```sql
      -- Drop unique constraint cũ
      ALTER TABLE admission_profile DROP CONSTRAINT IF EXISTS admission_profile_lead_id_key;
      DROP INDEX IF EXISTS ix_admission_profile_lead_id;

      -- Tạo index thường (non-unique) cho FK lookup
      CREATE INDEX ix_admission_profile_lead_id ON admission_profile (lead_id);

      -- Composite UNIQUE bảo vệ business rule: 1 lead 1 profile/year
      ALTER TABLE admission_profile
        ADD CONSTRAINT uq_admission_profile_lead_year
        UNIQUE (lead_id, academic_year);
      ```
    - Service `admission_service.create_profile()` validate: nếu lead đã có profile cùng `academic_year` → raise `DuplicateResourceError("Lead already has profile for this academic year")`. Cùng lead khác year → OK.
    - Down migration: drop composite, recreate `lead_id UNIQUE` (sẽ fail nếu lead đã apply nhiều year — manual cleanup required, ghi rõ playbook).
    - Update model `AdmissionProfile.lead_id`: `unique=True` → `unique=False`, thêm `__table_args__` composite UNIQUE.

15. **Audit task — `approved → admitted` workflow remap (KHÔNG migration, code task):**

    **Step 1 — Update state machine FIRST (BLOCKER, trước normalize layer):**
    - `app/services/admission_state_machine.py:44` — `AdmissionStatus` enum hard-code `APPROVED = "approved"`. Thêm member mới: `REVIEWING`, `RESULT_PUBLISHED`, `ADMITTED`, `WAITLISTED`.
    - `app/services/admission_state_machine.py:61` — `ALLOWED_TRANSITIONS` dict hard-code transitions từ `APPROVED`. Mở rộng cho 17 transition matrix mới (xem Phần 3.3.b). Giữ legacy transitions cho `uses_choice_engine=False` profile.
    - **Lý do Step 1 first**: state machine là source of truth cho `can_transition()`. Không update sẽ block mọi transition mới ngay khi deploy.

    **Step 2 — Normalize layer ở `admission_event_mapping.py`:**
      ```python
      LEGACY_TO_NEW_STATUS_MAP = {
          "approved": "admitted",
          "resubmitted": "submitted",
          "overridden": "admitted",  # legacy override = admin force admit
      }
      def is_admitted_like(profile):
          """True cho cả legacy approved/overridden và choice-engine admitted."""
          if profile.uses_choice_engine:
              return profile.status == 'admitted'
          return profile.status in ('approved', 'overridden')

      def effective_status(profile):
          """Trả status ổn định cho downstream (commission, fees, KPI)."""
          if profile.uses_choice_engine:
              return profile.status  # 'admitted'/'waitlisted'/...
          return LEGACY_TO_NEW_STATUS_MAP.get(profile.status, profile.status)
      ```

    **Step 3 — Mapping 4 new state ở `lead_admission_sync.py`:**
    Plan v2.1 chưa có mapping cho 4 state mới — lead pipeline projection sẽ không sync. Bổ sung table:
      ```python
      ADMISSION_TO_LEAD_STAGE_MAP = {
          # Legacy (giữ nguyên backward compat)
          'draft': 'sts06',           # đã có
          'submitted': 'sts06',       # đã có
          'approved': 'sts09',        # đã có
          # 4 state mới — choice engine
          'reviewing': 'sts06',       # tương đương submitted, vẫn xử lý
          'result_published': 'sts09', # đã công bố — giống approved
          'admitted': 'sts09',         # đậu — giống approved
          'waitlisted': 'sts06',       # chờ — giữ stage submitted
          # Terminal
          'confirmed': 'sts10',       # đã có
          'enrolled': 'sts11',        # đã có
          'rejected': 'sts08',        # đã có
          'withdrawn': 'sts08',       # đã có
      }
      ```
    Update function `sync_lead_from_admission()` dùng map này thay vì if-else hard-code.

    **Step 4 — Đổi caller (23 file ngoài state machine, mở rộng từ 11 → 23):**

    | # | File:Line | Vấn đề |
    |---|---|---|
    | 1 | `app/services/admission_service.py` | confirm/enroll endpoint |
    | 2 | `app/services/phase_manager.py:119` | Phase transition tuple `("approved","confirmed","overridden")` |
    | 3 | `app/services/admission_state_machine.py:44,61` | Enum + ALLOWED_TRANSITIONS — Step 1 |
    | 4 | `app/core/admission_event_mapping.py:154,187` | Event projection `admission_status="approved"` |
    | 5 | `app/routers/admissions.py` | Endpoints |
    | 6 | `app/routers/fees.py:81` | Fee gate `if profile.status not in ("approved","confirmed","enrolled")` |
    | 7 | `app/routers/collaborators.py:205` | Review endpoint check |
    | 8 | `app/services/collaborator_service.py` | Commission flow |
    | 9 | `app/services/commission_service.py:251,296` | Hard-coded `record.status = "approved"`, `if record.status != "approved"` |
    | 10 | `app/repositories/commission_repository.py:246` | Aggregate `elif row.status == "approved"` |
    | 11 | `app/repositories/admission_repository.py:429` | Analytics `status_counts.get("approved", 0)` |
    | 12 | `app/tasks/admission_tasks.py` | Celery tasks |
    | 13 | `app/tasks/collaborator_tasks.py:71` | `LeadClaim.status == "approved"` |
    | 14 | `app/core/event_catalog.py` | Event payload status field |
    | 15 | `app/templates/emails/admission_confirmed_*.html` | Template body có thể reference state name |
    | 16 | `app/services/lead_service.py` | `effective_status` compute, lead_id Lead.gpa effective_gpa |
    | 17 | `app/services/fsm_engine.py` (nếu có) | FSM state handling |
    | 18 | `app/services/drilldown_service.py` (nếu có) | Status-keyed drilldown |
    | 19 | `app/tasks/email_tasks.py` | Template dispatch cho 12 events mới |
    | 20 | `app/services/notification_dispatcher.py` | Routing logic theo `requires_outbox` flag (Phần 3.3.f) |
    | 21 | `app/services/zalo_dispatcher.py` | Bypass consent check theo `bypass_consent_check` flag |
    | 22 | `app/scripts/check_notification_event_coverage.py` | Extend check namespace collision + outbox INSERT site |
    | 23 | Frontend repository (`frontend/src/lib/zod/admissions.ts`, etc.) | Phần 4 Phase 3 Frontend deliverables (xem dưới) |

    Mỗi caller đổi từ `if status == 'approved'` sang `if is_admitted_like(profile)`. Tuple checks sang `effective_status(profile) in (...)`.

    **Step 5 — Test bắt buộc**: regression suite cho mỗi downstream (fees, commission, phase manager) với CẢ 3 case:
    - Legacy `approved` profile (`uses_choice_engine=False`)
    - Legacy `overridden` profile
    - Choice-engine `admitted` profile (`uses_choice_engine=True`)

    Tất cả 3 case phải trigger fee creation/commission compute/phase transition đúng.

    Bundle change Step 1-5 vào PR riêng MERGE **BEFORE** `phase1_11_extend_profile_status_check_constraint` (gate cứng theo Migration ordering chain). Lý do: nếu CHECK đã extend mà caller cũ vẫn set `'approved'` direct → DB accept nhưng state machine không update history_log → audit trail lệch.

**Migration ordering & dependencies — LINEAR CHAIN (v2.13 revised với 6 code task gate + 4 migration tách + Q9 defer):**

```
<current_head>
  → phase0_add_selected_subject_group_id_to_profile     (Phase 0: ADD COLUMN owner)
  → phase0b_relax_applied_rules_immutability_for_payment_keys (Phase 0b: trigger function whitelist)
  ─── CODE TASK Phase 0c (PR riêng): admission_config_repository.py:76,84 hot-fix ───
  ─── CODE TASK B1 (PR riêng, PATCH-16 v2.13): Casbin auth_model.conf rewrite + deny effect
       + matcher update + 4 role × 14 action matrix test. GATE BEFORE phase1_11. ────────
  ─── CODE TASK B2 (PR riêng, PATCH-17 v2.13): EventDefinition extend (requires_outbox +
       bypass_consent_check) + 12 SystemEvents enum + EVENT_CATALOG seed module-level.
       GATE BEFORE phase1_19a. ─────────────────────────────────────────────────────────
  → phase1_01_add_degree_level_fk_to_major_program
  → phase1_02_add_bonus_rule_to_method_and_path
  → phase1_03_add_applicable_to_method_quota_to_path     (kèm BE schema + service + FE Zod PR)
  → phase1_05_add_subject_kind_and_score_bounds
  → phase1_06_add_path_id_to_document_group
  → phase1_07b_create_backfill_exceptions_table
  → phase1_08_add_uses_choice_engine_flag_to_profile
  → phase1_09a_add_eligibility_scalars_and_backfill      (insert exceptions vào 7b)
  → phase1_10_create_status_history_table_and_backfill
  → phase1_XX_create_system_config_table                 (PATCH-14 v2.13 — Q4 dependency)
                                                          Table system_config + admin endpoint UPDATE
                                                          + seed current_intake_year=2026.
  → phase1_16_create_archived_admission_profile_table    (PATCH-20 v2.13 — Phần 7.5 archive;
                                                          slot assignment §8 line 4491 chốt 2026-05-03)
  → phase1_17_create_archived_outbox_table               (PATCH-20 v2.13 — outbox archive companion;
                                                          table tên `_archived_notification_outbox`
                                                          per Phần 1 #08 fix line 168-178; chứa cả
                                                          dispatched + failed outbox archived 90d,
                                                          KHÔNG chỉ failed; slot §8 line 4492)
  ─── CODE TASK #16 GATE (PR riêng): workflow contract boundary audit ─────────────────
  ─── CODE TASK #15 (PR riêng): approved→admitted workflow remap 23 file caller ──────
  → phase1_11_extend_profile_status_check_constraint     (BE+FE Zod 14 state strict atomic deploy)
  → phase1_12_backfill_selected_subject_group_id         (insert exceptions vào 7b)
  ─── PR Phase 1 #15a (PATCH-15 v2.13): DROP lead_id UNIQUE → ADD composite (lead_id, ─
       academic_year). KHÔNG đổi model relationship (giữ uselist=False, lookup mới nhất).
       ~~Soak 1 tuần.~~ **WAIVED v2.13.2 2026-05-05** per §X.Y solo cold cutover SOP. ─
  ─── PR Phase 1 #15b: model uselist=True + repository thêm 2 method (list_profiles_by_lead_id,
       get_profile_by_lead_year) + schema dual response. ~~Soak 1 tuần.~~ **WAIVED v2.13.2** ─
  ─── PR Phase 1 #15c: FE migrate component sang plural list. ────────────────────────
  → phase1_18_extend_confirmation_token_for_multi_action (action_type column + partial unique; gate trước public token routes)
  → phase1_19a_create_outbox_table                       (PATCH-13 v2.13 — tách 4 migration)
                                                          notification_outbox table + 2 column claim
                                                          + index ix_outbox_pending + ix_outbox_claim.
  → phase1_19b_backfill_casbin_eft_and_seed_deny_rules     CHIẾM SLOT 19b (PR #201 squash 6eac329e
                                                          ship 2026-05-03 trong Wave 1 Code track B1).
                                                          210 row v3='allow' backfill + 6 deny accountant.
                                                          KHÔNG phải là spec phase1_19b — cascade Q2
                                                          push-down 3 spec migration sang slot 19c/d/e.
  → phase1_19c_seed_event_catalog_db_rows                 (renamed từ spec phase1_19b per Q2 cascade)
                                                          12 EVENT_CATALOG DB rows cho admin UI
                                                          (notification_rule + notification_template).
                                                          Module-level Python dict đã ship ở B2.
                                                          ✅ SHIPPED PR #213 squash 9af7510b 2026-05-05.
  ─── ⚠ Wave 5 SHIP-ORDER REORDER (chốt 2026-05-05 Codex round 19): alembic ─────────────
  ─── chain string-based, KHÔNG numeric monotonic. archive task body cần ──────────────
  ─── _archived_notification_outbox table (phase1_17) tồn tại trước → ship 16/17 ─────
  ─── trước phase1_19d. Chain: 19c → 16 → 17 → 19d → 19e (file names giữ ─────────────
  ─── nguyên Q2 cascade; chỉ down_revision strings + ship sequence thay đổi). ─────────
  → phase1_19d_register_celery_beat_archive_task          (renamed từ spec phase1_19c per Q2 cascade;
                                                          ship AFTER phase1_17 per ship-order reorder)
                                                          dispatch_pending_outbox (10s) +
                                                          archive_outbox_dispatched_task (weekly 90d).
  → phase1_19e_seed_notification_rules                    (renamed từ spec phase1_19d per Q2 cascade)
                                                          Rule rows định tuyến channel (Zalo/email/in-app)
                                                          theo audience từng event.
  ─── CODE TASK #17 (PR riêng): public_admissions_service migrate sang round+audience ─
  → phase2_01_create_offering_admission_round            (PATCH-06 v2.13 thêm admit_quota field)
  → phase2_02_add_admission_round_id_to_admission_path   (Step 1-3 nullable + backfill)
  → phase2_02b_admission_path_round_not_null_swap_unique (Step 4-5 NOT NULL + unique swap, sau monitor 1w)
  → phase2_03_create_path_subject_group_config_and_item
  → phase2_04_widen_score_precision                      (chứa scale DGNL/V-ACT)
  → phase3_01_create_admission_profile_choice_and_score
  (Wave A 2026-07-23 hard commit; Wave B 2026-08-13 best-effort slip-able)
```

**DEFER sang Q1/2027 (PATCH-09 + Q9 chốt):**
- `phase1_04_add_extra_thresholds_to_criteria` — min_conduct, min_health_category, required_graduation_year_min/max.
- `phase1_07_add_demographics_to_profile` — area_code, priority_object_codes[], candidate_education_level.
- `phase1_09b_create_eligibility_lock_trigger` + AdmissionMaintenanceService admin UI (txid-bound bypass) — defer vì Phase 1 9a đã có lock-after-draft pre-condition (status check ở service); trigger DB-level là defense-in-depth Phase 4.

Lý do defer: 3 migration trên không block multi-NV core flow. Engine xét tuyển vẫn chạy với `min_gpa/min_score/min_subject_score` hiện có. Demographics + extra threshold là refinement features — admin có thể manual handle qua override path-level (Phase 1 #02 bonus_rule_override).

**Key topology rules:**
- Phase 0 KHÔNG phải branch riêng; là ancestor trực tiếp của `phase1_01`. Mọi env staging/dev áp full chain từ `<current_head>` sẽ apply Phase 0 → Phase 1 đúng thứ tự.
- `phase1_12` `down_revision = phase1_11_extend_profile_status_check_constraint`. KHÔNG trỏ trực tiếp về Phase 0 (sai topology).
- Pre-flight check ở `phase1_12` verify column `selected_subject_group_id` exists (do Phase 0 đã apply trước khi Phase 1 chain bắt đầu).

**CODE TASK gates — KHÔNG phải Alembic migration nhưng ENFORCE deploy ordering:**

| Code task | PR scope | GATE condition |
|---|---|---|
| Phase 0c hot-fix | `admission_config_repository.py:76,84` field name `admission_criteria_id → criteria_id` | MERGE BEFORE phase1_01 (repository được Phase 1 dependency check rely on) |
| #16 audit | Workflow contract boundary — grep + refactor mọi `profile.status='...'` direct set sang `state_service.transition()` | MERGE BEFORE phase1_11 (status CHECK extend). Lý do: nếu caller cũ vẫn set direct trong khi CHECK đã extend → DB accept nhưng state machine không update history → audit lệch. |
| #15 audit | `approved → admitted` workflow remap 23 file caller — `is_admitted_like()` helper + state machine enum extend | MERGE BEFORE phase1_11 (cùng wave với #16). |
| #17 public storefront | `public_admissions_service.py` migrate sang `admission_round_id` + `applicable_to` filter + 3-tier doc resolution | MERGE BEFORE phase2_02b (NOT NULL + swap unique). Lý do: storefront không thấy round → user không đăng ký được sau swap. **PHẦN 1 SHIPPED Wave 6 cutover (`applicable_to` audience filter + 3-tier doc resolution); `admission_round_id` filter defers Phase 2 storefront PR cùng `phase2_01`/`phase2_02` — gate condition unchanged vì phase2_02b vẫn chưa ship.** |

Mỗi file Alembic dùng `down_revision = '<previous>'` chain rõ ràng. Không apply parallel.

**Risk:** thấp. Tất cả nullable hoặc default false, callers cũ không bị ảnh hưởng. Trigger lock chỉ tạo SAU khi backfill xong (9b sau 9a).

### Phase 2 — Bảng mới song song (2-3 sprint)

Tạo bảng mới, backfill data, chưa drop bảng/field cũ.

**Migrations (~3 file + test suite):**

1. `phase2_01_create_offering_admission_round.py`
   - Tạo bảng `offering_admission_round` với `UNIQUE(academic_info_id, round_code)`.
   - Backfill: mỗi `OfferingAcademicInfo` đang có → tạo 1 round mặc định `DOT_1`, `start_date/end_date` từ academic_info nếu có. Dùng `ON CONFLICT (academic_info_id, round_code) DO NOTHING` để idempotent.

2. `phase2_02_add_admission_round_id_to_admission_path_and_swap_unique.py` + **end-to-end PR scope**

   **CRITICAL: `create_profile` path lookup contract** — verified `app/repositories/admission_path_repository.py:119` `get_path_by_offering_and_method(academic_info_id, admission_method_id)` dùng `.first()`. Sau swap unique sang `(round_id, method_id)`, cùng method có DOT_1 + DOT_2 cùng năm → `.first()` trả random path → snapshot `applied_rules` sai → document/quota/criteria sai.

   PR scope BẮT BUỘC bundle (KHÔNG chỉ migration DB):
   - Repository: deprecate `get_path_by_offering_and_method`. Thêm `get_path_by_round_and_method(admission_round_id, admission_method_id)`.
   - Service `create_profile`: API/schema nhận `admission_path_id` direct (preferred — explicit) hoặc `(admission_round_id, admission_method_id)` tuple (lookup mới). KHÔNG dùng `(academic_info_id, admission_method_id)` ambiguous.
   - FE form chọn path: hiển thị path with round_code label rõ ràng (e.g. "CNTT - Học bạ - DOT_1") để thí sinh không chọn nhầm.
   - Migration body bên dưới (Step 1-5):

   **Critical sequencing — KHÔNG NOT NULL ngay; ship shim service-layer trước:**

   - **Step 1**: thêm `admission_round_id` nullable.
   - **Step 2**: backfill mỗi path → round `DOT_1` của academic_info hiện tại (per-row guard: `WHERE admission_round_id IS NULL`).
   - **Step 3**: **Ship service-layer auto-resolve shim** TRƯỚC NOT NULL. Endpoint create/update path nhận payload chỉ có `academic_info_id` (không round) → service tự resolve `DOT_1` của academic_info đó:
     ```python
     async def create_admission_path(db, payload):
         if payload.admission_round_id is None and payload.academic_info_id:
             round = await db.execute(select(OfferingAdmissionRound)
                 .where(OfferingAdmissionRound.academic_info_id == payload.academic_info_id)
                 .where(OfferingAdmissionRound.round_code == 'DOT_1')).scalar_one_or_none()
             if round is None:
                 raise BusinessRuleViolation("DOT_1 round not found for academic_info")
             payload.admission_round_id = round.id
         # ... rest of create logic
     ```
   - **Step 4**: Monitor 1 tuần — log `admission_path` create call thiếu `admission_round_id`. Gate kiểm: 100% endpoint đã set round trước → mới thực hiện Step 5.
   - **Step 5 (migration RIÊNG `phase2_02b_admission_path_round_not_null_swap_unique.py`)**: ALTER COLUMN `admission_round_id SET NOT NULL` + drop unique cũ + tạo unique mới. Pre-check `COUNT(*) WHERE admission_round_id IS NULL` = 0, nếu không raise.
   - Lý do tách Step 5 thành migration riêng: ALTER NOT NULL là one-way breaking nếu caller cũ chưa migrate. Tách 2 tuần monitor giữa Step 1-4 và Step 5 cho phép detect + fix caller cũ trước khi NOT NULL kick in.
   - **Lưu ý dual-write**: trong Phase 2-3, `academic_info_id` vẫn còn (drop ở Phase 4). Service guard validate `path.academic_info_id == path.admission_round.academic_info_id` để tránh data drift.

   **⚠️ ONE-WAY MIGRATION khi prod đã enable multi-round:**
   - Sau khi prod đã tạo DOT_1/HB và DOT_2/HB cùng `academic_info_id`, dữ liệu vi phạm constraint cũ → down migration `recreate uq_admission_path_offering_method` sẽ FAIL.
   - **Down migration procedure** (manual rollback playbook, KHÔNG auto-execute):
     1. Audit duplicate paths: `SELECT academic_info_id, admission_method_id, COUNT(*) FROM admission_path GROUP BY 1,2 HAVING COUNT(*) > 1`.
     2. Cho mỗi nhóm duplicate, decide: archive (di chuyển sang `_archive_admission_path_dup` table) HOẶC merge (gộp paths về DOT_1, update mọi profile reference).
     3. Sau khi 0 duplicate, mới recreate unique cũ.
   - Tạo bảng `_archive_admission_path_dup` (cùng schema admission_path + `archived_at`, `archive_reason`) trong migration này để sẵn sàng dùng nếu rollback.
   - Down migration script chỉ raise `Exception("Manual rollback required - see Phần 7.5")` nếu detect duplicate, KHÔNG silent skip.

4. `phase2_04_widen_score_precision.py` ← **Cần thiết để chứa scale DGNL/V-ACT**
   - Verified: `AdmissionCriteria.min_score = Numeric(4,1)` (max 999.9), `max_possible_score = Numeric(5,2)` (max 999.99), `min_subject_score = Numeric(3,1)` (max 99.9). V-ACT max 1200 → overflow.
   - ALTER 3 column trên `AdmissionCriteria`:
     ```sql
     ALTER TABLE admission_criteria
       ALTER COLUMN min_score TYPE numeric(8,2),
       ALTER COLUMN min_subject_score TYPE numeric(8,2),
       ALTER COLUMN max_possible_score TYPE numeric(8,2);
     ```
   - `PathSubjectGroupConfig.min_score` + `min_subject_score` định nghĩa `Numeric(8,2)` ngay từ đầu khi tạo trong migration #3 (đã update schema phần 2.3).
   - Down migration: ALTER lại về precision cũ chỉ chạy được nếu KHÔNG có row > 999.9; raise pre-check.

3. `phase2_03_create_path_subject_group_config_and_item.py`
   - Tạo `path_subject_group_config` + `path_subject_group_item` với 2 UNIQUE constraints (xem schema Phần 2.3).
   - Backfill từ `CriteriaSubjectGroup` (idempotent qua `ON CONFLICT DO NOTHING`):
     ```sql
     -- Config: mỗi CriteriaSubjectGroup row → 1 PathSubjectGroupConfig
     INSERT INTO path_subject_group_config
         (admission_path_id, subject_group_id, min_score, min_subject_score)
     SELECT ap.id, csg.subject_group_id, ac.min_score, ac.min_subject_score
     FROM admission_path ap
     JOIN admission_criteria ac ON ac.id = ap.criteria_id
     JOIN criteria_subject_group csg ON csg.criteria_id = ac.id
     ON CONFLICT (admission_path_id, subject_group_id) DO NOTHING;

     -- Item: mỗi SubjectGroupSubject của catalog → 1 PathSubjectGroupItem
     INSERT INTO path_subject_group_item
         (path_subject_group_config_id, subject_group_subject_id, is_principal)
     SELECT psgc.id, sgs.id, false
     FROM path_subject_group_config psgc
     JOIN subject_group_subject sgs ON sgs.subject_group_id = psgc.subject_group_id
     ON CONFLICT (path_subject_group_config_id, subject_group_subject_id) DO NOTHING;
     ```
   - Service: enforce composite invariant `subject_group_subject.subject_group_id == path_subject_group_config.subject_group_id`.

4. **Test suite riêng — engine xét tuyển (separate sprint, ít nhất 30 case):**
   - GPA boundary (edge: `gpa_overall = min_gpa`)
   - Điểm liệt boundary (`raw_score = min_subject_score`)
   - 3-tầng resolution (item override > config default > criteria default)
   - Bonus áp/không áp theo method (HB không cộng, TN có cộng)
   - Multi-NV ranking (NV1 fail → xét NV2)
   - ScoreFormula custom (weighted_sum vs custom JSONB)
   - Snapshot integrity (admin xóa item → snapshot còn nguyên)
   - 5 kịch bản nghiệp vụ thực: post-THCS HB, post-THPT TN, liên thông TC, tuyển thẳng, xét chứng chỉ IELTS
   - Composite invariant fail (item của group khác config)
   - Quota guard 3 tầng: round_quota > annual, method_quota > round_quota, group_quota > method_quota

**Risk:** trung bình. Cần test consistency validator + invariant trong CI gate.

### Phase 3 — Migrate API/FE/repository (3-4 sprint)

Chuyển dần caller sang dùng entity mới. Endpoints nhận cả 2 kiểu param trong giai đoạn này.

**Pre-flight task (1 ngày):**
- Quyết định: choice-level snapshot (`bonus_rule_snapshot`, `eligibility_check_result`) đặt ở `AdmissionProfileChoice` — KHÔNG nhét vào `applied_rules` cũ. Tránh phải DROP/CREATE trigger trên prod.
- Nếu sau review thực tế phải update `applied_rules` (edge case): theo pattern migration cũ — DROP TRIGGER → backfill → CREATE TRIGGER (pattern đã có trong codebase).

**Migrations (~2 file + service/FE work):**

1. `phase3_01_create_admission_profile_choice_and_score.py`
   - Tạo `admission_profile_choice` + `profile_choice_score`
   - UNIQUE constraint `uq_profile_choice_unique_combination` + `UNIQUE(admission_profile_id, display_order)`
   - FK `path_subject_group_item_id ON DELETE SET NULL`
   - Backfill (dry-run trên DB replica trước):
     - **Chỉ profile có `selected_subject_group_id IS NOT NULL` → 1 choice với `display_order=1`**, ánh xạ về path/config hiện tại
     - Snapshot fields populate từ catalog tại thời điểm backfill
     - **GIỮ `uses_choice_engine = false`** — backfill chỉ tạo choice cho data integrity, KHÔNG flip profile cũ sang state machine mới
     - **Profile trong `_admission_backfill_exceptions` SKIP** — admin manual review qua UI ship Phase 1+2 (`AdmissionMaintenanceService.bulk_review_eligibility`). Khi admin set `selected_subject_group_id` qua UI, có thể re-run Phase 3 backfill chunk theo profile_id list.

     **Backfill execution order (3 step bắt buộc):**

     **Step 1 — INSERT exceptions TRƯỚC** (mismatch + malformed). Sau step này, mọi profile có vấn đề đã được flag để Step 2 anti-join.

     ```sql
     -- Exception 1: profile có selected_group nhưng path/config không khớp catalog hiện tại
     -- (data drift). Cast guard symmetric với Phase 1 rule (b).
     WITH eligible_for_mismatch_check AS (
         SELECT p.id AS profile_id,
                p.selected_subject_group_id,
                p.applied_rules->>'admission_path_id' AS admission_path_id_text,
                p.applied_rules->'admission_path_id' AS applied_rules_path_id_raw
         FROM admission_profile p
         WHERE p.selected_subject_group_id IS NOT NULL
           AND p.applied_rules ? 'admission_path_id'
           AND (p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'
     ),
     eligible_with_int AS (
         SELECT profile_id, selected_subject_group_id,
                admission_path_id_text::int AS admission_path_id_int,
                applied_rules_path_id_raw
         FROM eligible_for_mismatch_check
     )
     INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
     SELECT e.profile_id, 'BACKFILL_PATH_CONFIG_MISMATCH', jsonb_build_object(
            'selected_subject_group_id', e.selected_subject_group_id,
            'applied_rules_path_id', e.applied_rules_path_id_raw
        )
     FROM eligible_with_int e
     WHERE NOT EXISTS (
         SELECT 1 FROM path_subject_group_config psgc
         WHERE psgc.admission_path_id = e.admission_path_id_int
           AND psgc.subject_group_id = e.selected_subject_group_id
     )
     ON CONFLICT (profile_id, exception_type) DO NOTHING;

     -- Exception 2: profile có selected_group nhưng applied_rules thiếu key hoặc malformed.
     -- Guard NULL + non-object trước khi gọi jsonb_object_keys (set-returning function
     -- raise nếu không phải object hoặc NULL).
     -- jsonb_agg aggregate set-returning thành scalar.
     INSERT INTO _admission_backfill_exceptions (profile_id, exception_type, details)
     SELECT p.id, 'BACKFILL_MALFORMED_PATH_ID', jsonb_build_object(
            'applied_rules_keys',
            CASE
                WHEN p.applied_rules IS NULL THEN NULL::jsonb
                WHEN jsonb_typeof(p.applied_rules) <> 'object' THEN NULL::jsonb
                ELSE (SELECT jsonb_agg(k) FROM jsonb_object_keys(p.applied_rules) AS k)
            END,
            'applied_rules_full', p.applied_rules,
            'applied_rules_type', COALESCE(jsonb_typeof(p.applied_rules), 'null')
        )
     FROM admission_profile p
     WHERE p.selected_subject_group_id IS NOT NULL
       AND (
           p.applied_rules IS NULL
           OR jsonb_typeof(p.applied_rules) <> 'object'
           OR NOT (p.applied_rules ? 'admission_path_id')
           OR (p.applied_rules->>'admission_path_id') !~ '^[0-9]+$'
       )
     ON CONFLICT (profile_id, exception_type) DO NOTHING;
     ```

     **Step 2 — INSERT choice CHÍNH THỨC** chỉ cho profile đủ điều kiện (anti-join exception table):
     ```sql
     -- Tách 2 CTE: filter+regex TRƯỚC, expose cast int SAU.
     -- Postgres không đảm bảo regex predicate chạy trước cast trong cùng SELECT.
     WITH profiles_with_valid_path_id AS (
         -- Filter key + numeric regex TRƯỚC, KHÔNG cast trong WHERE
         SELECT p.id AS profile_id,
                p.selected_subject_group_id,
                p.applied_rules->>'admission_path_id' AS admission_path_id_text
         FROM admission_profile p
         WHERE p.selected_subject_group_id IS NOT NULL
           AND p.applied_rules ? 'admission_path_id'
           AND (p.applied_rules->>'admission_path_id') ~ '^[0-9]+$'
     ),
     profiles_with_path_id_int AS (
         -- Cast SAU, an toàn vì đã filter regex
         SELECT profile_id,
                selected_subject_group_id,
                admission_path_id_text::int AS admission_path_id_int
         FROM profiles_with_valid_path_id
     ),
     eligible_for_choice_creation AS (
         SELECT
             pwi.profile_id,
             pwi.admission_path_id_int AS admission_path_id,
             psgc.id AS path_subject_group_config_id
         FROM profiles_with_path_id_int pwi
         JOIN path_subject_group_config psgc
           ON psgc.admission_path_id = pwi.admission_path_id_int
          AND psgc.subject_group_id = pwi.selected_subject_group_id
         WHERE NOT EXISTS (
             SELECT 1 FROM _admission_backfill_exceptions e
             WHERE e.profile_id = pwi.profile_id
               AND e.exception_type IN (
                   'BACKFILL_PATH_CONFIG_MISMATCH',
                   'BACKFILL_MALFORMED_PATH_ID',
                   'AMBIGUOUS_SELECTED_GROUP'
               )
         )
     )
     INSERT INTO admission_profile_choice
         (admission_profile_id, display_order, admission_path_id, path_subject_group_config_id)
     SELECT
         e.profile_id, 1, e.admission_path_id, e.path_subject_group_config_id
     FROM eligible_for_choice_creation e
     WHERE NOT EXISTS (
         SELECT 1 FROM admission_profile_choice apc
         WHERE apc.admission_profile_id = e.profile_id
     )  -- idempotent: skip nếu profile đã có choice (re-run safe)
     ON CONFLICT (admission_profile_id, admission_path_id, path_subject_group_config_id) DO NOTHING;
     ```

     **Step 3 — Backfill `ProfileChoiceScore` từ `ProfileSubjectScore` cũ:**
     ```sql
     -- Resolve item_id từ catalog tại thời điểm backfill.
     -- Snapshot ĐẦY ĐỦ: subject_code/name + max + min_possible + weight.
     -- min_possible_score_snapshot bắt buộc — engine validate range cần cả min lẫn max.
     INSERT INTO profile_choice_score
         (profile_choice_id, path_subject_group_item_id,
          subject_code_snapshot, subject_name_snapshot,
          max_score_snapshot, min_possible_score_snapshot, weight_snapshot,
          raw_score, source)
     SELECT
         apc.id AS profile_choice_id,
         psgi.id AS path_subject_group_item_id,
         s.code, s.name_vi,
         COALESCE(s.max_score, 10),                     -- legacy default thang 10
         COALESCE(s.min_possible_score, 0),             -- legacy default 0
         COALESCE(psgi.weight_override, sgs.weight),
         pss.score AS raw_score,
         'SELF_DECLARED' AS source                       -- legacy data, không có verified flag
     FROM admission_profile_choice apc
     JOIN admission_profile p ON p.id = apc.admission_profile_id
     JOIN profile_subject_score pss ON pss.profile_id = p.id
     JOIN subject s ON s.id = pss.subject_id
     JOIN subject_group_subject sgs
       ON sgs.subject_group_id = p.selected_subject_group_id
      AND sgs.subject_id = pss.subject_id
     JOIN path_subject_group_item psgi
       ON psgi.path_subject_group_config_id = apc.path_subject_group_config_id
      AND psgi.subject_group_subject_id = sgs.id
     ON CONFLICT (profile_choice_id, path_subject_group_item_id) DO NOTHING;
     ```

     Score backfill idempotent qua UNIQUE constraint `(profile_choice_id, path_subject_group_item_id)` của `profile_choice_score`. Re-run safe.

   - **Execution order strict**: exception SQL (Step 1) → choice INSERT (Step 2) → score INSERT (Step 3). KHÔNG được đảo. Reason: Step 2 anti-join `_admission_backfill_exceptions` để skip profile flagged; nếu Step 1 chưa chạy, Step 2 sẽ tạo choice cho data drift.
   - Idempotent guard: skip profile đã có ≥1 choice (per-row `WHERE NOT EXISTS`).

2. ~~`phase3_02_seed_12_milestone_events_and_rules.py`~~ — **SUPERSEDED 2026-05-01: MOVED to Phase 1 #19a/#19b/#19c/#19d**

   12 ADMISSION_* milestone events catalog + notification_rule rows + template seed đã được tách + move lên Phase 1 chain để dispatch_event() wrapper code (ship trong B2 code task) có model + table sẵn sàng runtime. Active migration owner cho 12 events seed:
   - `phase1_19a_create_outbox_table` — owner table notification_outbox + 2 partial index.
   - `phase1_19b_seed_event_catalog_db_rows` — owner 12 ADMISSION_* DB row trong `notification_rule` + `notification_template` cho admin UI (EVENT_CATALOG module-level dict ship trong code task B2).
   - `phase1_19c_register_celery_beat_archive_task` — owner beat schedule `dispatch_pending_outbox` 30s + cron archive 90-day.
   - `phase1_19d_seed_notification_rules` — owner channel routing rules per audience.

   Phase 3 active migration chain CHỈ còn `phase3_01_create_admission_profile_choice_and_score` (xem dưới).

   ~~Catalog entries cho 12 events: ADMISSION_PROFILE_SUBMITTED, ADMISSION_REVISION_REQUESTED, ADMISSION_RESUBMITTED, ADMISSION_RESULT_PUBLISHED, ADMISSION_DECISION_ADMITTED, ADMISSION_DECISION_WAITLISTED, ADMISSION_DECISION_REJECTED, ADMISSION_WAITLIST_PROMOTED, ADMISSION_CONFIRMED, ADMISSION_ENROLLED, ADMISSION_WITHDRAWN, ADMISSION_ROLLED_BACK~~ (HISTORICAL — đã migrate lên Phase 1 #19b body). Rule rows định tuyến channel + template seed ~36 entries cũng moved.

3. ~~`phase3_03_create_notification_outbox.py`~~ — **SUPERSEDED 2026-05-01: MOVED to Phase 1 #19a (owner duy nhất bảng outbox)**

   `notification_outbox` table owner đã chuyển sang `phase1_19a_create_outbox_table` để outbox infrastructure ready trước Phase 1 #11 status CHECK extend + state service deploy. Không còn `phase3_03_create_notification_outbox.py` trong active chain.

   `down_revision` chain reorganized: phase1_19a/b/c/d sequence; `phase3_01_create_admission_profile_choice_and_score.down_revision = phase2_04_widen_score_precision` (Phase 2 cuối) thay vì cũ trỏ phase3_02.

   ~~Schema notification_outbox table với 2 partial index + claim columns lock-free worker~~ (HISTORICAL — body migration đã apply ở Phase 1 #19a, xem Phần 4 Phase 1 chain).

**Feature flags (3 — granular rollback):**

| Flag | Phạm vi | Rollback impact |
|---|---|---|
| `FLAG_MULTI_NV_ENABLED` | UI multi-NV + backend choice engine + flip `uses_choice_engine=true` cho profile mới | Tắt → profile mới tạo chạy state machine cũ |
| `FLAG_USE_PATH_CONFIG` | Engine xét tuyển dùng `PathSubjectGroupConfig` thay vì `CriteriaSubjectGroup` | Tắt → fallback về CriteriaSubjectGroup logic |
| `FLAG_USE_BONUS_RULE` | Áp dụng cộng điểm ưu tiên KV + đối tượng | Tắt → `computed_bonus = 0` cho mọi choice |

Round quota (Phase 2 entity) không có flag riêng — coupling chặt với `FLAG_USE_PATH_CONFIG`.

**Service/FE work:**
- Đổi mọi query "list paths by `academic_info_id`" → "list paths by `admission_round_id`". Endpoint nhận cả 2 param.
- Đổi mọi query "criteria.subject_groups" → "path.subject_group_configs". Service trả cấu trúc mới + field tương thích cho FE chưa migrate.
- FE đăng ký NV chuyển sang `PathSubjectGroupConfig` (cho phép thấy ngưỡng riêng theo path).
- UI mới cho phép thêm NV2, NV3 (gated bởi `FLAG_MULTI_NV_ENABLED`).
- Validator trước khi enable filter ở FE: "X path đang null `applicable_to` — cần admin set trước khi enable filter."
- Mọi router transition status MUST gọi `AdmissionStateService.transition()` thay vì set `profile.status` trực tiếp.

**Frontend deliverables (Phase 3, BLOCK items):**

Verified trên frontend codebase: 6 BLOCK items + 4 NICE-TO-HAVE.

| # | Deliverable | File | Severity |
|---|---|---|---|
| 1 | Mở rộng `AdmissionStatus` enum thêm 4 state mới + `STATUS_BADGE_CONFIG` mapping | `frontend/src/lib/zod/admissions.ts:495`, `frontend/src/lib/ui-config/status-badge.config.ts:40` | BLOCK |
| 2 | Thêm 9 Zod field mới + `uses_choice_engine` boolean: `selected_subject_group_id`, `gpa_overall`, `conduct`, `health_category`, `graduation_year`, `area_code`, `priority_object_codes[]`, `candidate_education_level` | `frontend/src/lib/zod/admissions.ts:296-348` | BLOCK |
| 3 | Tạo Zod schemas mới: `AdmissionProfileChoice`, `ProfileChoiceScore`, `PathSubjectGroupConfig`, `PathSubjectGroupItem` | `frontend/src/lib/zod/admissions.ts` (mới) | BLOCK |
| 4 | Mở rộng `admissionProfileResponseSchema` thêm `choices: AdmissionProfileChoice[]` nested | `frontend/src/lib/zod/admissions.ts:468` | BLOCK |
| 5 | Thêm `applicable_to` field cho path schemas | `frontend/src/lib/zod/admission-path.ts:217` | BLOCK |
| 6 | i18n keys: 25 keys cụ thể (xem sub-table dưới) — **Q8 chốt v2.13: inline 3 file existing** (`admissions.ts:880-891`, `status-badge.config.ts:96-196`, `StatusBadge.tsx:110-122`) + lint rule custom check 25 keys present trong cả 3 file. **next-intl defer Q1/2027**. Effort -1 sprint so với option xây i18n system mới. | BLOCK |

**i18n keys enumerate (25 keys, BLOCK #6 — FE dev pickup table không phải tự suy):**

| Group | Key | Vietnamese label (gợi ý) |
|---|---|---|
| Status (4) | `status.reviewing` | Đang xét duyệt |
| | `status.result_published` | Đã công bố kết quả |
| | `status.admitted` | Đã đậu |
| | `status.waitlisted` | Danh sách chờ |
| Event (12) | `event.ADMISSION_PROFILE_SUBMITTED` | Hồ sơ đã nộp |
| | `event.ADMISSION_REVISION_REQUESTED` | Yêu cầu chỉnh sửa hồ sơ |
| | `event.ADMISSION_RESUBMITTED` | Đã nộp lại hồ sơ |
| | `event.ADMISSION_RESULT_PUBLISHED` | Đã công bố kết quả |
| | `event.ADMISSION_DECISION_ADMITTED` | Quyết định đậu |
| | `event.ADMISSION_DECISION_WAITLISTED` | Vào danh sách chờ |
| | `event.ADMISSION_DECISION_REJECTED` | Quyết định không đậu |
| | `event.ADMISSION_WAITLIST_PROMOTED` | Được gọi từ danh sách chờ |
| | `event.ADMISSION_CONFIRMED` | Đã xác nhận nhập học |
| | `event.ADMISSION_ENROLLED` | Đã ghi danh |
| | `event.ADMISSION_WITHDRAWN` | Đã rút hồ sơ |
| | `event.ADMISSION_ROLLED_BACK` | Khôi phục về nháp |
| Reason code (6) | `reason.rule_1_subject_completeness` | Thiếu môn trong tổ hợp |
| | `reason.rule_2_min_gpa` | GPA chưa đạt ngưỡng |
| | `reason.rule_3_graduation_year` | Năm tốt nghiệp không hợp lệ |
| | `reason.rule_4_min_subject_score` | Điểm môn dưới ngưỡng liệt |
| | `reason.rule_5_total_score` | Tổng điểm chưa đạt |
| | `reason.rule_6_priority_bonus` | Lỗi tính điểm ưu tiên |
| Confirmed via (3) | `confirmed_via.magic_link` | Xác nhận qua liên kết |
| | `confirmed_via.officer` | Cán bộ xác nhận thay |
| | `confirmed_via.admin_override` | Quản trị viên override |

**5 component mới (estimated 2-3 sprint):**

| # | Component | Path | Mô tả |
|---|---|---|---|
| C1 | `ChoiceListEditor` | `app/(dashboard)/admissions/[id]/_components/ChoiceListEditor.tsx` | Add/remove NV, drag-reorder priority, validate UNIQUE display_order |
| C2 | `ChoiceScoreCard` | `app/(dashboard)/admissions/[id]/_components/ChoiceScoreCard.tsx` | Per-choice score input + range validate `min_possible ≤ score ≤ max` từ snapshot |
| C3 | `EligibilityResultViewer` | `app/(dashboard)/admissions/[id]/_components/EligibilityResultViewer.tsx` | Display `eligibility_check_result` JSONB chi tiết pass/fail per rule |
| C4 | `DecisionBadge` | `frontend/src/components/admissions/DecisionBadge.tsx` | Badge cho `decision: eligible/ineligible/admitted/waitlisted/rejected` |
| C5 | `AuditReasonDialog` | `frontend/src/components/admissions/AuditReasonDialog.tsx` | Reason input cho T10 (waitlist promote), T11 (waitlist reject), T12 officer/admin override, T17 rollback |

**Status literal hardcode cleanup (NICE-TO-HAVE → BLOCK nếu sai logic):**
- `AdmissionActions.tsx:89,141-160` — **GIỮ thin-client**: action gate qua `available_actions[]` từ backend response (verified pattern hiện tại ở `permission-adapter.ts:45`). KHÔNG suy luận `is_admitted_like(profile)` ở FE.
- **Backend trách nhiệm**: `_populate_response_fields()` trong `admission_service.py` PHẢI populate `available_actions` typed structure (KHÔNG list[str] generic) phân biệt T12 endpoint:
  ```python
  # Old (v2.6): available_actions: list[str] = ["confirm", "request_revision"]
  # New (v2.10): typed structure phân biệt target self vs override
  available_actions: list[AvailableAction] = [
      AvailableAction(
          action="confirm",
          target="self",                                          # candidate via magic_link
          endpoint="/api/v2/public/admissions/{token}/confirm",  # candidate context only
      ),
      AvailableAction(
          action="confirm",
          target="override",                                      # officer/admin override
          endpoint="/api/v2/admissions/{id}/staff-confirm",      # staff context
      ),
      AvailableAction(action="request_revision", target="staff",
                      endpoint="/api/v2/admissions/{id}/request-revision"),
  ]
  ```
- Backend logic: candidate context (request có magic_link token) → trả chỉ `target='self'` actions. Staff context (logged-in officer/admin) → trả `target='override'/'staff'` actions. Cả 2 context có thể có `confirm` action với `target` khác.
- FE branch: `actions.find(a => a.action === 'confirm' && a.target === 'self')` → render "Xác nhận nhập học" cho candidate; `target === 'override'` → render "Xác nhận thay thí sinh" cho staff với reason dialog.
- **Backward compat 3-step soft cutoff (P1 fix #6 v2.11 — chống FE outdated crash)**:
  - **Wave B+0** (2026-08-13): backend keep CẢ `available_actions` (typed) lẫn `available_actions_legacy` (list[str]). FE Wave B push update + service worker cache invalidate.
  - **Wave B+30 days** (2026-09-13): backend vẫn populate `available_actions_legacy` + thêm response header `X-API-Deprecation: 30 days`. FE log warning để dev biết user đang dùng client cũ.
  - **Wave B+90 days** (2026-11-13): backend drop `available_actions_legacy`. Response header `X-API-Schema-Version: 2`. FE outdated check version mismatch → trigger force reload.
  - Lý do: user mở browser tab cũ trước Wave B → FE bundle cached service worker → undefined access nếu hard drop. 90 days đủ cho mọi user refresh trong mùa tuyển sinh.
- `LeadDetailPanel.tsx`, `LeadInfoTab.tsx` — display `lead.gpa` (5 references) → dual-read fallback `profile.gpa_overall ?? lead.gpa` (xem Phần 2.5.a).
- `AdmissionStepper.tsx` — bổ sung 4 step mới cho choice-engine flow.

**Socket events register (NICE-TO-HAVE):**
- `frontend/src/lib/socket/client.ts` — listen 12 admission events. Critical: `RESULT_PUBLISHED`, `DECISION_*`, `WAITLIST_PROMOTED` để dashboard auto-refresh khi admin publish.
- Cache invalidate: gọi `queryClient.invalidateQueries(['admissions'])` khi nhận event.

**Wave B retroactive add NV timing rule (P1 fix #5 v2.12)**:

Profile tạo Wave A (W11-W12) có 1 choice. Wave B deploy (W13-W15) hiển thị "Add NV" button cho profile cũ. KHÔNG được phép add NV cho profile đã submitted/reviewing — break "applied_rules immutable after submit".

**Rule chốt**:
- Backend `available_actions` typed entry `add_choice` chỉ populate khi:
  - `profile.status IN ('draft', 'revision_requested')` AND
  - `round.end_date >= NOW()` (round chưa hết hạn)
  - VÀ `count(profile.choices) < MAX_CHOICES_PER_PROFILE` (default 5, configurable)
- Profile submitted/reviewing → button disabled với tooltip "Chỉ thêm NV trước khi submit hoặc khi tư vấn viên yêu cầu sửa".
- FE Wave B render add NV button qua check `available_actions.find(a => a.action === 'add_choice')`, KHÔNG suy luận từ status.

**Backend service**:
```python
async def add_choice_to_profile(db, profile_id, choice_payload, actor):
    profile = await db.get(AdmissionProfile, profile_id, with_for_update=True)
    if profile.status not in ('draft', 'revision_requested'):
        raise BusinessRuleViolation(
            "Chỉ thêm NV cho profile draft hoặc revision_requested"
        )
    round = await db.get(OfferingAdmissionRound, ...)
    if round.end_date < datetime.now(timezone.utc):
        raise BusinessRuleViolation("Round đã hết hạn, không thể thêm NV")
    # ... insert AdmissionProfileChoice
```

**FE effort revise**: timeline Phase 3 originally 1 sprint (W10-W13). Với deliverables trên, FE cần **2-3 sprint** (W10-W17). Có 2 lựa chọn:
- (a) Stretch Phase 3 timeline → đẩy Phase 4 sang Q1/2027 (vẫn kịp mùa 2026).
- (b) Multi-NV launch staged: Phase 3 Wave A (W10-W13) ship single-choice UI mới (1 NV/profile, dùng AdmissionProfileChoice nhưng UI giới hạn 1); Wave B (W14-W17) mở multi-NV.

Chốt (b) — staged launch giảm risk + cho phép soak Wave A trên prod 2 tuần trước Wave B.

**Risk:** trung bình-cao. Cần 3 feature flags để rollback granular, monitor log production xem caller cũ còn dùng không.

### Phase 4 — Drop cũ (1 sprint, sau 1-2 tháng quan sát)

Chỉ drop khi grep codebase + log production xác nhận không còn caller cũ.

1. Drop `AdmissionPath.academic_info_id`
2. Deprecate `CriteriaSubjectGroup` (giữ read-only một thời gian)
3. Sau khi mọi report/filter dùng `degree_level_id`: drop `MajorProgram.degree_level` text

**Risk:** thấp nếu Phase 3 đã monitor đủ.

---

## Phần 5 — Quota guard 3 tầng (service-layer)

Postgres không support cross-row CHECK. Validate ở service layer mọi create/update:

```python
# Tier 1: round_quota ≤ annual
sum(rounds.round_quota for r in academic_info.rounds if r.round_quota is not None)
    <= academic_info.annual_admission_quota

# Tier 2: method_quota ≤ round_quota (nếu round_quota set)
if round.round_quota is not None:
    sum(p.method_quota for p in round.paths if p.method_quota is not None)
        <= round.round_quota

# Tier 3: group_quota ≤ method_quota (nếu method_quota set)
if path.method_quota is not None:
    sum(c.group_quota for c in path.subject_group_configs if c.group_quota is not None)
        <= path.method_quota
```

Optional defense-in-depth: trigger `AFTER INSERT/UPDATE` validate sum.

### Phần 5.a — Concurrency strategy cho quota mutations

Service-layer sum check KHÔNG đủ trong production: 2 admin đồng thời đọc tổng quota còn hợp lệ, mỗi người update khác path/group, cả hai commit → tổng vượt quota. Bắt buộc thêm 1 trong 3 mechanism:

**Lựa chọn (chốt cho v1.9): Pattern A + B kết hợp**

**Pattern A — `SELECT ... FOR UPDATE` parent row** (cho mọi quota mutation):
```python
async def create_round_with_quota_check(db, academic_info_id, round_data):
    # Lock parent academic_info row TRƯỚC khi compute sum
    academic_info = await db.execute(
        select(OfferingAcademicInfo)
        .where(OfferingAcademicInfo.id == academic_info_id)
        .with_for_update()  # row-level lock, hold đến cuối transaction
    )
    # Compute sum + validate
    rounds = await db.execute(
        select(OfferingAdmissionRound)
        .where(OfferingAdmissionRound.academic_info_id == academic_info_id)
    )
    total_quota = sum(r.round_quota for r in rounds if r.round_quota is not None)
    if total_quota + round_data.round_quota > academic_info.annual_admission_quota:
        raise BusinessRuleViolation("Sum round_quota exceeds annual quota")
    # Insert mới
    db.add(OfferingAdmissionRound(**round_data))
```

**Pattern B — Advisory lock cho operations cross-table** (round → method → group):
```python
async def update_method_quota_with_concurrency_guard(db, path_id, new_method_quota):
    path = await db.get(AdmissionPath, path_id)
    # Advisory lock theo academic_info_id — tránh deadlock cross-row
    await db.execute(text(
        "SELECT pg_advisory_xact_lock(:key)"
    ), {"key": path.academic_info_id})
    # Sau lock: compute sum + validate
    ...
```

**Khi nào dùng Pattern nào:**
- Pattern A (`FOR UPDATE`): operations trên 1 entity với parent rõ ràng (round under academic_info, group_quota under path).
- Pattern B (advisory lock): operations cross-table nhiều bậc (e.g. service tính tổng method_quota nhưng đồng thời cho phép tạo path mới — lock theo academic_info_id ở cả 2 đường).
- KHÔNG dùng `SERIALIZABLE` isolation toàn bộ — cost cao, nhiều endpoint không cần.

**Tránh anti-pattern:**
- ❌ Đọc sum mà không lock → race window.
- ❌ Lock toàn bộ table (`LOCK TABLE`) → block mọi reader.
- ❌ Application-level mutex (e.g. Redis lock) → không atomic với DB transaction.

### Phần 5.b — Candidate quota consume (P1 fix #5 v2.11)

Phần 5.a chỉ cover admin mutate quota. Candidate consume quota khi submit cũng có race window:
- Round_quota = 100, đã 99 profile submitted.
- 2 candidate submit cùng lúc — endpoint check `count(profile WHERE round_id=X) < quota` → cả 2 pass (race đọc count = 99) → INSERT 101 profile.

**Pattern atomic check-and-decrement trên `submission_count` column**:
```python
async def public_submit(profile_id, db):
    profile = (await db.execute(
        select(AdmissionProfile).where(AdmissionProfile.id == profile_id)
        .with_for_update()
    )).scalar_one_or_none()

    round_id = profile.applied_rules['admission_round_id']

    # Atomic increment: chỉ thành công nếu submission_count < round_quota
    result = await db.execute(text("""
        UPDATE offering_admission_round
        SET submission_count = submission_count + 1
        WHERE id = :round_id
          AND (round_quota IS NULL OR submission_count < round_quota)
        RETURNING submission_count, round_quota
    """), {"round_id": round_id})
    row = result.scalar_one_or_none()
    if row is None:
        # KHÔNG match WHERE — đã đủ chỉ tiêu
        raise BusinessRuleViolation(
            "Đợt tuyển sinh đã đủ chỉ tiêu, không nhận thêm hồ sơ. "
            "Vui lòng liên hệ tư vấn viên để đăng ký đợt sau."
        )

    # Tiếp tục transition draft → submitted
    await transition(...)
```

**Lưu ý**:
- `submission_count` increment ATOMIC qua single UPDATE — không cần advisory lock.
- Withdraw profile → `submission_count -= 1` (UPDATE atomic tương tự, có check `submission_count > 0`).
- Backfill Phase 2 #01 (tạo `OfferingAdmissionRound`): set `submission_count = COUNT(profile WHERE round_id=...)` initial.
- Quota = NULL (no limit) → submission_count cứ tăng không reject. Useful cho training course không giới hạn slot.

**Phân biệt 2 loại quota** (chốt với product):
- `round_quota` = số slot **submission** (đăng ký) — current pattern.
- `admit_quota` = số slot **trúng tuyển** (passed score threshold) — cần thêm column riêng nếu nghiệp vụ phân biệt. Plan v2.11 default chỉ có submission_count.

**Tránh anti-pattern**:
- ❌ Check sum trước, INSERT sau → race window.
- ❌ Trigger AFTER INSERT count → không reject được, chỉ alert.
- ❌ Lock toàn bộ round table → block reader public storefront.

**Admin reduce `round_quota` mid-mùa (P1 fix #4 v2.12 — UX warning + audit)**:

Atomic UPDATE pattern reject submit khi `submission_count > new_quota`. Nhưng nếu admin giảm quota silent (100 → 60 sau khi đã 80 submitted) → mọi submit mới reject im lặng, candidate confused. Cần warning + override + audit:

```python
# app/services/round_service.py
async def update_round_quota(db, round_id, new_quota, *, override=False, reason=None, admin):
    round = await db.execute(
        select(OfferingAdmissionRound).where(id=round_id).with_for_update()
    ).scalar_one()

    if new_quota is not None and new_quota < round.submission_count:
        if not override:
            return {
                "status": "warning",
                "message": (f"Quota mới ({new_quota}) thấp hơn submission_count hiện tại "
                            f"({round.submission_count}). Đã có {round.submission_count - new_quota} hồ sơ "
                            f"vượt chỉ tiêu mới. Override=true + reason để confirm."),
                "current_submission_count": round.submission_count,
                "new_quota": new_quota,
                "delta": new_quota - round.submission_count,
            }
        # Override → audit log mandatory
        if not reason or len(reason) < 10:
            raise ValidationError("Reason ≥10 chars bắt buộc khi override quota reduction")
        audit_log_entry = RoundAuditLog(
            round_id=round_id,
            action='quota_reduced_with_oversubscribed',
            old_value=round.round_quota,
            new_value=new_quota,
            reason=reason,
            performed_by_user_id=admin.id,
        )
        db.add(audit_log_entry)

    round.round_quota = new_quota
    return {"status": "success"}
```

**Cron alert hàng ngày**: nếu round có `submission_count > round_quota` (oversubscribed state) → alert admin qua email/in-app notification daily đến khi resolve.

---

## Phần 5b — Idempotent backfill pattern

Mọi migration có backfill phải idempotent: re-run sau khi deploy fail giữa chừng KHÔNG được duplicate hoặc raise.

**Pattern A — Per-row idempotency dùng `WHERE NOT EXISTS` (KHÔNG dùng "skip nếu table có row"):**

⚠️ **Anti-pattern**: `if existing > 0 → skip` lỗ — nếu deploy fail giữa chừng (insert được 50/100 rows) → re-run sẽ skip → 50 rows thiếu vĩnh viễn. KHÔNG dùng pattern này.

```python
def upgrade():
    bind = op.get_bind()

    # Per-row idempotent: chỉ insert những academic_info chưa có round DOT_1
    bind.execute(sa.text("""
        INSERT INTO offering_admission_round
            (academic_info_id, round_code, round_name, is_active)
        SELECT ai.id, 'DOT_1', 'Đợt 1 (mặc định)', true
        FROM offering_academic_info ai
        WHERE ai.is_deleted = false
          AND NOT EXISTS (
              SELECT 1 FROM offering_admission_round r
              WHERE r.academic_info_id = ai.id
                AND r.round_code = 'DOT_1'
          )
    """))
```

Hoặc dùng `ON CONFLICT (natural_key) DO NOTHING` nếu có UNIQUE constraint:

```python
op.execute(sa.text("""
    INSERT INTO offering_admission_round
        (academic_info_id, round_code, round_name, is_active)
    SELECT id, 'DOT_1', 'Đợt 1 (mặc định)', true
    FROM offering_academic_info
    WHERE NOT is_deleted
    ON CONFLICT (academic_info_id, round_code) DO NOTHING
"""))
```

(Cần thêm `UNIQUE(academic_info_id, round_code)` vào schema của `offering_admission_round`.)

**Pattern B — `ON CONFLICT DO NOTHING` cho seed:**

```python
def upgrade():
    op.execute(sa.text("""
        INSERT INTO subject (code, name_vi, subject_kind, max_score, is_active)
        VALUES
            ('TB_HK1_L12', 'TB học kỳ 1 lớp 12', 'TERM_AVERAGE', 10, true),
            ('TB_HK2_L12', 'TB học kỳ 2 lớp 12', 'TERM_AVERAGE', 10, true),
            ('DGNL_DHQGHN', 'ĐGNL ĐHQG Hà Nội', 'ABILITY_TEST', 150, true),
            ('IELTS', 'IELTS', 'CERTIFICATE', 9, true)
        ON CONFLICT (code) DO NOTHING
    """))
```

**Pattern C — Conditional UPDATE per-row guard:**

```python
# Ví dụ generic — backfill scalar có guard NULL + idempotent
op.execute(sa.text("""
    UPDATE admission_profile p
    SET area_code = compute_area_code_fn(
        p.permanent_province, p.permanent_district, p.permanent_ward
    )
    WHERE p.area_code IS NULL
      AND p.permanent_province IS NOT NULL
"""))
```

⚠️ **KHÔNG dùng `academic_history->-1->>'gpa'`** cho GPA backfill — record cuối có thể thiếu gpa nhưng record trước có. Migration 9a thực tế dùng `LATERAL jsonb_array_elements(... ) WITH ORDINALITY` + filter numeric + `DISTINCT ON ... ORDER BY profile_id, ord DESC`. Xem migration 9a body cho shape đúng.

**Coverage:** Mọi migration backfill trong Phase 1, 2, 3 áp dụng pattern A, B, hoặc C tùy ngữ cảnh. Test rehearsal trên DB replica: chạy migration 2 lần liên tiếp, expect lần 2 no-op + không raise.

---

## Phần 6 — Test strategy

Phải có riêng cho engine xét tuyển. **1 sprint dedicated trong Phase 2.**

**Layer 1 — Unit test (engine pure logic, no DB):**
- 3-tier resolution: 8 case (mỗi tầng có/không có override)
- 6 rule × pass/fail = 12 case minimum
- Bonus rule resolution: 4 case (override / method default / null / both null)

**Layer 2 — Integration test (engine + DB fixtures):**
- 5 kịch bản nghiệp vụ end-to-end
- Snapshot integrity (admin xóa item config → score giữ nguyên)
- Quota guard 3 tầng (mỗi tầng overflow)
- Composite invariant fail
- Lock-after-draft trigger (UPDATE non-draft → raise)

**Layer 3 — Migration rehearsal (DB replica):**
- Backfill `PathSubjectGroupConfig` từ `CriteriaSubjectGroup` không mất data
- Backfill `AdmissionProfileChoice` từ `AdmissionProfile` không mất data
- Trigger lock không block migration backfill

**Layer 4 — Cross-module regression (BẮT BUỘC sau Phase 1 #15 task #15 ship):**

Verify mọi downstream service handle CẢ 3 case profile:
- `legacy_approved`: `uses_choice_engine=False`, `status='approved'` (profile cũ + Phase 0 P1 fix)
- `legacy_overridden`: `uses_choice_engine=False`, `status='overridden'` (admin override legacy)
- `choice_engine_admitted`: `uses_choice_engine=True`, `status='admitted'` (profile mới Phase 3+)

**Test cases bắt buộc cho mỗi downstream:**

| Downstream | Test scenario | Expected |
|---|---|---|
| `routers/fees.py` | Fee creation cho 3 case | Cả 3 trigger fee creation đúng (`is_admitted_like(profile) == True`) |
| `services/commission_service.py` | Commission compute cho 3 case | Commission record created, status linked đúng |
| `services/phase_manager.py` | Phase transition cho 3 case | Phase chuyển đúng (sts09 hoặc tương đương) |
| `repositories/admission_repository.py:429` | Analytics aggregate count | Status counts include cả `approved` lẫn `admitted` qua `effective_status()` |
| `core/admission_event_mapping.py` | Lead pipeline projection cho 3 case | Lead.consultation_status = `sts09` cho cả 3 |
| `routers/admissions.py confirm endpoint` | `is_admitted_like(profile)` gate | Cho phép confirm với cả 3 case |
| `services/admission_service.py:5904 (fee paid update)` | UPDATE applied_rules.fee_paid_at | KHÔNG raise nhờ Phase 0b whitelist |
| `lead_admission_sync.py 4 new states` | Profile transition `reviewing/result_published/admitted/waitlisted` | Lead stage projection đúng theo map mới |

**Test cases cho notification system:**
- 12 events mỗi event có dispatch site: 7 critical → INSERT outbox; 5 best-effort → safe_dispatch.
- Coverage script catch dev accidental dùng `safe_dispatch` cho `requires_outbox=True` event.
- Bypass consent: 5 critical events vẫn fanout dù `consent_status='revoked'`; 7 best-effort respect consent.
- Outbox worker idempotency: re-run task không duplicate fanout.

**Test cases cho frontend:**
- Status badge render cho 4 state mới + i18n key resolve.
- ChoiceListEditor: add 3 NV, drag-reorder, validate UNIQUE display_order.
- AuditReasonDialog: T10/T11/T12 (officer/admin)/T17 require reason ≥10 chars.
- Magic link flow: candidate confirm fanout `transitioned_by_lead_id` đúng.

**Coverage gate:**
- Tối thiểu 80% line coverage cho `admission_scoring_service.py`.
- Tối thiểu 90% coverage cho `admission_state_service.py` + `admission_event_mapping.py` (state transition + projection).
- 100% pass `check_notification_event_coverage.py` script (12 events).

---

## Phần 7 — Decision locked 2026-04-30: Multi-NV BẮT BUỘC cho mùa 2026

User confirm 2026-04-30: multi-NV phải sẵn sàng cho mùa tuyển sinh 2026 (mùa thường mở Q3, đợt 1 ~tháng 7). Timeline lock như sau:

### 7.1. Timeline gấp (absolute dates, baseline 2026-04-30)

| Phase | Start | Deadline | Tuần | Notes |
|---|---|---|---|---|
| Phase 0 (P1 fixes + 2 migration + B1/B2 code task) | 2026-04-30 | 2026-05-14 | W1-W2 (2w) | Stop bleeding scoring bugs + applied_rules whitelist + **Casbin deny rewrite (B1) + EventDefinition extend (B2)**. Ship độc lập. |
| Phase 1 (revised, 18 migration + #15a/15b/15c + #16 audit gate parallel) | 2026-05-14 | 2026-06-11 | W3-W6 (4w) | 18 migration (thêm 19a/b/c/d outbox tách + system_config); **#15 tách 3 PR sequence + #16 audit task chạy SONG SONG**; phải merge TRƯỚC migration #11. **DEFER per Q9: #04 extra thresholds, #07 demographics, #09 admin UI sang Q1/2027.** |
| Phase 2 (5 migration + admit_quota Q6 + #17 storefront) | 2026-06-11 | 2026-07-09 | W7-W10 (4w) | 5 migration + test suite + AdmissionPath unique swap + score precision widen + **`OfferingAdmissionRound.admit_quota` field per Q6**. Code task #17 ship CÙNG WAVE với phase2_02b. |
| **Phase 3 Wave A (single-choice UI) — HARD COMMIT** | **2026-07-09** | **2026-07-23** | **W11-W12 (2w)** | Single NV per profile. FE staged launch. **Q4 chốt: hard commit deadline 2026-07-23.** |
| Mùa 2026 mở Wave A | 2026-07-23 | — | — | Soak prod 2 tuần với single-choice UI. |
| **Phase 3 Wave B (multi-NV) — BEST-EFFORT, SLIP-ABLE** | **2026-07-23** | **2026-08-13** | **W13-W15 (3w)** | Mở multi NV1/NV2/NV3, 12 events, outbox, FE full deliverables. **Q4 chốt: best-effort 2026-08-13; SLIP OK** nếu Phase 1/2 chậm. Mùa 2026 single-NV vẫn run được, multi-NV defer Wave C nếu cần. |
| Mùa 2026 multi-NV | 2026-08-13 (best-effort) | — | — | Slip-able. Document risk slip với product. |
| **Phase 4 (drop cũ) — Q1/2027** | **2027-01-01** | **2027-03-31** | **Q1/2027** | **Q5 chốt: KHÔNG drop destructive Q4/2026 khi mùa còn nóng.** Drop legacy `Lead.gpa`, `AdmissionPath.academic_info_id`, `MajorProgram.degree_level` text. **+ Defer items per Q9**: Phase 1 #04 (extra thresholds min_conduct/min_health), #07 (demographics area_code/priority_object_codes), #09 admin UI (conduct/health input UI). + i18n next-intl migration per Q8. |

**Tổng từ baseline 2026-04-30 → Wave A hard 2026-07-23: 12 tuần. Wave B best-effort 2026-08-13: 15 tuần.** Mọi mốc absolute date. **Q9 chốt: drop scope, KHÔNG tăng người trễ.** Nếu Phase 1/2 chậm → drop Phase 1 #04/#07/#09 sang Q1/2027 (đã defer ở plan v2.13), KHÔNG ép Wave B. Wave A single-NV đủ cho mùa 2026.

### 7.2. Risk mitigation cho Phase 3 timeline gấp

Phase 3 backfill `AdmissionProfileChoice` chạy trên prod data live — risk cao nếu fail giữa chừng. Mitigation bắt buộc:

1. **Dry-run trên DB replica trước deploy thật**: clone snapshot prod → chạy migration end-to-end → diff verify. Repeat 2 lần (lần 1 baseline, lần 2 idempotency check).
2. **Rehearsal staging với prod-like data volume**: ≥100 profile mẫu copy từ prod (anonymized) → chạy full Phase 3 migration + smoke test. Đo time + memory peak.
3. **Feature flag mặc định OFF khi deploy**: `FLAG_MULTI_NV_ENABLED=false` lúc apply migration. Bật flag riêng sau khi smoke test pass trên prod.
4. **Backfill chunked + checkpoint**: nếu profile count > 1000, chia chunk 500/batch + insert checkpoint row. Re-run từ checkpoint nếu fail giữa chừng (idempotent guard pattern A/B/C ở Phần 5b).
5. **Rollback plan documented**: nếu Phase 3 deploy fail giữa mùa tuyển sinh, đường lùi là tắt `FLAG_MULTI_NV_ENABLED` → state machine cũ active lại cho profile mới (profile cũ không bị ảnh hưởng nhờ `uses_choice_engine = false`).

### 7.3. Pre-mùa 2026 checklist

Phải xong trước khi mùa 2026 mở (~tháng 7/2026):

- [ ] Phase 0/1/2/3 ship + monitor prod xanh ≥2 tuần
- [ ] Admin set `applicable_to[]` cho 100% path active của mùa 2026 (validator block enable filter nếu có path null)
- [ ] Admin set `default_bonus_rule` cho mọi `AdmissionMethod` được dùng trong mùa 2026
- [ ] Admin set `OfferingAdmissionRound` (DOT_1, DOT_2, BO_SUNG) với `round_quota` đúng tổng = `annual_admission_quota`
- [ ] Test suite engine xét tuyển ≥80% coverage + 30+ case pass
- [ ] 12 milestone events catalog + rule + template seed verified zero silent fanout
- [ ] FE đăng ký NV multi-priority (NV1/NV2/NV3) + UI confirm/withdraw
- [ ] Admin training: workflow result_published + waitlist_promoted + rollback override

### 7.5. Rollback playbook cho in-flight choice-engine profiles

Tắt `FLAG_MULTI_NV_ENABLED` chỉ block profile mới tạo. Profile đã `uses_choice_engine=true` ở `result_published/admitted/waitlisted` không tự về legacy flow. Có 3 chiến lược rollback tùy mức độ severity:

**Chiến lược A — Freeze + read-only (mức nhẹ, scope hẹp):**
- Chỉ áp dụng khi rollback do bug FE/UI hiển thị, KHÔNG phải engine xét tuyển sai.
- Tắt flag → profile mới về legacy. Profile in-flight giữ nguyên state, FE switch sang chế độ read-only (không cho transition tiếp).
- Officer manual export danh sách in-flight profile, xử lý qua admin UI riêng.
- Pre-condition: state_history có đầy đủ, audit log không lost.

**Chiến lược B — Status remap có kiểm soát (mức trung):**
- Áp dụng khi engine xét tuyển sai NHƯNG decision đã fanout cho thí sinh.
- Tạo migration rollback script 1-shot:
  ```sql
  -- Map new status DIRECTLY về legacy state (KHÔNG map sang state mới khác).
  -- Lý do: 'reviewing' cũng là state mới → CHECK constraint cũ reject.
  -- Phải map về set legacy {draft, submitted, approved, rejected, ...} đảm bảo
  -- downgrade CHECK chạy được.
  UPDATE admission_profile
  SET status = CASE status
    WHEN 'admitted' THEN 'approved'              -- legacy admitted equivalent
    WHEN 'waitlisted' THEN 'submitted'           -- chờ xử lý lại bằng legacy flow
    WHEN 'rejected' THEN 'rejected'              -- giữ nguyên (cũng có ở legacy)
    WHEN 'result_published' THEN 'submitted'    -- KHÔNG map về 'reviewing' (cũng là new state)
    WHEN 'reviewing' THEN 'submitted'            -- legacy không có 'reviewing'
    ELSE status
  END,
  uses_choice_engine = false
  WHERE uses_choice_engine = true
    AND status IN ('reviewing', 'result_published', 'admitted', 'waitlisted');

  -- Insert status_history row cho mỗi remap
  INSERT INTO admission_profile_status_history (...) ...;

  -- ASSERT TRƯỚC khi run downgrade CHECK migration: 0 row ở 4 new state
  DO $$
  DECLARE
      remaining_count INT;
  BEGIN
      SELECT COUNT(*) INTO remaining_count
      FROM admission_profile
      WHERE status IN ('reviewing', 'result_published', 'admitted', 'waitlisted');
      IF remaining_count > 0 THEN
          RAISE EXCEPTION 'Remap incomplete: % profiles still in new states', remaining_count;
      END IF;
  END $$;
  ```
- KHÔNG xóa `AdmissionProfileChoice` — giữ làm audit. FE legacy sẽ ignore choices.
- Re-fanout notification "Hệ thống tạm hoãn công bố kết quả" cho tất cả profile bị remap.

**Chiến lược C — Full DB restore (mức nặng, last resort):**
- Áp dụng khi engine sai nghiêm trọng + data corruption không thể remap.
- Trước khi deploy Phase 3, chụp DB snapshot pre-deploy → lưu offsite.
- Restore từ snapshot, mất mọi data từ điểm snapshot. Notify mọi user.
- **Tiền điều kiện bắt buộc**: snapshot phải được tạo + verify trước khi deploy Phase 3, không phải lúc cần.

**Decision matrix:**

| Severity | Strategy | Recovery time | Data loss |
|---|---|---|---|
| UI bug, engine OK | A | <1h | 0 |
| Engine sai, decision đã gửi | B | 4-8h | 0 (audit kept) |
| Data corruption, engine sai nghiêm trọng | C | 24h+ | data từ snapshot |

**Pre-flight bắt buộc trước Phase 3 deploy:**
- [ ] DB snapshot pre-deploy taken + verified (dùng cho strategy C)
- [ ] Status remap script (strategy B) viết sẵn + dry-run trên DB replica
- [ ] FE read-only mode (strategy A) tested + togglable bằng env var
- [ ] Runbook document strategy A/B/C với contact + escalation path

### 7.4. Phase 0 starts immediately

Phase 0 (3 P1 score/submit fixes) độc lập với refactor — bắt đầu ngay tuần này, không chờ Phase 1 design hoàn tất:

- P1-1: `submit_and_evaluate` subject_based check `score_result.passed`
- P1-2: `min_gpa` enforce cho subject_based path (avg of selected scores)
- P1-3: persist `Profile.selected_group` + enforce subject restriction

User approve mở PR Phase 0 → start.

---

## Phần 8 — Cheat sheet (tóm tắt thay đổi)

| Loại | Chi tiết | Phase |
|---|---|---|
| Bug fix + persist | P1-1/P1-2/P1-3 (scoring/submit) + `selected_subject_group_id` migration | 0 |
| FK mới | `MajorProgram.degree_level_id → config_degree_level.id` (catalog đã có) | 1 |
| Field mới (nullable) | `AdmissionMethod.default_bonus_rule` | 1 |
| Field mới (nullable) | `AdmissionPath.bonus_rule_override`, `applicable_to[]`, `method_quota` + GIN index | 1 |
| Field mới | `AdmissionCriteria.min_conduct`, `min_health_category`, `required_graduation_year_min/max` | 1 |
| Field mới | `Subject.subject_kind`, `max_score`, `min_possible_score` + seed subject ảo | 1 |
| Field mới (nullable) | `DocumentGroup.admission_path_id` + service resolution 3 tầng | 1 |
| Field mới (nullable) | `AdmissionProfile.area_code`, `priority_object_codes[]`, `candidate_education_level` | 1 |
| Field mới (NOT NULL default false) | `AdmissionProfile.uses_choice_engine` | 1 |
| Field mới (9a) | `AdmissionProfile.gpa_overall` + `graduation_year` backfill từ JSON; `conduct` + `health_category` để NULL — admin manual review qua UI (academic_history KHÔNG có nguồn) | 1 |
| DB trigger (9b) | `trg_lock_profile_eligibility_fields` block UPDATE 4 field khi status ≠ draft/revision_requested | 1 |
| Bảng mới | `admission_profile_status_history` + actor model split (user_id + lead_id) + backfill 1 row/profile | 1 |
| ALTER CHECK | Extend `ck_admission_profile_status` thêm states mới + giữ legacy | 1 |
| FK mới + decision tree | `AdmissionProfile.selected_subject_group_id` + bảng `_admission_backfill_exceptions` + 3 backfill rule (a/b/c) | 1 |
| Code task | Audit + remap workflow `approved → admitted` qua normalize layer ở 23 file (xem task #15 detail) | 1 |
| Bảng mới | `OfferingAdmissionRound` + `UNIQUE(academic_info_id, round_code)` + `admit_quota INT NULL` field (Q6 v2.13) | 2 |
| Field + unique swap (one-way) | `AdmissionPath.admission_round_id` + DROP unique cũ + tạo unique mới + bảng `_archive_admission_path_dup` cho rollback procedure | 2 |
| Bảng mới | `PathSubjectGroupConfig`, `PathSubjectGroupItem` | 2 |
| Pydantic schema | `ScoreFormulaConfig` discriminated union (whitelist `weighted_sum`) | 2 |
| Test suite | 30+ case engine xét tuyển | 2 |
| Service mới | `AdmissionStateService.transition()` với 17 transition matrix + reason guard | 3 |
| Bảng mới | `AdmissionProfileChoice` + `UNIQUE(profile_id, display_order)` + composite invariant; `ProfileChoiceScore` (`raw_score Numeric(8,2)` đủ chứa DGNL/V-ACT) | 3 |
| Rollback playbook | 3 chiến lược A/B/C cho in-flight choice-engine profiles (Phần 7.5) — pre-flight DB snapshot + remap script + FE read-only mode | 3 |
| Notification | Catalog + rule + template seed cho **12 milestone events** | 3 |
| Feature flags | `FLAG_MULTI_NV_ENABLED`, `FLAG_USE_PATH_CONFIG`, `FLAG_USE_BONUS_RULE` | 3 |
| Drop | `AdmissionPath.academic_info_id` | 4 |
| Deprecate | `CriteriaSubjectGroup` | 4 |
| Drop | `MajorProgram.degree_level` text | 4 |

**Tổng số migration (v2.13 revised, PATCH-18):**

- **Phase 0: 2** (`phase0_add_selected_subject_group_id`, `phase0b_relax_applied_rules_immutability_for_payment_keys`)
- **Phase 1: 18** (01, 02, 03, 05, 06, 07b, 08, 09a, 10, system_config, archived_admission_profile, archived_outbox, 11, 12, 15a/15b/15c logical-only, 18, 19a, 19b, 19c, 19d) — **Q9 defer #04 + #07 + #09b sang Q1/2027**.
- **Phase 2: 5** (01 thêm admit_quota field per Q6, 02, 02b NOT-NULL+swap-unique, 03, 04 widen score precision)
- **Phase 3: 1** (01 choice/score) — outbox table + 12 events seed moved sang Phase 1 #19a/b/c/d
- **Phase 4: 4 (Q1/2027)** — drop legacy + áp Phase 1 #04/#07/#09b defer + i18n next-intl migration

**Code task (6 PR riêng, KHÔNG Alembic):**
- **Phase 0c** — hot-fix field-name `admission_criteria_id → criteria_id` ở `admission_config_repository.py:76,84`. GATE: merge BEFORE phase1_01.
- **B1 (PATCH-16 v2.13)** — Casbin `auth_model.conf` rewrite + deny effect + 4 role × 14 action matrix test. GATE BEFORE phase1_11.
- **B2 (PATCH-17 v2.13)** — `EventDefinition` extend (`requires_outbox` + `bypass_consent_check`) + 12 SystemEvents enum + EVENT_CATALOG seed module-level. GATE BEFORE phase1_19a.
- **#15** — workflow remap `approved → admitted` 23 file caller + `is_admitted_like()` helper. GATE BEFORE phase1_11.
- **#16** — workflow contract boundary refactor **11 direct** `profile.status='...'` site (round 20 re-verify; lines 3918, 5014, 5317, 5517, 5708, 6085, 6284, 6862, 7786, 7994, 8214 — bao gồm 2 site bulk approve/reject sót audit ban đầu) sang `state_service.transition()` + lint rule. GATE BEFORE phase1_11.
- **#17** — `public_admissions_service` migrate sang round + audience filter + 3-tier doc. GATE BEFORE phase2_02b.

**Tổng v2.13.1 (post Phase 3 supersede): 26 file Alembic + 6 code task + Frontend Phase 3 Wave A/B.** (Phase 3 migration đếm = 1 sau khi phase3_02 + phase3_03 SUPERSEDED → moved Phase 1 #19a-d.)

**Effort ước tính (revised v2.13):**
- 2 BE dev full-time + 1 FE dev cho Phase 3 = **12 tuần đến Wave A** (hard commit 2026-07-23) + 3 tuần Wave B (best-effort 2026-08-13, slip OK).
- **Q4 + Q9 chốt: Wave B SLIP-ABLE; KHÔNG ép multi-NV nếu P0 chưa đóng**. Single-NV Wave A đủ cho mùa 2026.
- **Buffer ≈ 1 tuần** sau Q9 drop scope (defer Phase 1 #04/#07/#09b sang Q1/2027) + Wave B slip safety net.

---

## Phần 9 — Phụ lục: Field name verification log

Document v1.0 đã align với schema thực tế (verified 2026-04-30):

| Bản sai trước | DB thực tế |
|---|---|
| `AdmissionPath.is_active` | `AdmissionPath.status` |
| `ProgramOffering.major_program_id` | `ProgramOffering.program_id` |
| `OfferingAcademicInfo.program_offering_id` | `OfferingAcademicInfo.offering_id` |
| `AdmissionCriteria.note` | `AdmissionCriteria.conditions` |
| `DocumentGroupItem.is_required` | `DocumentGroupItem.is_mandatory` |
| `DocumentGroupItem.document_group_id` | `DocumentGroupItem.group_id` |
| `DocumentGroupItem.document_type` | `DocumentGroupItem.document_type_id` (FK) |
| `OfferingSemesterTuition.note` | `OfferingSemesterTuition.notes` |
| `AdmissionProfile.snapshot_rule` | `AdmissionProfile.applied_rules` |
| `Subject.name` | `Subject.name_vi` |
| `SubjectGroupSubject.display_order` | `SubjectGroupSubject.position` |
| `MajorProgram.name_en/description` (proposed) | KHÔNG TỒN TẠI — bỏ khỏi schema cuối |
| `SubjectGroup.description` (proposed) | KHÔNG TỒN TẠI — bỏ khỏi schema cuối |
| `OfferingAdmissionConfig.admission_criteria_id` (code-level drift, NOT proposal) | `criteria_id` (model thực tế); Phase 0c hot-fix `admission_config_repository.py:76,84` — silent broken `AttributeError` runtime |
| `AdmissionPath.admission_criteria_id` (code-level drift, NOT proposal) | `criteria_id` (model thực tế); Phase 0c hot-fix cùng PR — silent broken `AttributeError` runtime |

**Nguyên tắc:** giữ nguyên tên DB; alias ở API/serializer nếu cần đổi semantic. Trước mọi đề xuất schema mới, GREP/READ model file gốc để verify field name. Code-level drift (caller dùng sai tên field model) ship hot-fix riêng, không lẫn refactor PR.

### Mapping deviation log (post-frozen-PLAN)

PLAN section §4 task #15 line 3380-3395 quy định một mapping cụ thể. Khi implement #15 trên branch `feature/admission-issue-15` (2026-05-03), user re-chốt 3 deviation sau prod-state audit (qlts.tnpc.edu.vn) + DB seed semantic verification:

| Status | PLAN line 3380-3395 | Final implementation | Lý do deviation |
|---|---|---|---|
| `reviewing` | `sts06` | **`sts07` (admission-phase floor)** | sts06 = consultation phase pre-submission; reviewing = officer xét hồ sơ ĐÃ NỘP → MUST ở admission phase sts07. PLAN sts06 vi phạm pipeline forward-only (sẽ regress lead). Floor rule chỉ apply nếu lead đang ở pre-application; preserve later state nếu đã sts07+. |
| `waitlisted` | `sts06` | **`sts07` (admission-phase floor)** | Same rationale — đã nộp + xét + chờ ghế → admission phase sts07. |
| `result_published` | `sts09` (PLAN list as map entry) | **explicit no-op (`_RESULT_PUBLISHED_NO_OP` sentinel)** | Future intermediate state / T6 broadcast marker, không phải per-profile mutation. Per-profile transition do T7/T8/T9 (admitted/waitlisted/rejected) sở hữu. Sync function short-circuit, lead pipeline không mutate. |

`admitted → sts09` (PLAN unchanged), `is_admitted_like` set `{approved, overridden, admitted}` (PLAN unchanged), `LEGACY_TO_NEW_STATUS_MAP` 3-entry (PLAN unchanged) đều giữ nguyên. Codex reviewer round thêm `is_confirmation_eligible` strict subset `{approved, admitted}` cho 4 magic-link site (overridden excluded vì state machine route `overridden → enrolled` direct, bypass `confirmed`).

Audit reference: `Documents/ADMISSION_DAILY_LOG.md` 2026-05-03 #15 entry — 7-question matrix với rationale từng quyết định.

### #184 Phase 1 Schema — slot assignments + naming deviations (2026-05-03)

PLAN section §4 Phase 1 chain ordering uses placeholder revision IDs (`phase1_XX`) for migrations whose slot was reserved but not numbered (PATCH-14 system_config + PATCH-20 archive tables). The user-facing chốt 2026-05-03 + verified-empty audit assigns concrete IDs:

| Spec migration | Assigned revision ID | Wave | Notes |
|---|---|---|---|
| `phase1_XX_create_system_config_table` (PATCH-14) | **`phase1_13`** | Wave 1 | `current_intake_year=2026` seed; admin UPDATE endpoint |
| `phase1_XX_create_archived_admission_profile_table` (PATCH-20) | **`phase1_16`** | Wave 5 | 90-day archive policy (line 168) + round end_date+6m archive cron (line 195) |
| `phase1_XX_create_archived_outbox_table` (PATCH-20) | **`phase1_17`** | Wave 5 | Outbox archive companion |
| `phase1_19b_seed_event_catalog_db_rows` (spec) | **`phase1_19c`** | Wave 5 | **Naming deviation** — slot `phase1_19b` was claimed by B1's `phase1_19b_backfill_casbin_eft_and_seed_deny_rules` (PR #201, 6 deny rules per PLAN line 1411-1415; 16 referenced in #183 issue body is a cosmetic drift). The remaining notification-rule chain shifts: spec's `phase1_19c` → `phase1_19d`; spec's `phase1_19d` → `phase1_19e`. |

Slot `phase1_14` left free as a future-reserve gap; `phase1_15a/15b/15c` reserved for Wave 4 lead-1-many sub-PR split (DDL drop + soak 1w + model+repo + soak 1w + FE migrate per PLAN line 3468-3473).

Audit reference: `Documents/ADMISSION_DAILY_LOG.md` 2026-05-03 #184 preflight entry — 6-question matrix + Q1=C / Q2=A / Q3=phase1_13/16/17 / Q4=accept 3w / Q5=verify D12-D14 / Q6=start Wave 1 now.

### Phase 2 — Schema design pivot Option A (2026-05-09, v8.2 plan locked)

**MAJOR deviation from §2.1 line 532-535 + §4 Phase 2 line 3577-3608**.

Plan v8.2 chốt 2026-05-09 sau 8 audit rounds. Plan file: `C:\Users\Admin\.claude\plans\noble-launching-cocoa.md`. v6 PR-2A archived qua tag `phase2-pr-2a-v6-archived` (push origin) — 6 commits + 22 files + 2961 lines + 8/8 browser smoke PASS retained for git history reference.

#### Schema deviation — round entity location

| Aspect | PLAN §2.1 spec (v6 plan) | v8.2 Option A final |
|---|---|---|
| Round entity | `OfferingAdmissionRound.academic_info_id` FK (per academic_info) | `OfferingAdmissionRound.academic_year` int + UNIQUE(academic_year, round_code) — year-level globally |
| Storage | N rows per đợt (3 majors × 4 đợt = 12 rows replicate) | 1 row per đợt globally |
| Quota fields | `round_quota`, `admit_quota`, `submission_count` on round table | MOVED to `admission_path` (per-path counter + caps) |
| Round metadata sharing | Per academic_info (extend = N atomic UPDATEs) | Globally (extend = 1 UPDATE, paths inherit qua JOIN) |
| Tier 1 chain root | `sum(round.round_quota in academic_info) ≤ annual_admission_quota` | `∑(path.admit_quota WHERE academic_info_id=X) ≤ academic_info[X].annual_admission_quota` |
| AdmissionPath UNIQUE | swap to `(round_id, method_id)` [PR-2C v6] | swap to **3-col** `(round_id, academic_info_id, method_id)` [PR-2C v8.2 Q5] |
| Atomic submit increment | `offering_admission_round.submission_count` per round | `admission_path.submission_count` per path (P3-3) |
| Path FK | unspecified | `admission_path.admission_round_id` ON DELETE RESTRICT [Q7] |
| Path clone | implicit | Mandatory deep-copy `AdmissionCriteria` + `CriteriaSubjectGroup` + `PathSubjectGroupConfig` + `PathSubjectGroupItem` per ADM-003 1:1 invariant [Q6] |
| round_code namespace | implicit DOT_1/DOT_2 | Pure string + UI convention; program_type enum defer Phase 3 [Q8] |
| Round metadata Phase 2 | time-window + notification template | Time-window only (extension audit + lifecycle); notification template defer Phase 3 [Q3] |

#### Lý do deviation

User Pass 4 review (2026-05-09) flag UX issue PR-2A v6: bottom-up workflow buộc admin vào từng ngành tạo đợt. Walk-through 8 stories + 4 edge cases reveal v6 schema sinh problem replication:

1. Round metadata edit (extend/archive/notification template) → bulk update N rows atomic per academic_info
2. Phase 3+ notification template per round = N rows duplicate
3. Cross-major reporting "Đợt 1 status" = scan N rows GROUP BY
4. Bulk-create solves CREATE only — EXTEND/ARCHIVE/EDIT vẫn pay N-row coordination cost

Schema correctness Phase 2 trumps fast ship vì Phase 3+ cycle benefits multiply (multi-NV, choice engine, magic link multi-action depend on round metadata sharing).

#### 8 decisions LOCKED Q1-Q8

| # | Decision | Choice |
|---|---|---|
| Q1 | Schema | Option A (year-level round) |
| Q2 | Tier 1 chain root | `admit_quota` per academic_info |
| Q3 | Round metadata Phase 2 | time-window only |
| Q4 | Branch strategy | tag preserve v6 + new `feat/admission-phase2-01-rounds-v2` |
| Q5 | UNIQUE columns | 3-col `(round_id, academic_info_id, method_id)` |
| Q6 | Clone strategy | hybrid modal + deep-copy criteria chain |
| Q7 | FK ON DELETE | RESTRICT |
| Q8 | round_code namespace | pure string + UI convention |

#### Quota chain refactor v8.2 (Phần 5 update)

- **Tier 1**: `∑(path.admit_quota WHERE academic_info_id=X AND path.status != 'archived' AND path.admit_quota IS NOT NULL) ≤ academic_info[X].annual_admission_quota`. Scope PER academic_info.
- **Tier 2** (path-level invariant): `path.admit_quota ≤ path.round_quota` nếu cả 2 set.
- **Tier 3** (PR-2D): `∑(group_quota in path) ≤ path.admit_quota`. KHÔNG fallback "round.admit_quota".

#### Atomic increment SQL pattern shift

PLAN §4.1 line 4100-4107 atomic increment original target: `offering_admission_round.submission_count`. v8.2 moves counter to `admission_path.submission_count` per-path semantic. Per-path semantic correct vì candidate submit destination = (path × round × major), KHÔNG global round.

#### v8.1 P0 patches (3 blockers from Pass 5 review)

1. **P0-1**: `admission_path.archived_at` column **không tồn tại** — `AdmissionPath.status` enum value `'archived'` (`app/models/admission_config/admission_path.py:91-98`). Tier 1 filter: `path.status != 'archived'`.
2. **P0-2**: DB trigger `enforce_applied_rules_immutability` (`b5c6d7e8f9a0_add_applied_rules_immutability_trigger.py:42-47`) chặn UPDATE `applied_rules`. PR-2B Task 3 wrap `ALTER TABLE ... DISABLE/ENABLE TRIGGER` try/finally per precedent `aa1i2j3k4l5m_pr6_allow_unverified_submission.py:65-92`.
3. **P0-3**: PR-2B Task 4 cast unsafe — CTE `safe_profiles` wrapper với regex `~ '^[0-9]+$'` + EXISTS guard parity Task 3.

#### PR breakdown v8.2 (6 PRs ~10d)

| PR | Scope |
|---|---|
| PR-2A v2 | phase2_01_v2 year-level OfferingAdmissionRound + RoundsManagementTab top-level + bulk-create endpoint |
| PR-2B v2 | phase2_02_v2 admission_path 4 cols + 4-task backfill (DISABLE/ENABLE trigger + CTE safe_profiles) + service shim + Wave 6 #17 P2 storefront |
| PR-2C v2 ⚠ | phase2_02b_v2 NOT NULL + 3-col UNIQUE swap + archive table + manual rollback playbook v8 |
| PR-2D | phase2_03 PathSubjectGroupConfig + Item + QuotaMatrix UI + clone endpoint deep-copy |
| PR-2E | phase2_04 Numeric(8,2) score precision |
| PR-2F | engine sweep ≥22 cases + mandatory `test_tier1_chain_per_academic_info_scope` |

Audit reference: `Documents/ADMISSION_DAILY_LOG.md` 2026-05-09 design pivot entry + memory `phase2-plan-locked` v8.2 + plan file `C:\Users\Admin\.claude\plans\noble-launching-cocoa.md`.
