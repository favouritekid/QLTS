# Admission Refactor — Daily Log

**Branch:** `feat/admission-full-cutover` (parent integration)
**Started:** 2026-05-01
**Format:** append-only. Newest entries on top. Each day = 1 entry. Đừng edit entry cũ — sửa sai thì ghi entry mới đính chính.

**Mục đích:** audit trail trong window refactor (4-6 tuần). Sau cutover xong là full timeline.

---

## Hotfix policy (chốt 2026-05-02 — bắt buộc)

Production critical hotfix trong window refactor:

1. **Hotfix branch off `main`** (KHÔNG off `feat/admission-full-cutover`).
2. Implement + test + merge `main` → deploy production qua deploy gate.
3. **SAME-DAY cherry-pick hoặc equivalent-patch** SHA hotfix sang `feat/admission-full-cutover`. KHÔNG được defer sang cutover.
4. Append entry "Merged tới main (hotfix only)" với 3 SHA: main hotfix SHA → cherry-pick SHA → conflict notes (nếu có).
5. **Conflict touch admission core/state/lead/notification/RBAC** → **PAUSE refactor 0.5-1 ngày**, resolve conflict clean, re-test PASS rồi mới continue.
6. KHÔNG defer hotfix vào cutover bundle. Lý do: cutover sẽ replace toàn bộ codebase từ feat branch — nếu hotfix chỉ ở main mà chưa cherry-pick → cutover sẽ overwrite hotfix → bug production tái xuất.

