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

### T0-3 — Nginx admission block (commit local, branch chưa push)

**Branch:** `feature/admission-t0-3` off `feat/admission-full-cutover` HEAD `691e6457`. Defense-in-depth pair với T0-2 backend middleware vừa ship: edge layer chặn ngay tại Nginx, trước khi traffic chạm FastAPI.

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
