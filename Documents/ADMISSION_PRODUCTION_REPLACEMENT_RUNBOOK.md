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

⚠️ **Runbook này giả định 5 infrastructure family dưới đã được implement trong code.** Verified codebase 2026-05-01: tất cả CHƯA TỒN TẠI. Phải ship trong implementation phase (sub-PR riêng) TRƯỚC khi bắt đầu staging rehearsal Phần 7. KHÔNG assume. T0-4 được tách thành 2 tracker row: T0-4a skeleton an toàn trước khi có outbox table, T0-4b worker thật sau B2 + M-1-19a.

| Task 0 | Why | Codebase evidence (CHƯA CÓ) | Acceptance |
|---|---|---|---|
| **T0-1: 2 env flag gates** trong `Backend_FastAPI/docker-entrypoint.sh`: `RUN_MIGRATIONS_ON_STARTUP` + `RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP` | Cold cutover yêu cầu manual `alembic upgrade head` + manual `sync_notification_rules` SAU migration + backfill (KHÔNG auto trên container start vì pre-migration state có thể chưa có notification_rule table hoặc chưa seed → script fail/race) | `docker-entrypoint.sh` auto chạy `alembic upgrade head` (line 4-5) + `python -m app.scripts.sync_notification_rules` (line 7-8), cả 2 không conditional | Entrypoint thêm 2 gate độc lập: `if [ "${RUN_MIGRATIONS_ON_STARTUP:-true}" != "false" ]; then alembic upgrade head; fi` + `if [ "${RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP:-true}" != "false" ]; then python -m app.scripts.sync_notification_rules; fi`. Default `true` cho routine deploy. Cutover set CẢ 2 = `false`. Defensive: chỉ exact lowercase `"false"` mới skip; mọi value khác (TRUE/FALSE/typo) chạy như cũ. |
| **T0-2: `ADMISSION_FROZEN` middleware** | Freeze admission write endpoints khi maintenance window | Grep zero match `ADMISSION_FROZEN` trong `app/config.py`, `app/middleware/`, `app/routers/admissions.py` | Settings field + middleware raise 503 cho POST/PUT/PATCH/DELETE trên 3 prefix verified-from-code: `/api/admissions/*`, `/api/admission-config/*` (covers cả `admission_config.py` + `admission_paths.py` — 2 router file share cùng prefix), `/api/public/admissions/*`. Path-segment match (KHÔNG raw startswith) để `/api/admissionsfoo` không bị false positive. **Reload mechanism: env-based settings cần container restart** (Pydantic BaseSettings load 1 lần module-level) — runbook Phần 6.1 phải clarify restart container, KHÔNG hot-reload runtime. |
| **T0-3: Nginx admission block config** | Defense-in-depth với T0-2 backend middleware | `nginx/conf.d/default.conf.template` chỉ generic `/api/` proxy, zero conditional admission block | Conditional `location ~ ^/api/(admissions|admission-config|public/admissions)(/.*)?$ { ... return 503 ...}` env-driven `${NGINX_ADMISSION_FROZEN}` template variable (3 prefix match T0-2 middleware verified-from-code). |
| **T0-4a: `dispatch_pending_outbox` skeleton task** | Register Celery beat safely before outbox table/model exists | `app/celery_app.py:108-150` zero match | Beat schedule entry 30s + task function exists, logs "outbox not yet active", returns early, KHÔNG query/insert/dispatch `NotificationOutbox`. Safe to ship before B2 + M-1-19a. |
| **T0-4b: `dispatch_pending_outbox` real worker wiring** | Worker drain outbox notification queue | `notification_outbox` table/model chưa tồn tại trước B2 + M-1-19a | Replace skeleton with 3-step claim/dispatch/finalize implementation per PLAN Phần 3.3.e. Gate: B2 + M-1-19a shipped first. |
| **T0-5: `POST /api/v2/admin/casbin/reload` endpoint** | Diagnostic / smoke reload sau seed deny rules direct DB. **Chỉ tác động 1 Gunicorn worker process — KHÔNG fleet-wide.** Cutover-correct reload là restart backend container (lifespan re-init enforcer ở mọi worker, xem §7.2 T+3:15). | `admin/roles.py` chỉ side-effect trong CRUD endpoint, zero dedicated reload endpoint | Admin-only endpoint (`Depends(require_admin)` + `@limiter.limit(ADMIN_WRITE)`) gọi `await enforcer.load_policy()` + return `{"success", "reloaded_at", "policy_count", "actor_id", "scope": "current_process"}` + audit log. Failure → 500 với same shape, enforcer giữ in-memory state cũ (no partial flush). |

**Gate**: Phần 9.3 production readiness checklist verify 5 infrastructure family trên (6 tracker row vì T0-4 split) shipped + tested trên staging trước Go decision.

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
docker compose -f docker-compose.yml exec -T postgres pg_dump -U ${DB_USER} -Fc ${DB_NAME} > prod_${DATE}_pre_cutover.dump