**Equivalent-patch alternative** (khi cherry-pick không khả thi): hotfix touch file mà refactor đang rewrite từ đầu (e.g., `admission_service.py` mà task #16 sẽ refactor toàn bộ sang `admission_state_service.py`). Áp dụng equivalent-patch:
- Verify hotfix logic đã được áp dụng tương đương trong refactor feat branch (cùng-day audit, KHÔNG defer).
- Append DAILY_LOG entry: "hotfix equivalent-patched — main SHA → equivalent file:line trong feat branch + verification note".
- Test cover behavior hotfix bằng test mới hoặc existing trong feat branch.

KHÔNG được "defer to cutover" với bất kỳ lý do gì — cherry-pick hoặc equivalent-patch trong same-day, không có exception.

---

## Entry template (copy-paste khi thêm entry mới)

```markdown
## YYYY-MM-DD

**Merged hôm nay** (vào `feat/admission-full-cutover`):
- PR #N — task ID — short description (commit SHA)

**Merged tới main** (hotfix only — KHÔNG phải refactor):
- PR #N — main SHA → cherry-pick SHA → conflict notes if any

**Blocked / decisions cần:**
- task ID — blocker description — owner pending

**Tested / Rehearsed:**
- task ID — test result — link to CI run

**Tomorrow plan:**
- task ID — what & expected outcome

**Notes / surprises:**
- anything non-obvious worth remembering for post-mortem
```

---

## 2026-05-04

### #184 Phase 1 Schema Wave 1 PR-1B'-FE — admin form UI + BE governance SHIPPED

**PR**: [#207](https://github.com/favouritekid/QLTS/pull/207) merged squash `efb64ec8` (Wave 1 PR-1B'-FE — admin form UI 3 field + BE micro-patch).

**Parent advance**: `7aaed879` (tracker FE-zod-path drift fix) → `efb64ec8`.

**Codex round 5 P1+P2 catch + fix**:
- **P1** BE create_path silently drops 3 phase1_03 field (FE toast success nhưng DB null) → service dict thêm 3 field; convert `BonusRuleOverride` → JSONB dict.
- **P1** Manager governance bypass: guard chỉ cover `minor_correction_allowed_fields`, không cover 3 phase1_03 field → guard extend 4 admin-only field (create + update); reject (not silent-drop) với `BusinessRuleViolation`.
- **P2** `method_quota` decimal (1.5) → BE 400 → FE `Math.floor(parsed)`.
- **P2** `max_total_bonus` >10 → BE 400 → FE `Math.min(10, Math.max(0, parsed))` clamp.

**Scope shipped (7 file)**:
- FE: `admission-audience.ts` constants + i18n labels + 6-case test; `PathBasicInfo.tsx` extend 3 form section (audience checkbox grid, method_quota integer input, BonusRuleOverride toggle + 3 sub-field structured form, NEVER raw JSON editor) + 19-case payload builder test; `useAdmissionPaths.test.tsx` fixture extend.
- BE: `admission_path_service.py` create_path persist 3 field + 4-field governance guard (create + update); 18-case governance test.

**KHÔNG ship trong PR-1B'-FE** (defer):
- FE update form (chỉ extend create wizard).
- Manager API caller smoke test (defer pre-cutover manual Postman).
- Staging clone D12-D14 strict GIN auto-pick smoke (Wave 1 batch).

**Test result**:
- BE: 135 passed in 5.36s post-squash (PR-1B'-BE 117 + PR-1B'-FE 18 governance new).
- FE: 25 passed in 2.32s (6 audience constants + 19 payload builder). tsc 0 error.
- UI smoke Chrome MCP: 3 form section render với Vietnamese diacritics đầy đủ; toggle bonus override hiển thị 3 sub-field; console 0 error/warn.

**Tracker / board / issue**:
- TRACKER row M-1-03 + FE-form-path-admin → TESTED (cite PR + SHA + test evidence).
- Issue #184 body M-1-03 update với cả 2 PR (#206 + #207) cited.
- Board card #184 vẫn In Progress (3/29 sub-task done; 26 còn lại — Wave 1 còn PR-1C' + PR-1D, Wave 2/3/4/5 chưa start).

**Tomorrow plan** (Wave 1 còn 2 PR):
- **PR-1C'** (BE additive): `phase1_05_add_subject_kind_and_score_bounds` (subject_kind ENUM + 6-row seed: TB_HK1_L12, TB_HK2_L12, TB_CN_L12, DGNL_DHQGHN, V_ACT, IELTS) + `phase1_06_add_path_id_to_document_group` (3-tier resolution rule + service invariant). Off parent `efb64ec8`. Ước tính 0.5-1d.
- **PR-1D** (BE additive cuối Wave 1): `phase1_07b` (backfill_exceptions audit table) + `phase1_08` (uses_choice_engine flag) + `phase1_13` (system_config + admin endpoint + seed `current_intake_year=2026` — B4 P0 closer). Off parent post PR-1C'.

---

### #184 Phase 1 Schema Wave 1 PR-1B'-BE — phase1_03 SHIPPED

**PR**: [#206](https://github.com/favouritekid/QLTS/pull/206) merged squash `4547f881` (Wave 1 third sub-PR, post 4-round Codex supervising review).

**Parent advance**: `f344a6e3` (tracker drift repair) → `4547f881`.

**Q1/Q2/Q3 chốt 2026-05-04 sau Codex review**:
- Q1 `admission_round_id` ship Phase 1 hay 2? → **defer Phase 2** (Phase 1 chưa có `offering_admission_round` table → phantom field).
- Q2 Service duplicate check thay đổi? → **GIỮ NGUYÊN** (DB unique còn → bỏ service check biến `DuplicateResourceError` thành DB IntegrityError 500). Codex P1.
- Q3 FE split? → **Zod ship cùng BE PR (parse parity); UI form tách PR-1B'-FE riêng**. Codex P1.

**Codex round 4 catch + fix** (post-implementation, pre-commit):
- Source-grep tests passed nhưng `ARRAY(literal_column("admission_audience"))` fail compile với `AttributeError: '_variant_mapping'`.
- Fix: typed `_AUDIENCE_ARRAY_TYPE = postgresql.ARRAY(postgresql.ENUM(..., name="admission_audience", create_type=False))`.
- Compile probe verify: `@> CAST(ARRAY['POST_THPT'] AS admission_audience[])` + `&& CAST(...)` clean.
- Added 4 compile-dialect tests asserting `@>`/`&&`/`CAST AS admission_audience[]`/no `ANY` contract.

**Scope shipped**:
- Migration `phase1_03_add_applicable_to_method_quota_to_path.py`: ENUM `admission_audience` 5 values + `applicable_to admission_audience[]` nullable + `method_quota integer` nullable + GIN `ix_admission_path_applicable_to`.
- Model `admission_path.py`: 2 column wired (`bonus_rule_override` đã có từ phase1_02).
- Schema `admission_path.py`: `AdmissionAudience` Literal + typed `BonusRuleOverride` shape (`extra="forbid"`, range 0..10) + Create/Update/Response wire 3 field; Response REQUIRED no-default.
- Service `admission_service.py`: `applied_rules` Group 8 thêm 3 key đọc từ path attribute.
- Repository `admission_path_repository.py`: `list_paths_by_audience` (`@>`) + `list_paths_by_audiences_overlap` (`&&`). NEVER `.any()`. `include_legacy_null` Phase 3 cutover knob + OR NULL branch.
- Frontend Zod `admission-path.ts`: `admissionAudienceEnum` + `bonusRuleOverrideSchema.strict()` + 3 field wired.

**KHÔNG ship trong PR-1B'-BE** (per Q1/Q3):
- `admission_round_id` field (Phase 2 PR-2A).
- Bỏ duplicate check service-side (Phase 2 swap unique mới remove).
- FE form admin UI 3 field (PR-1B'-FE riêng off `4547f881`).

**Test result**:
- 117 passed in 6.54s (4 new file 59 case + 5 regression file 58 case `tests/unit/test_admission_path_*.py`).
- Re-run on parent post-squash `4547f881`: 117 passed in 6.82s — confirm squash collapsed cleanly.
- Live alembic upgrade `phase1_03` clean → schema applied.
- Live alembic downgrade `phase1_02` clean → column + index + enum dropped no orphan; `pg_type` không còn `admission_audience`.
- Re-upgrade idempotent.
- `uq_admission_path_offering_method` + `uq_admission_path_criteria_id` PRESERVED live verify.
- EXPLAIN smoke: dev DB nhỏ → Seq Scan (Codex P2 expected); `enable_seqscan=off` → `Bitmap Index Scan on ix_admission_path_applicable_to` (GIN reachable; auto-pick gate trên staging clone D12-D14).

**Tracker / board / issue**:
- TRACKER row M-1-03 → TESTED (PR + squash SHA + test evidence cited).
- Issue #184 body M-1-03 ticked `[x]` với PR + SHA + test result + Codex round 4 callout.
- Board card #184 vẫn In Progress (3/29 sub-task done; 26 còn lại).

**Tomorrow plan**:
- Tùy user chốt 1 trong 2 path:
  - **PR-1B'-FE-UI** (admin form 3 field — audience multi-select + method quota input + BonusRuleOverride structured form, KHÔNG raw JSON editor per Codex P2). Off parent `4547f881`. Branch `feature/admission-184-pr-1b-fe`.
  - **PR-1C'** (Wave 1 thứ 4 BE): `phase1_05_add_subject_kind_and_score_bounds` (subject_kind ENUM + 6-row seed) + `phase1_06_add_path_id_to_document_group` (3-tier resolution rule). Off parent `4547f881`.

---

## 2026-05-03

### #184 Phase 1 Schema — preflight chốt + Wave 1 start

**6-question chốt user 2026-05-03 (post-CI-tooling merge):**

| # | Question | Answer | Rationale |
|---|---|---|---|
| Q1 | Wave order | **C — start small** | Ship Wave 1 (8 active migrations) first; eval pace + scope before committing Wave 2-6. Avoids scope creep on multi-week project. |
| Q2 | Naming collision `phase1_19b` (casbin shipped vs spec event catalog seed) | **A — rename + push down** | spec's `phase1_19b` event catalog seed → `phase1_19c`; spec's `phase1_19c` celery beat → `phase1_19d`; spec's `phase1_19d` notification rules → `phase1_19e`. PLAN deviation log Phần 9 cite. |
| Q3 | `phase1_XX` slot assignments | **`phase1_13`** = system_config (PATCH-14); **`phase1_16`** = archived_admission_profile (PATCH-20); **`phase1_17`** = archived_outbox (PATCH-20) | All 4 slots (13/14/15a/16/17/18) verified free via `alembic ScriptDirectory.walk_revisions()` audit. `phase1_14` left free as future-reserve gap. |
| Q4 | Soak window Wave 4 (Lead 1-many) | **A — accept 3w wall-clock** | Spec line 3468-3473 mandate 1w soak between 15a / 15b / 15c. Total wall-clock ≈ 3 weeks. Accepted because Lead-Profile relationship change is structurally breaking; rollback-able per stage outweighs faster ship. |
| Q5 | Production rehearsal Wave 3 ONE-WAY | **Verify D12-D14 staging clone ready BEFORE Wave 3 ship** | Wave 3 has 4 ONE-WAY migrations (`phase1_11`, `phase1_15a`, `phase1_18`, `phase1_12` backfill). Staging clone with prod DB shape required for rehearsal; ops sign-off gate before prod deploy per RUNBOOK §7.2. |
| Q6 | Start Wave 1 now? | **A — start now** | Implementer begins Wave 1 preflight + sub-PR split proposal in this session; Wave 1 ship may complete this session if pace allows. |

**Branch / Setup:**
- Continue on parent `feat/admission-full-cutover` HEAD `d1f38725` (post-CI-tooling tracking).
- No code changes yet — preflight only.
- PLAN deviation log Phần 9 added new sub-section "#184 Phase 1 Schema — slot assignments + naming deviations" with the Q2/Q3 chốt + audit-empty evidence.

**Wave 1 sub-PR split — proposed (3 PRs)**:

| PR | Migrations | Scope | Effort |
|---|---|---|---|
| **PR-1A** "Major program + Method/Path schema additive" | `phase1_01` (degree_level FK to major_program) + `phase1_02` (bonus_rule on method + path) | 2 simple `add_column` migrations; no BE/FE work | ~2-3h |
| **PR-1B** "Path advanced features + subject kind seed" | `phase1_03` (applicable_to + method_quota on path; **+ BE schema + service + FE Zod**) + `phase1_05` (subject_kind + score bounds; **+ seed 6 subject ảo TB_HK1_L12, DGNL_DHQGHN, …**) + `phase1_06` (path_id FK on document_group; 3-tier resolution) | 3 migrations + BE schema + FE Zod + 6-row seed | ~5-6h |
| **PR-1C** "Audit table + Profile flag + System config" | `phase1_07b` (backfill_exceptions audit table) + `phase1_08` (choice_engine flag on profile) + `phase1_13` (system_config + admin endpoint UPDATE + seed `current_intake_year=2026`) | 3 migrations: 2 simple + 1 with admin endpoint | ~3-4h |

**Total Wave 1 effort estimate**: 10-13h ≈ 1.5-2 ngày làm việc.

**Alternative split (4 PRs)** — split heavy PR-1B further:
- PR-1A: phase1_01 + phase1_02 (simple)
- PR-1B': phase1_03 only (heavy — BE + FE)
- PR-1C': phase1_05 + phase1_06 (subject seed + document_group)
- PR-1D: phase1_07b + phase1_08 + phase1_13 (audit + profile + config)

Trade-off: smaller PRs (~2-3h each) vs more review cycles.

**Pending user chốt before code starts:** ~~3-PR vs 4-PR split~~ → user chốt **4-PR split** 2026-05-03.

### #184 Wave 1 PR-1A — phase1_01 + phase1_02 (TESTED, merged 2026-05-03)

**Branch / Commit / PR:**
- Branch `feature/admission-184-pr-1a` off parent `2864df20` (preflight tracking).
- PR [#205](https://github.com/favouritekid/QLTS/pull/205) — `[#184 Wave1] feat(schema): phase1_01 degree_level FK + phase1_02 bonus_rule` — squash `a50cdb79` (mergedAt `2026-05-03T14:55:56Z`, mergedBy `favouritekid` via `gh pr merge 205 --squash --delete-branch=false`). Parent advanced `2864df20 → a50cdb79`.
- Pre-merge: 2 commits collapsed (impl `83d05150` + docs sync `b493604a`) → 1 squash commit on parent.
- 2 migrations + 3 model updates + 1 unit test file.

**Migrations shipped:**
1. `phase1_01_add_degree_level_fk_to_major_program.py`
   - `revision='phase1_01'`, `down_revision='phase1_19b'` (chronological chain).
   - ADD COLUMN `major_program.degree_level_id INT NULL FK → config_degree_level.id ON DELETE SET NULL`.
   - Index `ix_major_program_degree_level_id` on FK column.
   - Backfill SQL: JOIN `lower(trim(name))` between legacy text + config table; per-row idempotent guard `WHERE degree_level_id IS NULL`.
   - Legacy `major_program.degree_level` text column STAYS — Phase 4 retire later.
2. `phase1_02_add_bonus_rule_to_method_and_path.py`
   - `revision='phase1_02'`, `down_revision='phase1_01'`.
   - ADD COLUMN `admission_method.default_bonus_rule JSONB NULL`.
   - ADD COLUMN `admission_path.bonus_rule_override JSONB NULL`.
   - Pure additive — no backfill. Existing rows keep NULL = bonus disabled fallback per the precedence rule (PLAN line 787-789).

**Model updates** (ORM parity với schema):
- `MajorProgram.degree_level_id` (FK) added; legacy `degree_level` text comment updated to mark Phase 4 retire candidate.
- `AdmissionMethod.default_bonus_rule` (JSONB) added with precedence-rule comment.
- `AdmissionPath.bonus_rule_override` (JSONB) added with precedence-rule comment.

**Tested / Rehearsed:**
- Live dev DB roundtrip on parent branch HEAD: `alembic upgrade head` `phase1_19b → phase1_01 → phase1_02` clean; both columns + FK + index verified via `information_schema.columns`.
- Backfill verified: 12 "Cao đẳng" + 8 "Trung cấp" rows correctly mapped to FK ids (22, 21).
- Downgrade roundtrip: `alembic downgrade phase1_19b` → 0 columns left → re-upgrade `head` → 3 columns back. Symmetric.
- Unit test `tests/unit/test_phase1_01_02_revision_chain.py`: **20 passed (0.98s)** locks: revision id + down_revision chain + linear (no branch labels) + idempotency guard substring + JSONB type + ORM model parity (FK column, JSONB columns, nullable=True) + downgrade DDL order + sanity upgrade/downgrade callables.
- Live: AST lint 0 violations across 148 files; coverage script `--allow-deferred` exit 0 (no admission status / event surface touched in PR-1A).

**Pending:**
- Tick `[x] **M-1-01**` + `[x] **M-1-02**` on issue #184 sub-task list.
- Start PR-1B' (`phase1_03` path advanced + BE schema + service + FE Zod) off updated parent `a50cdb79`.

**Post-merge verification on parent HEAD `a50cdb79`:**
- `alembic current` → `phase1_02 (head)` ✓
- Target test re-run: **20 passed (1.00s)** — same 20 case as PR run; confirms squash collapsed cleanly with no test drift.

---

### CI-tooling — patterns 1.3/1.4 + namespace collision + GH Action + pre-commit (TESTED, merged 2026-05-03)

**Branch / Commit / PR:**
- Branch `feature/admission-ci-tooling` off parent `d5a01ba8` (post-#16 tracking).
- PR [#204](https://github.com/favouritekid/QLTS/pull/204) — `[CI tooling] feat(ci): admission-contract-check — patterns 1.3/1.4 + namespace collision + GH Action + pre-commit` — squash `64314f0f` (mergedAt `2026-05-03T12:55:12Z`, mergedBy `favouritekid` via `gh pr merge 204 --squash --delete-branch=false`). Parent advanced `d5a01ba8 → 64314f0f`.
- Self-test workflow GREEN on the PR (first live run of `admission-contract-check.yml` on the very PR shipping it): `status-assignment` job 11s + `notification-coverage` job 44s; mergeStateStatus flipped UNSTABLE → CLEAN before merge.
- Atomic 1-PR per user chốt — wraps CI-status + CI-event + CI-workflow + pre-commit hook to share 1 review cycle and avoid intermediate parent state where one extension landed without the integration glue.

**Scope (3 of 3 CI rows on issue #183):**

1. **CI-status** — extend `app/scripts/check_status_assignment.py` to spec line 103-109 closure:
   - Pattern 1.3 (`__setattr__` AST detector) — `<alias>.__setattr__("status", value)`.
   - Pattern 1.4 (regex grep fallback) — 2 separate patterns for `setattr(<expr>, "status", ...)` (3-arg form) vs `<obj>.__setattr__("status", ...)` (2-arg bound form). Smart de-dupe via `ast_caught_lines | ast_rejected_lines` set; AST-inspected-but-rejected lines (e.g. `setattr(fee, "status", "paid")` where `fee` is recognized non-admission) are suppressed so the regex over-broad doesn't flag every Fee/User/ZaloDelivery `.status` write.
   - `.contract-allowlist.yaml` config file (spec line 109) at `Backend_FastAPI/.contract-allowlist.yaml`. Loaded at module init via `_load_config()`; falls back to hardcoded constants when YAML missing/malformed (warning printed to stderr).
   - Allow-list expanded from 1 entry (`admission_state_service.py`) to 5: `admission_state_service.py` + `alembic/versions/*.py` + `tests/*.py` + `tests/*/*.py` + `tests/*/*/*.py` (Python's fnmatch doesn't support `**` recursive — patterns spell each depth level explicitly per the actual repo layout).

2. **CI-event** — extend `app/scripts/check_notification_event_coverage.py`:
   - `_scan_dual_namespace_pairs()` AST walker — finds enclosing FunctionDef / AsyncFunctionDef / class methods that dispatch BOTH an `APPLICATION_*` event AND an `ADMISSION_*` event in their body.
   - `_print_dual_namespace_pairs()` reporter — default `strict=False` mode emits informational `warn` block to stderr + returns 0 (Phase 1 ships dual dispatch on purpose); `--strict-namespace` flag elevates each pair to a hard failure (Phase 4 retire flip).
   - Plumbed into `main()` after the existing per-event verdict so dual-namespace report sits beside the deferred-events report.

3. **CI-workflow** — `.github/workflows/admission-contract-check.yml` (new):
   - Triggers on push/PR touching `app/services/admission*.py`, `app/services/notification*.py`, `app/core/events*.py`, `app/core/event_catalog.py`, `app/core/notification_seed_defaults.py`, `app/scripts/check_*.py`, `.contract-allowlist.yaml`, or the workflow itself.
   - Two parallel jobs: `status-assignment` (just imports PyYAML + std-lib so installs minimal deps) + `notification-coverage` (full requirements + requirements-dev because the script imports the full app.core / app.models / app.services chain).
   - Coverage job uses the 4-event `--allow-deferred` set locked by `state_service.DEFERRED_ADMISSION_EVENTS`.

4. **Pre-commit hook** — `.pre-commit-config.yaml` (new):
   - 2 `local` hooks mirroring the GH Action commands.
   - Both `pass_filenames: false` because the scripts walk the whole tree, not individual file paths.
   - File-path filter regex matches the same surface as the GH Action `paths:` triggers.

**Tested / Rehearsed:**
- Target 5 file pytest: **83 passed (4.70s)** pre-merge → **83 passed (4.00s)** post-merge re-run on parent HEAD `64314f0f` (confirms squash collapsed cleanly) — `test_check_status_assignment.py` (43 case post-extension; previously 28 + 15 new for Pattern 1.3 / 1.4 / YAML config / glob coverage), `test_admission_state_service.py` (14 case unchanged), `test_admission_state_service_event_mapping.py` (10 case unchanged), `test_check_notification_event_coverage_deferred.py` (7 case unchanged), `test_check_notification_event_coverage_namespace.py` (9 case new — DualNamespacePair shape, default-mode warn vs strict-mode fail, AST walker on dual / single / nested / non-admission-legacy fixtures, live scan integration on the actual codebase confirming the submit-router cohabitation pair).
- Live: AST lint 0 violations across 148 scanned files (exit 0).
- Live: coverage script with `--allow-deferred` (default mode): exit 0; reports 1 dual-namespace pair (`submit_admission_profile` router) as informational warning.
- Live: coverage script with `--allow-deferred --strict-namespace`: exit 1 (1 cohabitation pair elevated to FAIL — confirms the Phase 4 flip path).
- Post-merge bite-verify on parent HEAD `64314f0f`: lint exit 0 (148 files clean) + coverage default exit 0 + coverage `--strict-namespace` exit 1 — all 3 modes match pre-merge expectations.

**Pending:**
- ~~(After this entry commits) tick `[x] **CI-status**`, `[x] **CI-event**`, `[x] **CI-workflow**` checkboxes on issue #183.~~ DONE — all 7 thematic checkboxes ticked.
- ~~Verify card #183 moves `In Progress → Done`.~~ Verified: 7/7 ticked, "Done when" criteria met, BUT issue #183 + card stay OPEN / `In Progress` per user chốt 2026-05-03 — keeping the thematic line available for future Phase 1-related work that depends on the existing tooling (e.g. follow-on extensions atop this scaffolding). When user decides to close, board auto-archives → card → Done.

---

### #16 — admission_state_service.py + 11 caller refactor (TESTED, merged 2026-05-03)

**Branch / Commit / PR:**
- Branch `feature/admission-issue-16` off parent `3f7ead4d` (post-#15 tracking).
- PR [#203](https://github.com/favouritekid/QLTS/pull/203) — `[#16] refactor(admission): centralize status transitions + wire admission events` — squash `a7b6c5c9` (mergedAt `2026-05-03T11:33:39Z`, mergedBy `favouritekid` via `gh pr merge 203 --squash --delete-branch=false`). Parent advanced `3f7ead4d → a7b6c5c9`.
- Pre-merge fix landed via `aca9f83c` (transition() dedupe key includes `:v{post_version}` suffix; legal cycle `rejected → resubmitted → rejected` regression test added) — collapsed into the squash SHA above.
- Atomic 1-PR per user chốt — avoids unused transition service intermediate state + parent state where caller refactor lands but coverage/lint truth doesn't.

**Scope (8 of 12 ADMISSION_* events wired; 4 deferred to Phase 3):**

| Site | Status | Event (T#) | Outbox |
|---|---|---|---|
| `submit_and_evaluate` (router-level dispatch helper) | submitted | `ADMISSION_PROFILE_SUBMITTED` (T1) | ❌ |
| `request_revision` | revision_requested | `ADMISSION_REVISION_REQUESTED` (T3/T4) | ❌ |
| `resubmit_profile` | resubmitted | `ADMISSION_RESUBMITTED` (T5) | ❌ |
| `approve_profile` + `bulk_approve` | approved | `ADMISSION_DECISION_ADMITTED` (T7) | ✅ |
| `reject_profile` + `bulk_reject` | rejected | `ADMISSION_DECISION_REJECTED` (T9) | ✅ |
| `override_profile` | overridden | `ADMISSION_DECISION_ADMITTED` (T7) + `override=true` payload | ✅ |
| `verify_and_confirm` (magic-link) | confirmed | `ADMISSION_CONFIRMED` (T12) | ❌ |
| `enroll_student` | enrolled | `ADMISSION_ENROLLED` (T13) | ✅ |
| `withdraw_profile` | withdrawn | `ADMISSION_WITHDRAWN` (T14/T15/T16) | ❌ |

11 write sites → 9 transition() entries → 8 distinct events (approved + overridden share T7). T7 outbox-event dedupe key uses `new_status` (`admission:{id}:approved` vs `admission:{id}:overridden`) so the two routes get distinct outbox rows.

**Deferred (4 events, --allow-deferred set):**
- `ADMISSION_RESULT_PUBLISHED` (T6) — admin batch broadcast endpoint not yet shipped
- `ADMISSION_DECISION_WAITLISTED` (T8) — choice-engine waitlist write not yet shipped
- `ADMISSION_WAITLIST_PROMOTED` (T10) — promote-from-waitlist endpoint not yet shipped
- `ADMISSION_ROLLED_BACK` (T17) — admin rollback path semantically distinct from legacy `overridden`; defers to Phase 3 dedicated endpoint

**Implementation:**

1. **`app/services/admission_state_service.py`** (new) — single mutation point. `transition()` validates via state machine, captures old_status, writes status+version+updated_at+extra_fields, calls audit_service.log_status_change (skip via `skip_audit=True` for override path which writes log_changes), dispatches mapped ADMISSION_* event via `dispatch_event()`. Returns `(profile, post_commit_callback)`. Public exports: `transition`, `LEGACY_STATUS_TO_EVENT` (9 entries), `DEFERRED_ADMISSION_EVENTS` (4 entries frozenset).

2. **Coverage-script anchor docstring** (`_DISPATCH_ANCHORS`) — the script greps `event=SystemEvents.<NAME>` line literals; `transition()` resolves the event from a mapping dict so the call site reads `event=event` (variable). The anchor docstring repeats each mapped event's literal form so the grep finds them. Parity locked by `tests/unit/test_admission_state_service_event_mapping.py`.

3. **`app/services/admission_service.py`** — 11 sites refactored. All direct `profile.status = ...` writes replaced with `await state_transition(...)`. Caller-specific extra_fields (`approved_at`/`approved_by_id`/`rejection_reason`/etc.) flow through the helper's `extra_fields` arg. Local `from ..services import audit_service` + `await audit_service.log_status_change(...)` blocks removed (transition() handles audit). Override site keeps its richer `log_changes` audit row (broader change-set per ADM-014); transition() called with `skip_audit=True` to avoid duplicate audit row.

4. **`app/routers/admissions.py`** — added `safe_dispatch(ADMISSION_PROFILE_SUBMITTED)` next to existing `safe_dispatch(APPLICATION_STATUS_CHANGED)` for the submit flow because `submit_and_evaluate` returns a dict (not the V3 `(result, callback)` tuple) and has no callback channel — the service uses `skip_dispatch=True` and the matching ADMISSION_* event fires from the router after `db.commit()` (same fire-and-forget semantics as the legacy bundle).

5. **`app/scripts/check_notification_event_coverage.py`** — new `--allow-deferred` flag with strict semantics:
   - Each name MUST exist in SystemEvents (typo → fail)
   - Each name MUST have EXACTLY the single gap `no-dispatch-site` (wired or extra-gap → fail)
   - Verdict prints `Deferred (allow-listed)` block listing each deferred event so the gap stays visible
   - Allow-list never silences `raw-dispatch-of-outbox-event` or `rule-has-zero-actions`

6. **`app/scripts/check_status_assignment.py`** (new) — AST lint blocking direct `profile.status = ...` writes outside `app/services/admission_state_service.py` allow-list. Detects three patterns: direct assignment, augmented assignment (`+=`), and dynamic `setattr(<alias>, "status", ...)`. Restricted to leftmost-name `ADMISSION_PROFILE_VAR_NAMES` covering 6 aliases — `profile` (canonical, all 11 legacy sites use this), plus `locked_profile`, `admission_profile`, `current_profile`, `profile_row`, `prof` (forward-prevention; codebase audit 2026-05-03 confirmed zero existing alias write sites). Restriction avoids false positives on Fee/User/ZaloDelivery `.status` writes. Initial run pre-restriction reported 5+ false positives across services tree; post-restriction: **0 violations** across 148 scanned files.

**NOT wired in #16** (per user chốt §5):
- Pre-commit hook integration → defers to TRACKER #183 row CI-tooling.
- Github Action workflow `admission-contract-check.yml` → same.

**Tested / Rehearsed:**
- Target 4 file pytest: **51 passed (2.74s)** baseline → **58 passed (3.24s)** post-alias-extension → **59 passed (2.28s)** post-dedupe-key — `test_admission_state_service.py` + `test_admission_state_service_event_mapping.py` + `test_check_status_assignment.py` + `test_check_notification_event_coverage_deferred.py`.
- Post-merge re-run on parent HEAD `a7b6c5c9`: **59 passed (1.86s)** — same 4 file. Confirms squash collapsed cleanly without test drift.
- Post-merge AST lint live: 0 violations across 148 files (exit 0).
- Post-merge coverage script live with `--allow-deferred=ADMISSION_RESULT_PUBLISHED,ADMISSION_DECISION_WAITLISTED,ADMISSION_WAITLIST_PROMOTED,ADMISSION_ROLLED_BACK`: exit 0 (8 wired + 4 deferred allow-listed).
- Lint script live: 0 violations across 148 scanned files (`scan()` exit 0).
- Coverage script live: with `--allow-deferred=ADMISSION_RESULT_PUBLISHED,ADMISSION_DECISION_WAITLISTED,ADMISSION_WAITLIST_PROMOTED,ADMISSION_ROLLED_BACK` → exit 0, 8 events ok + 4 events deferred (allow-listed).
- Wide unit + integration regression: **1768 passed + 8 pre-existing fail + 1 deselected** in 247s. 8 fail + 1 deselected verified pre-existing on parent `3f7ead4d` (stash + re-run identical) — same notification surface debt + zalo phase 1 debt + immediate-fixes debt category as #15.
- Service tests `tests/services/test_admission_service.py` + `test_admission_quota.py`: **45 errors at fixture setup** verified PRE-EXISTING on parent `3f7ead4d` (stash + same single test errors with same fixture marker). Memory `[test-debt-admission-workflow-e2e]` covers a subset (6 known); the broader 45 erroring tests are pre-existing finance fixture / dirty-state / Casbin drift debt — out of #16 scope per ATOMIC_PR rationale.

**Pending:**
- (After this entry commits) tick `[x] **#16**` checkbox on issue #183 thematic line.
- Project board card #183 (`[Phase 1 Code]` thematic) stays in `In Progress` until the 3 CI tooling rows close (gates B1+B2+#15+#16 done; CI-status + CI-event + CI-workflow remain).
- Follow-up: open `test-debt/admission-fixture-isolation` PR (fixture race / `DeadlockDetectedError` + `pipeline_stage_order_key` UniqueViolation) — pre-existing per memory `[test-debt-admission-workflow-e2e]` 2026-04-30; broader scope than the 6-failure subset memory tracks. Update memory with the broader scope after the cleanup PR ships.

---

### #15 — choice-engine status bridge (TESTED, merged 2026-05-03)

**Branch / Commit / PR:**
- Branch `feature/admission-issue-15` off parent `f382bc6b` (B1 post-merge tracking).
- PR [#202](https://github.com/favouritekid/QLTS/pull/202) — `[#15] feat(admission): choice-engine status bridge — helpers + lead-sync forward-compat` — squash `e3b09eaa` (mergedAt `2026-05-03T08:52:13Z`, mergedBy `favouritekid` via `gh pr merge 202 --squash --delete-branch=false`). Parent advanced `f382bc6b → e3b09eaa`.
- 13 files changed, 789 insertions(+), 27 deletions(-): 3 file mới (`app/utils/admission_status.py` + 2 test) + 7 file sửa (`lead_admission_sync.py`, `lead_profile_sync.py`, `phase_manager.py`, `admission_service.py`, `admission_tasks.py`, `routers/fees.py`, `tests/integration/test_lead_admission_sync.py`) + 3 doc sync (`ADMISSION_DAILY_LOG.md`, `ADMISSION_IMPLEMENTATION_TRACKER.md`, `ADMISSION_REFACTOR_PLAN.md`).
- Strict scope ship qua reviewer: helpers + map extension + caller refactor read-only. KHÔNG đụng profile.status write site, DB CHECK constraint, /api/v2 wiring, Casbin diamond, hoặc CommissionRecord/LeadClaim non-admission "approved". (Exception: 1 audit-log fix — capture pre-transition status in `verify_and_confirm` so choice-engine ``admitted`` profiles don't get logged as ``approved``; the actual ``profile.status = "confirmed"`` write site stays untouched.)

**User chốt 7 deviation từ PLAN line 3380-3395 (matrix sau prod audit qlts.tnpc.edu.vn):**
| # | Quyết định | PLAN nguyên gốc | User chốt | Lý do |
|---|---|---|---|---|
| 1 | `admitted →` | sts09 | **sts09** ✓ | UNAMBIGUOUS — same as legacy approved. |
| 2 | `reviewing →` | sts06 | **sts07 (floor)** | sts06 = consultation phase pre-submission; reviewing = officer xét hồ sơ ĐÃ NỘP → MUST ở admission phase sts07. PLAN sts06 sẽ regress lead, vi phạm pipeline forward-only. |
| 3 | `waitlisted →` | sts06 | **sts07 (floor)** | Same logic — đã nộp + xét + chờ ghế → admission phase sts07. |
| 4 | `result_published →` | sts09 (PLAN list as map entry) | **explicit no-op** | Future intermediate state / T6 broadcast marker, không phải per-profile mutation. Not added to MAP; sync function short-circuits với `_RESULT_PUBLISHED_NO_OP` sentinel. |
| 5 | `is_admitted_like()` set | (PLAN spec) | **{approved, overridden, admitted}** ✓ | Khớp PLAN spec. |
| 6 | `LOCKED_PROFILE_STATUSES` | (silent) | **+ "admitted"** | Forward-compat; identity field freeze at admitted state. |
| 7 | `PHASE_STATUSES` | (silent) | **không thêm** | PHASE_STATUSES map LeadPhase→consultation_status_id (sts0x), KHÔNG dùng profile.status. Out of scope. |

Prod audit evidence (qlts.tnpc.edu.vn via SSH 2026-05-03):
- 9 hồ sơ tổng (8 draft + 1 submitted). 0 approved/confirmed/enrolled. Risk dữ liệu ≈ 0.
- DB CHECK `ck_admission_profile_status` chấp nhận 10 status legacy; KHÔNG có `admitted/reviewing/waitlisted/result_published`. Forward-compat strict.
- consultation_status seed khớp 100% CSV; sts06 = consultation phase stg02, sts07 = admission phase stg03 — confirm sự khác biệt semantic giữa PLAN sts06 vs đề xuất sts07.

**Floor rule design (regress prevention):**
- `FLOOR_FROM_PROFILE_STATUSES = frozenset({"reviewing", "waitlisted"})` — hai status này chỉ FLOOR UP lead từ pre-application; KHÔNG được DOWN-grade lead đã ở sts07+.
- `PRE_APPLICATION_LEAD_STATUSES = frozenset({None, sts00, sts02, sts03, sts04, sts05, sts06})` — 6 consultation status + NULL. Universal sts01/sts15/sts19 KHÔNG include (chúng overlay underlying pipeline_stage có thể đã ở sts07+; flooring sẽ đè).
- Pure decision rule `_should_apply_admission_floor()` testable không cần DB; non-floor status passthrough → existing logic không thay đổi.
- Lý do thiết kế này (so với raw PLAN sts06): Pipeline progression đi 1 chiều CONSULTATION → ADMISSION → FEE → ENROLLED. Nếu lead đã ở sts09 (Đủ điều kiện) hoặc sts10 (Đã đóng học phí) mà profile transient back về `reviewing` (ví dụ admin re-evaluate), KHÔNG được phép kéo lead về sts07. Floor rule preserve later state.

**Codex reviewer Patch round (Pre-push):**
- Patch P1 — split `is_admitted_like` vs `is_confirmation_eligible`:
  - User flagged: `is_admitted_like(profile)` áp dụng cho TẤT CẢ 4 magic-link site (send_confirmation, generate_confirmation_token, get_token_info, verify_and_confirm) sẽ accept `overridden` profile vào confirmation flow. **NHƯNG state machine route `overridden → enrolled` direct, bypass `confirmed`** — không có successor state cho overridden+confirmed pair.
  - Patch: thêm `CONFIRMATION_ELIGIBLE_STATUSES = frozenset({"approved", "admitted"})` + helper `is_confirmation_eligible()`. 4 magic-link site swap sang helper mới. 5 site khác (eligibility, minor_correction permission/state/whitelist, calculate_fee, fee_calc_authorized) giữ `is_admitted_like` (overridden vẫn là admitted-like cho phase/fee/quota/read).
  - Test lock invariant `CONFIRMATION_ELIGIBLE_STATUSES < ADMITTED_LIKE_STATUSES` + delta = `{overridden}`.
- Patch P2 — wording về `result_published`: replace "not a status" → "future intermediate state / T6 broadcast marker; explicit no-op for lead sync" trong helper module + sync module + 2 test docstring + integration test docstring.

**Tested / Rehearsed:**
- Target 3 file pytest: **232 passed, 6 warnings (137.45s)** — `tests/unit/test_admission_status_helpers.py` + `tests/unit/test_lead_admission_sync_extended_map.py` + `tests/integration/test_lead_admission_sync.py`. (Per-file breakdown intentionally omitted — total reflects the single-shot run; rerun with `-v` if per-file counts needed.)
- Post-merge re-run on parent HEAD `e3b09eaa`: **232 passed, 6 warnings (136.56s)** — same 3 file. Confirms squash collapsed cleanly without test drift; parent test green.
- Wide unit + service regression (admission/status/phase/confirmation/magic_link keyword filter): **705 passed + 2 failed** trong 73s. 2 failed = pre-existing zalo_phase1_review_findings (verify trên parent f382bc6b stash → cùng 2 fail).
- Full unit + service regression: **1697 passed + 8 failed + 1 deselected + 1 skipped** trong 237s. 8 fail + 1 deselected = pre-existing trên parent (stash + re-run trên `f382bc6b` cho cùng test list ra **8 failed + 19 passed** trong 1.90s), bằng chứng:
  ```
  tests/unit/test_channel_normalization.py::TestCanonicalChannelsConstant::test_contains_four_values
    AssertionError: assert frozenset({'b...', 'zalo_bot'}) == {'browser', '...', 'sms', 'zalo'}
  tests/unit/test_dispatcher_per_action.py::TestBuildActionSnapshot::test_inherit_default
    AssertionError: assert None == '/default'
  tests/unit/test_entrypoint_ordering.py::TestEntrypointOrdering::test_alembic_before_sync
    AssertionError: alembic must run before sync
  tests/unit/test_notification_e2.py::TestRenderTemplateSnapshot::test_render_from_template
    AssertionError: assert None == '/leads/42'
  tests/unit/test_notification_e2.py::TestCRUDIntegration::test_create_rule_with_invalid_template_code_raises
    AssertionError: Regex pattern did not match.
  tests/unit/test_notification_e2.py::TestCRUDIntegration::test_create_rule_without_template_code_passes_validation
    BadRequest: Unknown event 'LEAD_ASSIGNED'
  tests/unit/test_zalo_phase1_review_findings.py::test_confirm_token_dispatches_only_application_status_changed
    TypeError: tracking_dispatch() got an unexpected keyword argument 'rooms'
  tests/unit/test_zalo_phase1_review_findings.py::test_application_deleted_seed_rule_exists
    KeyError: 'channels'
  ```
  Plus 1 deselected: `tests/unit/test_immediate_fixes.py::TestConsultationCascadeDispatch::test_all_admission_transitions_have_dispatch` (verified pre-existing trên parent stash run).
- Note vs `[test-debt-admission-workflow-e2e]` memory record (6 known failure): các 8 failure ở đây thuộc category KHÁC (notification surface debt + zalo phase 1 debt + immediate-fixes debt), KHÔNG overlap với 6 e2e finance/casbin/dirty-state failure. 8 + 9 thực tế là 2 lớp test debt riêng biệt, đều pre-existing không do #15.

**Pending:**
- (After this entry commits) tick `[x]` checkbox `#15` trên issue #183.
- Project board status comment / Mức 1 thematic kanban — card #183 stays in `In Progress` until #16 + CI tooling close (gates B1+B2 done; #15 done; #16 + CI remain).
- #16 next code task — chờ user OK trước khi start (do NOT auto-start per SOP).

---

### B2.4 / T0-4b — sub-PR merged (post-merge sync)

**Sub-PR merged today (vào `feat/admission-full-cutover`):**
- PR [#200](https://github.com/favouritekid/QLTS/pull/200) — `[B2.4/T0-4b] feat(notification): replace outbox skeleton with real worker` — squash `737eb1bc` (mergedAt `2026-05-03T03:40:37Z`). Parent advanced `87685ff4 → 737eb1bc`.

**Tested / Rehearsed:**
- Post-merge full notification regression on parent HEAD `737eb1bc`:
  ```
  pytest tests/unit/test_outbox_worker.py \
         tests/unit/test_outbox_skeleton.py \
         tests/unit/test_dispatch_event_wrapper.py \
         tests/unit/test_coverage_script_raw_dispatch.py \
         tests/unit/test_notification_outbox_model.py \
         tests/unit/test_notification_contract.py \
         tests/unit/test_b2_1_admission_milestone_events.py \
         tests/unit/test_celery_task_registry.py \
         tests/api/test_notification_event_groups_api.py -q
  → 177 passed, 1 skipped in 58.95s
  ```
- Coverage invariant: `raw_violations=0`, `no_dispatch=12`, `outbox=7`, `outbox_raw_sites=[]`. The 12 `no-dispatch-site` gaps remain expected until #16 wires `state_service.transition()` callers.
- Alembic head unchanged: `phase1_19a (head)`.

**Tracker / board:**
- TRACKER: T0-4b → TESTED; B2 → TESTED; B2 blocker row CLOSED / TESTED.
- Issue #183: `[x] **B2**` ticked after post-merge sync; card #183 stays In Progress because B1, #15, #16 and CI tooling remain open.
- Task 0 card #181 can move to Done only after the team accepts TESTED-with-staging-smoke-pending as board Done; otherwise keep In Progress until D12-D14 staging smoke.

**Next:**
- **Start B1 — Casbin deny-first.** #16 remains blocked until B1 + B2 are both TESTED; #15 can follow B2 but the agreed sequence remains B2.1 → B2.4 → B1 → #15 → #16.

**Sub-PR merged today (vào `feat/admission-full-cutover`):**
- PR [#197](https://github.com/favouritekid/QLTS/pull/197) — `[ADM-B2.1] feat(notification): 12 ADMISSION milestone events catalog + group + seed` — squash `df2111a9` (mergedAt `2026-05-03T00:05:57Z`, mergedBy `favouritekid` via `gh pr merge --squash --delete-branch=false`). Parent advanced `910d2c4d → df2111a9`.

**Scope landed:**
- 4-file notification surface sync: `events.py` (12 new `SystemEvents` enum) + `event_catalog.py` (12 `EVENT_CATALOG` entries, `EventDefinition` extended với `requires_outbox` + `bypass_consent_check` defaults `False`) + `event_groups.py` (12 → `NotificationEventGroup.APPLICATION`) + `notification_seed_defaults.py` (12 Vietnamese seed defaults theo PLAN §3.3.d audience matrix).
- Outbox / bypass-consent matrix (PLAN §3.3.d): 7 outbox · 5 bypass-consent.
- 65 lock-in tests `test_b2_1_admission_milestone_events.py` (enum + dataclass + cross-file parity + matrix).
- 2 lock tests trong `test_notification_contract.py` cho `_PENDING_DISPATCH_EVENTS` split (P2 fix): `test_pending_dispatch_events_disjoint_from_dispatched` + `test_pending_dispatch_events_locked_to_b2_1_admission_set`.

**Tested / Rehearsed:**
- Post-merge re-run trên parent HEAD `df2111a9` (Docker `qlts-backend-1`):
  ```
  pytest tests/unit/test_b2_1_admission_milestone_events.py \
         tests/unit/test_notification_contract.py \
         tests/api/test_notification_event_groups_api.py -q
  → 103 passed in 34.89s
  ```
- Breakdown: 65 B2.1 lock-in + 34 notification_contract (incl. 2 lock tests pending split) + 4 event_groups_api regression.
- Coverage script `app/scripts/check_notification_event_coverage.py` exits `1` với đúng 12 `no-dispatch-site` cho `admission_*` events — đây là **intentional gap cho B2.1**, sẽ green sau B2.3 wrapper + `#16` `state_service.transition()` wiring. `_PENDING_DISPATCH_EVENTS` removal-gate trong test giữ honest contract.

**Blocked / decisions cần:**
- B2.2 push approval (sau khi đề xuất scope: `NotificationOutbox` model + migration `phase1_19a` với `down_revision='phase0br01'` + retire canary `test_models_package_still_lacks_notification_outbox` cùng PR).

**Tomorrow plan (B2 sequential):**
- B2.2 `NotificationOutbox` model + migration `phase1_19a` (idempotent guards + retire canary).
- B2.3 `dispatch_event()` wrapper (gọi `dispatch(..., strict=True)` + return post-commit callback; honor `requires_outbox` / `bypass_consent_check` flag từ catalog).
- B2.4 / T0-4b real `notification_outbox_drain` worker (replaces T0-4a no-op skeleton).

**Notes / surprises:**
- Squash convention `[ADM-B2.1] feat(notification): ... (#197)` đúng pattern cutover SOP. Branch `feature/admission-b2-1` giữ lại (delete-branch=false) cho rollback / cherry-pick nếu cần.
- gh CLI cache + raw API ban đầu báo PR open ngay sau user xác nhận merged — lý do: merge thực tế xảy ra **sau** confirmation. Khi user approve `gh pr merge` qua CLI, raw API + git fetch đều confirm `merged: true` + parent advance ngay tức thì. Pattern: trust git fetch + raw API trước UI claim.
- Mức 1 board: B2 thuộc thematic card **#183 [Phase 1 Code] B1+B2+#15+#16 + CI tooling** (NOT #185 — `#185` is the Phase 2 multi-round card, unrelated). Card #183 column expected In Progress từ T0 wave; verify thủ công vì gh CLI thiếu `read:project` scope. Issue body của #183 có **1 checkbox cho B2 duy nhất** (covers all 4 sub-PR B2.1+B2.2+B2.3+B2.4) — KHÔNG tick `[x]` ở wave này; chỉ tick khi B2.4 / T0-4b close (per `admission-cutover-subpr-sop` 4-step post-merge).

---

### B2.2 / M-1-19a — `NotificationOutbox` model + migration (local, pending push)

**Branch:** `feature/admission-b2-2-m-1-19a` off parent `acdffc8e` (= post B2.1 tracking commit `docs(admission): B2.1 post-merge tracking — TESTED + #183 board correction`). The earlier branch `feature/admission-b2-2` off `df2111a9` was abandoned mid-implementation after Codex caught a scope leak — working tree had B2.1 post-merge tracking + B2.2 implementation mixed; the rename + reroot puts B2.2 on a clean parent state and aligns the branch name with the tracker convention `[B2.2/M-1-19a]`.

**Scope (B2.2 strict, no leak into B2.3/B2.4):**
- `Backend_FastAPI/app/models/notification_outbox.py` — new `NotificationOutbox` model. 10 cột match PLAN §3.3.e + §3.3.f: `id BIGSERIAL PK`, `event_code VARCHAR(64) NOT NULL`, `payload JSONB NOT NULL`, `idempotency_key VARCHAR(128) NOT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `dispatched_at TIMESTAMPTZ NULL`, `attempts INT NOT NULL DEFAULT 0`, `last_error TEXT NULL`, `claimed_at TIMESTAMPTZ NULL`, `claimed_until TIMESTAMPTZ NULL`. Named `UniqueConstraint("idempotency_key", name="uq_notification_outbox_idempotency_key")`. Two `Index(...)` với `postgresql_where=text("dispatched_at IS NULL")` cho `ix_outbox_pending(created_at)` + `ix_outbox_claim(claimed_until)` — partial index keeps the hot path cheap as the table grows.
- `Backend_FastAPI/alembic/versions/phase1_19a_create_notification_outbox.py` — new migration. `revision='phase1_19a'`, `down_revision='phase0br01'`. Idempotent guards `table_exists` + `index_exists` (mirror `phase0sg01` precedent). Upgrade creates table với 10 cột + named UNIQUE + 2 partial-WHERE indexes. Downgrade short-circuits nếu table đã gone, ngược lại drop indexes + table theo thứ tự đảo. Stable name constants `TABLE`, `INDEX_PENDING`, `INDEX_CLAIM`, `UNIQUE_IDEMPOTENCY` được import bởi test file để lock parity.
- `Backend_FastAPI/app/models/__init__.py` — re-export `NotificationOutbox` (import + thêm vào `__all__` ngay cluster Notification, alphabetical giữa `NotificationConsentHistory` và `NotificationQuota`).
- `Backend_FastAPI/tests/unit/test_notification_outbox_model.py` (new) — 14 lock-in tests: importable + `__all__` membership + tablename + column shape (name/nullable/PK 10 entries) + `id` is `BigInteger` + `payload` is `JSONB` (not generic JSON) + named UNIQUE constraint single-col `idempotency_key` + 2 partial indexes present + each on correct column + WHERE clause filters `dispatched_at IS NULL` + migration module loads + revision chain `phase1_19a → phase0br01` + no other migration declares phase1_19a as `down_revision` (= currently the head) + ORM ⇄ migration constants parity (TABLE / INDEX_PENDING / INDEX_CLAIM / UNIQUE_IDEMPOTENCY).
- `Backend_FastAPI/tests/unit/test_outbox_skeleton.py` — retire T0-4a canary `test_models_package_still_lacks_notification_outbox` (single delete, replaced với inline comment giải thích arc + pointer sang `test_notification_outbox_model.py`). 2 AST guards (`test_skeleton_module_does_not_reference_notification_outbox_in_code` + `test_tasks_package_init_does_not_reference_notification_outbox_in_code`) giữ nguyên — B2.2 KHÔNG touch skeleton task body hay `app/tasks/__init__.py` (vẫn locked cho B2.4 / T0-4b).

**Verification:**
- `docker compose exec -T backend python -m pytest tests/unit/test_notification_outbox_model.py tests/unit/test_outbox_skeleton.py tests/unit/test_celery_task_registry.py -q` → **26 / 26 PASS in ~3.5s**: 14 model+migration parity + 10 outbox skeleton (canary slot now empty) + 2 celery_task_registry regression. Đã re-run lần 2 trên branch sau pop stash + commit để xác nhận no regression.
- Live alembic roundtrip dev DB (`qlts_dev`):
  - `alembic current` → `phase0br01` (post B2.1 baseline).
  - `alembic upgrade head` → `phase1_19a (head)`. `\d notification_outbox` shows 10 cột + 4 indexes (PK + 2 partial WHERE + 1 named UNIQUE). Column shape exact match PLAN spec.
  - `alembic downgrade -1` → `phase0br01`. `\d notification_outbox` returns "Did not find any relation".
  - `alembic upgrade head` → `phase1_19a (head)`. `SELECT to_regclass('public.notification_outbox') IS NOT NULL` returns `t` ✓ idempotent re-apply.
  - **Sau verify đã downgrade lại về `phase0br01`** (per Codex hướng dẫn) để dev DB không đi trước parent unmerged. B2.2 PR merge xong sẽ re-upgrade trên dev sau.
- AST guards retained trong `test_outbox_skeleton.py` PASS — skeleton task body chưa reference model (B2.4 sẽ thay).

**Out of scope (next sub-PR):**
- B2.3 — `dispatch_event()` wrapper (gọi `dispatch(..., strict=True)` + return post-commit callback; honor `requires_outbox` / `bypass_consent_check` flag từ catalog).
- B2.4 / T0-4b — replace `notification_outbox_tasks.py` body với 3-step claim/dispatch/finalize loop per PLAN §3.3.f.
- B1 Casbin deny-first — separate sub-PR, không ràng buộc với B2.

**Process correction (Codex catch):**
- Working tree mid-implementation đã trộn 2 scope: B2.1 post-merge tracking docs + B2.2 implementation. Tôi định roll cả 2 vào một PR duy nhất, Codex chặn: scope creep, B2.1 docs phải land trước trên parent qua direct commit, B2.2 trên branch riêng theo SOP.
- Sửa: stash B2.2 implementation 5 file, checkout parent, commit B2.1 tracking + drift fix `acdffc8e`, push parent, branch lại `feature/admission-b2-2-m-1-19a` off `acdffc8e`, pop stash. Stash đã drop sạch (no leftover).
- Drift fix kèm: original notes claim card #185 = Notification Surface; thực tế `gh issue view 185 --json title` returns "[Phase 2] Multi-round + admission_round + path swap". Sửa wording sang #183 [Phase 1 Code] với 1 checkbox B2 covering 4 sub-PR (B2.1..B2.4), không tick cho đến B2.4 close.

**Blocked / decisions cần:**
- B2.2 push approval cho `feature/admission-b2-2-m-1-19a` + sub-PR creation → `feat/admission-full-cutover` với title `[B2.2/M-1-19a] feat(notification): NotificationOutbox model + create-table migration`.

**Tomorrow plan (sau merge B2.2):**
- B2.3 wrapper `dispatch_event()` — branch `feature/admission-b2-3` off updated parent.
- Coverage script vẫn red 12 `no-dispatch-site` cho đến #16 (B2.3 ship wrapper, #16 wires `state_service.transition()`).

**Board correction (append-only, 2026-05-03):** card #183 [Phase 1 Code] thực tế vẫn ở Todo trước phiên này; đã move thủ công Todo → In Progress sau khi verify board qua Chrome MCP. Entry B2.1 trong `acdffc8e` ghi "expected In Progress" là giả định chưa xác minh tại thời điểm viết, không phải trạng thái đã kiểm chứng.

---

### B2.2 / M-1-19a — sub-PR merged (post-merge sync)

**Sub-PR merged today (vào `feat/admission-full-cutover`):**
- PR [#198](https://github.com/favouritekid/QLTS/pull/198) — `[B2.2/M-1-19a] feat(notification): NotificationOutbox model + create-table migration` — squash `e05732c2` (mergedAt `2026-05-03T01:12:39Z`, mergedBy `favouritekid` via `gh pr merge --squash --delete-branch=false`). Parent advanced `acdffc8e → e05732c2`.

**Tested / Rehearsed:**
- Post-merge re-run trên parent HEAD `e05732c2` (Docker `qlts-backend-1`):
  ```
  pytest tests/unit/test_notification_outbox_model.py \
         tests/unit/test_outbox_skeleton.py \
         tests/unit/test_celery_task_registry.py -q
  → 26 passed in 4.29s
  ```
- Breakdown: 14 model+migration parity + 10 outbox skeleton (canary slot empty post-retire) + 2 celery_task_registry regression.
- Live alembic upgrade trên parent: dev DB `phase0br01 → phase1_19a (head)` ✓. Pre-merge roundtrip evidence (downgrade -1 → re-upgrade head idempotent) on local branch trước khi push.

**Mức 1 board:**
- Card #183 [Phase 1 Code] vẫn ở In Progress (đã move sang trong session trước qua Chrome MCP).
- **B2 thematic checkbox `[ ] **B2**` NOT ticked** — đúng SOP, chỉ tick khi B2.4/T0-4b close (single checkbox covers all 4 sub-PR B2.1..B2.4).

**Tomorrow plan (sau B2.2 merge):**
- B2.3 — `dispatch_event()` wrapper. Branch `feature/admission-b2-3` off updated parent `e05732c2`. Scope: gọi `dispatch(..., strict=True)` + return post-commit callback; honor `requires_outbox` / `bypass_consent_check` flag từ `event_catalog.py`; INSERT `NotificationOutbox` cho 7 outbox-flagged events.
- B2.4 / T0-4b — replace `notification_outbox_tasks.py` body với 3-step claim/dispatch/finalize loop per PLAN §3.3.f.

**Notes / surprises:**
- Squash convention `[B2.2/M-1-19a] feat(notification): ... (#198)` đúng pattern cutover SOP. Branch `feature/admission-b2-2-m-1-19a` giữ remote (`--delete-branch=false`) cho rollback / cherry-pick.
- Stale local `feature/admission-b2-2` (off original `df2111a9`, abandoned mid-implementation) vẫn còn — local-only, never pushed; an toàn `git branch -d feature/admission-b2-2` cleanup.

---

### B2.3 — `dispatch_event()` wrapper (sub-PR opened)

**Branch:** `feature/admission-b2-3` off parent `31f7e001` (post B2.2 tracking commit). Strict scope: wrapper + tests + coverage-script extension only — KHÔNG touch worker body, state service / admission transition call-sites, Casbin/B1, hay board checkbox B2.

**Sub-PR opened:** [#199](https://github.com/favouritekid/QLTS/pull/199) — base `feat/admission-full-cutover`, head `feature/admission-b2-3`. Mergeable: `MERGEABLE`, mergeStateStatus: `CLEAN`. Pending review/merge approval at open time; B2 checkbox remains unticked until B2.4/T0-4b.

**Contract verification (resolved doc drift before code):**

User flagged B2.3 must verify the dispatcher contract before implementing because PLAN §3.3.f sample uses `safe_dispatch()` while DAILY_LOG (and PLAN-internal note) suggested `dispatch(..., strict=True)`. Verified ground-truth signatures in `Backend_FastAPI/app/services/notification_dispatcher.py`:

| Primitive | Line | `strict` param | Returns | Use case |
|---|---|---|---|---|
| `dispatch(...)` | 593 | yes (default `False`) | `(notif_ids, post_commit_callback)` — caller commits then awaits callback | Service body within caller's tx; `strict=True` for `dispatch_bundle()` savepoint pattern |
| `safe_dispatch(...)` | 1853 | **no** | `notif_ids` | Router AFTER `db.commit()` — owns own commit + swallows errors |

**Decision: B2.3 wrapper uses `safe_dispatch()` (no `strict`) inside the best-effort callback.** Reasoning:

1. The post-commit callback runs in the **router after `await db.commit()`**, exactly the use case `safe_dispatch()` doc (line 1864-1866) describes — own commit + swallow errors.
2. **No outer transaction** to protect with savepoints — memory `dispatch-bundle-strict-required` (3 internal `db.rollback()` paths in `dispatch()`) only applies when wrapping `dispatch()` in `begin_nested()`. The post-commit callback path doesn't have that wrapping.
3. RISK_REVIEW PATCH-11 wording `safe_dispatch(... strict=True, ...)` is itself drift — `safe_dispatch()` doesn't accept a `strict` param (verified at line 1853-1859). Ground-truth signatures govern the implementation; aspirational doc notes do not. Documented this rationale in the wrapper docstring + commit message.
4. Outbox path (7 events, `requires_outbox=True`) **doesn't call dispatch/safe_dispatch at all** — it INSERTs a `NotificationOutbox` row in the caller's tx and returns `None`. The Celery beat task (`dispatch_pending_outbox`, T0-4a skeleton today, B2.4/T0-4b real worker) drains the table out-of-band.

**Catalog matrix correction (post-implementation discovery):**

Mid-test it became clear the actual `EVENT_CATALOG` matrix differs from the early PLAN draft / B2.1 PR body table. Live snapshot via `python -c "from app.core.event_catalog import EVENT_CATALOG; ..."`:

- **Outbox (7)**: `RESULT_PUBLISHED`, `DECISION_ADMITTED`, `DECISION_WAITLISTED`, `DECISION_REJECTED`, `WAITLIST_PROMOTED`, `ENROLLED`, `ROLLED_BACK` (5 of these have `bypass_consent_check=True`).
- **Best-effort (5)**: `PROFILE_SUBMITTED`, `REVISION_REQUESTED`, `RESUBMITTED`, `CONFIRMED`, `WITHDRAWN` (all `bypass_consent_check=False`).

The B2.1 PR body table and B2.2 commit message had an aspirational matrix that didn't match the catalog as merged. B2.3 tests pin the actual matrix; future PRs that re-tune the catalog must update the test parametrize lists to match. No production behavior change — this is documentation drift in PR descriptions, not code.

**Scope (B2.3 strict, no leak into B2.4):**

- `Backend_FastAPI/app/services/notification_dispatcher.py` — add `dispatch_event()` at end of file (after `safe_dispatch`). Signature: `async def dispatch_event(db, *, event: SystemEvents, payload: dict, dedupe_key: Optional[str] = None) -> Optional[Callable[[], Awaitable[None]]]`. Body: `isinstance(event, SystemEvents)` guard (raw str rejected because `SystemEvents(str, Enum)` would otherwise dict-lookup successfully via str hashing) → `get_event(event)` catalog lookup → outbox branch (`db.add(NotificationOutbox(event_code=event.value, payload=payload, idempotency_key=dedupe_key))` + return None; raises if `dedupe_key is None`) OR best-effort branch (return closure that calls `safe_dispatch(db=captured_db, event=captured_event, payload=captured_payload, dedupe_key=captured_dedupe, skip_preference_check=event_def.bypass_consent_check)`). Add `Awaitable` to typing import.
- `Backend_FastAPI/tests/unit/test_dispatch_event_wrapper.py` (new) — 27 lock-in tests in 4 classes:
  - `TestDispatchEventOutboxPath` (7 events × 2 + 1 sanity = 15 cases): outbox event inserts row + returns None; missing dedupe_key raises ValueError mentioning event name; outbox path doesn't call safe_dispatch (mock).
  - `TestDispatchEventBestEffortPath` (5 events + 2 forwarding = 7 cases): best-effort returns callable + no outbox row; callback awaits safe_dispatch with full kwargs (mock); bypass_consent True-case via `get_event` patch with MagicMock(spec=EventDefinition).
  - `TestDispatchEventInputValidation` (3 cases): raw string rejected; non-enum int rejected; unknown SystemEvents member raises (skip if catalog complete — currently SKIPPED because all 12 admission events are in catalog).
  - `TestDispatchEventApiSurface` (2 cases): `dispatch_event` exported from dispatcher module + signature has keyword-only `event/payload/dedupe_key`.
- `Backend_FastAPI/app/scripts/check_notification_event_coverage.py` — extend with `_scan_raw_dispatch_calls()` AST walker that finds `dispatch()` / `safe_dispatch()` call sites passing `event=SystemEvents.<NAME>` outside the allowlist (`app/services/notification_dispatcher.py` + `app/tasks/notification_outbox_tasks.py`). Add `requires_outbox` + `raw_dispatch_sites` fields to `EventStatus`. New gap type `raw-dispatch-of-outbox-event` triggers when any outbox-flagged event has a raw call site outside the allowlist. Munge wrapper docstring example to use `<OUTBOX_EVENT>` placeholder so the legacy regex-based `_scan_dispatch_sites` doesn't false-positive on the docstring.

**Coverage detector — both keyword and positional forms (Codex catch during amend):**

The first cut of `_scan_raw_dispatch_calls()` only walked `node.keywords` for `event=SystemEvents.X`, so it silently missed the positional form `safe_dispatch(db, SystemEvents.X, payload={})`. Codex caught this between the first commit and approval. Refactored: extracted `_extract_systemevents_from_event_arg(node)` covering both forms (keyword takes precedence; if keyword is parameterized, do NOT fall through to args[1]). The signatures of `dispatch()` and `safe_dispatch()` both have `event` at positional index 1, so the helper checks `args[1]` only. Added `Backend_FastAPI/tests/unit/test_coverage_script_raw_dispatch.py` (14 tests) to lock both forms + the allowlist + the parameterized-skip + the gap-surfacing integration so the next refactor can't quietly regress.

**Verification:**

- `docker compose exec -T backend python -m pytest tests/unit/test_dispatch_event_wrapper.py -v` → **26 passed, 1 skipped in 1.09s** (skip = `test_unknown_systemevents_member_raises_valueerror` because all events are catalogued — correct behavior).
- `docker compose exec -T backend python -m pytest tests/unit/test_coverage_script_raw_dispatch.py -v` → **14 / 14 passed in 0.83s**.
- Full notification regression: `test_dispatch_event_wrapper.py + test_coverage_script_raw_dispatch.py + test_notification_outbox_model.py + test_outbox_skeleton.py + test_notification_contract.py + test_b2_1_admission_milestone_events.py + test_celery_task_registry.py + tests/api/test_notification_event_groups_api.py` → **169 passed, 1 skipped in 36.92s** (1 skip same as above).
- Coverage script:
  - `python -m app.scripts.check_notification_event_coverage` → exit `1` with **12 expected `no-dispatch-site`** (admission_*, unchanged baseline; will green after #16 wires `state_service.transition()` callers).
  - JSON output verified: 7 outbox events tracked, `total_raw_dispatch_sites_for_outbox_events=0`, `raw_dispatch_of_outbox_violations=0`. Detector dormant (correct — nothing to flag).
  - **Bite-verified twice (keyword + positional)**: keyword stub `safe_dispatch(event=SystemEvents.ADMISSION_DECISION_ADMITTED, ...)` AND positional stub `safe_dispatch(db, SystemEvents.ADMISSION_DECISION_REJECTED, {})` each in non-allowlisted files produced exactly the expected `raw-dispatch-of-outbox-event` gap; removing each stub returned the script to baseline (12 `no-dispatch-site`, 0 raw-dispatch).
- Alembic head unchanged: `phase1_19a (head)` (B2.3 doesn't touch DB — model + migration shipped in B2.2).

**Out of scope (next sub-PR):**

- B2.4 / T0-4b — replace `notification_outbox_tasks.py` body with 3-step claim/dispatch/finalize loop per PLAN §3.3.f. Worker is the legitimate raw `dispatch()` caller (allowlisted in coverage script). #16 separately wires `state_service.transition()` to call `dispatch_event()` — that's a B-cluster code task, not a B2 sub-PR.

**Blocked / decisions cần:**

- Review/merge PR [#199](https://github.com/favouritekid/QLTS/pull/199). Branch already pushed; sub-PR open against parent. Reviewer **MUST NOT** tick the `[ ] **B2**` checkbox on issue #183 — that single box covers all four B2 sub-PRs and stays unticked until B2.4 / T0-4b closes the wave.

**Tomorrow plan (sau merge B2.3):**

- B2.4 / T0-4b — branch `feature/admission-b2-4` off updated parent. Replace skeleton task body with 2-step CTE claim + 3-step dispatch/finalize per PLAN §3.3.f. Tests: concurrency rig (2 workers don't double-claim) + crash-recovery (claim_until expiry) + dispatch-error-path (last_error populated).
- After B2.4 merge → tick `[ ] **B2**` checkbox on issue #183 (entire B2 wave closed).

---

### B2.3 — sub-PR merged (post-merge sync)

**Sub-PR merged today (vào `feat/admission-full-cutover`):**
- PR [#199](https://github.com/favouritekid/QLTS/pull/199) — `[B2.3] feat(notification): add dispatch_event wrapper + outbox coverage guard` — squash `f2f0d62b` (mergedAt `2026-05-03T02:43:33Z`). Parent advanced `31f7e001 → f2f0d62b`.

**Tested / Rehearsed:**
- Post-merge re-run trên parent HEAD `f2f0d62b` (Docker `qlts-backend-1`):
  ```
  pytest tests/unit/test_dispatch_event_wrapper.py \
         tests/unit/test_coverage_script_raw_dispatch.py \
         tests/unit/test_notification_outbox_model.py \
         tests/unit/test_outbox_skeleton.py \
         tests/unit/test_notification_contract.py \
         tests/unit/test_b2_1_admission_milestone_events.py \
         tests/unit/test_celery_task_registry.py \
         tests/api/test_notification_event_groups_api.py -q
  → 169 passed, 1 skipped in 37.94s
  ```
- Coverage invariant post-merge: `raw_violations=0`, `no_dispatch=12`, `outbox=7`, `outbox_raw_sites=[]`. The 12 `no-dispatch-site` rows are expected until #16 wires `state_service.transition()` callers.
- Alembic head unchanged: `phase1_19a (head)` — B2.3 is code/test/doc only, no DB migration.

**Mức 1 board / issue checkbox:**
- Card #183 [Phase 1 Code] stays In Progress.
- **B2 thematic checkbox remains unchecked** — B2 closes only after B2.4 / T0-4b real worker lands.

**Next:**
- Start B2.4 / T0-4b on `feature/admission-b2-4` off parent `f2f0d62b`: replace T0-4a no-op skeleton with 3-step outbox claim/dispatch/finalize worker per PLAN §3.3.f.

---

### B2.4 / T0-4b — `dispatch_pending_outbox` real worker (sub-PR opened)

**Branch:** `feature/admission-b2-4` off parent `87685ff4` (= post B2.3 tracking commit, one commit beyond the `f2f0d62b` PR #199 squash). Strict scope: replace T0-4a no-op skeleton with the real claim/dispatch/finalize worker — KHÔNG touch `state_service` / admission service callers (#16 owns that wiring), Casbin/B1, or board checkbox B2.

**Sub-PR opened:** [#200](https://github.com/favouritekid/QLTS/pull/200) — base `feat/admission-full-cutover`, head `feature/admission-b2-4` (head SHA `e806597a`). Mergeable: `MERGEABLE`, mergeStateStatus: `CLEAN`. **Do not merge** — review-only until further approval. Reviewer must NOT tick the `[ ] **B2**` checkbox on issue #183 — it stays unticked until this PR merges + post-merge tests pass on parent.

**Implementation (`Backend_FastAPI/app/tasks/notification_outbox_tasks.py`):**

Three-step pattern per PLAN §3.3.f. Module-level constants surface the tunables:

| Constant | Value | Purpose |
|---|---|---|
| `BATCH_LIMIT` | 100 | Max rows claimed per tick |
| `MAX_ATTEMPTS` | 5 | DLQ threshold — rows ≥ this attempts excluded from claim filter |
| `PER_ROW_TIMEOUT_SECONDS` | 5 | Lease seconds per claimed row |
| `CLAIM_TIMEOUT_CAP_SECONDS` | 600 | Lease cap (10 min) |
| `TASK_ID` | `"T0-4b"` | Result-dict discriminator (was `"T0-4a"` for skeleton) |

- **Step 1 — `_claim_batch(session)`**: short tx with 2-step CTE. Inner CTE `candidates` does `SELECT id ... FOR UPDATE SKIP LOCKED ORDER BY created_at LIMIT 100` filtering `dispatched_at IS NULL AND attempts < MAX_ATTEMPTS AND (claimed_until IS NULL OR claimed_until < NOW())`. Outer `UPDATE ... WHERE id IN (SELECT id FROM candidates)` sets `claimed_at = NOW()`, `claimed_until = NOW() + (interval '1 second' * LEAST((SELECT COUNT(*) FROM candidates) * PER_ROW_TIMEOUT_SECONDS, CLAIM_TIMEOUT_CAP_SECONDS))`, `attempts = attempts + 1`, `RETURNING id, event_code, payload, idempotency_key`. Adaptive lease scales with actual claimed rowcount via the inline CTE `COUNT(*)` (Postgres materializes `candidates` once per statement, so the count + the `WHERE id IN (SELECT id ...)` share one rowset — no double-lock). The 2-step CTE matches PLAN's v2.3-fix pattern (avoids the v2.2 `UPDATE ... RETURNING ... fetchmany(100)` bug that mutated every pending row before the client cap kicked in).
- **Step 2 — `_dispatch_each(session, pending)`**: per-row dispatch loop, NO claim lock held (Step 1's tx already committed before Step 2 starts; `task_db_session()` reuses session for connection efficiency). For each row: cast `event_code` string → `SystemEvents` enum (mark error if not in enum); `get_event(event)` lookup (mark error if not in catalog); call `dispatch(db=session, event=event, payload=payload, dedupe_key=idem_key, skip_preference_check=event_def.bypass_consent_check, strict=True)`; await `session.commit()`; await post-commit callback (best-effort — callback failures are logged but don't fail the row, mirroring `safe_dispatch()` convention). On exception: `session.rollback()` + record `(row_id, "error", str(e)[:1000])`. `strict=True` ensures persistence errors propagate so this loop can mark the row as failed instead of silently rolling back (memory `dispatch-bundle-strict-required`).
- **Step 3 — `_finalize(session, results)`**: short tx, per-row UPDATE. `ok` rows: `dispatched_at = NOW(), claimed_until = NULL, last_error = NULL` (terminal — never re-claimed; `last_error` cleared so a successfully-retried row does not carry stale failure text). `error` rows: `last_error = :err, claimed_until = NULL` (release claim for retry until `attempts >= MAX_ATTEMPTS`).

Worker uses raw `dispatch()` (not `dispatch_event()` wrapper) — IT IS the dispatcher for outbox events. Worker module is allowlisted in `app/scripts/check_notification_event_coverage.py::RAW_DISPATCH_ALLOWLIST` (per B2.3) so this raw call does not trigger the `raw-dispatch-of-outbox-event` gap.

**Test surface:**

- `tests/unit/test_outbox_skeleton.py` — RETIRED 2 skeleton-specific tests (`test_skeleton_module_does_not_reference_notification_outbox_in_code` + `test_skeleton_call_returns_stable_no_op_shape`); KEPT 8 registration / discoverability / package-init AST guards (beat schedule + cadence, `conf.include` lock, cold-import subprocess test, after-import register sanity, package re-export, autodiscover smoke, zero-required-arg signature, tasks-package init NotificationOutbox-free guard). File docstring rewritten to reflect the post-T0-4b purpose (registration contract that survived the body swap).
- `tests/unit/test_outbox_worker.py` (NEW, 10 tests against real `qlts_test` DB via `setup_test_database` + `AsyncSessionLocal` seeding):
  - `test_empty_queue_returns_zero_claimed`: empty table → `status=ok, claimed=0, task_id=T0-4b, reason=queue_empty`.
  - `test_single_pending_row_dispatched_ok_marks_dispatched_at`: seeds 1 row, mocks `dispatch` returning `([], None)`, asserts dispatch called with right kwargs (`strict=True`, `skip_preference_check=True` for `ADMISSION_DECISION_ADMITTED` whose `bypass_consent_check=True`), row `dispatched_at` set, `claimed_until` cleared, `attempts=1`, `last_error` NULL.
  - `test_post_commit_callback_is_awaited_when_dispatch_returns_one`: dispatch returns callable callback → worker awaits it (verified via `AsyncMock.assert_awaited_once`).
  - `test_dispatch_failure_increments_attempts_writes_last_error`: mock `dispatch` raises → row `dispatched_at` NULL, `claimed_until` NULL, `attempts=1`, `last_error` contains the message.
  - `test_expired_claim_is_re_claimable`: row pre-seeded with `claimed_until=2020-01-01` + `attempts=1` → worker re-claims, `attempts=2` after run.
  - `test_active_claim_is_not_re_claimed`: row pre-seeded with `claimed_until=2099-01-01` → worker returns `claimed=0`, dispatch never called, row state unchanged.
  - `test_max_attempts_excludes_row_from_claim`: row with `attempts=MAX_ATTEMPTS=5` → worker returns `claimed=0`, dispatch never called (DLQ).
  - `test_retry_success_clears_prior_last_error`: pre-failed row (last_error set, expired lease, attempts=1) re-claimed and dispatched ok → `last_error` cleared along with `dispatched_at` set + `claimed_until` NULL + `attempts=2`. Locks the Step-3 ok-branch contract that a successful retry must not carry stale failure text.
  - `test_single_row_claim_lease_is_per_row_seconds`: seed 1 row, call `_claim_batch` directly, inspect `claimed_until - claimed_at` ≈ `PER_ROW_TIMEOUT_SECONDS` (~5s) — NOT `BATCH_LIMIT * PER_ROW_TIMEOUT_SECONDS` (~500s). Locks the adaptive-lease contract: a 1-row claim holds a 5s lease, not the worst-case 500s.
  - `test_mixed_batch_marks_each_row_independently`: 3 rows, dispatch alternates ok/fail/ok → `claimed=3 dispatched=2 failed=1`; row 0+2 dispatched, row 1 has `last_error`; per-row commit/rollback isolation verified (dispatch failure on row N does not poison N+1, N+2 in same batch).

**Patches applied during review (Codex catch on 2026-05-03 before push):**

1. **Step 3 ok branch must clear `last_error`**: a successfully-retried row would otherwise carry stale failure text from the prior attempt, making the operator chase non-existent issues. Added `last_error = NULL` to the ok-branch UPDATE alongside `dispatched_at = NOW()` + `claimed_until = NULL`. Locked by `test_retry_success_clears_prior_last_error`.
2. **Adaptive lease per actual claim count**: the prior shape used `min(BATCH_LIMIT * PER_ROW_TIMEOUT_SECONDS, CLAIM_TIMEOUT_CAP_SECONDS)` for every claim — a 1-row claim got a 500s lease, blocking recovery for far longer than the work warranted. Refactored Step-1 SQL to compute the lease inline via `LEAST((SELECT COUNT(*) FROM candidates) * PER_ROW_TIMEOUT_SECONDS, CLAIM_TIMEOUT_CAP_SECONDS)` so the lease scales with the actual rowcount. Postgres materializes the CTE once per statement, so `COUNT(*)` and `WHERE id IN (SELECT id ...)` read the same materialized rowset — no double-locking. Locked by `test_single_row_claim_lease_is_per_row_seconds`.

**Verification:**

- `docker compose exec -T backend python -m pytest tests/unit/test_outbox_worker.py -q` → **10 passed in ~25s**.
- `docker compose exec -T backend python -m pytest tests/unit/test_outbox_skeleton.py -q` → **8 passed in ~4s** (after retire of 2 skeleton-specific tests).
- Full notification regression: `tests/unit/test_outbox_worker.py + test_outbox_skeleton.py + test_dispatch_event_wrapper.py + test_coverage_script_raw_dispatch.py + test_notification_outbox_model.py + test_notification_contract.py + test_b2_1_admission_milestone_events.py + test_celery_task_registry.py + tests/api/test_notification_event_groups_api.py` → **177 passed, 1 skipped in 58.62s** (the 1 skip = uncatalogued-enum branch in dispatch_event wrapper test, pre-existing).
- Coverage script invariant (B2.3 detector unchanged):
  - `python -m app.scripts.check_notification_event_coverage` → exit `1` with **12 expected `no-dispatch-site`** (admission_*, baseline preserved); will green after #16 wires `state_service.transition()` callers.
  - **0 `raw-dispatch-of-outbox-event` violations** — worker's raw `dispatch()` call does not trigger the gap because `app/tasks/notification_outbox_tasks.py` is in `RAW_DISPATCH_ALLOWLIST` (per B2.3 design).
- Alembic head unchanged: `phase1_19a (head)` (B2.4 doesn't touch DB schema).

**Concurrency note (no-double-claim):**

The worker relies on Postgres `FOR UPDATE SKIP LOCKED` at the connection level: two workers competing for the same row will see one of them claim it; the other's `SELECT ... FOR UPDATE SKIP LOCKED` skips the locked row. The tests cover the same guarantee from the SQL filter side — the active-lease test proves a row with `claimed_until > NOW()` is excluded by the predicate, which is what `FOR UPDATE SKIP LOCKED` resolves to during contention. A true two-process race test would require a multi-process harness; deferred to staging smoke (D12-D14) with two `celery-worker` replicas.

**Out of scope (next code tasks, sequenced):**

- **B1** Casbin deny-first — IS the next code task after B2.4 merge.
- **#15** `approved → admitted` workflow remap + helpers — depends on B2.
- **#16** — wire `state_service.transition()` to call `dispatch_event()` for the 12 admission events. **Blocked until B1 + B2 are both TESTED.** That's where the 12 `no-dispatch-site` gaps finally close.

**Blocked / decisions cần:**

- Review/merge PR [#200](https://github.com/favouritekid/QLTS/pull/200). Branch already pushed; sub-PR open against parent. Reviewer **MUST NOT** tick the `[ ] **B2**` checkbox on issue #183 — stays unticked until this PR merges + post-merge tests pass on parent.

**Tomorrow plan (sau merge B2.4):**

- Tick `[ ] **B2**` checkbox on issue #183 (B2 wave + T0-4b both close at the same merge — single thematic checkbox covers all four B2.x sub-PRs per project SOP).
- **Start B1 — Casbin deny-first.** **#16 remains blocked until B1 + B2 are both TESTED**; then proceed #15 / #16 per sequence. Coverage script stays red with 12 `no-dispatch-site` until #16 wires `state_service.transition()` through `dispatch_event()`.

---

### B1 — Casbin deny-first auth model + 6 accountant deny rules (local, pending push)

**Branch:** `feature/admission-b1` off parent `88c19c16` (post B2.4 tracking). Single-commit B1 PR per **Strategy A** (chốt 2026-05-03 sau Codex reviewer reject phương án 2-PR split B1.1 → B1.2). Atomic deploy: migration backfill + 4-field auth_model + plumbing + boot gate + runbook patch trong cùng một PR; cutover sequence dùng RUN_CASBIN_LOAD_ON_STARTUP env-flag gate (mirror T0-1 pattern) thay vì shim.

**Pre-flight evidence (proves B1 cannot ship without bundled migration):**

Codex reviewer + implementer probed Casbin Python lib + adapter source + dev DB before any code change:
- `casbin_async_sqlalchemy_adapter.CasbinRule.__str__` breaks at first `None` v-column (`adapter.py:42-46`).
- 210/210 prod-shape `ptype='p'` rules có `v3 IS NULL` (psql probe trên dev DB).
- Casbin Python `core_enforcer.py:447-448` raises `RuntimeError("invalid policy size")` khi `len(p_tokens) != len(pvals)`.
- **Both directions fail**: 4-field model + 3-element rules → crash; 4-element rules + 3-field model → also crash. Backfill phải xảy ra cùng deploy với model flip (atomic), không thể split.
- Effect string: Casbin lib does literal-match against `casbin/constant/constants.py::ALLOW_AND_DENY_EFFECT = "some(where (p_eft == allow)) && !some(where (p_eft == deny))"`. Order matters (allow first, deny second). Lib normalizes `p.eft → p_eft` automatically khi parse `.conf` file.

**Strategy A chosen over B (adapter shim) and C (2-PR split):**

- A win on long-term codebase cleanliness (no permanent shim layer; future Casbin lib upgrades trivial).
- A win on tracker fit (3 row separate B1 + M-1-casbin + BF-casbin map 1-1 với 3 phase: code task + migration file + deploy execution).
- A acceptable on cutover risk vì T0-1 đã proven env-flag pattern: thêm 3rd flag `RUN_CASBIN_LOAD_ON_STARTUP` mirror 2 flag hiện có (`RUN_MIGRATIONS_ON_STARTUP` + `RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP`). Cutover team đã thực tập flip 2 flag từ PR #189 merged 2026-05-02.
- A trade-off cost = one-time runbook patch (small, single section §7.2 with 3 step changes).

**Scope landed:**

- `Backend_FastAPI/auth_model.conf` — 4-field `p = sub, obj, act, eft` + canonical Casbin effect `e = some(where (p.eft == allow)) && !some(where (p.eft == deny))` (allow first, deny second per `ALLOW_AND_DENY_EFFECT` constant).
- `Backend_FastAPI/app/casbin_config/policy_templates.py` — `PolicyRule` TypedDict thêm `eft: Literal["allow", "deny"]` (optional in source data, defaults to "allow"); `apply_template()` luôn normalize 4-field output; 6 accountant deny rules append vào `ACCOUNTANT_TEMPLATE.policies` per PLAN §3.3.b lines 1411-1415 với `waitlist-*` expanded thành 2 entry (`waitlist-promote` + `waitlist-reject`) cho keyMatch4 precision: `/api/v2/admissions/*/{claim, request-revision, publish-result, waitlist-promote, waitlist-reject, admin-rollback}`.
- `Backend_FastAPI/app/services/casbin_service.py::add_policies_batch` — accept 3-tuple (eft default "allow", backward compat for admin UI) hoặc 4-tuple (template seed); pass `enforcer.add_policy(sub, obj, act, eft)`. `_update_template_tracking` SQL match `v3=:eft` explicitly để allow/deny variants không collide.
- `Backend_FastAPI/app/services/casbin_service.py::apply_template_to_role` + `Backend_FastAPI/app/main.py:273` bootstrap — both unpack `apply_template` 4-field result.
- `Backend_FastAPI/app/main.py` lifespan — gate `await enforcer.load_policy()` behind `RUN_CASBIN_LOAD_ON_STARTUP` env flag. Defensive default: only exact lowercase `"false"` skips; mọi value khác (unset / true / typo) chạy load.
- `Backend_FastAPI/docker-entrypoint.sh` — thêm 3rd gate echo mirror 2 gate hiện có.
- `Backend_FastAPI/alembic/versions/phase1_19b_backfill_casbin_eft_and_seed_deny_rules.py` — `revision='phase1_19b'`, `down_revision='phase1_19a'`. Upgrade: UPDATE casbin_rule SET v3='allow' WHERE ptype='p' AND v3 IS NULL (idempotent predicate); 6 INSERT rows for accountant deny với `WHERE NOT EXISTS` guard + `template_id='_system_b1_deny'` audit marker. asyncpg-safe `CAST(:p AS varchar)` casts trên mọi parameter (avoid `AmbiguousParameterError: inconsistent types deduced for parameter $1` khi cùng param dùng ở untyped INSERT SELECT + varchar WHERE — encountered live during dev-DB upgrade). Downgrade: DELETE 6 deny rows by exact (ptype, v0, v1, v2, v3) match; UPDATE v3=NULL WHERE v3='allow'.
- `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md` §7.2 — 3 step patch:
  - T+1:00: deploy backend với `RUN_CASBIN_LOAD_ON_STARTUP=false` (3rd flag).
  - T+3:15: restart backend với `RUN_CASBIN_LOAD_ON_STARTUP=true` (flipped back) để lifespan reload enforcer trên backfilled DB.
  - T+24h: switch all 3 flag back to `true`/unset cho routine deploy.

**Test surface (39 B1 lock-in tests + 9 existing Casbin tracking regression = 48 B1 focused):**

- `tests/unit/test_casbin_b1_deny_first.py` (29 tests, 4 classes — incl. `test_boot_gate_skip_bypasses_empty_policy_fail_fast` added during Codex review patch round; structural-check via Patch A signature OR Patch B indent comparison; bite-verified by reverting Patch A → test fails, restoring → test passes):
  - `TestAuthModelConfShape` (2): policy_definition is 4-field; policy_effect matches canonical allow-and-deny order.
  - `TestEffectStringIsLibCanonical` (3): `casbin.effect.get_effector()` accepts on-disk effect post `p.eft → p_eft` normalize; rejects reversed order (`!deny && allow`); `AsyncEnforcer(auth_model.conf)` parses without raising.
  - `TestPolicyRuleTypedDict` + `TestApplyTemplateEmits4Field` (5): default eft='allow'; role substitution; 6 explicit deny rules locked to set; deny rules target role:accountant; no other template carries deny rules (drift catch).
  - `TestBootGateContract` (18): default load behavior; lowercase 'false' skips; 13-case parametrize (FALSE/True/typo/etc.) all default to load; entrypoint shell + main.py source-grep checks for the gate.
- `tests/unit/test_phase1_19b_casbin_eft_backfill.py` (7 tests):
  - revision contract (revision='phase1_19b', down_revision='phase1_19a').
  - phase1_19b is current alembic head.
  - upgrade predicate-guards (regex match `WHERE ptype='p' AND v3 IS NULL` + `WHERE NOT EXISTS`).
  - downgrade predicate-guards (`WHERE v3='allow'` + DELETE by exact match).
  - asyncpg `CAST(:p AS varchar)` count ≥ 8 (4 INSERT + 4 DELETE).
  - 6 deny rules locked (count + paths + role:accountant + POST + deny shape).
  - `_system_b1_deny` template marker present.
- `tests/integration/test_casbin_b1_4x14_matrix.py` (3 tests on real qlts_test DB):
  - 4 role × 14 action matrix (56 cells) — admin/manager/accountant/officer × representative routes (5 baseline + 3 manager-only + 6 v2 routes carrying accountant deny).
  - Bite-verify: removing one accountant deny rule + injecting synthetic inherited allow flips matrix outcome → deny rule load-bearing, không tautology.
  - Sanity: 6 deny rows seeded as expected post-bootstrap.
- `tests/api/test_casbin_tracking.py` (9 existing Casbin tracking tests) — regression PASS, backward compat OK với 3-tuple add_policies_batch.

**Verification:**

- `docker compose exec -T backend python -m pytest tests/unit/test_casbin_b1_deny_first.py tests/unit/test_phase1_19b_casbin_eft_backfill.py tests/integration/test_casbin_b1_4x14_matrix.py tests/api/test_casbin_tracking.py -q` → **48 passed in 22.79s**.
- Full B1 + B2 regression (13 files: 4 B1 + 9 B2 / outbox / notification): `+ tests/unit/test_outbox_worker.py + test_outbox_skeleton.py + test_dispatch_event_wrapper.py + test_coverage_script_raw_dispatch.py + test_notification_outbox_model.py + test_notification_contract.py + test_b2_1_admission_milestone_events.py + test_celery_task_registry.py + tests/api/test_notification_event_groups_api.py` → **225 passed, 1 skipped in 87.76s** (1 skip = pre-existing uncatalogued-enum branch trong dispatch_event wrapper test).
- **Codex reviewer note (verified independent live probe)**: 2 tests trong `tests/api/test_admin_casbin.py::{policy,role}_crud_flow` fail trên parent `88c19c16` với HTTP 404 (endpoints không tồn tại) — pre-existing parent state, KHÔNG phải B1 regression. Confirmed bằng cách cherry-pick 4 B1 source files sang parent + run targeted test → vẫn fail cùng cách. B1 không chạm test này; nó không nằm trong 13-file regression bundle B1+B2 đã chạy.
- Live alembic roundtrip on dev DB (`qlts_dev`):
  - `phase1_19a → upgrade head → phase1_19b (head)`: 210 rows v3=NULL → v3='allow' + 6 deny rows seeded.
  - Idempotent re-apply: predicates match zero rows, no-op.
  - `downgrade -1 → phase1_19a`: 6 deny rows deleted, 210 rows v3 reverted to NULL.
  - Re-upgrade: state restored.
- Coverage script invariant (B2.3 detector unchanged): no change expected since B1 doesn't touch outbox dispatch surface.

**Diamond inheritance gotcha (documented for future):**

Admin inherits accountant via `g, role:admin, role:accountant` (main.py:330 — kept "BOTH branches" diamond intent). With the new deny-first effect, deny rules propagate via `g()` matcher → admin transitively matches accountant's deny rules → admin DENIED on the 6 v2 routes despite admin's `role:admin /* .*` allow wildcard. Casbin's allow-and-deny effect is unconditional: ANY matching deny short-circuits to forbidden, even when an allow also matches.

PLAN §3.3.b line 1407 expects admin to have explicit allow on `/api/v2/admissions/*/admin-rollback` and `/api/v2/admissions/bulk-publish-result`. With the diamond intact, those allow rules are overridden by inherited accountant deny → admin still denied → contradicts PLAN's "Admin: Full toàn bộ T1-T17 (kể cả T17 rollback)".

Resolution path **deferred** to follow-up (likely co-shipped with #15 wiring real /api/v2 internal staff routes):
- Drop `g, role:admin, role:accountant` diamond edge (admin's `/* .*` wildcard still grants admin everything; admin no longer transitively inherits accountant deny). Cleanest fix.
- OR custom matcher that scopes deny to direct subject (not transitive via g) — requires Casbin priority_effect / custom adapter.
- Either approach is wider scope than B1 atomic. B1 ships the deny rules + canonical lib effect; the diamond resolution is the right scope of #15 (when v2 routes go live + admin actually needs them).

The 4×14 matrix test EXPECTED matrix encodes admin DENY on v2 routes for now, with a docstring explaining the diamond conflict. Bite-verify confirms the matrix lock catches a removed deny rule (so the matrix isn't tautological).

**Out of scope (next code tasks, sequenced):**

- **#16** — wire `state_service.transition()` to call `dispatch_event()` for the 12 admission events. **Blocked until B1 + B2 are both TESTED on parent.** That's where the 12 `no-dispatch-site` gaps finally close.
- **#15** `approved → admitted` workflow remap + helpers — depends on B2; can ship parallel to #16 or co-ship with diamond admin↔accountant resolution.
- **Diamond admin↔accountant resolution** — drop the inheritance edge or add custom matcher; ships when /api/v2/* internal staff routes go live in #15.

**Blocked / decisions cần:**

- Review/merge B1 PR (when opened). Reviewer must NOT tick the `[ ] **B1**` checkbox on issue #183 until this PR merges + post-merge tests pass on parent. Single thematic checkbox covers B1 wave (single PR — not split).

**Tomorrow plan (sau merge B1):**

- Issue #183: tick `[ ] **B1**` checkbox (B1 wave is single PR — checkbox flips at merge, unlike B2 which had 4 sub-PRs).
- Card #181 [Task 0] eligible to move to Done if RUN_CASBIN_LOAD_ON_STARTUP gate verified in staging (D12-D14 smoke covers all 3 entrypoint flags + Casbin reload behavior).
- Start **#15 + #16 wave**: state_service.transition() through dispatch_event(); /api/v2 internal staff route wiring; diamond admin↔accountant resolution as part of that wave.

---

### B1 — sub-PR merged (post-merge sync)

**Sub-PR merged today (vào `feat/admission-full-cutover`):**
- PR [#201](https://github.com/favouritekid/QLTS/pull/201) — `[B1] feat(casbin): deny-first auth model + accountant deny rules + cold-cutover gate` — squash `6eac329e` (mergedAt `2026-05-03T05:57:46Z`, mergedBy `favouritekid` via `gh pr merge --squash --delete-branch=false`). Parent advanced `88c19c16 → 6eac329e`.

**Tested / Rehearsed:**
- Post-merge focused B1 re-run trên parent HEAD `6eac329e` (Docker `qlts-backend-1`):
  ```
  pytest tests/unit/test_casbin_b1_deny_first.py \
         tests/unit/test_phase1_19b_casbin_eft_backfill.py \
         tests/integration/test_casbin_b1_4x14_matrix.py \
         tests/api/test_casbin_tracking.py -q
  → 48 passed in 19.79s
  ```
- Post-merge full B1 + B2 regression (13 files): **225 passed, 1 skipped in 75.89s** (1 skip = pre-existing uncatalogued-enum branch trong dispatch_event wrapper).
- Live alembic upgrade trên parent dev DB:
  - `phase1_19a → upgrade head → phase1_19b (head)` ✓ — 210 row backfill v3='allow' + 6 INSERT deny rules accountant.
  - DB state verified: `SELECT v3, COUNT(*) FROM casbin_rule WHERE ptype='p' GROUP BY v3` → `allow=210, deny=6`.

**B-cluster wave closed:** B1 + B2 đều TESTED trên parent. **#16 (state_service.transition wiring through dispatch_event) đã unblocked**. Bắt đầu được khi user approve.

**Mức 1 board / issue checkbox:**
- Card #183 [Phase 1 Code] vẫn ở In Progress (B-cluster đóng, nhưng còn #15, #16, 3 CI tooling task).
- **B1 checkbox `[ ] **B1**` trên issue #183** PENDING tick — chờ post-merge tracking commit này lands per SOP.

**Coverage script invariant:**
- 12 expected `no-dispatch-site` (admission_*) — baseline preserved; sẽ green sau #16 wires `state_service.transition()`.
- 0 raw-dispatch-of-outbox-event violations.

**Next:**
- Tick `[ ] **B1**` checkbox trên issue #183 sau khi post-merge tracking commit lands.
- Start #16 wave: wire `state_service.transition()` qua `dispatch_event()` cho 12 admission events. Đây là code task tạo real dispatch sites + turn coverage script green.
- Diamond admin↔accountant resolution + admin v2 allow rules per PLAN §3.3.b line 1407 → co-ship với #15 wiring khi /api/v2/admissions/* internal staff routes go live.

---

## 2026-05-02

**Sub-PR merged today (vào `feat/admission-full-cutover`):**
- PR [#189](https://github.com/favouritekid/QLTS/pull/189) — `[T0-1] feat(admission): add entrypoint cutover gates`
  - Squash merge SHA: `bebb31feceb451fb72995c554ac512a72ecba604` (mergedAt 2026-05-02T04:46:55Z)
  - Base: `feat/admission-full-cutover` ← Head: `feature/admission-t0-1` (3 commits squashed: `74ed8b94` + `4c439a27` + `b8d1fa79`)
  - Files: 6 changed (+133 / -25). Pre-merge: Mergeable ✓. Body cover 2 flag + 14-case test matrix + 6 file changes + cutover scenario + defensive default + thematic #181 link.
  - **CI: no checks reported** (repo workflow trigger filter chưa cover PR vào `feat/admission-full-cutover`). Manual verification thay thế: pre-merge `bash -n` PASS + 14-case logic matrix PASS local; post-merge 14-case re-run trên parent branch HEAD `bebb31fe` cũng PASS (mock alembic + python).

**Project board update (Mức 1 pattern):**
- Thematic card #181 manual moved Todo → In Progress (sub-PR T0-1 đầu tiên thuộc thematic đã start). Board state: Todo 7 / In Progress 1 / Done 0.
- Move qua chrome-devtools UI (More actions → Move to column → In Progress). gh CLI `project` mutations cần scope `read:project,project` không sẵn.
- **KHÔNG move card #181 sang Done** sau T0-1 merge: thematic gồm T0-1..T0-5 (5 sub-task), mới ship 1/5. Card chỉ → Done khi cả 5 (T0-1, T0-2, T0-3, T0-4a, T0-4b ship sau B2+M-1-19a, T0-5) đều merged.

**Pushed hôm nay** (origin/feature/admission-t0-1):

1. `74ed8b94` — `docs(admission): split T0-4 + lock hotfix same-day cherry-pick policy`
   - C1: TRACKER Section 1 — T0-4 split → T0-4a (no-op skeleton, no dep) + T0-4b (real worker, dep B2 + M-1-19a). Section 12.3 production readiness checklist tương ứng.
   - C2: DAILY_LOG header — hotfix policy explicit (same-day cherry-pick OR equivalent-patch mandatory; KHÔNG defer to cutover; pause 0.5-1d nếu conflict touch admission core/state/lead/notification/RBAC).

2. `4c439a27` — `feat(admission): add 2 entrypoint env flag gates (T0-1)`
   - `Backend_FastAPI/docker-entrypoint.sh`: 2 gate độc lập:
     - Gate 1: `RUN_MIGRATIONS_ON_STARTUP` (default `true`) — skip `alembic upgrade head` khi `false`.
     - Gate 2: `RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP` (default `true`) — skip `sync_notification_rules` khi `false`.
   - Default behavior preserved khi cả 2 unset (routine deploy chạy alembic + sync như cũ).
   - Cutover scenario set CẢ 2 = `false` → container start chỉ uvicorn ready; manual run alembic + backfill + sync_notification_rules ngoài container ở T+1:30 / T+3:00 / T+3:30.
   - `Backend_FastAPI/CLAUDE.md`: Common Commands note 2 flag cutover-only.
   - `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md` §3.5 + §7.2 + §9.3 update reflect 2 flag.
   - `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md`: T0-1 status TODO → CODE_DONE (branch pushed).

**Tested / Rehearsed:**
- T0-1 — `bash -n` syntax PASS. 14-case logic test PASS:
  - 9-case matrix (3 RUN_MIGRATIONS × 3 RUN_SYNC):
    - unset×unset / unset×true / unset×false / true×unset / true×true / true×false / false×unset / false×true / false×false → expected output match
    - Cutover combo `false×false` → cả 2 skip ✓
    - Default `unset×unset` → cả 2 run (current behavior preserved) ✓
  - 5 defensive variant: TRUE / FALSE / typo / 0 / "False" capitalize → đều run (chỉ exact lowercase "false" skip) ✓

**Blocked / decisions cần:**
- (none) — T0-1 unblock cho staging smoke khi clone D12-D14. T0-2..T0-5 không depend T0-1, có thể start parallel.

**Tomorrow plan:**
- Start T0-2 (`ADMISSION_FROZEN` middleware) — independent của T0-1, parallel. Branch: `feature/admission-t0-2`.
- Start T0-3 (Nginx admission block) — Ops owner, parallel. Branch: `feature/admission-t0-3`.
- Start T0-4a skeleton (no-op safe registration) — đã unblock. Branch: `feature/admission-t0-4a`.
- Start T0-5 (Casbin reload endpoint) — independent, parallel. Branch: `feature/admission-t0-5`.
- T0-1 staging smoke: chờ staging clone D12-D14 (ngoài scope hôm nay).

**Notes:**
- C3 patch áp dụng ngay sau khi user catch oversight: T0-1 ban đầu chỉ gate Alembic, vẫn auto chạy `sync_notification_rules` → cutover deploy backend `RUN_MIGRATIONS_ON_STARTUP=false` sẽ vẫn chạy sync rules trên empty schema → script fail/race. Add gate riêng cho sync.
- Branch đã push; KHÔNG rewrite history. Mọi cleanup setup docs sau push đi bằng commit bổ sung trên `feature/admission-t0-1`.
- Test framework cho bash entrypoint: chỉ syntax check + logic test, không có integration framework. Manual smoke trong staging clone D12-D14 sẽ verify end-to-end (apply 2 flag, observe entrypoint output, smoke API ready).
- Q11 closed (PLAN §3.3.g.1) → KHÔNG còn product decision blocker; D2 + D3 chỉ chặn cutover, không chặn dev start.

### T0-3 — Nginx admission block (sub-PR merged)

**Branch:** `feature/admission-t0-3` off `feat/admission-full-cutover` HEAD `691e6457`. Pushed `fbbe22d0` 2026-05-02; sub-PR [#191](https://github.com/favouritekid/QLTS/pull/191) opened + merged squash `092a12bd` cùng ngày (mergedAt 2026-05-02T10:30:06Z). Base `feat/admission-full-cutover`, kept branch (`--delete-branch=false`). Status: **TESTED**, DONE pending staging smoke.

**CI manual verification (no checks reported pattern T0-1 + T0-2 + T0-3 đều cùng):**
- Pre-merge: `bash scripts/test_nginx_admission_freeze.sh` → 32/32 PASS (3-layer harness, < 5s sau Docker image cached).
- Post-merge re-run trên parent HEAD `092a12bd`: 32/32 PASS.
- Repo workflow filter chưa cover PR vào `feat/admission-full-cutover` → CI tự động không chạy. Manual verification thay thế ghi trong TRACKER + DAILY_LOG đủ pass-fail evidence cho 3 layer (render + syntax + regex URI). Layer 4 (live HTTP smoke) deferred staging.

Defense-in-depth pair với T0-2 backend middleware vừa ship: edge layer chặn ngay tại Nginx, trước khi traffic chạm FastAPI.

**Scope:**
- `nginx/conf.d/default.conf.template`: thêm regex location `^/api/(admissions|admission-config|public/admissions)(/.*)?$` đặt TRƯỚC prefix `location /api/` (regex thắng anyway, đặt trước cho rõ intent). Trong block: `set $freeze_check "$request_method:${NGINX_ADMISSION_FROZEN}"` + `if ($freeze_check ~ "^(POST|PUT|PATCH|DELETE):true$") { return 503 '{"detail":"...","code":"NGINX_ADMISSION_FROZEN"}'; }` + fall through `proxy_pass http://backend` cho read methods và non-admission flow. Bare prefix + subpath đều match nhờ `(/.*)?$` optional group.
- `scripts/deploy.sh` Step 3: thêm `${NGINX_ADMISSION_FROZEN}` vào envsubst allowlist + default `"${NGINX_ADMISSION_FROZEN:-false}"` để khi ops chưa set thì template emit `false` (regex `:true$` không match → gate mở).
- `scripts/test_nginx_admission_freeze.sh` (mới): 3-layer test harness Docker-driven (render layer + syntax layer + regex layer).

**Drift catch + fix verified:**
- RUNBOOK §6.1 line 244 + line 310 + §8 rollback line 376/418 dùng `NGINX_ADMISSION_FROZEN=1` / `=0` (numeric). Convention thực tế match T0-2: chỉ exact lowercase `"true"` enable, mọi value khác (`false`/unset/typo/`1`/`0`) đều disable. Sửa: `=1` → `=true`, `=0` → `=false` toàn bộ 4 chỗ trong RUNBOOK.
- §6.1 cũng cập nhật reload procedure: KHÔNG còn "edit env file rồi nginx reload trực tiếp" (nginx container nhận file mounted, envsubst chạy ở host). Đúng quy trình: edit `.env.production` → `bash scripts/deploy.sh` (Step 3 envsubst regenerate) → `docker compose --profile production exec -T nginx nginx -s reload`.

**Tested / Rehearsed:**
- T0-3 — `bash scripts/test_nginx_admission_freeze.sh` PASS 32/32 (re-run sau Docker image cached, < 5s):
  - **15 render-layer** assertions (3 flag values × 5 markers): regex location, `set $freeze_check`, flag substitution literal, `return 503`, `code: NGINX_ADMISSION_FROZEN`. Confirms envsubst với `${NGINX_ADMISSION_FROZEN}` allowlist hoạt động đúng cho `false` / `true` / unset (empty literal).
  - **3 syntax-layer** `nginx -t` (3 flag values) trong throw-away `nginx:1.27-alpine` container chống isolated minimal config (không cần SSL certs). Verifies nginx grammar accept `if ... ~ ...` regex condition + return 503 inline JSON.
  - **14 regex-layer** URI match cases (bash POSIX ERE simulating nginx PCRE; 7 should-match + 7 should-NOT-match): bare prefix, subpath, `/api/admissionsfoo` lookalike, legacy plurals (`admission-configs`, `admission-paths`), non-admission baseline (`/api/leads/123`, `/api/admin/users`, `/health`).
  - **First run had 1 spurious FAIL** trên syntax-layer test #1: Docker image pull progress interleaved với `nginx -t` output → `grep -q "test is successful"` race condition. Re-run sau image cached → 32/32 PASS clean. Bug ghi nhận trong harness comment; future runs trên CI sẽ không gặp vì image pre-pulled.

**Test scope limitation (deferred to staging):**
- Live HTTP functional smoke (POST /api/admissions/test → 503; GET → pass-through; non-admission unaffected) **KHÔNG chạy local** vì cần SSL certs tại `/etc/letsencrypt/live/${DOMAIN}/...` + live upstream backend. Sẽ verify trong staging clone D12-D14 cutover rehearsal: apply `NGINX_ADMISSION_FROZEN=true` → `bash scripts/deploy.sh` → curl matrix.
- Reload mechanism (nginx -s reload picks up new config sau envsubst regenerate) **KHÔNG test local**; verify trong staging.

**Files changed:**
- `nginx/conf.d/default.conf.template` (+19 lines: regex location + freeze_check `if` + 503 JSON + fall-through proxy_pass).
- `scripts/deploy.sh` (Step 3: +5 lines, envsubst allowlist + default value).
- `scripts/test_nginx_admission_freeze.sh` (mới, ~145 lines: 3-layer Docker test harness).
- `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md` (drift fix §6.1 + §6.1 reload procedure + §7.2 cutover step + §8 rollback step).
- `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` (T0-3 row CODE_DONE + Section 12.3 wording).
- `Documents/ADMISSION_DAILY_LOG.md` (entry này).

**Blocked / decisions cần:**
- Push approval cho `feature/admission-t0-3` + sub-PR creation → `feat/admission-full-cutover`.

**Tomorrow plan (sau merge T0-3):**
- T0-4a `dispatch_pending_outbox` Celery beat skeleton (BE) — independent, no-op safe trước B2 + M-1-19a.
- T0-5 `POST /api/v2/admin/casbin/reload` admin endpoint (BE) — independent.
- T0-1/T0-2/T0-3 đều TESTED → DONE chờ staging clone D12-D14 smoke (3 task pair test cùng trong staging rehearsal).

**Notes:**
- Defense-in-depth: T0-3 Nginx returns 503 trước khi traffic vào FastAPI; nếu Nginx bị bypass (internal Docker, healthcheck) thì T0-2 middleware sẽ catch. Hai gate độc lập, cùng convention `=true` → enable.
- Convention chuẩn cross-task: cả T0-1 (RUN_MIGRATIONS_ON_STARTUP, RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP) + T0-2 (ADMISSION_FROZEN backend) + T0-3 (NGINX_ADMISSION_FROZEN) đều exact lowercase string match. T0-1 dùng `false` để skip, T0-2/T0-3 dùng `true` để enable. Defensive default: typo → "safe" behavior (T0-1 chạy migrations, T0-2/T0-3 không freeze).
- Nginx `if` directive rule "if is evil": chỉ dùng cho `return` + `set` directives — pattern an toàn. Pattern combined regex `$request_method:$flag` cho phép single `if` block thay vì nested.

**Review feedback applied (post-commit `c574d49a`):**
- **P1** (rollback ops drift) — RUNBOOK §8 Rollback Step 1 (re-freeze trong rollback window) + Step 6 (unlock sau smoke PASS) sửa env xong gọi `nginx -s reload` trực tiếp. Với T0-3 envsubst-bake-at-deploy-time, reload đơn lẻ sẽ load `nginx/conf.d/default.conf` CŨ → freeze edge layer fail-stale (Step 1: KHÔNG bật freeze; Step 6: KHÔNG tắt freeze). Patch: thêm `set -a && source .env.production && set +a` + `envsubst '${DOMAIN} ${NGINX_ADMISSION_FROZEN}' < template > default.conf` + `nginx -t` ngay trước `nginx -s reload` ở cả 2 step.
- **P2** (cutover timeline) — RUNBOOK §7.2 timeline T+0:15 single-line gộp cả "Set env + Nginx reload" thiếu regenerate step. Cùng pattern P1 — ops sẽ reload config cũ + freeze edge layer không bật. Patch: expand T+0:15 thành block 4 step rõ (edit env → envsubst regenerate → restart backend + nginx -t + nginx -s reload → curl verify cả 2 layer block).
- **Cross-check sau patch**: 4 reload site trong RUNBOOK (§6.1 + §7.2 T+0:15 + §8 rollback Step 1 + §8 rollback Step 6) đều có envsubst regenerate ngay TRƯỚC `nginx -s reload`. §6.1 đã đúng từ T0-3 commit ban đầu; 3 site còn lại patch trong commit follow-up.

---

### T0-4a — `dispatch_pending_outbox` Celery beat skeleton (sub-PR merged)

**Branch:** `feature/admission-t0-4a` off `feat/admission-full-cutover` HEAD `46461d12`. Pushed `fbc1e6bf` + post-PR docs `e1140d00` 2026-05-02; sub-PR [#192](https://github.com/favouritekid/QLTS/pull/192) opened + merged squash `e239ba35` cùng ngày (mergedAt 2026-05-02T11:16:28Z). Base `feat/admission-full-cutover`, kept branch (`--delete-branch=false`). Status: **TESTED**, DONE pending staging smoke.

**CI manual verification (no checks reported pattern T0-1 + T0-2 + T0-3 + T0-4a đều cùng):**
- Pre-merge: `pytest tests/unit/test_outbox_skeleton.py tests/unit/test_celery_task_registry.py -v` → 13/13 PASS in Docker (2.70s).
- Post-merge re-run trên parent HEAD `e239ba35`: 13/13 PASS (2.48s).
- Subprocess cold-import regression test bite-verified: revert `import app.tasks` ở cuối `celery_app.py` → FAIL với `non_builtin_tasks=[]`; restore → PASS.
- Repo workflow filter chưa cover PR vào `feat/admission-full-cutover` → CI tự động không chạy; manual evidence trong TRACKER + DAILY_LOG đủ pass-fail.

Skeleton-only ship: register beat 30s + task name `dispatch_pending_outbox`, no-op body returning structured `{"status": "skipped", "reason": "outbox_not_active", "task_id": "T0-4a"}`. T0-4b (gated trên B2 + M-1-19a) sẽ replace body trong cùng module + cùng task name; beat schedule entry stable.

**Scope:**
- `Backend_FastAPI/app/tasks/notification_outbox_tasks.py` (mới): module mới chứa `dispatch_pending_outbox` skeleton task. Imports chỉ `logging` + `celery_app` — KHÔNG import `NotificationOutbox` model (chưa tồn tại trước M-1-19a). Docstring lock-in contract cho T0-4b: giữ task name + module path + result keys `status`/`reason`/`task_id`.
- `Backend_FastAPI/app/celery_app.py`: thêm beat schedule entry `dispatch-pending-outbox` (30.0s, queue `default`) sau `check-notification-alerts` block. Comment trỏ T0-4b sẽ replace body, không touch entry.
- `Backend_FastAPI/app/tasks/__init__.py`: import + re-export `dispatch_pending_outbox` (match pattern existing test guard `test_every_beat_scheduled_task_is_registered` — đảm bảo task registered trong celery_app.tasks dict, không silent-discard khi beat fire).
- `Backend_FastAPI/tests/unit/test_outbox_skeleton.py` (mới): 11 lock-in test — beat cadence + static `conf.include` config + subprocess cold-import regression + post-import sanity + return-shape + AST no-NotificationOutbox import-safety (skeleton module + `__init__.py`) + models package gap canary + autodiscover smoke + zero-arg signature contract.

**Tested / Rehearsed:**
- T0-4a — `pytest tests/unit/test_outbox_skeleton.py tests/unit/test_celery_task_registry.py -v` PASS **13/13** trong Docker (2.73s post-fix; 1.03s pre-fix):
  - 1 beat-schedule cadence: `dispatch-pending-outbox` entry tồn tại + task name `dispatch_pending_outbox` + schedule = 30.0s.
  - **1 static `conf.include` config check** (post P1 fix): `"app.tasks" in celery_app.conf.include` — locks worker entrypoint declaration.
  - **1 subprocess cold-import regression test** (post P2 fix): spawn `python -c "from app.celery_app import celery_app"` không call finalize/import_default_modules → assert `dispatch_pending_outbox` đã registered. Bite-verified: revert `import app.tasks` ở cuối `celery_app.py` → FAIL với `non_builtin_tasks=[]`; restore → PASS.
  - 1 post-import sanity (renamed cũ): sau `import app.tasks` task có trong registry — sanity check, KHÔNG phải worker-boot guarantee.
  - 1 export contract: `from app.tasks import dispatch_pending_outbox` resolvable + callable.
  - 1 result-shape stability lock: skeleton return dict có `status="skipped"` + `reason="outbox_not_active"` + `task_id="T0-4a"` (load-bearing cho T0-4b — T0-4b sẽ flip `task_id` → `"T0-4b"` + có thể thêm key, KHÔNG drop).
  - 2 AST-based import-safety guards: skeleton module + tasks `__init__.py` không có code-level reference `NotificationOutbox` (docstring/comment OK; AST walk imports + Name + Attribute nodes).
  - 1 model-gap assertion: `models.NotificationOutbox` vẫn không tồn tại (sau M-1-19a ship → fail loud → trigger T0-4a retire + T0-4b plan).
  - 1 autodiscover smoke: `importlib.find_spec("app.tasks.notification_outbox_tasks")` resolvable + module import safe + decorator gắn task name đúng.
  - 1 zero-arg signature contract: `dispatch_pending_outbox` signature không có required args (beat fire không pass args).
  - 2 existing celery-task-registry tests (regression check): `test_every_beat_scheduled_task_is_registered` + `test_previously_unregistered_finance_and_ctv_tasks_are_registered` — đều PASS sau khi thêm task mới + beat entry mới.

**Test scope limitation (deferred):**
- KHÔNG test live Celery worker tick (cần Celery worker process + Redis broker + beat scheduler chạy thực) — `bash scripts/test_nginx_admission_freeze.sh`-style live integration không apply ở đây vì Celery worker đang chạy trong Docker compose stack background, không phải đối tượng of unit test.
- KHÔNG test schedule actually firing every 30s in real time — Celery beat live behavior verify trong staging clone (apply T0-4a → quan sát log "skeleton tick" 30s/lần trong worker output → confirm).

**Drift catch (KHÔNG): KHÔNG verified drift trong code/docs/PLAN/RISK liên quan T0-4a này. PLAN §3.3.e + RUNBOOK §3.5 T0-4a wording match implementation. Không touch PLAN/RISK.

**Files changed:**
- `Backend_FastAPI/app/tasks/notification_outbox_tasks.py` (new, ~60 lines: skeleton task + docstring + result dict).
- `Backend_FastAPI/app/celery_app.py` (+12 lines: beat schedule entry).
- `Backend_FastAPI/app/tasks/__init__.py` (+5 lines: import + re-export + __all__ entry).
- `Backend_FastAPI/tests/unit/test_outbox_skeleton.py` (new, ~250 lines: 11 lock-in tests including subprocess cold-import regression + static include config check after P1+P2 review fix).
- `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` (T0-4a row CODE_DONE + Section 12.3 row CODE_DONE).
- `Documents/ADMISSION_DAILY_LOG.md` (entry này).

**Blocked / decisions cần:**
- Push approval cho `feature/admission-t0-4a` + sub-PR creation → `feat/admission-full-cutover`.

**Tomorrow plan (sau merge T0-4a):**
- T0-5 `POST /api/v2/admin/casbin/reload` admin endpoint (BE) — last sub-task of thematic #181 cụm Task 0; standalone, không depend gì.
- B2 + M-1-19a (Phase 1 wave) sau Task 0 đầy đủ → unblock T0-4b real worker.

**Notes:**
- `test_models_package_still_lacks_notification_outbox` là **canary test** — sẽ fail khi M-1-19a ship + add `NotificationOutbox` model. Đây là tín hiệu cố ý: trigger ops retire T0-4a skeleton + ship T0-4b real worker. Test phải fail loud, không phải bug.
- Stable shape `{"status", "reason", "task_id"}`: T0-4b sẽ flip `task_id` → `"T0-4b"`, có thể bổ sung key `claimed`/`dispatched`/`failed` count, nhưng KHÔNG drop 3 key gốc — dashboards monitoring T0-4a tick trong staging dry-run window vẫn tương thích.
- Beat schedule entry name `dispatch-pending-outbox` (kebab) ≠ task name `dispatch_pending_outbox` (snake). Convention repo: schedule entry kebab-case, task name snake_case. Match existing pattern (`check-consultation-reminders-every-minute` → `check_consultation_reminders_task`).

**Review feedback applied (post-commit `1b627167`):**
- **P1** (worker entrypoint task registration) — User catch: `celery -A app.celery_app worker/beat` chỉ import `app.celery_app`. Verified container: `from app.celery_app import celery_app` cold → `dispatch_pending_outbox` registered = False (0 business tasks). Sau `loader.import_default_modules()` (worker boot internally) hoặc explicit `import app.tasks` mới register. Risk: bất kỳ consumer cold-import (FastAPI process via `celery_utils` để `.delay()`, ad-hoc REPL, pytest helper khác) sẽ thấy registry rỗng + `send_task` fire vào registry trống → silent discard. Patch belt-and-suspenders: (a) `include=["app.tasks"]` vào `Celery()` constructor (worker boot path via `loader.import_default_modules`); (b) explicit `import app.tasks` ở cuối `celery_app.py` (cold import path cho mọi consumer khác). Bottom placement tránh circular import (task modules import `from ..celery_app import celery_app`).
- **P2** (test mask actual gap) — User catch: existing `test_dispatch_pending_outbox_is_registered_on_celery_app` do `import app.tasks` trước khi assert → cheat, pass kể cả khi worker entrypoint thật fail. Patch: tách 3 test rõ vai trò:
  - `test_celery_app_explicitly_includes_app_tasks_package` — static config check `app.tasks in celery_app.conf.include` (cheap, deterministic).
  - `test_worker_entrypoint_registers_outbox_task_without_explicit_app_tasks_import` — **subprocess fresh-process** test simulating cold consumer. Spawns `python -c "from app.celery_app import celery_app; assert ..."` không call finalize/import_default_modules — chính xác user prescription.
  - `test_dispatch_pending_outbox_registers_after_app_tasks_import` — renamed cũ; rõ ràng đây là sanity post-`import app.tasks`, KHÔNG phải worker-boot guarantee.
- **Bite test verification**: temporarily revert `import app.tasks` ở cuối `celery_app.py` → subprocess test FAIL với `non_builtin_tasks=[]`; restore → PASS. Subprocess test thực sự catch regression, không phải tautology.
- Test count 9 → 11 (added static include + subprocess fresh; renamed/clarified existing). Total suite 11 + 2 existing celery_task_registry = **13/13 PASS** (2.73s in Docker).

---

### T0-5 — `POST /api/v2/admin/casbin/reload` admin endpoint (sub-PR merged)

**Branch:** `feature/admission-t0-5` off `feat/admission-full-cutover` HEAD `edd055a1`. Pushed `c952c699` + post-PR docs `f5e1359d` 2026-05-02; sub-PR [#193](https://github.com/favouritekid/QLTS/pull/193) opened + merged squash `9d34e820` cùng ngày (mergedAt 2026-05-02T12:35:00Z). Base `feat/admission-full-cutover`, kept branch (`--delete-branch=false`). Status: **TESTED**, DONE pending staging smoke.

**CI manual verification (no checks reported pattern T0-1 + T0-2 + T0-3 + T0-4a + T0-5 đều cùng):**
- Pre-merge: `pytest tests/api/test_admin_v2_casbin_reload.py -v` → 9/9 PASS in Docker (58.19s).
- Post-merge re-run trên parent HEAD `9d34e820`: 9/9 PASS (56.67s).
- Repo workflow filter chưa cover PR vào `feat/admission-full-cutover` → CI tự động không chạy; manual evidence trong TRACKER + DAILY_LOG + PR body table đủ pass-fail.

**Wording chuẩn (post P1+P2 review):** endpoint là **current-process diagnostic only**; fleet-wide reload = backend restart per §7.2 T+3:15. Cutover-only HTTP surface để runbook trigger smoke/diagnostic Casbin reload sau restart, KHÔNG dùng làm cơ chế reload chính.

**Scope strict (B1 boundary):**
- Endpoint ONLY: `POST /api/v2/admin/casbin/reload`. Path prefix `/api/v2/admin/casbin` tách khỏi v1 admin tree (`/api/admin/...`).
- Reload runtime ONLY: gọi `enforcer.load_policy()` trên `request.app.state.enforcer` đã set tại lifespan. KHÔNG instantiate enforcer mới.
- KHÔNG touch: `auth_model.conf` (Casbin model), deny block, policy templates, `policy_templates.py` registry. Tất cả thuộc B1 RBAC refactor wave (Phase 1 Code task gates).
- Architecture compliance: auth/RBAC ở `Depends(require_admin)` deps (raise `PermissionDeniedError` nếu non-admin). Router thin coordinator: nhận request → call enforcer → audit log → return.

**Response shape (locked-in):**
- Success 200: `{"success": True, "reloaded_at": "<iso>", "policy_count": <int|null>, "actor_id": <int>}`. `policy_count` informational (qua `len(enforcer.get_policy())`); fallback `None` nếu accessor exception (KHÔNG turn success → 500).
- Failure 500: `{"success": False, "reloaded_at": "<iso>", "error": "<str>", "actor_id": <int>}`. Enforcer giữ in-memory state cũ — KHÔNG partial flush, worker/API stay serviceable.

**Audit log:**
- Success path: `activity_service.log_activity(action="casbin_reload", resource_type="casbin_policy", changes={"policy_count": <int>}, ip_address, user_agent)` + `db.commit()`.
- Failure path: best-effort `action="casbin_reload_failed"` audit. Nếu audit cũng fail → log warning, KHÔNG mask original error (defensive try/except chỉ wrap audit, không wrap reload result).

**Tested / Rehearsed:**
- T0-5 — `pytest tests/api/test_admin_v2_casbin_reload.py -v` PASS 9/9 trong Docker (60.70s — chậm vì mỗi test set up DB fixture + auth flow):
  - `test_admin_can_reload_casbin_policy`: admin → 200 + response shape (success/reloaded_at ISO/policy_count/actor_id).
  - `test_admin_reload_returns_non_negative_policy_count_when_present`: nếu `policy_count` trả int thì >= 0.
  - `test_unauthenticated_caller_denied`: no auth header → 401.
  - `test_manager_caller_denied`: manager token → 403 (admin-only enforced).
  - `test_officer_caller_denied`: officer token → 403.
  - `test_regular_user_caller_denied`: user token → 403.
  - `test_reload_failure_surfaces_500_without_crashing`: monkeypatch `fastapi_app.state.enforcer.load_policy` raise `RuntimeError` → 500 + structured body (success=False, error contains "simulated DB unreachable", actor_id, reloaded_at). Defensive restore trong try/finally để tránh subsequent test bị poison.
  - `test_subsequent_reload_after_failure_recovers`: bad reload (stub raise) → 500 → restore stub → next reload → 200. Verifies enforcer KHÔNG bị poison sau failure (resilience guard against runbook's "worker stuck on stale enforcer" failure mode).
  - `test_reload_endpoint_registered_at_documented_path`: lock URL contract — `POST /api/v2/admin/casbin/reload` route tồn tại trong `fastapi_app.routes`, prevent path drift breaking runbook recipe.

**Test scope limitation:**
- KHÔNG test live cutover scenario (seed deny rules direct DB → call reload → verify policy active) trong unit test — cần seed migration rồi mới reload. Sẽ verify staging clone D12-D14 cutover rehearsal.
- KHÔNG test rate limit (endpoint không có `@limiter.limit` decorator — admin-only + cutover-only, không cần rate gate; nếu cần thêm sau B1).

**Drift catch (KHÔNG): Wording RUNBOOK §3.5 T0-5 + PLAN match implementation. KHÔNG touch PLAN/RISK.

**Files changed:**
- `Backend_FastAPI/app/routers/admin_v2_casbin.py` (new, ~115 lines: endpoint + docstring lock B1 boundary + response shapes + audit log).
- `Backend_FastAPI/app/main.py` (+2 lines: import `admin_v2_casbin` + `include_router`; router declares full prefix nên KHÔNG cần `prefix=` ở include).
- `Backend_FastAPI/tests/api/test_admin_v2_casbin_reload.py` (new, ~165 lines: 9 lock-in tests).
- `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` (T0-5 row CODE_DONE + Section 12.3 row CODE_DONE).
- `Documents/ADMISSION_DAILY_LOG.md` (entry này).

**Blocked / decisions cần:**
- Push approval cho `feature/admission-t0-5` + sub-PR creation → `feat/admission-full-cutover`.

**Tomorrow plan (sau merge T0-5):**
- 5/6 sub-task thematic #181 ship xong (T0-1 + T0-2 + T0-3 + T0-4a + T0-5). Card #181 vẫn In Progress vì T0-4b gated trên B2 + M-1-19a.
- Kế hoạch Phase 1 Code task gates: B1 (Casbin auth_model deny-first + 16 deny rules), B2 (EventDefinition extend + NotificationOutbox model + migration M-1-19a) — unblock T0-4b downstream.

**Notes:**
- Path prefix `/api/v2/admin/casbin` tách v2 — sau cutover deploy, route này vẫn live nhưng admin-only sẽ ít dùng (chỉ trigger thủ công khi seed direct DB). Nếu post-cutover cần retire, sẽ deprecate trong cleanup wave.
- Defensive `try/except` cho `enforcer.get_policy()` count: nếu accessor crash trên broken state, KHÔNG turn 200 → 500 (count chỉ informational).
- Failure audit log best-effort: nếu DB/audit_service down cùng lúc → silent log warning, return original error nguyên vẹn — caller nhận đúng nguyên nhân.

**Review feedback applied (post-commit `c92b3601`):**
- **P1 multi-worker reality** (operational gap) — User catch: `request.app.state.enforcer` build per-process tại lifespan; production Gunicorn `workers = min(GUNICORN_WORKERS, 4)`. Endpoint chỉ reload 1 worker process nhận HTTP request; workers còn lại giữ stale enforcer → policy enforcement không nhất quán (request A deny, request B allow tùy worker). Patch:
  - **Code**: Module docstring + endpoint docstring rephrase explicit "single-process reload only — NOT a production-wide guarantee". Response shape add field `"scope": "current_process"` (cả success path lẫn failure path) — machine-readable signal cho monitoring để phân biệt diagnostic vs fleet-wide reload.
  - **Test**: `test_admin_can_reload_casbin_policy` + `test_reload_failure_surfaces_500_without_crashing` lock `body["scope"] == "current_process"` — endpoint không thể silent masquerade là fleet-wide.
  - **RUNBOOK §7.2 T+3:00 → T+3:15**: thêm bước **restart backend container** sau Casbin seed deny rules (giữ 2 cutover env flags `RUN_MIGRATIONS_ON_STARTUP=false` + `RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=false` để tránh re-trigger auto-migration/sync). Verify lifespan boot success từ ALL Gunicorn workers (≥2 dòng "Casbin AsyncEnforcer initialized" trong log). Endpoint kept như diagnostic post-restart — KHÔNG cơ chế reload chính.
  - **RUNBOOK §3.5 T0-5**: rephrase "Cutover safety" → "Diagnostic / smoke reload". Why column nói rõ "Chỉ tác động 1 Gunicorn worker — KHÔNG fleet-wide. Cutover-correct reload là restart backend container".
  - **RUNBOOK §9.3 readiness**: T0-5 checkbox add "Multi-worker reality: fleet-wide reload = restart backend (§7.2 T+3:15); endpoint = current-process diagnostic only".
- **P2 missing rate limit** — User catch: admin endpoints khác (role/policy CRUD) đều có `@limiter.limit(RateLimits.ADMIN_WRITE)`; endpoint mới T0-5 thiếu → có thể hammer DB/adapter. Patch: import `from app.core.rate_limits import RateLimits, limiter` + `@limiter.limit(RateLimits.ADMIN_WRITE)` decorator (above `@router.post`). Match baseline existing admin surface.
- **Test re-verify**: `pytest tests/api/test_admin_v2_casbin_reload.py -v` → 9/9 PASS (56.31s) sau khi add scope field assert + rate limit decorator. Test count unchanged (cùng 9 case nhưng 2 case mở rộng assert).

---

### P0c — `admission_config_repository.py` field-name hot-fix (sub-PR merged)

**Branch:** `feature/admission-p0c` off `feat/admission-full-cutover` HEAD `e5f607b4`. Pushed `ed21f1d1` + post-PR docs `b0a34afa` 2026-05-02; sub-PR [#194](https://github.com/favouritekid/QLTS/pull/194) opened + merged squash `36d095a4` cùng ngày (mergedAt 2026-05-02T13:02:29Z). Base `feat/admission-full-cutover`, kept branch (`--delete-branch=false`). Status: **TESTED**, DONE pending staging smoke / Phase 1 full-integration wave.

**CI manual verification (no checks reported pattern P0c đầu tiên ngoài cụm T0):**
- Pre-merge: `pytest tests/repositories/test_admission_config_repository_p0c.py -v` → 6/6 PASS in Docker (0.34s).
- Post-merge re-run trên parent HEAD `36d095a4`: 6/6 PASS (0.44s).
- Bite-verified pre-merge: revert 1 site → 4/6 FAIL (3 behaviour AttributeError + 1 source-grep), restore → 6/6 PASS.
- Repo workflow filter chưa cover PR vào `feat/admission-full-cutover` → CI tự động không chạy; manual evidence trong TRACKER + DAILY_LOG đủ pass-fail.

Phase 0 hot-fix scope-tight; KHÔNG đụng B1/B2 hay migration nào khác.

**Drift verified-from-code:**
- PLAN §3.4 line 95 + §8 cheat sheet 4429-4430 đã track: code reference `admission_criteria_id`, model field thực tế `criteria_id`.
- Grep verified 2 site duy nhất ngoài comment/docstring/alembic-table-name:
  - `app/repositories/admission_config_repository.py:76` — `OfferingAdmissionConfig.admission_criteria_id`
  - `app/repositories/admission_config_repository.py:84` — `AdmissionPath.admission_criteria_id`
- Model thực tế:
  - `app/models/admission_config/offering_config.py:38` — `criteria_id = Column(...)`
  - `app/models/admission_config/admission_path.py:82` — `criteria_id = Column(...)`
- Caller path: `admission_config_service.delete_criteria()` line 182 gọi `repo.check_criteria_usage()`. Pre-fix path: SQLAlchemy `.where(SomeModel.bad_attr == ...)` raise `AttributeError` ngay tại expression construction → handler trả 500 thay vì `BusinessRuleViolation("Cannot delete criteria...")`. Silent broken admin DELETE flow.
- Alembic refs (`ix_admission_criteria_id` index, `admission_criteria_id_seq` sequence) là DB-level NAMES cho table `admission_criteria` — **khác namespace**, KHÔNG trong scope P0c.

**Patch:**
- `app/repositories/admission_config_repository.py` lines 76 + 84: `admission_criteria_id` → `criteria_id`. Function docstring extend ghi lý do hot-fix + cross-ref model file:line + ref test file lock-in.
- KHÔNG đụng B1 (auth_model.conf / Casbin), KHÔNG đụng B2 (EventDefinition / NotificationOutbox), KHÔNG migration mới.

**Tested / Rehearsed:**
- P0c — `pytest tests/repositories/test_admission_config_repository_p0c.py -v` PASS 6/6 trong Docker (0.34s):
  - 3 behaviour (mock DB session): `check_criteria_usage` returns_false_when_unused / returns_true_when_offering_uses_it / returns_true_when_path_uses_it. SQLAlchemy expression construction (`getattr(Model, attr_name)` tại `.where(...)` line) verify model attribute resolve đúng — pre-fix sẽ raise `AttributeError` ngay test 1.
  - 2 model-contract assertions: `OfferingAdmissionConfig` + `AdmissionPath` đều expose `criteria_id` AND không expose `admission_criteria_id`. Lock chống re-drift nếu future model rename.
  - 1 source-grep regression trap: scan `admission_config_repository.py` source cho substring `admission_criteria_id`; tolerate hits trong fix docstring (giải thích lý do), forbid hits trong code lines. Trap caught ngay khi reviewer đọc diff, không cần chờ runtime.
- **Bite test verified**: temporarily revert 1 site → 4/6 FAIL (3 behavior tests AttributeError + 1 source-grep), 2 model-contract pass (model itself unchanged). Restore → all 6 PASS.

**Test scope limitation:**
- KHÔNG live integration test (call admin DELETE criteria endpoint với criteria-in-use → expect BusinessRuleViolation 400 thay vì 500). Lý do: cần seed criteria + offering/path FK linked trong test DB, scope test rộng. Mock DB tests + model contract đủ catch the original AttributeError; live API test sẽ verify trên staging clone D12-D14 hoặc trong Phase 1 wave full integration test.

**Drift catch khác (KHÔNG): KHÔNG verified drift trong PLAN/RISK ngoài 2 site repository đã track. KHÔNG touch PLAN/RISK.

**Files changed:**
- `Backend_FastAPI/app/repositories/admission_config_repository.py` (modified, +13/-7 lines: rename 2 sites + extend docstring với hot-fix context).
- `Backend_FastAPI/tests/repositories/test_admission_config_repository_p0c.py` (new, ~165 lines: 6 lock-in tests).
- `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` (P0c row CODE_DONE).
- `Documents/ADMISSION_DAILY_LOG.md` (entry này).

**Blocked / decisions cần:**
- Push approval cho `feature/admission-p0c` + sub-PR creation → `feat/admission-full-cutover`.

**Tomorrow plan (sau merge P0c):**
- M-P0a (`phase0_add_selected_subject_group_id_to_profile`) — migration Phase 0, độc lập P0c.
- M-P0b (`phase0b_relax_applied_rules_immutability_for_payment_keys`) — migration Phase 0, độc lập P0c + M-P0a.
- Sau Phase 0 đầy đủ (P0c + M-P0a + M-P0b) → start B1 (Casbin auth_model deny-first + 16 deny rules) hoặc B2 (EventDefinition + NotificationOutbox model + M-1-19a) — Phase 1 Code task gates.

**Notes:**
- P0c là code-only hot-fix; KHÔNG cần migration. RISK_REVIEW line 180 đã list rollback strategy: `git revert`, LOW risk.
- Scope ràng buộc: chỉ rename 2 reference repository, không touch model/schema/migration/router/service signature. Test mock DB pattern (existing `test_activity_repository.py` precedent) giữ unit-level scope.
- 2 alembic file references `ix_admission_criteria_id` + `admission_criteria_id_seq` là DB-level NAMES cho TABLE `admission_criteria` — index name pattern `ix_<table>_<column>` (PostgreSQL convention) + sequence auto-name. Khác hoàn toàn với column attr `admission_criteria_id` trên model `OfferingAdmissionConfig`/`AdmissionPath`. KHÔNG cần touch alembic.

---

### M-P0a — `phase0_add_selected_subject_group_id_to_profile` migration (sub-PR merged)

**Branch:** `feature/admission-m-p0a` off `feat/admission-full-cutover` HEAD `7f4ba89d`. Pushed `69e7e774` + post-PR docs `96ef27ae` 2026-05-02; sub-PR [#195](https://github.com/favouritekid/QLTS/pull/195) opened + merged squash `2fe77921` cùng ngày (mergedAt 2026-05-02T13:30:45Z). Base `feat/admission-full-cutover`, kept branch (`--delete-branch=false`). Status: **TESTED**, DONE pending staging smoke.

**CI manual verification:**
- Pre-merge: `pytest tests/unit/test_m_p0a_selected_subject_group_id.py -v` → 9/9 PASS Docker (1.20s) + live alembic roundtrip dev DB (upgrade/downgrade/re-upgrade/no-op-at-head).
- Post-merge re-run trên parent HEAD `2fe77921`: 9/9 PASS (0.98s).
- Repo workflow filter chưa cover PR vào `feat/admission-full-cutover` → CI tự động không chạy; manual evidence trong TRACKER + DAILY_LOG đủ pass-fail.

**Project board update (Mức 1 SOP):**
- Card #182 [Phase 0] Foundation moved Todo → In Progress (gap caught: card đáng lẽ phải move khi P0c bắt đầu = sub-PR đầu tiên thuộc thematic Phase 0; tôi missed do transition Task 0 → Phase 0 không có alarm tự động). Memory `admission-cutover-subpr-sop` cập nhật thematic↔sub-task mapping table + alarm reminder để future session check ngay sau push branch.
- Board state hiện tại: Todo 6 / In Progress 2 (#181 Task 0 + #182 Phase 0) / Done 0.
- Issue #182 sub-task tick: `[x] P0c` + `[x] M-P0a`; `[ ] M-P0b` chưa tick.

Phase 0 wave migration; single owner column DDL — Phase 1 #13 sau này chỉ backfill, KHÔNG re-define column.

**Decision arc (đã chốt 2026-05-02):**
- `ondelete="SET NULL"` (KHÔNG `RESTRICT`/`CASCADE`) — match pattern `AdmissionProfile.offering_admission_config_id` FK-traceability convention. `subject_group` là catalog có `is_active` → soft-retire, hard delete hiếm; `CASCADE` sẽ erase profiles, `RESTRICT` block catalog cleanup. `SET NULL` giữ profile + drop reference + cleanup task có thể surface affected rows qua `IS NULL` query.
- Scope tight: chỉ DDL migration + model field. KHÔNG service write `selected_subject_group_id` khi submit (PLAN line 2493 đề cập, nhưng tách sub-PR riêng để giữ M-P0a thuần migration).
- Model field co-shipped trong cùng PR (best practice tránh model-DB drift).
- Reasoning chi tiết: `subject_group` FK convention (CASCADE trên mapping/config tables `SubjectGroupSubject`/`CriteriaSubjectGroup`, nhưng đó là bảng cấu hình KHÔNG phải hồ sơ đã nộp — không áp dụng cho `AdmissionProfile`).

**Migration design:**
- Revision: `phase0sg01`. Down revision: `admstrict01` (head trên parent HEAD `7f4ba89d` khi tạo branch).
- Stable name constants (locked by tests): `TABLE="admission_profile"`, `COLUMN="selected_subject_group_id"`, `INDEX_NAME="ix_admission_profile_selected_subject_group_id"`, `FK_NAME="fk_admission_profile_selected_subject_group_id"`. Named FK + named index để downgrade drop deterministic (unnamed FK auto-name của Postgres brittle qua revisions).
- Idempotent helpers `column_exists` / `fk_exists` / `index_exists` match precedent `q3a1b2c3d4e5_add_audit_columns_to_admission_profile.py`.
- Upgrade order: ADD COLUMN → CREATE FK SET NULL → CREATE INDEX (mỗi step guarded).
- Downgrade order: DROP INDEX → DROP FK → DROP COLUMN (reverse, mỗi step guarded).

**Model field:**
- `app/models/admission.py` AdmissionProfile: thêm `selected_subject_group_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("subject_group.id", ondelete="SET NULL"), nullable=True, index=True, comment=...)` đặt ngay sau `offering_admission_config_id` (cluster FK-traceability columns). Comment ghi rõ Phase 0 owner + Phase 1 #13 backfill historical.
- KHÔNG add relationship — service hiện tại chưa cần eager load; có thể thêm sau khi Phase 3 backfill dùng tới.

**Tested / Rehearsed:**
- M-P0a unit — `pytest tests/unit/test_m_p0a_selected_subject_group_id.py -v` PASS **9/9** trong Docker (1.20s):
  - 3 revision-chain contract: `revision == "phase0sg01"`, `down_revision == "admstrict01"`, exposed name constants stable.
  - 2 source-grep idempotency: upgrade dùng `column_exists`/`fk_exists`/`index_exists` guards + assert `ondelete="SET NULL"` literal; downgrade reverse order assert (drop_index pos < drop_constraint pos < drop_column pos).
  - 4 model contract: column nullable + Integer type, FK target `subject_group.id` với `ondelete="SET NULL"`, backing index trên `__table__.indexes`, catalog-side sanity (`SubjectGroup.__tablename__ == "subject_group"`).
- M-P0a live — `docker compose exec backend alembic upgrade head` dev DB:
  - Upgrade applied column `selected_subject_group_id integer` + FK `fk_admission_profile_selected_subject_group_id ... ON DELETE SET NULL` + index `ix_admission_profile_selected_subject_group_id`. Verified qua `psql \d admission_profile`.
  - `alembic downgrade -1`: column/FK/index gone clean. Verified column count = 0 qua `information_schema.columns`.
  - Re-upgrade `alembic upgrade head`: column + FK + index restore.
  - Idempotent: `alembic upgrade head` khi đã ở head → no-op (alembic native skip).

**Test scope limitation (deferred):**
- KHÔNG live integration test với data: insert profile + set `selected_subject_group_id` + delete subject_group → verify FK SET NULL behavior. Sẽ verify trong staging clone D12-D14 hoặc Phase 1 full-integration wave (cần seed subject_group + admission_profile fixtures).
- KHÔNG test concurrent migration apply (race) — Phase 0 single-owner pattern + idempotent guards đủ cho cutover deploy sequential.

**Drift catch (KHÔNG): PLAN §3.4 P1-3 + §4 Phase 0 wording match implementation; KHÔNG touch PLAN/RISK.

**Files changed:**
- `Backend_FastAPI/alembic/versions/phase0sg01_add_selected_subject_group_id_to_profile.py` (new, ~110 lines: idempotent migration với upgrade/downgrade + helpers + name constants).
- `Backend_FastAPI/app/models/admission.py` (+19 lines: thêm field `selected_subject_group_id` với docstring lock-in Phase 0 owner + ondelete reasoning).
- `Backend_FastAPI/tests/unit/test_m_p0a_selected_subject_group_id.py` (new, ~190 lines: 9 lock-in tests).
- `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` (M-P0a row CODE_DONE).
- `Documents/ADMISSION_DAILY_LOG.md` (entry này).

**Blocked / decisions cần:**
- Push approval cho `feature/admission-m-p0a` + sub-PR creation → `feat/admission-full-cutover`.

**Tomorrow plan (sau merge M-P0a):**
- M-P0b (`phase0b_relax_applied_rules_immutability_for_payment_keys`) — migration trigger function update; CRITICAL chặn fee endpoint break sau khi extend status CHECK ở Phase 1 #11. Độc lập M-P0a, có thể start ngay sau M-P0a merge hoặc parallel nếu cần.
- Sau M-P0a + M-P0b → Phase 0 hoàn tất (P0c đã ship). Bước tiếp: B1 (Casbin auth_model deny-first) hoặc B2 (EventDefinition + NotificationOutbox + M-1-19a).

**Notes:**
- M-P0a là "single owner column" pattern: chỉ migration này tạo column qua DDL. Phase 1 #13 (`phase1_12_backfill_selected_subject_group_id`) chỉ làm 2 việc: pre-flight verify column tồn tại (raise hint nếu không) + backfill data lịch sử qua decision tree 3 rule + insert exception rows. KHÔNG re-define column.
- Decision audit trail: user catch quá vội chốt `RESTRICT` ban đầu (chưa đọc codebase đủ sâu), re-verify các FK pattern hiện có (`offering_admission_config_id` SET NULL, mapping tables CASCADE) → adjust thành `SET NULL`. Memory `verify-schema-before-proposing` tiếp tục apply cho mọi schema decision.
- Live alembic smoke trên dev DB là confidence boost ngoài unit test: thực sự verify Postgres apply column type/FK/index đúng tên + SET NULL behavior literal trong DDL output.

---

### M-P0b — `phase0b_relax_applied_rules_immutability_for_payment_keys` (sub-PR merged)

**Branch:** `feature/admission-m-p0b` off `feat/admission-full-cutover` HEAD `be64348b`. Pushed `d879a43f` + post-PR docs `ea5a0d2f` 2026-05-02; sub-PR [#196](https://github.com/favouritekid/QLTS/pull/196) opened + merged squash `080a8b26` cùng ngày (mergedAt 2026-05-02T14:21:42Z). Base `feat/admission-full-cutover`, kept branch (`--delete-branch=false`). Status: **TESTED**, DONE pending staging smoke.

**CI manual verification:**
- Pre-merge: 4/4 unit + 6/6 psql behavior matrix + 14/14 fee tests + alembic roundtrip PASS.
- Post-merge re-run trên parent HEAD `080a8b26`: `pytest tests/unit/test_m_p0b_applied_rules_whitelist.py tests/services/test_admission_application_fee.py::TestRecordFeePayment::test_admin_can_record_fee_payment` → **5/5 PASS** (12.05s) — 4 source contract + 1 fee record_payment regression confirms trigger active không break existing path.
- Repo workflow filter chưa cover PR vào `feat/admission-full-cutover` → CI tự động không chạy; manual evidence trong TRACKER + DAILY_LOG đủ pass-fail.

**Phase 0 wave CLOSED:**
- P0c (#194 squash `36d095a4`) ✓ TESTED — repository field-name hot-fix.
- M-P0a (#195 squash `2fe77921`) ✓ TESTED — `selected_subject_group_id` column.
- M-P0b (#196 squash `080a8b26`) ✓ TESTED — `applied_rules` whitelist trigger.
- Card #182 [Phase 0] Foundation: In Progress → **Done** (3/3 sub-task TESTED).
- Issue #182 sub-task tick: `[x] P0c` + `[x] M-P0a` + `[x] M-P0b`.
- Tomorrow plan unblocked: B1 (Casbin auth_model deny-first + 16 deny rules) hoặc B2 (EventDefinition extend + NotificationOutbox model + M-1-19a) — Phase 1 Code task gates wave. User khuyên đọc/scope B1 + B2 TRƯỚC khi code vì cả hai là infrastructure contracts lớn hơn Phase 0.

Phase 0 wave migration #2; trigger function update — KHÔNG đụng schema/column/FK.

**Decision arc — drift catch verified mid-implementation:**
- PLAN v2.13.1 §3.4 lines 2526-2531 đề xuất whitelist 4 key: `fee_paid_at`, `fee_payment_data`, `fee_calculated_at`, `fee_invoice_id`.
- Verified-from-code 2026-05-02: `admission_service.py:5904-5906` ghi **3 key** post-create: `fee_status`, `fee_paid_at`, `fee_payment_data`. PLAN miss `fee_status`. Existing test `tests/services/test_admission_application_fee.py:340` assert `fee_status == "paid"` chỉ pass vì trigger chưa apply trong test fixtures hiện tại; deploy Phase 1 → trigger active prod → fee endpoint break vì PLAN whitelist thiếu.
- User chốt **A: 5 key whitelist** (thêm `fee_status`). PLAN patch trong cùng PR (drift fix verified, không scope creep).
- **Logic trigger** thay từ strip-and-compare (PLAN line 2543-2552 pattern) → per-key classifier. Strip pattern blind spot với deletion: strip allowed key khỏi cả OLD lẫn NEW khiến delete equal add equal update — silent allow. Per-key classifier phân biệt rõ:
  - Add allowed key (NEW có, OLD không): allow
  - Update allowed key (cả 2 có, value khác): allow
  - Delete allowed key (OLD có, NEW không): **REJECT** (PLAN nói "thêm/update", không nói xóa)
  - Add/update/delete non-whitelisted key: REJECT
  - Wipe entire `applied_rules` (NEW = NULL): REJECT
  - No-op (OLD == NEW): allow (fast-path)

**Migration design:**
- Revision `phase0br01`, down `phase0sg01` (parent HEAD khi tạo branch = M-P0a merge).
- `ALLOWED_KEYS` exposed at module level (`tuple[str, ...]`) — locked by source test, mirrors SQL `allowed_keys TEXT[]` array literal.
- Trigger name `enforce_applied_rules_immutability` unchanged — chỉ replace function body via `CREATE OR REPLACE FUNCTION`.
- Downgrade restore v1 strict body literal-for-literal từ `b5c6d7e8f9a0` (RAISE EXCEPTION text exact match: `"applied_rules is immutable after creation and cannot be modified"`).

**PLAN patch (drift fix in same PR):**
- §3.4 line 2518: "2 key" wording → 3 key chi tiết với line refs.
- §3.4 lines 2526-2531: whitelist 4 → 5 key (thêm `fee_status` đầu danh sách).
- §3.4 lines 2543-2552: strip-and-compare → per-key classifier (mới SQL block với deletion guard).
- §3.4 thêm "Drift fix (round 24 — chốt 2026-05-02 trong M-P0b PR)" subsection ghi rõ 2 thay đổi (whitelist 4→5 + logic strip→classifier) với reasoning.

**Tested / Rehearsed:**
- M-P0b unit — `pytest tests/unit/test_m_p0b_applied_rules_whitelist.py -v` PASS **4/4** trong Docker (1.17s):
  - revision-chain (`phase0br01`/`phase0sg01`).
  - `ALLOWED_KEYS` 5-tuple lock (`fee_status` ở index 0).
  - upgrade SQL has per-key classifier markers (5 quoted keys + `jsonb_object_keys` walk + deletion guard + wipe-entire-object guard).
  - downgrade SQL restore v1 strict literal.
- M-P0b live psql 6-scenario behavior matrix (dev DB, trigger active):
  - **Scenario 1**: 5 allowed keys (1 update fee_status + 4 add) → `UPDATE 1` ✓
  - **Scenario 2**: non-whitelisted `min_gpa` change → `ERROR: applied_rules: key min_gpa is immutable` ✓
  - **Scenario 3**: non-whitelisted `admission_path_id` change → `ERROR: ... admission_path_id is immutable` ✓
  - **Scenario 4**: mixed allowed `fee_status` + non-allowed `min_gpa` → `ERROR: ... min_gpa is immutable` (rejection on first non-allowed key) ✓
  - **Scenario 5**: delete whitelisted `fee_status` → `ERROR: ... deletion of key fee_status is not allowed; only add/update permitted` ✓ (deletion guard bites)
  - **Scenario 6**: no-op same JSONB → `UPDATE 1` (fast-path) ✓
- M-P0b live alembic roundtrip dev DB:
  - `alembic upgrade head` apply v2 function with whitelist + classifier; `pg_get_functiondef` confirm.
  - `alembic downgrade -1` restore v1 strict (`pg_get_functiondef` confirm `'applied_rules is immutable after creation and cannot be modified'` literal).
  - `alembic upgrade head` re-apply v2 successfully.
- M-P0b existing fee tests — `pytest tests/services/test_admission_application_fee.py -v` PASS **14/14** (108.23s) post-trigger-active:
  - `TestRecordFeePayment::test_admin_can_record_fee_payment` exercises actual `record_application_fee_payment` writing `fee_status="paid"` + `fee_paid_at` + `fee_payment_data` → trigger allow ✓
  - `TestFullFlowWithFee` end-to-end fee flow PASS
  - 11 other fee tests (status get, idempotent, approve gating, event dispatch) PASS

**Test scope limitation (lessons learned):**
- Live psql smoke gây dev DB drift: profile id 189 bị overwrite `applied_rules` bằng smoke baseline `{"min_gpa": 7.0, "fee_status": "pending", "admission_path_id": 1}`. Nguyên nhân: DO block backup table fail vì `RAISE NOTICE jsonb_object_keys()` — set-returning function trong NOTICE → DO abort trước INSERT backup. Workaround future runs: wrap toàn bộ smoke trong `BEGIN; ... ROLLBACK;` transaction (atomic, rollback nếu fail → dev DB clean kể cả khi smoke crash).
- Profile 189 dev-only test data, regenerable qua seed scripts. KHÔNG production impact.
- Pytest live tests (initial attempt) bị scope mismatch + psycopg unavailable → drop khỏi pytest, dùng psql smoke + alembic CLI roundtrip thay thế. Source tests + 14 existing fee tests PASS đủ catch regression.

**Drift catch verified (round 24):**
- PLAN §3.4 patched in same PR — KHÔNG nguyên trạng PLAN frozen rule vì là verified drift (PLAN miss `fee_status`).
- KHÔNG touch RISK_REVIEW (rollback strategy `git revert` LOW risk vẫn đúng).

**Files changed:**
- `Backend_FastAPI/alembic/versions/phase0br01_relax_applied_rules_immutability_for_payment_keys.py` (new, ~150 lines: full SQL trigger function với per-key classifier upgrade + v1 strict downgrade).
- `Backend_FastAPI/tests/unit/test_m_p0b_applied_rules_whitelist.py` (new, ~115 lines: 4 source contract tests).
- `Documents/ADMISSION_REFACTOR_PLAN.md` (drift fix §3.4 lines 2516-2557 — whitelist 4→5 + logic strip→classifier + drift fix audit-trail subsection).
- `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` (M-P0b row CODE_DONE).
- `Documents/ADMISSION_DAILY_LOG.md` (entry này).

**Blocked / decisions cần:**
- Push approval cho `feature/admission-m-p0b` + sub-PR creation → `feat/admission-full-cutover`.
- Future smokes cần wrap BEGIN/ROLLBACK transaction (lesson learned từ profile 189 drift).

**Tomorrow plan (sau merge M-P0b):**
- Phase 0 wave hoàn tất (P0c + M-P0a + M-P0b 3/3 ship).
- Card #182 Phase 0 Foundation move In Progress → Done.
- Bước tiếp: B1 (Casbin auth_model deny-first + 16 deny rules) hoặc B2 (EventDefinition + NotificationOutbox model + M-1-19a) — Phase 1 Code task gates wave.

**Notes:**
- Per-key classifier > strip-and-compare: complexity tăng (~30 line PL/pgSQL vs 15 line) đổi lấy correctness rõ ràng (deletion guard explicit). Strip pattern blind spot với deletion là silent semantic bug — không catch qua test cho đến khi production user invoke profile-edit endpoint xóa fee_status.
- `fee_status` là state transition legitimate (`pending`/`exempt` → `paid`/`waived`), KHÔNG security-sensitive như `min_gpa` mà PLAN nguyên thủy bảo vệ. Đối xứng với `fee_paid_at` (cả 2 cập nhật cùng lúc trong record_payment line 5904-5905).
- Phase 0 wave: 3 sub-task (P0c + M-P0a + M-P0b) đều ship cùng day 2026-05-02. Card #182 In Progress → sẽ → Done sau M-P0b merge.

---

### B2.1 — admission 12 milestone events catalog + group + seed (commit local, branch chưa push)

**Branch:** `feature/admission-b2-1` off `feat/admission-full-cutover` HEAD `910d2c4d`. Phase 1 Code wave sub-PR đầu tiên (B2.1 of 4 split: B2.1 catalog + group + seed → B2.2 model+migration → B2.3 wrapper → B2.4 T0-4b worker). Card #183 [Phase 1 Code] sẽ move Todo → In Progress khi push.

**Decision arc — scope corrections post initial-plan review:**
- User catch (verified-from-code): tôi miss `event_groups.py` + `notification_seed_defaults.py` trong scope đầu. Coverage script `check_notification_event_coverage.py:65` `requires_seed = in_catalog and notification_class == "user" and not retired` — user-class events PHẢI có seed defaults. 12 event mới default class=user → bắt buộc 4 file thay vì 2.
- User catch: `APPLICATION_SUBMITTED` không tồn tại trong code. PLAN table 3.3.d wording "APPLICATION_SUBMITTED (legacy, giữ + alias)" stale; thực tế submit dùng `APPLICATION_STATUS_CHANGED`. 12 event mới `ADMISSION_*` namespace KHÔNG alias gì legacy.
- User catch: `safe_dispatch` line 1853 không có `strict` param. B2.3 wrapper sẽ dùng `dispatch(..., strict=True)` cho callback path, KHÔNG `safe_dispatch(strict=True)`. Tracked cho B2.3 (không scope B2.1).
- Sequence chốt: B2.1 → B2.2 → B2.3 → B2.4 (T0-4b) → B1 → #15 → #16. B2 split để additive risk thấp + unblock T0-4b sớm.

**Scope B2.1 (4 file):**
- `Backend_FastAPI/app/core/events.py`: thêm 12 SystemEvents enum mới (`ADMISSION_PROFILE_SUBMITTED`, `_REVISION_REQUESTED`, `_RESUBMITTED`, `_RESULT_PUBLISHED`, `_DECISION_ADMITTED`, `_DECISION_WAITLISTED`, `_DECISION_REJECTED`, `_WAITLIST_PROMOTED`, `_CONFIRMED`, `_ENROLLED`, `_WITHDRAWN`, `_ROLLED_BACK`) sau `ADMISSION_CONFIRMATION_HARD_LOCKED` block với docstring per-event.
- `Backend_FastAPI/app/core/event_catalog.py`: extend `EventDefinition` dataclass thêm 2 field optional `requires_outbox: bool = False` + `bypass_consent_check: bool = False` (additive, default False — 200+ existing entries untouched). Add 12 EVENT_CATALOG entries vào `_ADMISSION_EVENTS` tuple với cluster comment + per-event variables/resolver/channels/priority/dedup_key.
- `Backend_FastAPI/app/core/event_groups.py`: thêm 12 entries vào `EVENT_GROUP_MAPPING` (all → `NotificationEventGroup.APPLICATION` — admin notification UI cluster).
- `Backend_FastAPI/app/core/notification_seed_defaults.py`: thêm 12 entries vào `NOTIFICATION_SEED_DEFAULTS` với title_template/message_template/notification_type/recipient_config (Vietnamese display, recipient_config theo audience PLAN §3.3.d).

**Outbox/bypass routing matrix (verified match PLAN §3.3.d table line 1644-1657):**
- 7 events `requires_outbox=True`: RESULT_PUBLISHED, DECISION_ADMITTED, DECISION_WAITLISTED, DECISION_REJECTED, WAITLIST_PROMOTED, ENROLLED, ROLLED_BACK.
- 5 events `bypass_consent_check=True`: RESULT_PUBLISHED, DECISION_ADMITTED, DECISION_WAITLISTED, DECISION_REJECTED, ENROLLED.
- 5 events neither (best-effort + consent honored): PROFILE_SUBMITTED, REVISION_REQUESTED, RESUBMITTED, CONFIRMED, WITHDRAWN.

**Scope KHÔNG đụng:**
- KHÔNG `dispatch_event()` wrapper (B2.3).
- KHÔNG `NotificationOutbox` model/migration (B2.2).
- KHÔNG service caller wiring (B2.3 + #16).
- KHÔNG B1 Casbin.

**Tested:**
- `pytest tests/unit/test_b2_1_admission_milestone_events.py -v` PASS **65/65** (0.98s):
  - 1 enum value lock (12 enum + canonical string values).
  - 1 EventDefinition fields exist (`requires_outbox` + `bypass_consent_check`).
  - 1 existing 4 events default False (additive non-regression).
  - 12 `test_event_present_in_catalog`.
  - 12 `test_event_present_in_group_mapping` (→ APPLICATION).
  - 12 `test_event_present_in_seed_defaults` (4 required keys per entry).
  - 12 `test_requires_outbox_flag_matches_plan` (7 True + 5 False).
  - 12 `test_bypass_consent_check_flag_matches_plan` (5 True + 7 False).
  - 1 total outbox count = 7.
  - 1 total bypass count = 5.
- Regression: `pytest tests/unit/test_notification_contract.py tests/api/test_notification_event_groups_api.py` PASS **36/36** (34.22s) sau khi update `_DISPATCHED_EVENTS` whitelist với 12 entry mới + cluster comment ghi rõ "dispatch sites land #16".
- Coverage script `python -m app.scripts.check_notification_event_coverage`: 12 event mới hiện `Cat=Y / Class=user / Seed=Y / Dispatch=0 / Gaps=no-dispatch-site` — **expected gap** sẽ close khi #16 wire `state_service.transition() → dispatch_event()`. Exit code 1 = expected during multi-PR wave; tracked rõ trong PR body.

**Files changed:** 5 (4 modified + 1 new test file)
- `Backend_FastAPI/app/core/events.py` (+~70 lines: 12 enum + docstring per event)
- `Backend_FastAPI/app/core/event_catalog.py` (+~270 lines: 2 field extension + 12 EVENT_CATALOG entries)
- `Backend_FastAPI/app/core/event_groups.py` (+~15 lines: 12 mapping entries)
- `Backend_FastAPI/app/core/notification_seed_defaults.py` (+~140 lines: 12 seed entries)
- `Backend_FastAPI/tests/unit/test_b2_1_admission_milestone_events.py` (new, ~200 lines: 65 lock-in tests)
- `Backend_FastAPI/tests/unit/test_notification_contract.py` (+15 lines: whitelist 12 events với cluster marker comment)
- `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` (B2 row split status update)
- `Documents/ADMISSION_DAILY_LOG.md` (entry này)

**Blocked / decisions cần:**
- Push approval cho `feature/admission-b2-1` + sub-PR creation → `feat/admission-full-cutover`.

**Tomorrow plan (sau merge B2.1):**
- B2.2: NotificationOutbox model + migration `phase1_19a` (down `phase0br01`) + retire T0-4a canary `test_models_package_still_lacks_notification_outbox`.
- B2.3: `dispatch_event()` wrapper với `dispatch(..., strict=True)` cho callback path + coverage script extend `check_outbox_consistency()`.
- B2.4 = T0-4b: real worker wiring 3-step claim/dispatch/finalize replace skeleton.

**Notes:**
- Pattern catch B2.1: 4 file của notification system (events + catalog + groups + seed defaults) phải sync. Coverage script `check_notification_event_coverage.py` là source of truth — báo gap nếu một trong 3 surface (catalog/group/seed) miss + dispatch site count.
- 12 `ADMISSION_*` namespace mới hoàn toàn — KHÔNG alias `APPLICATION_*` legacy (memory `notification-coverage-roadmap` ghi 6 APPLICATION_* legacy giữ backward-compat cho payload key `application_id` per Backend_FastAPI/CLAUDE.md). Phase 4 deprecate APPLICATION_* khi 0 caller production.
- `category="application"` cho cả 12 — admin notification UI grouping. Convention từ existing ADMISSION_CONFIRMATION_* events.
- `ADMISSION_CONFIRMED` (T12) distinct với existing `ADMISSION_CONFIRMATION_REMINDER_24H/_6H/_HARD_LOCKED` — 3 event cũ là reminder/lock awareness, T12 fires khi confirm action thực sự land.

**Review feedback applied (post-commit `802bad4f`):**
- **P2** (test contract honesty) — User catch: ban đầu tôi gộp 12 admission event vào `_DISPATCHED_EVENTS` whitelist trong `test_notification_contract.py:462-482` cùng comment "land in #16". Test xanh nhưng **nói dối** — assertion "Every notification_class=user event must be dispatched somewhere in app/" không còn đúng nghĩa vì 12 event chưa có caller thật. Sửa: tách `_PENDING_DISPATCH_EVENTS` frozenset riêng (12 admission events), assertion `excused = _DISPATCHED_EVENTS | _PENDING_DISPATCH_EVENTS` — pending list explicit + comment removal-gate per cluster ("admission_*: remove in #16"). Add 2 lock test mới: `test_pending_dispatch_events_disjoint_from_dispatched` (event chỉ ở 1 list) + `test_pending_dispatch_events_locked_to_b2_1_admission_set` (count + names lock to exact 12, fail loudly nếu thêm hoặc quên xóa khi #16 ship).
- **Bite-verified P2 fix**: temporarily empty `_PENDING_DISPATCH_EVENTS` → 3 fail (`test_user_events_have_dispatch_in_codebase`, `test_dispatched_set_covers_all_user_events`, `test_pending_dispatch_events_locked_to_b2_1_admission_set`); restore → 4/4 PASS. Pending set là real regression catcher, không tautology.
- **Soft-fix `zalo_template_approved` comment** (note non-block): comment đầu tiên ở `event_catalog.py` field declaration nhắc flag `zalo_template_approved` cho Q7 chốt; flag KHÔNG tồn tại trong codebase hiện tại. Sửa wording sang "FUTURE-GATED — does NOT exist in the codebase yet" + ghi rõ B2.3/B2.4 phải either honor consent for Zalo/SMS until flag ships OR wire flag at that time. Đồng bộ wording trong `events.py` cluster comment cùng PR.
- **Test count**: 101 → 103 (+2 lock tests cho pending set). Total `pytest tests/unit/test_b2_1_admission_milestone_events.py tests/unit/test_notification_contract.py tests/api/test_notification_event_groups_api.py` → **103/103 PASS** (33.26s).

---

**Pattern correction — GitHub Project board (chốt 2026-05-02):**
- User catch logic conflict: nếu mỗi sub-PR auto-add vào board → 8 thematic card → 50+ card pollution sau full cutover (revert về Mức 2 đã reject ban đầu).
- Action: disabled "Auto-add to project" workflow (sidebar count 7 → 6 enabled); manually removed PR #189 card (Todo count 9 → 8).
- Board pattern (chuẩn từ giờ): **Mức 1 / 8 thematic kanban** — chỉ 8 issue #181-#188, manual move Todo → In Progress (khi sub-PR đầu tiên start) → Done (khi tất cả sub-PR merged).
- Sub-PR detail tracking (chuẩn từ giờ): TRACKER.md row-level + DAILY_LOG.md entries + GitHub PR list URL filter (`is:pr base:feat/admission-full-cutover`) — KHÔNG add board card cho sub-PR.
- Lý do: scaling. Full cutover dự kiến 30-50+ sub-PR; auto-add → board ngập, mất ý nghĩa high-level kanban; row-level đã có trong TRACKER + audit-trail trong DAILY_LOG đủ rồi.

---

### T0-2 — `ADMISSION_FROZEN` middleware (sub-PR merged)

**Branch:** `feature/admission-t0-2` off `feat/admission-full-cutover` HEAD `2c57e5d6`. Pushed `f6ddad7b` 2026-05-02; sub-PR [#190](https://github.com/favouritekid/QLTS/pull/190) opened + merged squash `1a8e0ca2` cùng ngày (mergedAt 2026-05-02T05:57:55Z). Base `feat/admission-full-cutover`, kept branch (`--delete-branch=false`). Status: **TESTED**, DONE pending staging smoke.

**CI manual verification (no checks reported pattern T0-1 + T0-2 đều cùng):**
- Pre-merge: `pytest tests/middleware/test_admission_freeze.py -v` → 47/47 PASS (Docker `qlts-backend-1`, 0.80s).
- Post-merge re-run trên parent HEAD `1a8e0ca2`: 47/47 PASS (1.10s).
- Repo workflow filter chưa cover PR vào `feat/admission-full-cutover` → CI tự động không chạy. Manual verification thay thế ghi trong TRACKER + DAILY_LOG đủ pass-fail evidence.

**Scope:**
- `Backend_FastAPI/app/config.py`: thêm `ADMISSION_FROZEN: bool = False` (Field validation_alias). Module-level load, restart container để pickup mới (per RUNBOOK §6.1).
- `Backend_FastAPI/app/middleware/admission_freeze.py` (mới): `AdmissionFreezeMiddleware` (Starlette `BaseHTTPMiddleware`). Đọc `settings.ADMISSION_FROZEN` per request → nếu True và method ∈ {POST, PUT, PATCH, DELETE} và path under 3 prefix verified-from-code → trả 503 JSON `{detail, code: "ADMISSION_FROZEN", frozen_prefix}`. Path-segment match (`path == prefix or path.startswith(prefix + "/")`) để `/api/admissionsfoo` không bị false positive.
- `Backend_FastAPI/app/main.py`: `add_middleware(AdmissionFreezeMiddleware)` đặt giữa CSRF (innermost) và CORS (outermost). 503 response sẽ đi qua CORS layer → CORS headers preserved; freeze chạy outside CSRF nên frozen request short-circuit trước CSRF state machine.
- `Backend_FastAPI/tests/middleware/test_admission_freeze.py` (mới): isolated stub app cho method×prefix matrix (KHÔNG cần lifespan/DB/Redis cho phần lớn case) + 1 route-table drift catch import `app.main.fastapi_app`. 47 case parametrized.

**Drift catch + fix verified-from-code:**
- RUNBOOK §3.5 + §6.2 + §9.3 + Issue #181 ban đầu ghi 4 prefix `/api/admission-paths` + `/api/admission-configs`. Verified `grep "router = APIRouter" Backend_FastAPI/app/routers/admission*.py public_admissions.py`: 4 router file share **3 distinct prefix** — `/api/admissions`, `/api/admission-config` (singular, shared bởi `admission_config.py` + `admission_paths.py`), `/api/public/admissions`.
- Sửa: RUNBOOK §3.5 T0-2 + §3.5 T0-3 (Nginx regex) + §6.2 method matrix + §6.2 block scope + §9.3 readiness — tất cả align với 3 prefix verified-from-code.
- Sửa Issue #181 sub-task T0-2 wording match.
- KHÔNG sửa PLAN/RISK_REVIEW (frozen v2.13.1) — prefix list không nằm trong PLAN spec, chỉ trong RUNBOOK ops doc.

**Tested / Rehearsed:**
- T0-2 — `pytest tests/middleware/test_admission_freeze.py -v` PASS 47/47 trong Docker (0.91s):
  - 1 contract-shape sanity: `FROZEN_PREFIXES` tuple + `/api/` prefix + `FROZEN_METHODS` set.
  - **1 route-table drift catch** (post user-review P2 round 2): import `app.main.fastapi_app`, scan `fastapi_app.routes`, filter `/api/...admission...` (substring `"admission"` không match `"admin"` — different word), assert mọi admission route đều under some `FROZEN_PREFIXES` ⇄ không có spurious freeze prefix. Test bind vào live route table — KHÔNG cần edit khi admission router mới được mount; tự động fail nếu router rename hoặc admission router mới chưa update FROZEN_PREFIXES.
  - 12 unfrozen-pass-through (3 prefix × 4 write method).
  - 12 frozen-block-503 (3 prefix × 4 write method) — body kiểm `code="ADMISSION_FROZEN"` + `frozen_prefix` match input.
  - 9 frozen-read-allowed (3 prefix × {GET, HEAD, OPTIONS}).
  - 4 non-admission unaffected (`/api/leads/123` × 4 write method).
  - 1 health endpoint reachable khi frozen.
  - 4 path-segment lookalike rejection (`/api/admissionsfoo` × 4 write method) → 200 (không match `/api/admissions` prefix).
  - 3 bare prefix POST blocked (POST `/api/admissions`, `/api/admission-config`, `/api/public/admissions` không trailing slash).

**Review feedback applied:**
- **P2 round 1** (post `955810d5`) — original `test_frozen_prefixes_match_real_router_prefixes` chỉ assert tuple-against-hard-coded-tuple (giả drift catch). Sửa lần 1 (`7269780d`): tách `test_freeze_constants_have_expected_shape` (contract sanity) + `test_frozen_prefixes_cover_live_admission_router_prefixes` (lazy import 4 router cố định + introspect `.prefix`).
- **P2 round 2** (user catch tiếp) — sửa lần 1 vẫn KHÔNG bắt được admission router mới (nếu mount trong main.py mà không thêm vào danh sách import 4 router cố định, test vẫn pass). Sửa lần 2: thay bằng `test_no_admission_route_escapes_freeze_coverage` — scan `fastapi_app.routes` filter substring `"admission"` (không match `"admin"`); fail nếu admission route nào không under FROZEN_PREFIXES. Tự động cover router mới mà KHÔNG cần edit test khi admission surface đổi.
- **P3 doc count drift** — RUNBOOK §6.2 line 273 stale `46 case` (sau P2 round 1 thực tế là 47). Sửa: 47 case + breakdown chi tiết từng nhóm test.
- **P3 ops logging** (deferred) — middleware không log blocked write attempt. Ops hardening, không bắt buộc cho T0-2 acceptance. Có thể follow-up trong T0-3 wave hoặc cleanup PR sau.

**Files changed:**
- `Backend_FastAPI/app/config.py` (+10 lines, ADMISSION_FROZEN field)
- `Backend_FastAPI/app/main.py` (+8 lines, import + add_middleware giữa CSRF/CORS)
- `Backend_FastAPI/app/middleware/admission_freeze.py` (new, ~75 lines)
- `Backend_FastAPI/tests/middleware/test_admission_freeze.py` (new, ~180 lines)
- `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md` (drift fix §3.5 + §6.2 + §9.3)
- `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` (T0-2 row CODE_DONE + Section 12.3 wording sync)
- `Documents/ADMISSION_DAILY_LOG.md` (entry này)

**Blocked / decisions cần:**
- Push approval cho `feature/admission-t0-2` + sub-PR creation → `feat/admission-full-cutover`.

**Tomorrow plan (sau merge T0-2):**
- T0-3 Nginx admission block (Ops owner) — 3 prefix regex match T0-2.
- T0-4a `dispatch_pending_outbox` skeleton — independent, ship parallel.
- T0-5 Casbin reload endpoint — independent, ship parallel.

**Notes:**
- Reload semantics RUNBOOK §6.1 đúng: `Settings` load module-level → flip `ADMISSION_FROZEN` cần `docker compose restart backend`. Test verify monkeypatch `app_settings.ADMISSION_FROZEN` per fixture → middleware đọc lại attribute mỗi request, không cần restart trong test.
- Defense-in-depth: T0-3 Nginx regex `^/api/(admissions|admission-config|public/admissions)(/.*)?$` sẽ match T0-2 prefix; bare prefix (no trailing path) cũng match nhờ `(/.*)?$` optional group.
- 4-method × 3-prefix matrix là **12 case** chứ không phải 16 (4×4) như Tracker wording cũ; Tracker đã sync.

---

## 2026-05-01

**Merged tới main** (deploy gate scaffolding):
- PR #180 — `chore(ci): gate VPS deploy on production environment approval` — squash SHA `d8b3191d`
  - GitHub Environment `production` + required reviewer = `favouritekid` configured
  - End-to-end verified: test job 9m22s PASS → deploy paused at status=`waiting` ✅ → API approve → deploy 1m29s PASS → smoke FE 200 + BE FastAPI 404 JSON

**Created today:**
- Branch `feat/admission-full-cutover` from main HEAD `d8b3191d`
- `Documents/ADMISSION_DAILY_LOG.md` (this file)
- `Documents/ADMISSION_REHEARSAL_LOG.md`
- TRACKER section 0 reworded: D1 CLOSED, D2/D3 không chặn dev (chỉ chặn cutover/Go)

**Tomorrow plan:**
- Bắt đầu Task 0 prerequisites (T0-1, T0-2, T0-3, T0-4a/4b, T0-5) per RUNBOOK §3.5
- Q11 đã closed → Phase 0 hot-fix (P0c, M-P0a, M-P0b) có thể start parallel với T0

**Notes:**
- Hotfix policy active: nếu prod break → hotfix → main → cherry-pick SHA sang feat branch + ghi entry vào log này (cả main SHA + cherry-pick SHA + conflict scope)
- All other work pause: trong window refactor, main chỉ nhận hotfix, không nhận wave Lead/Finance/Notification mới
