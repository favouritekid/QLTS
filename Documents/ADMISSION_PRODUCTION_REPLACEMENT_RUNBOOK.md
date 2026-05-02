# Admission Production Replacement Runbook

**Version:** 1.0
**Last updated:** 2026-05-01
**Document type:** Operations runbook (KHÔNG phải spec nghiệp vụ).
**Source of truth cho spec:** `Documents/ADMISSION_REFACTOR_PLAN.md` v2.13.1.

---

## 1. Purpose

Build và test toàn bộ Admission refactor (full v2.13/v2.13.1 scope) trên môi trường local + staging clone của production. Khi pass migration rehearsal + E2E vận hành, **thay thế production một lần bằng cold cutover** trong maintenance window. Production hiện đang khóa Admission intake, không nhận hồ sơ mới — không có hot path live cần backward-compat staged rollout.

## 2. Source of Truth

| Topic | Document |
|---|---|
| Schema, migration, business rules, RBAC, IDOR, notification, state machine, FE contract, scoring engine, multi-NV, multi-round | `Documents/ADMISSION_REFACTOR_PLAN.md` v2.13.1 (4437 dòng) |
| Risk findings + 10 product decisions Q1-Q10 + P0/P1 blocker tracker | `Documents/ADMISSION_REFACTOR_RISK_REVIEW.md` |
| Daily progress tracker (task status, owner, branch/PR, blocker) | `Documents/ADMISSION_IMPLEMENTATION_TRACKER.md` |

**Event/pipeline projection source of truth = code, KHÔNG documentation** (matrix file `ADMISSION_MATRIX_MAPPING.md` đã archive vì stale 2026-01-15 lệch với code thật):
- `Backend_FastAPI/app/core/admission_event_mapping.py` — `ADMISSION_TO_LEAD_STATUS_MAP` + `ADMISSION_EVENT_PROJECTIONS` dict.
- `Backend_FastAPI/app/services/lead_admission_sync.py` — projection logic + sync function.
- `Backend_FastAPI/scripts/data/consultation_status_v3.csv` — lead consultation_status seed.
- `Backend_FastAPI/scripts/data/allowed_transitions_v3.csv` — allowed transitions seed.

Runbook này KHÔNG copy nội dung spec. Mọi câu hỏi về "schema field gì", "transition rule gì", "migration nội dung gì" → đọc PLAN. Mọi câu hỏi "event/status projection mapping" → đọc 4 file code trên.

## 3. Non-goals

Runbook này KHÔNG:
- Định nghĩa lại schema, business rules, migration contract, transition matrix, scoring engine, RBAC matrix.
- Liệt kê acceptance criteria per code task — đọc PLAN Phần 4 + RISK_REVIEW Phần 8 patches.
- Track P0 blocker progress — đọc RISK_REVIEW Phần 2.
- Quyết định product Q1-Q10 — đọc PLAN changelog v2.13 + RISK_REVIEW Phần 0. (Q11 đã resolved trong PLAN §3.3.g.1, không phải open decision nữa.)

## 3.5. Task 0 — Pre-implementation Prerequisites (BẮT BUỘC ship TRƯỚC staging rehearsal)

⚠️ **Runbook này giả định 5 infrastructure mục dưới đã được implement trong code.** Verified codebase 2026-05-01: tất cả CHƯA TỒN TẠI. Phải ship trong implementation phase (sub-PR riêng) TRƯỚC khi bắt đầu staging rehearsal Phần 7. KHÔNG assume.