# Verify file size + magic bytes (PGDMP header)
ls -la prod_${DATE}_pre_cutover.dump
file prod_${DATE}_pre_cutover.dump  # Expect: "PostgreSQL custom database dump"
head -c 5 prod_${DATE}_pre_cutover.dump | xxd  # Expect first bytes: 50 47 44 4d 50 (= PGDMP)

# Verify integrity qua pg_restore -l (list contents, không restore)
# Pipe file vào container stdin để pg_restore -l có thể đọc:
cat prod_${DATE}_pre_cutover.dump | docker compose -f docker-compose.yml exec -T postgres pg_restore -l | wc -l
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
docker compose -f docker-compose.yml exec -T backend tar czf /tmp/uploads_${DATE}.tar.gz /app/uploads /app/app/static/uploads

# Copy archive từ container ra host
docker compose -f docker-compose.yml cp backend:/tmp/uploads_${DATE}.tar.gz ./

# Cleanup tmp file inside container
docker compose -f docker-compose.yml exec -T backend rm /tmp/uploads_${DATE}.tar.gz

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
# Từ 12-08-2026 cấu hình nginx nằm ở `nginx/` và đi theo IMAGE (xem
# nginx/Dockerfile) — không còn `nginx/conf.d/` để sao lưu, và cũng không còn
# tệp render nào nằm ngoài git. Sao lưu ở đây chỉ để có bản chụp tại chỗ; nguồn
# chuẩn là git.
cp -r nginx/ nginx_backup_${DATE}/

# Docker compose
cp docker-compose.yml docker-compose_backup_${DATE}.yml
cp docker-compose.override.yml docker-compose_override_backup_${DATE}.yml

# Upload bundle offsite
tar czf config_backup_${DATE}.tar.gz env_backup_*.txt nginx_backup_${DATE}/ docker-compose_*_backup_${DATE}.yml
aws s3 cp config_backup_${DATE}.tar.gz s3://qlts-backup/admission-cutover/
```

### 5.4. Docker image tag backup

```bash
# BỐN ảnh, không phải hai. Compose đặt tên ảnh dựng được theo
# `<project>-<service>`, nên `celery-worker` và `celery-beat` có ảnh RIÊNG chứ
# không dùng chung ảnh của `backend` (kiểm: `docker images | grep qlts-celery`).
# Tag thiếu hai cái đó thì rollback sẽ lùi backend mà để worker ở phiên bản
# MỚI, chạy trên lược đồ CSDL đã lùi.
# Tag theo ID ẢNH CỦA CONTAINER ĐANG CHẠY, KHÔNG theo `:latest`.
# `qlts-<service>:latest` là một tag DI ĐỘNG: nó có thể đã trôi sang một bản
# build khác từ trước khi ta chạm vào. Tag từ nó nghĩa là tài sản rollback sai
# ngay lúc tạo ra, và không có gì phát hiện được điều đó về sau. `.Image` của
# container đang chạy là thứ duy nhất chắc chắn đúng "phiên bản đang phục vụ".
export QLTS_ROLLBACK_TAG=pre-admission-cutover-${DATE}
MANIFEST=rollback_manifest_${QLTS_ROLLBACK_TAG}.txt
: > "$MANIFEST"

# `set -e` phủ TRỌN khối, kể cả `docker push`. Đừng tắt nó giữa chừng: một lần
# push hỏng (hết hạn đăng nhập, sai repo, registry sập) mà bị nuốt thì tag chỉ
# tồn tại TRÊN CHÍNH MÁY NÀY — và preflight vẫn ĐẠT, vì `docker image inspect`
# thấy tag local nên không bao giờ thử `pull`. Cổng T-1d sẽ tuyên bố "sẵn sàng
# rollback" cho một tài sản sẽ bốc hơi ngay khi máy chủ mất hoặc bị prune.
set -e

# Ghi cả REVISION GIT — §8.1 Step 5 cần nó để khôi phục cây nginx chính xác.
printf '# git-rev\t%s\n' "$(git rev-parse HEAD)" >> "$MANIFEST"

for S in backend celery-worker celery-beat frontend; do
    CID=$(docker compose -f docker-compose.yml --env-file .env.production \
        --profile production ps -q "$S")
    [ -n "$CID" ] || { echo "KHONG THAY container dang chay cho '$S'"; exit 1; }
    IMG_ID=$(docker inspect -f '{{.Image}}' "$CID")
    docker tag "$IMG_ID" "qlts-${S}:${QLTS_ROLLBACK_TAG}"
    printf '%s\t%s\t%s\t%s\n' \
        "$S" "$CID" "$IMG_ID" "qlts-${S}:${QLTS_ROLLBACK_TAG}" >> "$MANIFEST"
done

# Push registry — VẪN trong `set -e`. Hỏng ở đây là DỪNG, không phải ghi chú.
for S in backend celery-worker celery-beat frontend; do
    docker push "qlts-${S}:${QLTS_ROLLBACK_TAG}"
done
set +e

cat "$MANIFEST"    # git-rev · service · container ID · image ID · reference

