# PHASE 3 CLOSE-OUT PLAN

**Date drafted**: 2026-05-14
**Date locked**: 2026-05-14
**Status**: **LOCKED v2** — 3 open Qs locked (Q-CO-1=B, Q-CO-2=A, Q-CO-3=B); READY-TO-EXECUTE Day 0
**Predecessor plans**:
- `C:\Users\Admin\.claude\plans\noble-launching-cocoa.md` v0.7 (Phase 3 implementation, LOCKED 2026-05-12)
- `Documents/PHASE3_UI_DESIGN.md` v0.5 (UI design contract)
- `Documents/ADMISSION_REFACTOR_PLAN.md` v2.13.1 (source-of-truth spec)

**Trigger**: Wave A + Wave B core SHIPPED 2026-05-13 (~3 tháng sớm so target), nhưng:
1. **PR-3E magic-link router chưa ship** — block Wave A acceptance gate "Magic-link consume atomic"
2. **8 deferred follow-ups** (1 P0 infra + 1 P0/Phase 4 + 4 P2 + 2 P3) chưa xử lý
3. ~~1 pre-existing P3 bug `resubmit_profile NoneType`~~ — **CLOSED**: verified main HEAD, fix `(data.get('notes') or 'No notes')[:50]` đã có tại `admission_service.py:6310`, ship trong PR #234 (`d8554bca`) post-cutover follow-up batch. Memory `resubmit-notes-none-bug` updated CLOSED 2026-05-11
4. ~~Bundle 4 code drift~~ — **RESOLVED 2026-05-14**: deploy run `25787180541` rerun PASS (1m27s), containers Up 1 phút verified, prod on SHA `7f859415` live

---

## Outcome mong muốn

- Phase 3 đóng hoàn toàn trước **mùa tuyển sinh 2026-08-01**
- 100% Wave A + Wave B acceptance gates PASS
- 0 P0/P1 outstanding
- FE CI gap đóng để không lặp pattern Bundle 1 hotfix #274
- Hardening buffer còn ~10w trước Wave A hard commit 2026-07-23 → dư cho hard-review + soak

---

## Inventory việc còn lại

### A. P0 — MUST ship trước Wave A acceptance signoff

| ID | Việc | Effort | Source | Block gate |
|---|---|---|---|---|
| **PR-CO-1** | FE CI workflow at PR-level | 0.3d | FU #126 (memory `phase3-wave-b-closure`) | Infra debt |
| **PR-CO-2-BE** | PR-3E magic-link router + service + tests | 1.2d | Plan v0.7 PR-3E BE | Wave A "Magic-link consume atomic" |
| **PR-CO-2-FE** | PR-3E FE 4-action UI + Zod + smoke | 0.6d | Plan v0.7 PR-3E FE | Wave B "Magic-link 4 actions consumable" |

### B. P2 — Test/audit debt sweep (tách theo nature, KHÔNG bundle 1 PR)

| ID | Việc | Effort | Source | Nature |
|---|---|---|---|---|
| **PR-CO-3** | DELETE choice audit log + reason + actor_id | 0.3d | FU #114 (memory `phase3-pr3d-b-backlog`) | feat (production code) |
| **PR-CO-4** | Casbin matrix anchor test + bulk-resolve atomicity test | 0.5d | FU #115 + FU #118 | test (pure test) |
| **PR-CO-5** | CSV true streaming generator | 0.2d | FU #117 | perf (refactor; defer-able Phase 4) |
| **PR-CO-6** | Multi-NV CRUD E2E spec nightly | 0.5d | FU #129 | test (Playwright nightly) |

### C. P3 — Nice-to-have, có thể defer Phase 4

| ID | Việc | Effort | Source |
|---|---|---|---|
| PR-CO-7 | dnd-kit SSR `aria-describedby` hydration mismatch | 0.2d | FU #124 |
| (cosmetic) | DAILY_LOG SHA references refresh post squash | 0.1d | Fold vào Day-0 checklist, KHÔNG PR riêng (N1) |

### D. Phase 4 (Q1/2027, KHÔNG trong close-out)

