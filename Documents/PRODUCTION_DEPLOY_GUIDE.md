# Production Deploy Guide — QLTS

**Last updated**: 2026-04-05
**VPS**: `qlts.tnpc.edu.vn` (root@)
**Repo on server**: `/opt/qlts`
**Branch**: `main`

---

## Prerequisites

- SSH key: `~/.ssh/id_ed25519_qlts`
- GitHub repo: `favouritekid/QLTS`
- Production env: `.env.production` (on server, NOT in repo)

---

## Checklist (copy-paste for each deploy)

```
[ ] 1. Local: code reviewed, tests pass, branch merged to main
[ ] 2. SSH vào VPS
[ ] 3. Backup DB
[ ] 4. Prune Docker cache (nếu disk > 70%)
[ ] 5. Pull code
[ ] 6. Build + Deploy
[ ] 7. Verify healthy
[ ] 8. Verify migration/sync
[ ] 9. Seed (nếu có template mới) — dry-run trước
[ ] 10. Smoke test
```

---

## Step-by-step

### 1. Local: Merge to main

```bash
# Push feature branch
git push -u origin feature/your-branch

# Create PR + Merge (via GitHub UI hoặc CLI)
gh pr create --base main --head feature/your-branch --title "..."
gh pr merge <PR_NUMBER> --merge
```

### 2. SSH vào VPS

```bash
ssh -i ~/.ssh/id_ed25519_qlts root@qlts.tnpc.edu.vn
cd /opt/qlts
```

### 3. Backup DB (BẮT BUỘC trước mọi deploy)

```bash
docker exec qlts-postgres-1 pg_dump -U qlts qlts_production | gzip > /root/backup_$(date +%Y%m%d_%H%M%S).sql.gz

# Verify
ls -lh /root/backup_*.sql.gz | tail -1
```

### 4. Prune Docker cache

```bash
# Kiểm tra disk
df -h /

# Nếu > 60%, prune:
docker builder prune -f
docker image prune -a -f --filter "until=72h"

# Verify
df -h /
```

### 5. Pull code

```bash
git fetch --all
git checkout main
git pull origin main

# Verify HEAD đúng
git log --oneline -3
```

### 6. Build + Deploy

**QUAN TRỌNG**: Phải dùng `--env-file .env.production`. KHÔNG dùng `docker compose up` mà thiếu flag này.

```bash
# Build — PHẢI có `nginx`
docker compose -f docker-compose.yml --env-file .env.production --profile production build backend frontend nginx

# Deploy — liệt kê service TƯỜNG MINH, KHÔNG `up -d` trần
docker compose -f docker-compose.yml --env-file .env.production --profile production \
    up -d --wait postgres redis backend celery-worker celery-beat frontend

# nginx đi qua CỔNG CANDIDATE, không bao giờ bị thay thẳng
set -a && source .env.production && set +a
bash scripts/nginx-apply.sh "$DOMAIN"
```

⚠️ **`up -d` trần sẽ thay thẳng container nginx đang phục vụ.** Cấu hình mới
chưa được đo lần nào mà container tốt đã bị stop+remove; template hỏng, chứng
thư thiếu hay `DOMAIN` rỗng đều thành :80/:443 chết không đường lùi. Đó chính là
sự cố 12-08. `scripts/nginx-apply.sh` dựng candidate, đo TLS/SNI thật với một
route backend và một route frontend, **chỉ khi đạt** mới thay bản đang chạy.
Đường chuẩn `scripts/deploy.sh` đã làm đúng thế — hướng dẫn tay phải theo.

⚠️ **`nginx` bắt buộc nằm trong lệnh build.** Từ khi cấu hình nginx đi theo image
(`nginx/Dockerfile`, tag cố định `qlts-nginx:local`), một máy đã có sẵn tag đó sẽ
được `up -d` **dùng lại ảnh CŨ** — mọi thay đổi template hay script entrypoint
lặng lẽ không được deploy, và không có dấu hiệu nào báo. Đường deploy chuẩn
(`scripts/deploy.sh`) build `--parallel` toàn bộ nên không dính; chỉ đường tay
này mới hở.

**Nếu chỉ deploy backend** (không đổi frontend):
```bash
docker compose -f docker-compose.yml --env-file .env.production --profile production build backend
docker compose -f docker-compose.yml --env-file .env.production --profile production up -d backend celery-worker celery-beat
```

**Nếu chỉ deploy frontend**:
```bash
docker compose -f docker-compose.yml --env-file .env.production --profile production build frontend
docker compose -f docker-compose.yml --env-file .env.production --profile production up -d frontend
```

**Nếu có đụng `nginx/`** (template, `nginx.conf`, `docker-entrypoint.d/`) — dùng
đường chuẩn thay vì hai lệnh trên, vì nó dựng candidate và đo bằng request thật
trước khi thay container đang phục vụ:
```bash
set -a && source .env.production && set +a
docker compose -f docker-compose.yml --env-file .env.production --profile production build nginx
bash scripts/nginx-apply.sh "$DOMAIN"
```

### 7. Verify healthy

```bash
# Chờ 30-60s cho container startup
sleep 30

# Check all services
docker ps --format "table {{.Names}}\t{{.Status}}"

# Expected: 7 services (8 nếu tính certbot), tất cả Up/Healthy
# - postgres (healthy)
# - redis (healthy)
# - backend (healthy)
# - frontend (healthy)
# - nginx (healthy)
# - celery-worker (Up)
# - celery-beat (Up)

# Health endpoint
curl -s http://localhost:8000/health
```

### 8. Verify migration/sync

`alembic upgrade head` và `sync_notification_rules` chạy tự động qua entrypoint. Verify:

