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

### M-P0a — `phase0_add_selected_subject_group_id_to_profile` migration (commit local, branch chưa push)

**Branch:** `feature/admission-m-p0a` off `feat/admission-full-cutover` HEAD `7f4ba89d`. Phase 0 wave migration; single owner column DDL — Phase 1 #13 sau này chỉ backfill, KHÔNG re-define column.

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
