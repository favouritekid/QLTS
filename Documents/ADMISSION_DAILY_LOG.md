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

## 2026-05-02

**Pushed hôm nay** (origin/feature/admission-t0-1, sub-PR pending open → `feat/admission-full-cutover`):

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
- Sub-PR creation approval (target `feat/admission-full-cutover` — solo dev self-review + merge).

**Tomorrow plan (sau sub-PR mở/merge):**
- Open sub-PR target `feat/admission-full-cutover` + link issue #181 sub-task 1.
- Start T0-2 (`ADMISSION_FROZEN` middleware) — independent của T0-1, parallel.
- Start T0-3 (Nginx admission block) — Ops owner, parallel.
- Start T0-4a skeleton (no-op safe registration) — sau patch C1, đã unblock.
- Start T0-5 (Casbin reload endpoint) — independent, parallel.

**Notes:**
- C3 patch áp dụng ngay sau khi user catch oversight: T0-1 ban đầu chỉ gate Alembic, vẫn auto chạy `sync_notification_rules` → cutover deploy backend `RUN_MIGRATIONS_ON_STARTUP=false` sẽ vẫn chạy sync rules trên empty schema → script fail/race. Add gate riêng cho sync.
- Branch đã push; KHÔNG rewrite history. Mọi cleanup setup docs sau push đi bằng commit bổ sung trên `feature/admission-t0-1`.
- Test framework cho bash entrypoint: chỉ syntax check + logic test, không có integration framework. Manual smoke trong staging clone D12-D14 sẽ verify end-to-end (apply 2 flag, observe entrypoint output, smoke API ready).
- Q11 closed (PLAN §3.3.g.1) → KHÔNG còn product decision blocker; D2 + D3 chỉ chặn cutover, không chặn dev start.

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