| Task 0 | Why | Codebase evidence (CHƯA CÓ) | Acceptance |
|---|---|---|---|
| **T0-1: 2 env flag gates** trong `Backend_FastAPI/docker-entrypoint.sh`: `RUN_MIGRATIONS_ON_STARTUP` + `RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP` | Cold cutover yêu cầu manual `alembic upgrade head` + manual `sync_notification_rules` SAU migration + backfill (KHÔNG auto trên container start vì pre-migration state có thể chưa có notification_rule table hoặc chưa seed → script fail/race) | `docker-entrypoint.sh` auto chạy `alembic upgrade head` (line 4-5) + `python -m app.scripts.sync_notification_rules` (line 7-8), cả 2 không conditional | Entrypoint thêm 2 gate độc lập: `if [ "${RUN_MIGRATIONS_ON_STARTUP:-true}" != "false" ]; then alembic upgrade head; fi` + `if [ "${RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP:-true}" != "false" ]; then python -m app.scripts.sync_notification_rules; fi`. Default `true` cho routine deploy. Cutover set CẢ 2 = `false`. Defensive: chỉ exact lowercase `"false"` mới skip; mọi value khác (TRUE/FALSE/typo) chạy như cũ. |
| **T0-2: `ADMISSION_FROZEN` middleware** | Freeze admission write endpoints khi maintenance window | Grep zero match `ADMISSION_FROZEN` trong `app/config.py`, `app/middleware/`, `app/routers/admissions.py` | Settings field + dependency/middleware raise 503 cho POST/PUT/DELETE/PATCH `/api/admissions/*` + `/api/admission-paths/*` + `/api/admission-configs/*` + `/api/public/admissions/*`. **Reload mechanism: env-based settings cần container restart** (Pydantic BaseSettings load 1 lần module-level) — runbook Phần 6.1 phải clarify restart container, KHÔNG hot-reload runtime. |
| **T0-3: Nginx admission block config** | Defense-in-depth với T0-2 backend middleware | `nginx/conf.d/default.conf.template` chỉ generic `/api/` proxy, zero conditional admission block | Conditional `location ~ ^/api/(admissions|admission-paths|admission-configs|public/admissions)/.*$ { ... return 503 ...}` env-driven `${NGINX_ADMISSION_FROZEN}` template variable. |
| **T0-4: `dispatch_pending_outbox` Celery beat task** | Worker drain outbox notification queue | `app/celery_app.py:108-150` zero match | Beat schedule entry 30s + 3-step claim/dispatch/finalize implementation per PLAN Phần 3.3.e. |
| **T0-5: `POST /api/v2/admin/casbin/reload` endpoint** | Cutover safety: reload Casbin policy sau seed deny rules direct DB | `admin/roles.py` chỉ side-effect trong CRUD endpoint, zero dedicated reload endpoint | Admin-only endpoint gọi `await enforcer.load_policy()` + return policy count + audit log. |

**Gate**: Phần 9.3 production readiness checklist verify 5 mục trên shipped + tested trên staging trước Go decision.

## 4. Environment Strategy

```
Local dev          →   Staging (prod clone)   →   Production (cold cutover)
─────────────          ──────────────────         ──────────────────────
Full implementation    Migration rehearsal        Maintenance window
sub-PR work breakdown  E2E vận hành               replace whole system
unit + integration     2-pass idempotency         post-deploy soak 48h
test loop              cutover dry-run
```

**Local dev:**
- Branch: `feat/admission-full-cutover` (parent của sub-feature branches per workstream).
- DB: Postgres 16 local (Docker) clone từ production dump anonymized PII.
- Dev workflow: sub-PR → review → merge vào `feat/admission-full-cutover`. KHÔNG ship sub-PR riêng lẻ lên production.

**Staging (production clone):**
- DB clone full from production via `pg_dump -Fc`.
- Identical infra với production (Postgres 16, Redis 7, same OS, same Nginx config).
- Apply migration chain + backfill + E2E vận hành. Reset clone + re-apply lần 2 cho idempotency.

**Production:**
- Hiện đang freeze admission intake (per quyết định kinh doanh — không nhận hồ sơ mới giai đoạn refactor).
- Cold cutover trong maintenance window 4-6h replace whole image + DB schema.
- KHÔNG staged rollout, KHÔNG soak windows giữa phase.

## 5. Safe Production Backup

**MUST complete TRƯỚC freeze.** Không có backup verified = không cutover.

### 5.1. Database snapshot

⚠️ **TTY flag `-T` BẮT BUỘC** cho `docker compose exec` khi redirect binary stdout. KHÔNG có `-T` → TTY allocation chèn `\r\n` vào `pg_dump -Fc` binary stream → dump file corrupt, không restore được.

⚠️ **File location**: `>` redirect chạy ở **host shell** → file output ở host current directory. `pg_restore -l <file>` phải chạy **inside container** (vì cần đọc file đó qua tool postgres) → cần copy file vào container TRƯỚC khi verify, hoặc pipe qua stdin.