- FU #113 Drop `g, role:admin, role:accountant` Casbin edge — admin diamond gotcha (cần D2 maintenance window + regression sweep)
- Phase 1 #04 extra thresholds per criteria
- Phase 1 #07 demographics ethnicity/religion
- Phase 1 #09b admin UI extension
- Lock-after-draft DB trigger
- Auto-promote waitlist
- next-intl migration
- Storefront round picker UI (Q-P3-03)

### E. Timer events đã setup, KHÔNG trong close-out

- 2026-08-13 Wave B+0 boundary (deprecation tracking starts)
- 2026-09-13 B+30: BE toggle `X-API-Deprecation` header → FE listener log warn
- 2026-12-15 B+90: BE drop `available_actions_legacy` field → FE listener force reload

---

## PR breakdown chi tiết

### PR-CO-1 — FE CI workflow at PR-level (P0, ~0.3d)

**Branch**: `chore/ci-frontend-pr-gate`

**Scope**:
- Tạo `.github/workflows/frontend-test.yml`
  - Trigger: `pull_request` paths `frontend/**`
  - Job: vitest + tsc + lint + build (4 step độc lập)
  - Reuse cache pattern từ deploy.yml hiện tại
  - `concurrency: { group: fe-pr-${{ github.ref }}, cancel-in-progress: true }` cho cùng PR
- **Cross-file workflow sync check** (H6, memory `ci-workflow-flag-cross-file-sync`):
  - `grep -rn "node-version" .github/workflows/` → verify pin khớp deploy.yml (1 single version)
  - `grep -rn "cache-key" .github/workflows/` → verify cache naming consistent
  - Anchor regression: cố tình tạo PR draft với `react-hooks/set-state-in-effect` lỗi → verify gate FAIL

**Performance budget** (H5 concrete):
- Target: <4 phút median, <6 phút p95
- Fallback nếu >6 phút median sau 1 tuần soak: tách build step thành matrix job song song (vitest|tsc|lint|build) hoặc cache `.next/cache` aggressively
- KHÔNG include E2E Playwright trong PR-level gate (deferred PR-CO-6 nightly)

**Rationale**: Bundle 1 hotfix #274 cycle = lint rule chỉ catch ở deploy gate (push:main), không ở PR gate. Memory `phase3-wave-b-closure` ghi đây là **P0 infra debt**. Bundle 2-3 cũng phát hiện cùng pattern → fix preemptive.

**Acceptance**:
- PR đầu tiên đi qua workflow → 4 checks visible
- Cố tình break lint local → PR check FAIL
- CI run <4 phút median
- Cross-file workflow grep PASS (node-version + cache-key aligned)

---

### PR-CO-2-BE — PR-3E magic-link router + service + tests (P0, ~1.2d)

**Branch**: `feat/admission-phase3-06-magic-link-router-be`

**Scope BE** (~0.8d):
1. Router `Backend_FastAPI/app/routers/admissions_magic_link.py`
   - `POST /api/v2/admissions/magic-link/{action}/{token}` — 4 action handlers
   - Action enum Pydantic: `submit | resubmit | confirm | withdraw`
   - Body: `{ cccd: str }`
2. `MagicLinkService.consume_token(token, cccd, action)`:
   - Step 1: Redis rate limit `mlt:{token}` max 5/60s
   - Step 2: Atomic `UPDATE confirmed_at=NOW() WHERE token=:t AND action_type=:a AND confirmed_at IS NULL AND expires_at > NOW() RETURNING ...`
   - Step 3: CCCD verify từ `lead.citizen_id` constant-time compare (`hmac.compare_digest`)
   - Step 4: Rollback consume + rate_limit++ nếu CCCD sai
   - Step 5: Dispatch action handler per action_type
3. CSRF exempt: prefix `/api/v2/admissions/magic-link/` trong CSRFMiddleware allowlist (P-UI-06)
4. Token issuance action-aware: `create_confirmation_token(action_type=)` (P-UI-09)

**Tests** (~0.4d):
1. Race: concurrent consume → atomic `WHERE confirmed_at IS NULL` chỉ 1 win
2. CCCD wrong: rollback consume + rate_limit++
3. Rate limit: 5 fails → 6th return locked
4. Expired token: return `ResourceNotFoundError`
5. CSRF exempt: smoke verify với CSRF cookie tắt
6. CCCD constant-time compare anchor test (no timing leak)