# Diễn tập NGAY tại T-1d bằng ĐÚNG script mà rollback sẽ chạy.
# `docker-compose.rollback.yml` đã có sẵn trong repo — KHÔNG sinh ad-hoc.
QLTS_ROLLBACK_TAG=${QLTS_ROLLBACK_TAG} bash scripts/rollback-preflight.sh
# Nó fail-closed ở cả năm ca: thiếu manifest · manifest thiếu service · ảnh
# không lấy được · tag đã trôi sang ID khác · service còn `build:`.
# Không ĐẠT ở đây = KHÔNG có đường lùi = KHÔNG cutover.
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
    docker compose -f docker-compose.yml exec -T postgres pg_restore \
        -U ${DB_USER} -d ${STAGING_DB} --clean --if-exists --no-owner --no-acl
END_TIME=$(date +%s)
RESTORE_TIME=$((END_TIME - START_TIME))

# Step 2: Verify count match production qua psql trực tiếp (ổn định hơn Python ad-hoc)
docker compose -f docker-compose.yml exec -T postgres psql -U ${DB_USER} -d ${STAGING_DB} <<'SQL'
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
# Backend env — BẮT BUỘC dựng lại container sau khi set (KHÔNG phải `restart`:
# `env_file` chỉ được đọc lúc container được TẠO — xem §6.1b, đã đo hai chiều).
# Edit .env.production:
#   ADMISSION_FROZEN=true
docker compose -f docker-compose.yml --env-file .env.production --profile production up -d --no-deps --wait backend
docker compose -f docker-compose.yml --env-file .env.production --profile production ps backend

# Verify middleware active
curl -X POST http://localhost:8000/api/admissions/test-endpoint  # Expect: 503 Service Unavailable
curl -X GET  http://localhost:8000/api/admissions/                # Expect: 200 (read-only allowed)

# Nginx env (T0-3): xem §6.1b "Cần gạt đóng băng — quy trình DUY NHẤT" ngay
# dưới đây. TUYỆT ĐỐI không dùng `nginx -s reload` hay `docker compose restart
# nginx`: cả hai đều KHÔNG bật được cần gạt, mà vẫn in ra ba dòng xanh.
```

**Quan trọng**: backend restart mất ~10-30s, có downtime ngắn. Nếu cần zero-downtime → escalate scope T0-2 implement Redis-backed config (out of scope runbook hiện tại).

### 6.1b. Cần gạt đóng băng — quy trình DUY NHẤT

> **Đây là nơi duy nhất mô tả cách bật/tắt cần gạt.** §7.2 T+0:15 và §8 Step 1 /
> Step 6 đều trỏ về đây. Trước 13-08-2026 mỗi chỗ tự chép một biến thể, và cả
> ba biến thể đều đã CHẾT mà vẫn in ra màu xanh.

**Vì sao ba lệnh quen thuộc đều không dùng được:**

| Lệnh | Kết quả thật |
|---|---|
| `envsubst … > nginx/conf.d/default.conf` | đường vào không còn tồn tại; `>` vẫn cắt cụt một tệp mà **không container nào mount** |
| `nginx -s reload` | tiến trình đang chạy nạp lại đúng bản render **CŨ của chính nó**; `nginx -t` vẫn "syntax is ok", reload vẫn exit 0 |
| `docker compose restart nginx` | `restart` tái dùng biến môi trường đã nướng vào container, **không đọc lại** `.env.production` |
| `docker compose restart backend` | **Cùng một lỗi, ở tầng backend.** `ADMISSION_FROZEN` vào container qua `env_file`, mà `env_file` chỉ được đọc lúc container được TẠO. Đã đo hai chiều trên một stack tối giản: sửa tệp env rồi `restart` ⇒ container y nguyên, biến vẫn `false`; `up -d` ⇒ container MỚI, biến thành `true`. Nên cả hai tầng của cần gạt (nginx và backend) đều câm nếu dùng `restart`. |

Vì `up -d` chỉ dựng lại khi cấu hình đã đổi thật, nó **không** phải `--force-recreate`: đổi
`.env.production` thì nó recreate, không đổi gì thì nó là no-op. `--wait` để lệnh chỉ trả về
khi container mới đã `healthy`.

Cờ được `envsubst` bake vào bản render lúc container **khởi động**, không đọc lúc chạy. Nên cách duy nhất là để Compose **tạo container mới** với biến mới.

> 🔴 **`-f docker-compose.yml` là BẮT BUỘC ở mọi lệnh production.** Thiếu nó, Compose tự nạp
> `docker-compose.override.yml` — tệp override của DEV. Đã đo trong worktree này: cùng một
> lệnh `--env-file .env.production --profile production config`, bản thiếu `-f` cho backend
> `command = uvicorn app.main:app --reload` và `APP_ENV = development`, kèm `env_file:
> ./Backend_FastAPI/.env` và bind-mount mã nguồn; bản có `-f` cho `command = None`,
> `APP_ENV = None`. Trên máy chưa có `Backend_FastAPI/.env` thì lệnh đổ — ồn ào nhưng vô
> hại. Trên máy CÓ tệp đó, nó **dựng cấu hình development trên production** và không báo gì.
> `test_lenh_compose_phai_ghim_docker_compose_yml` khoá bất biến này cho cả runbook,
> `PRODUCTION_DEPLOY_GUIDE.md` và các script chạm production.

```bash
# 1. Sửa .env.production:
#      ADMISSION_FROZEN=true
#      NGINX_ADMISSION_FROZEN=true
#    Chỉ đúng chuỗi thường `true` mới bật. Guard entrypoint
#    (nginx/docker-entrypoint.d/10-qlts-kiem-bien.sh) TỪ CHỐI mọi giá trị khác,
#    nên một cú gõ nhầm (TRUE, 1, "true ") thành container không lên — thấy
#    ngay — thay vì một cần gạt câm mà ai cũng tưởng đã đóng.