```bash
# Trên production HOST (không phải container)
DATE=$(date +%Y%m%d_%H%M%S)
DB_USER=${POSTGRES_USER:-qlts}
DB_NAME=${POSTGRES_DB:-qlts_production}

# pg_dump với -T disable TTY, output binary -Fc về host file
docker compose exec -T postgres pg_dump -U ${DB_USER} -Fc ${DB_NAME} > prod_${DATE}_pre_cutover.dump

# Verify file size + magic bytes (PGDMP header)
ls -la prod_${DATE}_pre_cutover.dump
file prod_${DATE}_pre_cutover.dump  # Expect: "PostgreSQL custom database dump"
head -c 5 prod_${DATE}_pre_cutover.dump | xxd  # Expect first bytes: 50 47 44 4d 50 (= PGDMP)

# Verify integrity qua pg_restore -l (list contents, không restore)
# Pipe file vào container stdin để pg_restore -l có thể đọc:
cat prod_${DATE}_pre_cutover.dump | docker compose exec -T postgres pg_restore -l | wc -l
# Expect: số > 0 (số TOC entry trong dump)

# Upload offsite (S3 hoặc cloud storage organization-approved)
aws s3 cp prod_${DATE}_pre_cutover.dump s3://qlts-backup/admission-cutover/
aws s3 ls s3://qlts-backup/admission-cutover/ | grep ${DATE}
```

### 5.2. Uploaded files / media backup

⚠️ **Paths verified codebase 2026-05-01** (`Backend_FastAPI/Dockerfile:44-49` + `docker-compose.yml:80-81, 116-117`):
- `/app/uploads` (Docker named volume `backend_uploads`) — admission documents, magic link attachments.
- `/app/app/static/uploads` (Docker named volume `backend_static_uploads`) — static uploads (avatars, documents).

KHÔNG có `/app/media`. Sử dụng đúng 2 path trên.

```bash
# Tar uploaded files INSIDE backend container (mount points đã có volume)
docker compose exec -T backend tar czf /tmp/uploads_${DATE}.tar.gz /app/uploads /app/app/static/uploads

# Copy archive từ container ra host
docker compose cp backend:/tmp/uploads_${DATE}.tar.gz ./

# Cleanup tmp file inside container
docker compose exec -T backend rm /tmp/uploads_${DATE}.tar.gz

# Verify archive size + structure
ls -la uploads_${DATE}.tar.gz
tar tzf uploads_${DATE}.tar.gz | head -10

# Upload offsite
aws s3 cp uploads_${DATE}.tar.gz s3://qlts-backup/admission-cutover/
```

**Alternative** (Docker volume backup direct, không cần backend container running):
```bash
docker run --rm -v backend_uploads:/data/uploads -v backend_static_uploads:/data/static_uploads \
    -v $(pwd):/backup alpine \
    tar czf /backup/uploads_${DATE}.tar.gz /data/uploads /data/static_uploads
```

### 5.3. Env / config backup

```bash
# .env files (KHÔNG commit secrets, copy ra offsite riêng)
cp .env env_backup_${DATE}.txt
cp Backend_FastAPI/.env backend_env_backup_${DATE}.txt
cp frontend/.env.local frontend_env_backup_${DATE}.txt
cp .env.production prod_env_backup_${DATE}.txt

# Nginx config
cp -r nginx/conf.d/ nginx_conf_backup_${DATE}/

# Docker compose
cp docker-compose.yml docker-compose_backup_${DATE}.yml
cp docker-compose.override.yml docker-compose_override_backup_${DATE}.yml

# Upload bundle offsite
tar czf config_backup_${DATE}.tar.gz env_backup_*.txt nginx_conf_backup_${DATE}/ docker-compose_*_backup_${DATE}.yml
aws s3 cp config_backup_${DATE}.tar.gz s3://qlts-backup/admission-cutover/
```

### 5.4. Docker image tag backup

```bash
# Tag current production images với pre-cutover marker
docker tag qlts-backend:latest qlts-backend:pre-admission-cutover-${DATE}
docker tag qlts-frontend:latest qlts-frontend:pre-admission-cutover-${DATE}

# Push registry (nếu có)
docker push qlts-backend:pre-admission-cutover-${DATE}
docker push qlts-frontend:pre-admission-cutover-${DATE}

# Document image SHA
docker images --no-trunc qlts-backend:pre-admission-cutover-${DATE} >> image_tags_${DATE}.txt
docker images --no-trunc qlts-frontend:pre-admission-cutover-${DATE} >> image_tags_${DATE}.txt
```

### 5.5. Restore rehearsal (BẮT BUỘC trước cutover)

⚠️ **File location mismatch fix**: `pg_restore` chạy **inside container** nhưng dump file ở **host** (do Phần 5.1 redirect). Phải pipe qua stdin hoặc copy vào container TRƯỚC.