**Acceptance BE-first**:
- 6 tests PASS
- BE deploy + smoke prod: issue token via existing flow → consume từ Postman với CCCD đúng/sai
- Wave A acceptance gate "Magic-link submit/confirm token consume atomic" ✅ (BE side)
- BE-first ship cho phép Wave A signoff partial PASS sớm; FE follow-up không block

---

### PR-CO-2-FE — PR-3E FE 4-action UI (P0, ~0.6d)

**Branch**: `feat/admission-phase3-06-magic-link-router-fe`

**Depends on**: PR-CO-2-BE merged + smoke PASS

**Folder convention decision (C3 fix)**:
- ✅ ROOT pattern `app/magic-link/[action]/[token]/page.tsx` — new canonical namespace cho 4-action multi-link
- ❌ NOT `app/(auth)/...` — group này chứa session-required flows (login/register/forgot-password), middleware redirect risk
- Existing `app/confirm/[token]/page.tsx` (action-implicit confirm) → giữ backward compat, redirect tới `/magic-link/confirm/[token]` qua 301 nếu cần consolidate Phase 4

**Scope FE** (~0.6d):
1. 4 magic-link landing pages `app/magic-link/[action]/[token]/page.tsx`
   - Form input CCCD + verify
   - On success: redirect dashboard hoặc landing per action
   - On fail: error friendly (rate-limit / expired / wrong CCCD / already used)
2. Zod schema `lib/zod/magic-link.ts` cho 4 actions
3. API client `lib/api/magic-link.ts`
4. Vitest: form validation + error states 4 actions
5. Playwright smoke 1 happy-path per action

**Acceptance**:
- 4 vitest PASS + 4 Playwright smoke PASS
- Browser smoke prod: 1 action thực qua /magic-link/confirm/<token> with real CCCD
- Wave B acceptance gate "Magic-link 4 actions all consumable" ✅

---

### PR-CO-3 — DELETE choice audit log (P2, ~0.3d)

**Branch**: `feat/phase3-delete-choice-audit-log`

**Nature**: feat (production code change — touches service signature + schema)

**Scope**:
- `ChoiceDeleteRequest` schema thêm `reason: Optional[str]`
- Service `delete_choice(profile_id, choice_id, reason, actor_id)` signature change
- `log_activity` row với reason + actor + before/after snapshot JSONB
- Anchor test: DELETE → assert activity_log row inserted với đầy đủ fields
- Migration: KHÔNG cần (activity_log table append-only, không backfill historical)

**Source**: FU #114 memory `phase3-pr3d-b-backlog`

---

### PR-CO-4 — Casbin matrix + bulk-resolve atomicity tests (P2, ~0.5d)

**Branch**: `test/phase3-coverage-sweep`

**Nature**: pure test (không touch production code)

**Scope** (2 FUs bundle vì cùng pure-test nature):
1. **FU #115** Casbin matrix anchor test
   - `tests/unit/test_casbin_phase3_routes.py` extend
   - 8 routes × {officer, manager, accountant, admin} = 32 cells assertive
   - Mỗi cell có comment "expected reason" (non-tautological per memory `pattern-change-impact-audit`)
2. **FU #118** Bulk-resolve atomicity test
   - `tests/api/test_phase3_pr3d_b_admin_backfill.py` extend
   - `test_bulk_resolve_partial_fail_rolls_back_all` — mock 1 UPDATE raise mid-batch → assert all 500 rolled back + counters reflect zero resolved + caller sees domain error

**Source**: FU #115 + #118 memory `phase3-pr3d-b-backlog`

---

### PR-CO-5 — CSV true streaming (P2, ~0.2d) — defer-able Phase 4

**Branch**: `perf/phase3-csv-true-streaming`

**Nature**: perf (refactor production code path)