# 2. Áp. `nginx-apply.sh` dựng một container candidate, đo hành vi thật của nó
#    (TLS + SNI thật, route backend, route frontend), CHỈ KHI ĐẠT mới thay
#    container đang phục vụ. Cấu hình hỏng ⇒ dừng lại, last-good vẫn chạy.
set -a && source .env.production && set +a
docker compose -f docker-compose.yml --env-file .env.production --profile production up -d --no-deps --wait backend
bash scripts/nginx-apply.sh "$DOMAIN"

# 3. CHỨNG MINH bằng request thật. Không dòng log nào được tính là bằng chứng.
curl -s -o /dev/null -w 'POST admissions -> %{http_code}\n' -X POST "https://$DOMAIN/api/admissions/"
#    PHẢI 503

curl -s -o /dev/null -w 'GET  admissions -> %{http_code}\n' "https://$DOMAIN/api/admissions/"
#    KHÔNG được 503 — đọc vẫn phải mở để còn soi dữ liệu

curl -s -o /dev/null -w 'POST payments   -> %{http_code}\n' -X POST "https://$DOMAIN/api/payments/"
#    KHÔNG được 503 — ngoài phạm vi đóng băng
```

**Mở băng** = đúng ba bước trên với `false`, và phép chứng minh đảo lại: `POST /api/admissions/` phải **thôi** trả 503 (401/422 tuỳ payload đều được — điều cần thấy là nó đã đi tới backend).

Cặp 200 ↔ 503 này có ca chạy thật trong `tests-e2e/nginx-packaging/` (mục "Cần gạt đóng băng"), chạy trên stack cô lập nên diễn tập được mà không đụng prod.

### 6.2. Read-only allowed endpoints

T0-2 middleware filter theo HTTP method, KHÔNG hard-code path list. Method matrix:

| Method | Path prefix | Behavior khi `ADMISSION_FROZEN=true` |
|---|---|---|
| GET / HEAD / OPTIONS | `/api/admissions/*`, `/api/admission-config/*`, `/api/public/admissions/*` (3 distinct prefix verified-from-code on branch `feat/admission-full-cutover` HEAD `2c57e5d6` 2026-05-02) | **Allowed** — view profiles/paths/criteria/documents |
| POST/PUT/PATCH/DELETE | Any admission write endpoint trên 3 prefix trên | **503 Service Unavailable** với JSON body `{detail, code: "ADMISSION_FROZEN", frozen_prefix}` |
| POST | `/api/admissions/confirm/{token}` (magic link consume) | **503** — block candidate consume token trong window |

Block scope (theo router source verified `Backend_FastAPI/app/routers/admissions.py`, `admission_paths.py`, `admission_config.py`, `public_admissions.py` — 4 router file nhưng share 3 prefix; `admission_config.py` + `admission_paths.py` đều `APIRouter(prefix="/admission-config")`):
- Profile mutation (create/update/delete)
- Status transition (approve/reject/confirm/withdraw/override/...)
- Document upload + reset
- Magic link issue/consume + token verification
- Path/config admin CRUD
- Public storefront submit endpoints

T0-2 acceptance test: 4 write method × 3 distinct prefix matrix verify trong staging trước rollout. 47 case PASS local on PR T0-2: 12 unfrozen pass-through + 12 frozen-block 503 + 9 frozen read-allowed (GET/HEAD/OPTIONS) + 4 non-admission baseline (`/api/leads/*`) + 4 path-segment lookalike rejection (`/api/admissionsfoo`) + 3 bare-prefix block + 1 health reachable + 1 contract-shape sanity + 1 route-table drift catch (`fastapi_app.routes` scan flags any `/api/...admission...` path not under FROZEN_PREFIXES).

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

> **🚨 Self-update caveat — pre-stage `deploy.sh` before invoking** (lesson
> from 2026-05-07 cutover ship):
>
> When `scripts/deploy.sh` changes ship via main, invoking
> `./scripts/deploy.sh` directly on prod runs the **OLD** logic — bash
> loads the script into memory at invocation, then Step 2 `git pull
> origin main` updates the file on disk but the in-memory copy stays
> OLD. Any new flag (e.g. `COLD_CUTOVER` detection added in Hotfix #4)
> only takes effect from the **SECOND** invocation onwards.
>
> **Mitigation**: pre-stage updated script before invoking:
>
> ```bash
> ssh prod && cd /opt/qlts
> git fetch origin && git checkout main && git pull --ff-only origin main
> cp scripts/deploy.sh /tmp/deploy_NEW.sh && chmod +x /tmp/deploy_NEW.sh
> COLD_CUTOVER=true /tmp/deploy_NEW.sh
> ```
>
> The `/tmp` copy is loaded into bash memory; Step 2's git pull updates
> the on-disk script but our running invocation already loaded the NEW
> logic. See `scripts/deploy.sh` Self-update caveat header for full
> rationale.

```
T+0:00   Communicate freeze (email + Slack + in-app banner)
T+0:15   Edit .env.production: ADMISSION_FROZEN=true + NGINX_ADMISSION_FROZEN=true
         Apply + Verify: theo §6.1b "Cần gạt đóng băng — quy trình DUY NHẤT"
           set -a && source .env.production && set +a
           docker compose -f docker-compose.yml --env-file .env.production --profile production up -d --no-deps --wait backend
           bash scripts/nginx-apply.sh "$DOMAIN"
         # KHÔNG dùng envsubst trên host / nginx -s reload / restart nginx —
         # cả ba đều KHÔNG bật được cần gạt mà vẫn in ra màu xanh (§6.1b).
         Verify BẮT BUỘC: curl POST /api/admissions/ → 503, và GET → khác 503
T+0:30   Final pg_dump + uploads tar + config backup → upload S3 + integrity verify
T+1:00   Deploy backend image MỚI với 3 env flag = false:
           RUN_MIGRATIONS_ON_STARTUP=false
           RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=false
           RUN_CASBIN_LOAD_ON_STARTUP=false
         (per RISK_REVIEW OG-1 + B1 cold-cutover gate: tách Alembic + notification rule
          sync + Casbin policy load khỏi container startup cho cutover.
          Lý do skip sync rules: pre-migration state có thể chưa có notification_rule table hoặc chưa seed
          12 ADMISSION_* DB rows → script fail/race. Manual run ở T+3:30 sau migration + DB seed.
          Lý do skip Casbin load: 4-field auth_model.conf trên image mới yêu cầu casbin_rule.v3
          được backfill 'allow' cho 210 row legacy + 6 deny row accountant đã seed; nếu lifespan load
          policy trước khi migration phase1_19b chạy → enforcer.enforce() raise
          RuntimeError("invalid policy size") trên mọi request. Manual reload qua container restart
          ở T+3:15 sau migration backfill.)
         Verify: container start → KHÔNG chạy alembic, KHÔNG chạy sync_notification_rules,
                 KHÔNG load Casbin policy, chỉ uvicorn ready (log "Skipping..." cho cả 3 gate).
T+1:30   Manual run Alembic chain:
           docker compose -f docker-compose.yml exec backend alembic upgrade head
         Stream log realtime; checkpoint mỗi migration step.
         Time tracking — nếu một migration > 5 phút unexpected → pause, investigate.
         Estimate full chain ~30-60 phút (data backfill heavy).
T+3:00   Manual run backfill scripts theo PLAN Phần 4 + 5b:
           - status_history initial (1 row/profile + 5 scattered scalar)
           - selected_subject_group_id decision tree 3 rule
           - GPA backfill từ academic_history JSON (length-bounded regex)
           - graduation_year backfill
           - Casbin v3='allow' + seed deny rules accountant
T+3:15   **Restart backend container** để fleet-wide reload Casbin enforcer
         (T0-5 endpoint reload chỉ tác động 1 Gunicorn worker — KHÔNG đủ
          cho multi-worker production; cần lifespan re-load mọi worker).
         Giữ 2 cutover env flags để tránh re-trigger auto-migration / sync,
         FLIP RUN_CASBIN_LOAD_ON_STARTUP về true (hoặc unset) cho lifespan
         load_policy() đọc casbin_rule đã backfill ở T+3:00:
           RUN_MIGRATIONS_ON_STARTUP=false
           RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=false
           RUN_CASBIN_LOAD_ON_STARTUP=true   # ← B1: bật lại load để enforcer pickup 4-field rule
           docker compose -f docker-compose.yml --env-file .env.production --profile production up -d --no-deps --wait backend
         Verify mọi worker:
           - `docker compose -f docker-compose.yml --profile production logs backend --tail=50` — kiểm
             tra log lifespan boot success từ ALL Gunicorn workers (≥2 dòng
             "✅ Casbin AsyncEnforcer initialized and policies loaded.").
           - 4 role × 14 action smoke matrix qua Casbin (Phần 7.3 smoke có
             cover) hoặc curl `/api/v2/admin/casbin/reload` chỉ để diagnostic
             cho worker đang nhận request — KHÔNG dùng làm cơ chế reload chính.
T+3:30   Manual run sync notification rules:
           docker compose -f docker-compose.yml exec backend python -m app.scripts.sync_notification_rules
         Verify: 12 ADMISSION_* event có DB rule row.
T+3:45   Deploy frontend image MỚI (Next.js standalone container restart)
         KHÔNG có CDN purge — verify browser cache header `Cache-Control: no-cache, no-store`.
T+4:00   Deploy celery worker + celery beat images (new schedule với dispatch_pending_outbox 30s)
         Verify: celery beat schedule includes new task; worker registered.
T+4:15   Smoke tests (Phần 7.3)
T+4:45   Set ADMISSION_FROZEN=false + Nginx reload bỏ admission block
T+5:00   Communicate unlock (email + Slack + in-app banner)
T+5:15   Monitor handoff to oncall (Phần 9)
T+24h    Switch backend env back CẢ 3 flag về true (hoặc unset) cho future routine deploy:
           RUN_MIGRATIONS_ON_STARTUP=true (or unset)
           RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=true (or unset)
           RUN_CASBIN_LOAD_ON_STARTUP=true (or unset)
         (cutover behavior chỉ áp dụng 1 lần; routine deploy phục hồi auto migration + auto sync
          + auto Casbin load như trước)
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
# Edit .env.production: ADMISSION_FROZEN=true + NGINX_ADMISSION_FROZEN=true
# Rồi theo §6.1b — quy trình DUY NHẤT. Đây là thời điểm TỆ NHẤT để cần gạt câm:
# đang trong cửa sổ rollback, ai cũng tin ghi đã bị chặn.
set -a && source .env.production && set +a
docker compose -f docker-compose.yml --env-file .env.production --profile production up -d --no-deps --wait backend
bash scripts/nginx-apply.sh "$DOMAIN"
curl -s -o /dev/null -w 'POST admissions -> %{http_code}\n' -X POST "https://$DOMAIN/api/admissions/"   # PHẢI 503

# Step 2: KIỂM TÀI SẢN ROLLBACK — TRƯỚC KHI CHẠM VÀO CSDL
#
# Thứ tự này là toàn bộ vấn đề. Bản trước khôi phục CSDL ở Step 2 rồi mới đi
# tìm ảnh cũ ở Step 3. Nếu ảnh không còn (registry đã dọn, tag đã trôi, máy đã
# prune) thì lúc phát hiện ra, `pg_restore --clean` đã xoá và nạp lại lược đồ
# CŨ trong khi mã đang chạy vẫn là mã MỚI — không tiến được, không lùi được.
#
# Script fail-closed ở cả năm ca; `docker pull ... || echo` của bản trước thì
# KHÔNG: nó trả exit 0, in ra chữ "DỪNG LẠI" rồi chạy tiếp.
export QLTS_ROLLBACK_TAG=pre-admission-cutover-${DATE}   # tag đã ghi ở §5.4
bash scripts/rollback-preflight.sh || exit 1
# ĐẠT rồi mới được đi tiếp. Chưa đạt thì CSDL vẫn còn nguyên và cửa tiến vẫn mở.

# Step 3: Restore DB từ pre-cutover backup
# Pipe file vào container stdin (tránh file location mismatch)
cat prod_${DATE}_pre_cutover.dump | \
    docker compose -f docker-compose.yml exec -T postgres pg_restore \
        -U ${POSTGRES_USER:-qlts} -d ${POSTGRES_DB:-qlts_production} \
        --clean --if-exists --no-owner --no-acl

# Step 4: Deploy old images — MỘT quy trình duy nhất
#
# 13-08-2026: "Cách A" cũ (export BACKEND_IMAGE_TAG / FRONTEND_IMAGE_TAG rồi
# down/up) đã bị GỠ vì nó KHÔNG rollback gì cả. `docker-compose.yml` không hề
# đọc hai biến đó — bốn service ứng dụng chỉ khai `build:`, không khai `image:`.
# Đo thật: render compose với hai tag giả cho `services.backend.image` = None và
# `services.frontend.image` = None; `grep -c IMAGE_TAG docker-compose.yml` = 0.
# Nên `down` + `up -d` chỉ dựng lại đúng ảnh hiện hành. Chính chú thích của Cách
# A cũng ghi "Yêu cầu: docker-compose.yml phải support env var trong image tag"
# — một tiền đề chưa bao giờ được đáp ứng.
#
# "Cách B" cũ cũng hỏng theo hai đường: nó chép đè `docker-compose.override.yml`
# (tệp mà prod CỐ Ý giữ ở trạng thái đã xoá), và mọi lệnh production nay đều
# ghim `-f docker-compose.yml` nên override sẽ KHÔNG được nạp.
#
# Quy trình đúng: thêm MỘT `-f`. `docker-compose.rollback.yml` nằm sẵn trong
# repo, ghim `image:` + `build: !reset null` cho ĐỦ BỐN service.
# Ảnh đã được Step 2 chứng minh là có thật và đúng ID. Ở đây chỉ còn việc áp.
#
# ⚠️ TỪ ĐÂY TỚI HẾT §8.1, MỌI lệnh compose chạm backend/celery/frontend đều
# PHẢI mang CẢ HAI `-f`. Thiếu tệp rollback thì Compose thấy service không có
# `image:` và dựng lại từ mã MỚI — tức tự hoàn tác rollback, im lặng. Đo model:
# có rollback `backend image=qlts-backend:<cũ> build=false`; không có rollback
# `image=None build=true`.
docker compose -f docker-compose.yml -f docker-compose.rollback.yml \
    --env-file .env.production --profile production up -d --wait \
    backend celery-worker celery-beat frontend

# Quên đặt QLTS_ROLLBACK_TAG thì lệnh ĐỔ ngay (`:?` trong tệp rollback) thay vì
# lặng lẽ dựng lại ảnh hiện hành — đúng cái bẫy của quy trình cũ.

# Step 5: Restore env/config từ backup
tar xzf config_backup_${DATE}.tar.gz
cp env_backup_${DATE}.txt .env
cp backend_env_backup_${DATE}.txt Backend_FastAPI/.env
cp frontend_env_backup_${DATE}.txt frontend/.env.local
cp prod_env_backup_${DATE}.txt .env.production
# Cấu hình nginx đi theo IMAGE: khôi phục = đưa cây về ĐÚNG commit rồi BUILD
# LẠI. `cp` vào `nginx/conf.d/` là vô nghĩa (thư mục ấy không còn được mount);
# và `restart nginx` KHÔNG nạp lại biến môi trường.
#
# ⚠️ KHÔNG dùng `cp -r nginx_backup/* nginx/`. Chép chồng chỉ ghi đè những tệp
# TRÙNG ĐƯỜNG; tệp mà bản lỗi THÊM vào `nginx/` (template mới, script
# entrypoint mới) vẫn nằm nguyên. Image dựng ra là bản LAI giữa cấu hình cũ và
# chính cấu hình vừa gây sự cố — rollback có thể tái tạo lại đúng sự cố.
PRE_SHA=$(awk -F'\t' '$1=="# git-rev"{print $2}' rollback_manifest_${QLTS_ROLLBACK_TAG}.txt)
[ -n "$PRE_SHA" ] || { echo "manifest thiếu git-rev — DỪNG"; exit 1; }

git checkout "$PRE_SHA" -- nginx/     # đưa mọi tệp được theo dõi về đúng bản cũ
git clean -fd nginx/                  # xoá tệp CHỈ CÓ ở bản lỗi
git status --porcelain nginx/         # PHẢI rỗng; còn dòng nào là chưa sạch
git diff --quiet "$PRE_SHA" -- nginx/ || { echo "cây nginx CHƯA khớp $PRE_SHA — DỪNG"; exit 1; }
# nginx build từ cây git là ĐÚNG (cấu hình của nó đi theo image), nên lệnh này
# KHÔNG cần tệp rollback.
docker compose -f docker-compose.yml --env-file .env.production --profile production build nginx
# Nhưng bốn service ứng dụng thì CÓ: thiếu `-f docker-compose.rollback.yml` ở
# đây là dựng lại chúng từ mã MỚI, hoàn tác đúng thứ Step 4 vừa làm.
docker compose -f docker-compose.yml -f docker-compose.rollback.yml \
    --env-file .env.production --profile production up -d --no-deps --wait \
    backend celery-worker celery-beat frontend
set -a && source .env.production && set +a
bash scripts/nginx-apply.sh "$DOMAIN"

# Step 6: Verify smoke
curl http://localhost:8000/api/admissions/health  # Expect 200
docker compose -f docker-compose.yml exec -T postgres psql -U ${POSTGRES_USER:-qlts} -d ${POSTGRES_DB:-qlts_production} \
    -c "SELECT COUNT(*) FROM admission_profile"   # Expect: count match pre-cutover

# Step 7: Unlock (nếu smoke PASS)
# Edit .env.production: ADMISSION_FROZEN=false + NGINX_ADMISSION_FROZEN=false
# Theo §6.1b — cùng quy trình với Step 1, phép chứng minh đảo chiều.
# VẪN mang cả hai `-f`: stack đang chạy ảnh CŨ, và lệnh mở băng này dựng lại
# backend. Thiếu tệp rollback ở bước cuối cùng là lùi xong rồi tiến lại.
set -a && source .env.production && set +a
docker compose -f docker-compose.yml -f docker-compose.rollback.yml \
    --env-file .env.production --profile production up -d --no-deps --wait backend
bash scripts/nginx-apply.sh "$DOMAIN"
curl -s -o /dev/null -w 'POST admissions -> %{http_code}\n' -X POST "https://$DOMAIN/api/admissions/"   # PHẢI THÔI 503
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

5 infrastructure family Task 0 BẮT BUỘC ship + tested trên staging trước Go decision (6 tracker row vì T0-4 split):
- [ ] **T0-1** 2 env flag gates trong `docker-entrypoint.sh` — tested 9-case matrix (3 RUN_MIGRATIONS × 3 RUN_SYNC_NOTIFICATION_RULES) + 5 defensive variant (TRUE/FALSE/typo) PASS. Cutover combo `RUN_MIGRATIONS_ON_STARTUP=false` + `RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP=false` skip cả 2; default unset/true chạy alembic + sync_notification_rules như cũ.
- [ ] **T0-2** `ADMISSION_FROZEN` middleware shipped — 4 write method × 3 prefix matrix tested (GET/HEAD/OPTIONS allowed, POST/PUT/PATCH/DELETE 503 trên `/api/admissions`, `/api/admission-config`, `/api/public/admissions`); path-segment match rejects `/api/admissionsfoo` lookalike.
- [ ] **T0-3** Nginx admission block config (env-driven `NGINX_ADMISSION_FROZEN`) — nghiệm thu bằng **cặp request thật 200 ↔ 503** theo §6.1b, KHÔNG bằng `nginx -t` + reload smoke. `nginx -t` báo "syntax is ok" cho cả một config rỗng, và reload nạp lại đúng bản render cũ: bộ đôi ấy xanh ngay cả khi cần gạt không hề động đậy.
- [ ] **T0-4a** `dispatch_pending_outbox` skeleton scheduled 30s + worker registered + no-op safe before outbox table/model exists.
- [ ] **T0-4b** `dispatch_pending_outbox` real worker wiring shipped after B2 + M-1-19a + 3-step claim/dispatch/finalize tested.
- [ ] **T0-5** `POST /api/v2/admin/casbin/reload` endpoint shipped + admin-only `require_admin` + `ADMIN_WRITE` rate limit + audit log + `scope="current_process"` field. **Multi-worker reality**: fleet-wide reload = restart backend (§7.2 T+3:15); endpoint = current-process diagnostic only.

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

### 10.0 Solo dev sign-off (Phase1-Hotfix-4 amend, 2026-05-07)

Per memory `solo-developer` + `solo-cutover-simple-data-import`: dự án này solo dev (1 owner). Multi-role sign-off table dưới đây originally thiết kế cho team-style cutover; cho solo cold cutover, các role consolidated thành single-owner sign-off với explicit waiver acceptance for the V3 effective gate (~99% direct + ~1% indirect via locked unit tests).

**Effective Go gate satisfied** thay vì literal 100% strict per V3 plan, với rationale:

| Gap class | Indirect coverage source | Acceptance |
|---|---|---|
| §B alt paths direct API | §F RBAC matrix 56/56 (auth/IDOR layer) + state machine 17/17 unit tests (business-rule transitions) | Multi-angle locked; recreate alt paths = redundant với existing test suite |
| §C C6 documents 3-tier resolution với items | PR #227 12/12 unit tests (resolver isolated) + §C2-4 curl earlier (audience filter narrowing) | Resolver behavior locked by unit tests independent of fixture items |
| §E best-effort dispatch log assertion | V3 plan itself: "log-only-not-asserted"; non-strict per spec; 3/3 reachable outbox events dispatched | Outbox path (CRITICAL) verified; log-only events explicitly outside V3 strict scope |

Sign-off table dưới đây applies to solo dev: cùng 1 owner xác nhận tất cả role-specific scope đã satisfied (full audit trail trong DAILY_LOG + REHEARSAL_LOG entries 2026-05-06/07).

### 10.1 Sign-off table

| Role | Signed by | Date | Decision (Go/No-Go) |
|---|---|---|---|
| Backend Lead | favouritekid (solo dev) | 2026-05-07 | GO Phase 7 Step B (gated user explicit signal) |
| Frontend Lead | favouritekid (solo dev) | 2026-05-07 | GO |
| DBA / Ops Lead | favouritekid (solo dev) | 2026-05-07 | GO |
| QA Lead | favouritekid (solo dev) | 2026-05-07 | GO (per Rehearsal #1/#2/#3 GREEN) |
| Product Owner | favouritekid (solo dev) | 2026-05-07 | GO |
| Admission Ops | favouritekid (solo dev) | 2026-05-07 | GO (no live admission intake — frozen 2026-05-01) |
| Legal/Compliance | N/A | 2026-05-07 | N/A — solo dev, no live live intake during refactor window |

**Sign-off evidence references**: `Documents/ADMISSION_DAILY_LOG.md` 2026-05-06/07 entries + `Documents/ADMISSION_REHEARSAL_LOG.md` Rehearsal #1/#2/#3 + Implementation Tracker Section 12 sign-off + 4 hotfix PRs (#228 status_history runtime writer, #229 payload-template parity, #230 status_history override, #231 deploy alignment).

**Sign-off scope per role:**
- **Backend Lead**: full scope v2.13.1 implementation + 26 migration + 14 code task + Task 0 prerequisites (Phần 3.5) + state service + outbox + multi-NV engine. Sign-off rằng code đã pass CI/test/lint trên `feat/admission-full-cutover` branch.
- **Frontend Lead**: i18n inline 25 keys + 14 status render + 5 component mới + multi-NV UX + typed `available_actions` contract. Sign-off rằng FE bundle production-ready.
- **DBA / Ops Lead**: backup/restore plan + 26 migration chain review + one-way migration risk acceptance + maintenance window schedule + rollback playbook + monitoring dashboard + Nginx admission block config (T0-3).
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