```bash
# Trên staging env (KHÔNG phải production)
DB_USER=${POSTGRES_USER:-qlts}
STAGING_DB=qlts_staging  # hoặc tên DB staging tương ứng

# Step 1: Pipe dump file qua stdin để pg_restore container đọc được
START_TIME=$(date +%s)
cat prod_${DATE}_pre_cutover.dump | \
    docker compose exec -T postgres pg_restore \
        -U ${DB_USER} -d ${STAGING_DB} --clean --if-exists --no-owner --no-acl
END_TIME=$(date +%s)
RESTORE_TIME=$((END_TIME - START_TIME))

# Step 2: Verify count match production qua psql trực tiếp (ổn định hơn Python ad-hoc)
docker compose exec -T postgres psql -U ${DB_USER} -d ${STAGING_DB} <<'SQL'
SELECT 'lead' AS table_name, COUNT(*) AS row_count FROM lead
UNION ALL
SELECT 'admission_profile', COUNT(*) FROM admission_profile
UNION ALL
SELECT 'admission_path', COUNT(*) FROM admission_path
UNION ALL
SELECT 'admission_confirmation_token', COUNT(*) FROM admission_confirmation_token
UNION ALL
SELECT 'payment', COUNT(*) FROM payment;
SQL

# Step 3: Document restore time + counts
echo "Restore time: ${RESTORE_TIME}s" >> backup_rehearsal_log_${DATE}.md
echo "Restore date: $(date)" >> backup_rehearsal_log_${DATE}.md
```

**Acceptance gate (BẮT BUỘC pass trước cutover)**:
- [ ] Restore complete với exit code 0 (không có ERROR trong stderr).
- [ ] Restore time documented (cho window estimate cutover Phần 7.2).
- [ ] Row count 5 critical table match production exactly.
- [ ] Smoke query: `SELECT * FROM admission_profile LIMIT 1` trả 1 row có dữ liệu.

Nếu restore fail bất kỳ step → **KHÔNG cutover**. Investigate root cause.

## 6. Production Freeze Plan

### 6.1. Khóa Admission intake

⚠️ **Pydantic BaseSettings load env 1 lần module-level → BẮT BUỘC restart container** để pickup `ADMISSION_FROZEN=true`. KHÔNG có hot-reload runtime mechanism mặc định. Nếu cần zero-downtime reload, T0-2 phải implement Redis-backed config + cache invalidate (không khuyến nghị cho cutover scope).

```bash
# Backend env — BẮT BUỘC restart container sau khi set
# Edit .env hoặc .env.production:
#   ADMISSION_FROZEN=true
docker compose restart backend  # restart để Settings load env mới
docker compose ps backend       # verify state running

# Verify middleware active
curl -X POST http://localhost:8000/api/admissions/test-endpoint  # Expect: 503 Service Unavailable
curl -X GET  http://localhost:8000/api/admissions/                # Expect: 200 (read-only allowed)

# Nginx env (khi T0-3 ship): edit env file hoặc compose
#   NGINX_ADMISSION_FROZEN=1
# Reload nginx container (KHÔNG cần restart):
docker compose exec -T nginx nginx -s reload
docker compose exec -T nginx nginx -t          # verify config syntax OK

# Verify nginx block active (defense-in-depth)
curl -X POST http://localhost/api/admissions/test-endpoint        # Expect: 503 từ nginx (trước khi reach backend)
```

**Quan trọng**: backend restart mất ~10-30s, có downtime ngắn. Nếu cần zero-downtime → escalate scope T0-2 implement Redis-backed config (out of scope runbook hiện tại).

### 6.2. Read-only allowed endpoints

T0-2 middleware filter theo HTTP method, KHÔNG hard-code path list. Method matrix:

| Method | Path prefix | Behavior khi `ADMISSION_FROZEN=true` |
|---|---|---|
| GET | `/api/admissions/*`, `/api/admission-paths/*`, `/api/admission-configs/*` (verify exact prefix theo `app/routers/admission*.py`) | **Allowed** — view profiles/paths/criteria/documents |
| POST/PUT/DELETE/PATCH | Any admission write endpoint | **503 Service Unavailable** với header `Retry-After: <maintenance_end_unix>` |
| POST | `/api/admissions/confirm/{token}` (magic link consume) | **503** — block candidate consume token trong window |