**Scope**:
- `admin_backfill.py:export_csv` chuyển sang async generator yield chunks
- Hiện tại `io.StringIO()` then `iter([buf.getvalue()])` defeats StreamingResponse — entire CSV loaded to memory first. ~5MB at 10k rows acceptable cho QLTS scale
- Anchor test: 10k rows mock → assert peak memory <50MB (psutil)
- Existing CSV output byte-byte match (RC5): test diff bytes pre/post refactor

**Decision**: Defer Phase 4 nếu S1 timeline tight. QLTS scale chưa cần urgent.

**Source**: FU #117 memory `phase3-pr3d-b-backlog`

---

### PR-CO-6 — Multi-NV CRUD E2E spec nightly (P2, ~0.5d)

**Branch**: `test/multi-nv-crud-e2e`

**Nature**: test (Playwright nightly tag, không block PR merge)

**Scope**:
- Playwright spec `test/e2e/admission-multi-nv-workflow.spec.ts`
- 5 scenarios:
  1. Add 3 NV → reorder → save → reload verify display_order
  2. Add NV → delete → confirm count
  3. Add 5 NV → 6th button disabled (max gate)
  4. Per-NV score input → blur → API save → revert on error
  5. Submit profile → engine run → 1 admitted → 4 skip cascade
- Mark `@nightly-regression` tag

**Source**: FU #129 memory `phase3-wave-b-closure`

---

### PR-CO-7 — dnd-kit SSR hydration (P3, ~0.2d) — DEFER

DEFER unless soak window phát hiện user-visible glitch. Cosmetic, doesn't break.

---

## Sequencing đề xuất

```
Sprint S1 — Phase 3 close-out
─────────────────────────────────────────
Active dev: ~3.6d (sum P0 + P2 must) | Optional: +0.5d (PR-CO-6) | Defer-able: +0.2d (PR-CO-5)
Calendar:   ~5-6 working days với weekend reset (memory R11)

Day 0 (sau khi user APPROVE plan v1):
├─ ✅ Bundle 4 deploy hoàn tất (verified 2026-05-14 13:18 UTC+7, rerun #25787180541 PASS)
├─ Append DAILY_LOG entry "Phase 3 close-out kickoff" với final Bundle 1-4 squash SHAs (cosmetic N1)
└─ Memory `phase3-closeout-plan` save (sau LOCK)

Day 1 — Infra debt first:
└─ PR-CO-1 FE CI workflow (~0.3d) → merge + verify gate active trên 1 test PR
   └─ Rationale: Block CI hygiene cho mọi PR sau; nếu skip thì PR-CO-2 onwards
     lặp Bundle 1 pattern (memory `test-before-push`)

Day 2-3 — Wave A acceptance unblock:
└─ PR-CO-2-BE PR-3E magic-link router + service + tests (~1.2d)
   ├─ BE router + service (~0.8d)
   └─ 6 tests (~0.4d)
   → Smoke prod via Postman + Wave A gate "Magic-link consume atomic" PASS

Day 4 — Wave B acceptance unblock:
└─ PR-CO-2-FE PR-3E FE 4-action UI (~0.6d)
   → Browser smoke prod 1 happy-path per action
   → Wave B gate "Magic-link 4 actions consumable" PASS

Day 5 — Test/audit debt sweep (3 PRs parallel-reviewable):
├─ PR-CO-3 DELETE choice audit log (~0.3d) [feat]
└─ PR-CO-4 Casbin matrix + bulk-resolve atomicity tests (~0.5d) [test]

Day 6 — Optional (Q-CO-1 lock-dependent):
├─ PR-CO-6 Multi-NV E2E nightly (~0.5d) — recommend defer S2
└─ PR-CO-5 CSV streaming (~0.2d) — recommend defer Phase 4

═════════════════════════════════════════
Sprint S2 — Hard-review + Soak (~3-5d, bắt đầu sau S1)

├─ Hard-review pass 1: grep parseApiError consumers, role string checks, React Query cache invalidation gaps
├─ Hard-review pass 2: dispatch(strict=True) coverage, IDOR sweep PR-3D-B BE endpoints
├─ 48h soak post Sprint S1 ship — KPI track + error budget monitor
├─ PR-CO-6 Multi-NV E2E nightly nếu defer từ S1 (Q-CO-1 = B)
├─ PR-CO-7 dnd-kit SSR fix nếu surface user-visible
└─ Documentation polish

═════════════════════════════════════════
Sprint S3 — Phase 4 prep (Q1/2027 scope)

├─ FU #113 Drop admin→accountant Casbin edge (cần D2 window + regression sweep)
├─ PR-CO-5 CSV streaming nếu defer từ S1
├─ Auto-promote waitlist design doc
├─ Storefront round picker scope (Q-P3-03 deferred)
├─ B+30 deprecation header BE toggle 2026-09-13 (calendar reminder)
└─ B+90 cutover 2026-12-15 (calendar reminder)
```