```bash
# Check alembic version
docker exec qlts-postgres-1 psql -U qlts -d qlts_production -t -c "SELECT version_num FROM alembic_version;"

# Check notification tables exist
docker exec qlts-postgres-1 psql -U qlts -d qlts_production -t -c "
  SELECT table_name FROM information_schema.tables
  WHERE table_schema='public' AND table_name LIKE 'notification%'
  ORDER BY table_name;
"

# Check rule count
docker exec qlts-postgres-1 psql -U qlts -d qlts_production -t -c "SELECT count(*) FROM notification_rule;"
```

### 9. Seed template library (khi có template mới)

```bash
# LUÔN dry-run trước
docker exec qlts-backend-1 python -m app.scripts.seed_notification_template_library --dry-run

# Verify output khớp expectation, rồi mới apply
docker exec qlts-backend-1 python -m app.scripts.seed_notification_template_library --apply

# Verify DB
docker exec qlts-postgres-1 psql -U qlts -d qlts_production -t -c "
  SELECT template_type, count(*) FROM notification_template GROUP BY template_type;
"
```

### 10. Smoke test

```bash
# Backend
curl -s http://localhost:8000/health

# Frontend
curl -sk -o /dev/null -w "HTTP %{http_code}" https://qlts.tnpc.edu.vn/login

# Check logs for errors
docker logs qlts-backend-1 --since=5m 2>&1 | grep -iE "error|traceback|500" | grep -v health
docker logs qlts-celery-worker-1 --tail=10 2>&1 | grep -E "ready|error"
```

---

## Gotchas / Bẫy đã gặp

### 1. `docker-compose.override.yml` chạy frontend dev mode

**Triệu chứng**: Frontend serve Turbopack chunks, Server Actions fail, login form submit không tới backend.

**Nguyên nhân**: `docker-compose.override.yml` tồn tại trên server → override frontend command thành `npm run dev`.

**Fix**: Rename hoặc xóa override file trên production:
```bash
mv docker-compose.override.yml docker-compose.override.yml.dev-only
```

**Phòng ngừa**: KHÔNG copy `docker-compose.override.yml` lên production. File này chỉ dùng cho dev.

### 2. Celery worker/beat crash vì thiếu volume

**Triệu chứng**: celery-worker và celery-beat restart loop, log hiện `PermissionError: /app/app/static/uploads/avatars`.

**Nguyên nhân**: `config.py` chạy `os.makedirs()` khi import. Backend container có volume `backend_static_uploads` nhưng celery containers thiếu.

**Fix**: Thêm volume vào celery services trong `docker-compose.yml`:
```yaml
celery-worker:
  volumes:
    - backend_static_uploads:/app/app/static/uploads  # thêm dòng này
    
celery-beat:
  volumes:
    - backend_static_uploads:/app/app/static/uploads  # thêm dòng này
```

### 3. POSTGRES_PASSWORD missing khi build

**Triệu chứng**: `error while interpolating: POSTGRES_PASSWORD is missing a value`

**Nguyên nhân**: Compose đọc `.env` mặc định, nhưng production dùng `.env.production`.

**Fix**: Luôn dùng `--env-file .env.production`:
```bash
docker compose -f docker-compose.yml --env-file .env.production --profile production build ...
```

### 4. MFA enforce cho admin/manager

**Triệu chứng**: Login OK nhưng mọi API trả 403 "MFA is required for privileged accounts".

**Nguyên nhân**: Backend enforce MFA cho role admin/manager (OWASP ASVS 5.0). Nếu MFA bị disable, admin không thể dùng hệ thống.

**Fix**: Admin phải bật MFA qua Settings > Xác thực 2 lớp. Nếu locked out:
```bash
# Tạm disable MFA (emergency only)
docker exec qlts-postgres-1 psql -U qlts -d qlts_production -c "
  UPDATE \"user\" SET mfa_enabled=false WHERE username='admin';
"
# Sau đó login và bật lại MFA ngay
```

---

## Rollback

Nếu deploy lỗi nghiêm trọng:

```bash
# 1. Rollback code
cd /opt/qlts
git log --oneline -5  # tìm commit trước deploy
git checkout <previous_commit>

# 2. Rebuild + redeploy — `nginx` PHẢI có mặt
#    `git checkout` ở bước 1 đã đưa cả `nginx/` về bản cũ, nhưng ảnh
#    `qlts-nginx:local` trên máy vẫn là ảnh của bản LỖI cho tới khi build lại.
#    Thiếu `nginx` ở đây = rollback code mà nginx vẫn chạy cấu hình vừa gây sự cố.
docker compose -f docker-compose.yml --env-file .env.production --profile production build backend frontend nginx
docker compose -f docker-compose.yml --env-file .env.production --profile production \
    up -d --wait postgres redis backend celery-worker celery-beat frontend
# nginx qua cổng candidate — kể cả khi rollback, nhất là khi rollback
set -a && source .env.production && set +a
bash scripts/nginx-apply.sh "$DOMAIN"

# 3. Rollback DB (nếu cần)
gunzip < /root/backup_YYYYMMDD_HHMMSS.sql.gz | docker exec -i qlts-postgres-1 psql -U qlts -d qlts_production
```

---

## Server info

| Item | Value |
|------|-------|
| Host | qlts.tnpc.edu.vn |
| IP | VPS (check DNS) |
| OS | Ubuntu, kernel 6.8.0 |
| SSH user | root |
| SSH key | `~/.ssh/id_ed25519_qlts` |
| Repo path | `/opt/qlts` |
| DB name | `qlts_production` |
| DB user | `qlts` |
| Env file | `.env.production` |
| Timezone | Asia/Ho_Chi_Minh (+07) |
| SSL | Let's Encrypt, auto-renew via certbot |