Block scope (theo router source verified `Backend_FastAPI/app/routers/admissions.py`, `admission_paths.py`, `admission_config.py`, `public_admissions.py`):
- Profile mutation (create/update/delete)
- Status transition (approve/reject/confirm/withdraw/override/...)
- Document upload + reset
- Magic link issue/consume + token verification
- Path/config admin CRUD
- Public storefront submit endpoints

T0-2 acceptance test: 4 method × 4 router prefix matrix verify trong staging trước rollout.

### 6.3. Module không liên quan vẫn chạy

KHÔNG khóa: Lead module (CRUD), Finance (payment view), Dashboard, KPI reports, User management, Casbin policy admin.

### 6.4. Thông báo vận hành

| Thời điểm | Audience | Channel | Message |
|---|---|---|---|
| T-7d | All staff + Admin/Officer | Email | "Maintenance window scheduled ${DATE} ${HH:MM_START} → ${HH:MM_END}. Admission intake sẽ khóa toàn bộ. Detail attached." |
| T-3d | Admin/Officer | In-app banner | "Hệ thống tuyển sinh sẽ bảo trì lớn ngày ${DATE}." |
| T-1d | Candidate (active leads) | Email + Zalo | "Hệ thống nâng cấp ngày ${DATE}. Hồ sơ sẽ được xử lý sau bảo trì." |
| T-1h | All | Slack #ops + in-app | "Maintenance starting in 1 hour." |
| T+0 | All | Slack #ops + in-app banner | "Maintenance đã bắt đầu. Admission frozen." |
| T+end | All | All channels | "Maintenance complete. Admission unlocked." |

## 7. Cutover Sequence

### 7.1. Preflight checklist (T-1d → T-0)

- [ ] Backup verified offsite (Phần 5.5 PASS).
- [ ] Staging migration rehearsal 2 lần PASS (idempotency).
- [ ] E2E vận hành smoke test PASS toàn bộ flow trên staging.
- [ ] Casbin matrix 4 role × 14 action PASS.
- [ ] Sign-off 7 stakeholder (Phần 10).
- [ ] Rollback playbook tested (Phần 8).
- [ ] Maintenance window communicated 7d trước.
- [ ] Standby team confirmed: 2 BE + 1 FE + 1 DBA + 1 Ops + 1 QA.
- [ ] Profile creation flow per PLAN §3.3.g.1 implemented (Q11 resolved): officer/admin tạo Lead → system auto-create draft AdmissionProfile + issue submit token (TTL 7d) → candidate click link submit.
- [ ] Image tag pre-cutover saved (Phần 5.4).
- [ ] Migration apply time documented từ rehearsal (estimate cho window timing).

### 7.2. Cutover steps (target window 4-6h)

```
T+0:00   Communicate freeze (email + Slack + in-app banner)
T+0:15   Set ADMISSION_FROZEN=true env + Nginx reload với NGINX_ADMISSION_FROZEN=1
         Verify: curl POST /api/admissions/... → 503
T+0:30   Final pg_dump + uploads tar + config backup → upload S3 + integrity verify
T+1:00   Deploy backend image MỚI với 2 env flag = false:
           RUN_MIGRATIONS_ON_STARTUP=false
           RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=false
         (per RISK_REVIEW OG-1: tách Alembic + notification rule sync khỏi container startup cho cutover.
          Lý do skip sync rules: pre-migration state có thể chưa có notification_rule table hoặc chưa seed
          12 ADMISSION_* DB rows → script fail/race. Manual run ở T+3:30 sau migration + DB seed.)
         Verify: container start → KHÔNG chạy alembic, KHÔNG chạy sync_notification_rules,
                 chỉ uvicorn ready (log "Skipping..." cho cả 2 gate).
T+1:30   Manual run Alembic chain:
           docker compose exec backend alembic upgrade head
         Stream log realtime; checkpoint mỗi migration step.
         Time tracking — nếu một migration > 5 phút unexpected → pause, investigate.
         Estimate full chain ~30-60 phút (data backfill heavy).
T+3:00   Manual run backfill scripts theo PLAN Phần 4 + 5b:
           - status_history initial (1 row/profile + 5 scattered scalar)
           - selected_subject_group_id decision tree 3 rule
           - GPA backfill từ academic_history JSON (length-bounded regex)
           - graduation_year backfill
           - Casbin v3='allow' + seed deny rules accountant
T+3:30   Manual run sync notification rules:
           docker compose exec backend python -m app.scripts.sync_notification_rules
         Verify: 12 ADMISSION_* event có DB rule row.
T+3:45   Deploy frontend image MỚI (Next.js standalone container restart)
         KHÔNG có CDN purge — verify browser cache header `Cache-Control: no-cache, no-store`.
T+4:00   Deploy celery worker + celery beat images (new schedule với dispatch_pending_outbox 30s)
         Verify: celery beat schedule includes new task; worker registered.
T+4:15   Smoke tests (Phần 7.3)
T+4:45   Set ADMISSION_FROZEN=false + Nginx reload bỏ admission block
T+5:00   Communicate unlock (email + Slack + in-app banner)
T+5:15   Monitor handoff to oncall (Phần 9)
T+24h    Switch backend env back CẢ 2 flag về true (hoặc unset) cho future routine deploy:
           RUN_MIGRATIONS_ON_STARTUP=true (or unset)
           RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=true (or unset)
         (cutover behavior chỉ áp dụng 1 lần; routine deploy phục hồi auto migration + auto sync như trước)
```