**Timeline tổng**: Sprint S1 ~3.6d active dev / 5-6 calendar days (H7 distinction) + Sprint S2 ~3-5d active dev. Còn ~10w buffer trước Wave A hard commit 2026-07-23, mùa tuyển sinh 2026-08-01 mở với polish FULL.

---

## Acceptance signoff checklist (N2 consolidated — Magic-link gate đếm 1 lần)

Gate sau S1 (Wave A + Wave B core):

- [ ] 14 status states render đúng badge + i18n
- [ ] Single-NV submit flow end-to-end
- [ ] State machine T1-T16 traversable per role
- [ ] Multi-NV up to MAX_CHOICES create/reorder/save
- [ ] Engine sequential admit/skip cascade verify (1 NV admitted → remaining skip)
- [ ] 12 events fanout LIVE prod (notification delivery confirmed in-app + email)
- [ ] **Magic-link 4 actions all atomic consume** (cần PR-CO-2-BE + PR-CO-2-FE) ← gate đơn cho cả 2 Wave
- [ ] Retroactive add-choice gate respect status + round open + count
- [ ] Bundle 4 listener deploy verified prod (✅ verified 2026-05-14)
- [ ] FE CI PR gate active (cần PR-CO-1)

Gate sau S2 hardening:

- [ ] 0 P0/P1 regressions 48h post Sprint S1 ship
- [ ] Multi-NV CRUD E2E nightly green (cần PR-CO-6 nếu Q-CO-1=A, S2 nếu Q-CO-1=B)
- [ ] Hard-review pass 1+2 completed
- [ ] Mùa 2026-08-01 open với 0 critical bugs

---

## Risk register

| # | Risk | Mitigation |
|---|---|---|
| RC1 | PR-3E magic-link consume race trên prod | Atomic UPDATE + Redis rate limit + 4 race tests trước merge |
| RC2 | CCCD verify leak via timing attack | `hmac.compare_digest` constant-time compare + rate limit lockout |
| RC3 | FE CI workflow chậm (>5 phút) → bottleneck dev velocity | Target <4 phút median <6 phút p95; concurrency cancel-in-progress; fallback matrix split nếu >6 phút median sau 1w soak; KHÔNG include E2E PR-level (H5) |
| RC4 | DELETE audit cần backfill historical rows | Audit log table append-only, không backfill — apply forward only |
| RC5 | CSV streaming refactor break existing consumer | Anchor test bytes pre/post refactor match |
| RC6 | Solo dev burn-out sau 2 sprint sát nhau | R11 weekend reset; S1 active dev ≤3.6d / calendar 5-6d; S2 chia nhỏ 3-5d |
| RC7 NEW | PR-CO-1 mới workflow drift với existing deploy.yml | Cross-file grep node-version + cache-key (H6, memory `ci-workflow-flag-cross-file-sync`) |
| RC8 NEW | PR-CO-2 BE-first ship trước FE → admin issue token nhưng candidate chưa có UI consume | Cảnh báo support team paused issue tokens trong gap ~1 ngày BE→FE; smoke verify Postman trong gap; ship sequential KHÔNG parallel |

---

## Pre-conditions trước Sprint S1