### 7.3. Smoke tests (T+4:15 — T+4:45)

Reference PLAN Phần 6 test strategy + RISK_REVIEW Phần 6 E2E checklist.

**Critical journeys (top-down):**
1. Officer/admin tạo Lead → system auto-create draft AdmissionProfile + issue submit token (per PLAN §3.3.g.1) → candidate click magic link submit → status `submitted`.
2. Officer claim → `reviewing` → admin publish-result → `result_published` → system distribute → `admitted`/`waitlisted`/`rejected`.
3. Candidate magic link confirm → `confirmed`. System enroll → `enrolled` + Student row created.
4. Casbin matrix: accountant call any 14 admission action → 403.
5. Multi-NV (per PLAN scope): profile có 3 NV → engine compute 3 eligibility → admin xem result.
6. Outbox worker: backlog = 0 sau 60s post bulk publish 100 profile.
7. Lead pipeline projection: `Lead.consultation_status_id` update đúng cho mọi 14 status.
8. Frontend: 14 status badge render đúng + typed `available_actions` button rendering correct.

**Acceptance**: 8 critical PASS toàn bộ. Nếu fail bất kỳ → STOP, không unlock; trigger rollback (Phần 8).

## 8. Rollback Strategy

### 8.1. Default rollback

```
Default = restore DB snapshot + old images + old env/config
Estimate recovery: 1-2h
```

```bash
# Step 1: Re-freeze admission (block writes during rollback window)
# Edit .env.production: ADMISSION_FROZEN=true + NGINX_ADMISSION_FROZEN=1
docker compose restart backend
docker compose exec -T nginx nginx -s reload

# Step 2: Restore DB từ pre-cutover backup
# Pipe file vào container stdin (tránh file location mismatch)
cat prod_${DATE}_pre_cutover.dump | \
    docker compose exec -T postgres pg_restore \
        -U ${POSTGRES_USER:-qlts} -d ${POSTGRES_DB:-qlts_production} \
        --clean --if-exists --no-owner --no-acl

# Step 3: Deploy old images — 2 cách:
# Cách A (recommended): override image tag qua env, KHÔNG sửa docker-compose.yml
docker pull qlts-backend:pre-admission-cutover-${DATE}
docker pull qlts-frontend:pre-admission-cutover-${DATE}
export BACKEND_IMAGE_TAG=pre-admission-cutover-${DATE}
export FRONTEND_IMAGE_TAG=pre-admission-cutover-${DATE}
docker compose down
docker compose up -d
# Yêu cầu: docker-compose.yml phải support env var trong image tag, e.g.:
#   image: qlts-backend:${BACKEND_IMAGE_TAG:-latest}

# Cách B (nếu compose không hỗ trợ env): commit override file riêng pre-cutover
# cp docker-compose.rollback.yml docker-compose.override.yml
# docker compose down && docker compose up -d
# Lưu ý: rollback compose file MUST exist sẵn từ T-1d preflight, KHÔNG generate ad-hoc.

# Step 4: Restore env/config từ backup
tar xzf config_backup_${DATE}.tar.gz
cp env_backup_${DATE}.txt .env
cp backend_env_backup_${DATE}.txt Backend_FastAPI/.env
cp frontend_env_backup_${DATE}.txt frontend/.env.local
cp prod_env_backup_${DATE}.txt .env.production
cp -r nginx_conf_backup_${DATE}/* nginx/conf.d/
docker compose restart backend frontend nginx

# Step 5: Verify smoke
curl http://localhost:8000/api/admissions/health  # Expect 200
docker compose exec -T postgres psql -U ${POSTGRES_USER:-qlts} -d ${POSTGRES_DB:-qlts_production} \
    -c "SELECT COUNT(*) FROM admission_profile"   # Expect: count match pre-cutover

# Step 6: Unlock (nếu smoke PASS)
# Edit .env.production: ADMISSION_FROZEN=false + NGINX_ADMISSION_FROZEN=0
docker compose restart backend
docker compose exec -T nginx nginx -s reload
```