- [x] Bundle 4 deploy PASS — verified 2026-05-14 13:18 UTC+7 (C2 fix)
- [x] Resubmit bug verification — code already fixed, memory `resubmit-notes-none-bug` CLOSED (C1 fix)
- [x] User APPROVE plan v1 (locked 2026-05-14)
- [x] **Q-CO-1 LOCKED = B** (PR-CO-6 defer S2 — E2E nightly tag không block PR merge; S1 tight ~3.6d active dev)
- [x] **Q-CO-2 LOCKED = A** (PR-CO-3/4/5 split 3 PR theo nature feat/test/perf — separation of concerns, granular rollback)
- [x] **Q-CO-3 LOCKED = B** (PR-3E split BE-first → FE-second — Wave A signoff sớm; gap risk ~0 user-facing trong solo dev context: admin UI chưa expose 4-action issue, email template 4 actions chưa exist, mùa tuyển sinh chưa mở)
- [x] Memory `phase3-wave-b-closure` next-session pointer update (N3 — KHÔNG tạo memory mới)

---

## Open questions — LOCKED 2026-05-14

**Q-CO-1 ✅ LOCKED = B (defer S2)**
- ~~(A) S1 — ship cùng test debt sweep~~
- **(B) S2 — defer cho hardening sprint, focus S1 P0 items**
- **Rationale**: E2E `@nightly-regression` tag không block PR merge → không phải gate Wave A/B acceptance. S1 keep tight ~3.6d active dev / 5-6 calendar (memory R11 solo burn-out mitigation). S2 hardening viết E2E song song với 48h soak — regression real-world catch sớm.

**Q-CO-2 ✅ LOCKED = A (3 PR split theo nature)**
- **(A) 3 PR riêng theo nature (feat/test/perf)**
- ~~(B) 4 PR riêng 1-1 mapping FU~~
- ~~(C) 1 PR bundle (v0 spec)~~
- **Rationale**: FU #114 DELETE audit là production code change (schema + service signature) — KHÔNG cùng nature pure test FU #115/#118 và perf refactor FU #117. Solo dev review nhỏ dễ; rollback granularity tốt (perf nếu break consumer rollback riêng); PR-CO-5 perf defer Phase 4 nếu tight.

**Q-CO-3 ✅ LOCKED = B (BE-first → FE-second)**
- ~~(A) 1 PR full-stack atomic~~
- **(B) Tách 2 PR BE-first → FE-second**
- **Rationale**: Wave A acceptance gate "Magic-link consume atomic" PASS sớm sau BE-only ship (Day 2-3), mở buffer S2 hardening dài hơn 1 ngày. Gap risk BE-deployed-no-FE thực tế **0 user-facing** trong solo dev context:
  - Mùa tuyển sinh chưa mở (open 2026-08-01) → traffic candidate-side ~0 trong gap 1 ngày
  - Admin UI hiện tại chỉ issue `confirm` action token (existing flow); BE expand `action_type` thêm capability, default behavior unchanged → không trigger submit/resubmit/withdraw URL gửi candidate
  - Email template 4 actions chưa exist → không có URL FE-404 nào gửi đi
- **RC8 mitigation**: sequential ship Day 2-3 BE → Day 4 FE; smoke verify Postman trong gap; không parallel ship.

---

## Memory updates planned (post-lock)

1. **Update** `memory/project_phase3_wave_b_closure.md` — add "Next session candidates" pointer tới `Documents/PHASE3_CLOSEOUT_PLAN.md` v1 (N3 — KHÔNG tạo 3 memory parallel, fold vào memory existing)
2. **NEW** `memory/project_phase3_closeout_plan.md` chỉ tạo nếu plan execute >1 session — defer
3. **Update** `MEMORY.md` index entry (1 dòng update existing)

---

## v0 → v1 changelog (2026-05-14 review-revised)

Reviewer feedback applied:

| Finding | Fix | Section |
|---|---|---|
| **C1** PR-CO-3 obsolete | Removed entirely; bug `admission_service.py:6310` already fixed in PR #234 `d8554bca`. Memory `resubmit-notes-none-bug` CLOSED | Triggers + Inventory + PR breakdown |
| **C2** Bundle 4 deploy success | Trigger #4 updated to RESOLVED; pre-condition ticked | Triggers + Pre-conditions |
| **C3** FE folder convention | Magic-link path corrected to `app/magic-link/[action]/[token]/page.tsx` (root, NOT in `(auth)/` group). Justification: `(auth)/` chứa session flows; existing `/confirm/[token]` is canonical root pattern | PR-CO-2-FE |
| **H1** Bundle naming misleading | Split PR-CO-4..7 → 3 PR theo nature: feat (PR-CO-3 DELETE audit), test (PR-CO-4 Casbin+atomicity), perf (PR-CO-5 CSV) | Inventory + PR breakdown |
| **H2** Day 0 wording mâu thuẫn | Reworded — Day 0 chỉ verify + DAILY_LOG entry, KHÔNG PR | Sequencing |
| **H3** Priority mismatch | Moot sau C1 | — |
| **H4** Q-CO-3 self-contradictory | Recommendation flipped A → B (split BE-first/FE-second) | Open questions |
| **H5** RC3 mitigation vague | Concrete budget <4 phút median, fallback matrix split nếu >6 phút | PR-CO-1 + Risk register |
| **H6** Memory `ci-workflow-flag-cross-file-sync` not invoked | Added cross-file grep node-version + cache-key check trong PR-CO-1 acceptance | PR-CO-1 |
| **H7** Day count inconsistency | Phân biệt rõ active dev (~3.6d) vs calendar (5-6d) | Sequencing |
| **N1** DAILY_LOG SHA refresh PR riêng cosmetic | Folded vào Day-0 checklist | Sequencing |
| **N2** Wave A vs B checklist overlap | Consolidated thành 1 checklist single gate "Magic-link 4 actions atomic" | Acceptance signoff |
| **N3** Memory phình | Update existing `phase3-wave-b-closure` thay vì tạo memory mới | Memory updates planned |
| **N4** Open Q chưa lock | Pre-condition checklist updated | Pre-conditions |

**Effort revised**:
- v0: ~3-4d active dev (10 items, 1.8d PR-CO-2 monolithic, 1d bundle)
- v1: ~3.6d active dev (10 items including dropped PR-CO-3 obsolete + split into 3 P2 PRs; total work unchanged since most items kept)
  - P0: PR-CO-1 0.3d + PR-CO-2-BE 1.2d + PR-CO-2-FE 0.6d = **2.1d**
  - P2 must: PR-CO-3 0.3d + PR-CO-4 0.5d = **0.8d**
  - P2 optional/defer: PR-CO-5 0.2d + PR-CO-6 0.5d = 0.7d (S1 nếu Q-CO-1=A, S2 nếu B)
  - P3 defer: PR-CO-7 0.2d

**Status**: v1 READY-TO-LOCK pending 3 open Q decisions từ user. Sau lock → execute Day 0 ngay.

---

## v1 → v2 changelog (2026-05-14 LOCKED)

3 open Qs locked với rationale ghi inline trên Open questions section:

| Q | LOCK | Effort impact |
|---|---|---|
| Q-CO-1 | **B** (PR-CO-6 defer S2) | S1 −0.5d → ~3.6d active dev (calendar 5-6d) |
| Q-CO-2 | **A** (3 PR split nature feat/test/perf) | +0.05d overhead 3 PR vs 1 bundle; gain granular rollback |
| Q-CO-3 | **B** (PR-3E BE-first → FE-second) | Wave A signoff +1d sớm; FE follow-up không block; gap risk 0 user-facing |

**S1 effort final post-lock**:
- P0 (must ship): PR-CO-1 0.3d + PR-CO-2-BE 1.2d + PR-CO-2-FE 0.6d = **2.1d**
- P2 must (S1): PR-CO-3 0.3d + PR-CO-4 0.5d = **0.8d**
- P2 deferred S1 → S2/Phase 4: PR-CO-5 0.2d (perf, defer Phase 4 OK) + PR-CO-6 0.5d (E2E, S2) = 0.7d
- P3 defer: PR-CO-7 0.2d

**S1 total active dev**: 2.9d (gọn hơn 3.6d quoted ban đầu vì PR-CO-5+6 defer)
**S1 calendar**: 4-5 working days với weekend reset
**Buffer remaining post-S1**: ~10.2w trước Wave A hard commit 2026-07-23

**Ready to execute Day 0**: ✅