### 8.2. KHÔNG rollback nửa vời

**One-way migrations** trong PLAN.md chain không reversible an toàn:
- `phase1_11_extend_profile_status_check_constraint` (CHECK extend)
- `phase1_15_drop_lead_id_unique_constraint`
- `phase2_02b_admission_path_round_not_null_swap_unique`
- `phase1_18_extend_confirmation_token_for_multi_action` (UNIQUE swap)
- `phase2_04_widen_score_precision`

Nếu cutover đã apply một trong 5 migration trên + phát hiện bug critical:
- ❌ KHÔNG `alembic downgrade` từng step.
- ❌ KHÔNG patch hot-fix trên schema mới (risk data drift).
- ✅ **Restore DB snapshot full + old images** (Phần 8.1) — chấp nhận mất data window cutover (admission đã frozen, không có write activity → mất 0 transaction).

### 8.3. Trigger rollback

| Severity | Action |
|---|---|
| Smoke test fail bất kỳ critical step trong Phần 7.3 | Rollback ngay theo Phần 8.1 |
| Error rate > 5% trong 30 phút post-unlock | Rollback ngay |
| Critical bug data corruption phát hiện | Rollback ngay |
| UX bug, no data corruption | Hot-fix forward trong 24h, KHÔNG rollback |

### 8.4. Post-rollback

- Communicate revert: email + Slack + in-app banner.
- Schedule post-mortem trong 72h.
- Standby team root cause + fix + reschedule cutover (target +14 days).

## 9. Go/No-Go Checklist

**MUST 100% PASS trước T-1d sign-off:**

### 9.1. Backup
- [ ] DB pg_dump verified offsite + restore rehearsal PASS.
- [ ] Uploads tar verified.
- [ ] Env/config bundle uploaded S3.
- [ ] Image tag pre-cutover pushed registry.

### 9.2. Staging rehearsal
- [ ] Migration chain apply lần 1 PASS trên staging clone.
- [ ] Migration chain apply lần 2 (idempotency) — diff với lần 1 = 0.
- [ ] 5 backfill scripts run PASS, exception count expected.
- [ ] E2E vận hành smoke test 8 critical journey PASS.
- [ ] Casbin matrix 4×14 PASS.
- [ ] Outbox worker rig (concurrency + crash recovery) PASS.
- [ ] Frontend full multi-NV E2E PASS.

### 9.3. Production readiness — Task 0 prerequisites (xem Phần 3.5)

5 mục Task 0 BẮT BUỘC ship + tested trên staging trước Go decision:
- [ ] **T0-1** 2 env flag gates trong `docker-entrypoint.sh` — tested 9-case matrix (3 RUN_MIGRATIONS × 3 RUN_SYNC_NOTIFICATION_RULES) + 5 defensive variant (TRUE/FALSE/typo) PASS. Cutover combo `RUN_MIGRATIONS_ON_STARTUP=false` + `RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=false` skip cả 2; default unset/true chạy alembic + sync_notification_rules như cũ.
- [ ] **T0-2** `ADMISSION_FROZEN` middleware shipped — 4 method × admission router prefix matrix tested (GET allowed, POST/PUT/DELETE/PATCH 503).
- [ ] **T0-3** Nginx admission block config (env-driven `NGINX_ADMISSION_FROZEN`) tested với `nginx -t` syntax check + reload smoke.
- [ ] **T0-4** `dispatch_pending_outbox` Celery beat task scheduled 30s + worker registered + 3-step claim/dispatch/finalize tested.
- [ ] **T0-5** `POST /api/v2/admin/casbin/reload` endpoint shipped + admin-only Casbin guard + audit log.

Misc readiness:
- [ ] Profile creation flow PLAN §3.3.g.1 implemented (Q11 resolved — auto-create draft + issue submit token).
- [ ] Maintenance window communicated 7d trước.
- [ ] Standby team confirmed availability.
- [ ] Rollback compose override file `docker-compose.rollback.yml` chuẩn bị sẵn (Phần 8.1 Cách B) HOẶC `docker-compose.yml` support env var image tag (Cách A).

### 9.4. Rollback readiness
- [ ] Rollback procedure documented + tested trên staging.
- [ ] Recovery time documented (Phần 5.5).
- [ ] Pre-cutover image tags verified pullable.

**Nếu bất kỳ checkbox FAIL → No-Go, reschedule cutover.**

## 10. Owner / Sign-off

| Role | Signed by | Date | Decision (Go/No-Go) |
|---|---|---|---|
| Backend Lead | __________ | __________ | __________ |
| Frontend Lead | __________ | __________ | __________ |
| DBA / Ops Lead | __________ | __________ | __________ |
| QA Lead | __________ | __________ | __________ |
| Product Owner | __________ | __________ | __________ |
| Admission Ops | __________ | __________ | __________ |
| Legal/Compliance | __________ | __________ | __________ |

**Sign-off scope per role:**
- **Backend Lead**: full scope v2.13/v2.13.1 implementation + 27 migration + 14 code task + Task 0 prerequisites (Phần 3.5) + state service + outbox + multi-NV engine. Sign-off rằng code đã pass CI/test/lint trên `feat/admission-full-cutover` branch.
- **Frontend Lead**: i18n inline 25 keys + 14 status render + 5 component mới + multi-NV UX + typed `available_actions` contract. Sign-off rằng FE bundle production-ready.
- **DBA / Ops Lead**: backup/restore plan + 27 migration chain review + one-way migration risk acceptance + maintenance window schedule + rollback playbook + monitoring dashboard + Nginx admission block config (T0-3).
- **QA Lead**: E2E checklist + rehearsal protocol 2 lần + smoke test 8 critical journey sign-off + Casbin matrix 4×14 verified.
- **Product Owner**: Q1-Q10 decisions chốt (Q11 resolved trong PLAN §3.3.g.1) + multi-NV launch user-facing + maintenance window 4-6h communication.
- **Admission Ops** (vận hành admission daily): freeze window timing acceptable cho operational continuity + read-only allowed endpoints đáp ứng tham khảo officer trong window + post-cutover unlock procedure.
- **Legal/Compliance**: bypass consent in-app+email; Zalo/SMS gated `zalo_template_approved` flag (12 ZNS template approval roadmap).

**Rollback decision authority**: Backend Lead + DBA/Ops Lead **bất kỳ một** có thẩm quyền trigger rollback (Phần 8.3 trigger conditions). Product Owner + Admission Ops được notify, KHÔNG block rollback decision khi data corruption phát hiện.

---

**Appendix: file map sau cleanup 2026-05-01**

```
Documents/
├── ADMISSION_REFACTOR_PLAN.md            (KEEP — source of truth, v2.13.1)
├── ADMISSION_REFACTOR_RISK_REVIEW.md     (KEEP — evidence/risk log)
├── ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md  (THIS FILE — operations runbook)
├── ADMISSION_IMPLEMENTATION_TRACKER.md   (KEEP — daily progress tracker)
└── archive/
    ├── ADMISSION_MATRIX_MAPPING.md             (ARCHIVED 2026-05-01 — stale 2026-01-15 lệch với code; source of truth là code, không doc)
    ├── ADMISSION_MVP_CUTOVER_PLAN.md           (ARCHIVED — MVP rút scope mâu thuẫn full v2.13)
    ├── ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md  (ARCHIVED — v3.1 historical)
    ├── ADMISSION_PIPELINE_SYNC_SOLUTION.md     (ARCHIVED — historical impl summary)
    ├── ADMISSION_MODULE_AUDIT_2026-04-27.md    (ARCHIVED — Wave 1+2 audit closed)
    └── PR_DRAFTS_2026-05-01.md                 (ARCHIVED — staged PR sequence không còn áp dụng)
```

**Event/pipeline projection source of truth = code** (4 file):
- `Backend_FastAPI/app/core/admission_event_mapping.py`
- `Backend_FastAPI/app/services/lead_admission_sync.py`
- `Backend_FastAPI/scripts/data/consultation_status_v3.csv`
- `Backend_FastAPI/scripts/data/allowed_transitions_v3.csv`

`ADMISSION_FULL_CUTOVER_PLAN.md` (DELETED 2026-05-01 — duplicate spec với REFACTOR_PLAN.md, không tạo full plan thứ hai).
