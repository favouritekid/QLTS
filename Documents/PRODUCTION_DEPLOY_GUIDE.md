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
# Build — cả NĂM. Bốn service ứng dụng có ảnh RIÊNG, không dùng chung ảnh nào
docker compose -f docker-compose.yml --env-file .env.production --profile production \
    build backend celery-worker celery-beat frontend nginx

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

⚠️ **`celery-worker` và `celery-beat` bắt buộc nằm trong lệnh build.** Đo model
Compose sau khi gộp: `backend`, `celery-worker`, `celery-beat`, `frontend` đều
khai `build:` riêng và **không** service nào khai `image:` chung — Compose đặt
tên ảnh dựng được theo `<project>-<service>`, nên mỗi service có ảnh của riêng
nó. Build mỗi `backend` rồi `up` cả ba là chạy **worker phiên bản CŨ** trên mã
backend mới; ở nhánh rollback thì ngược lại — worker giữ **bản MỚI** trên lược
đồ CSDL vừa lùi. Cả hai đều là lệch âm thầm, không log, không healthcheck nào
bắt được.

⚠️ **`nginx` bắt buộc nằm trong lệnh build.** Từ khi cấu hình nginx đi theo image
(`nginx/Dockerfile`, tag cố định `qlts-nginx:local`), một máy đã có sẵn tag đó sẽ
được `up -d` **dùng lại ảnh CŨ** — mọi thay đổi template hay script entrypoint
lặng lẽ không được deploy, và không có dấu hiệu nào báo. Đường deploy chuẩn
(`scripts/deploy.sh`) build `--parallel` toàn bộ nên không dính; chỉ đường tay
này mới hở.

**Nếu chỉ deploy backend** (không đổi frontend) — build đủ **ba** ảnh, vì
`up` bên dưới dựng lại cả ba:
```bash
docker compose -f docker-compose.yml --env-file .env.production --profile production \
    build backend celery-worker celery-beat
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

# 2. Rebuild + redeploy — đủ NĂM ảnh
#    `git checkout` ở bước 1 đã đưa cả `nginx/` về bản cũ, nhưng ảnh
#    `qlts-nginx:local` trên máy vẫn là ảnh của bản LỖI cho tới khi build lại.
#    Thiếu `nginx` ở đây = rollback code mà nginx vẫn chạy cấu hình vừa gây sự cố.
#    Thiếu hai service Celery = worker/beat ở lại BẢN MỚI trên CSDL vừa lùi.
docker compose -f docker-compose.yml --env-file .env.production --profile production \
    build backend celery-worker celery-beat frontend nginx
docker compose -f docker-compose.yml --env-file .env.production --profile production \
    up -d --wait postgres redis backend celery-worker celery-beat frontend
# nginx qua cổng candidate — kể cả khi rollback, nhất là khi rollback
set -a && source .env.production && set +a
bash scripts/nginx-apply.sh "$DOMAIN"

# 3. Rollback DB (nếu cần)
gunzip < /root/backup_YYYYMMDD_HHMMSS.sql.gz | docker exec -i qlts-postgres-1 psql -U qlts -d qlts_production
```

---

## MFA backup code — triển khai HAI PHA (pha B cần GO riêng)

Định dạng lưu backup code đổi từ `list[str]` (legacy) sang `list[dict]` v2 có
selector. Ảnh CŨ chỉ biết legacy và đưa thẳng từng phần tử vào
`pwd_context.verify()`, nên **ghi v2 ngay lần deploy đầu là một cutover MỘT
CHIỀU**: deploy → có người regenerate → rollback → mã backup của họ hỏng, và
không có đường phục hồi vì bản rõ chỉ hiện một lần.

Vì thế đường ĐỌC và đường GHI được tách bằng `MFA_BACKUP_CODE_V2_WRITER_ENABLED`
(mặc định `false`).

### Pha A — deploy bản đọc-được-v2, vẫn ghi legacy

1. `.env.production` phải có `MFA_BACKUP_CODE_PEPPER` **thật** trước khi deploy.
   Thiếu nó backend **không khởi động được** (fail-fast trong `app/config.py`).
   Sinh bằng: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
   ⚠️ Đổi pepper về sau = vô hiệu MỌI backup code v2 đã phát.
2. Giữ `MFA_BACKUP_CODE_V2_WRITER_ENABLED=false`.
3. Deploy theo đúng §6 ở trên (build đủ NĂM ảnh, `up -d --wait` liệt kê service
   tường minh, nginx qua `scripts/nginx-apply.sh`).

Pha A lấy được gì, và KHÔNG lấy được gì — nói cho đúng:

| | Pha A (writer=false) | Pha B (writer=true) |
|---|---|---|
| TOTP sai / sai hình dạng | không chạm backup, **0 bcrypt** | như pha A |
| 10-hex sai | **vẫn quét tối đa 8 bcrypt** (rounds 12, ngoài event loop) | selector trượt ⇒ **0 bcrypt** |
| 10-hex đúng | quét tới khi khớp | đúng **1 bcrypt** |
| Đặt chỗ nguyên tử chặn trước mọi bcrypt | có | có |

Nói cách khác: pha A cắt được đường tốn kém nhất (mã TOTP gõ nhầm rơi xuống quét
backup) và hạ chi phí mỗi phép băm từ rounds 15 xuống 12, nhưng **quét tuyến
tính vẫn còn** cho mã 10-hex sai vì dữ liệu vẫn ở định dạng legacy `list[str]`
(`mfa_service.generate_backup_codes` khi cờ tắt) và reader legacy lặp từng hash.
Chỉ selector v2 ở pha B mới xoá hẳn phép quét ấy.

### Mốc rollback an toàn

Chỉ được sang pha B khi **mọi ảnh còn nằm trong tầm rollback đều đọc được v2** —
nghĩa là ảnh pha A đã chạy đủ lâu để không còn kế hoạch lùi qua nó. Kiểm bằng
tag ảnh đang giữ để rollback (§Rollback) và đối chiếu với commit đưa reader v2
lên.

### Pha B — bật writer v2

Đây là **thao tác production riêng, cần GO riêng**, vì nó đổi định dạng dữ liệu
được ghi ra.

```bash
# 0. BASELINE TRƯỚC — LƯU VÀO BIẾN, không chỉ in ra màn hình. Không có nó thì
#    "có 1 bản ghi v2" không phân biệt được "vừa sinh ra" với "đã có từ trước",
#    và bước 5 không có gì để trừ.
TRUOC=$(docker exec -i qlts-postgres-1 psql -U qlts -d qlts_production -t -A -F' ' <<'SQL'
SELECT count(*) FILTER (WHERE btrim(backup_codes_hashed) LIKE '[{%'),
       count(*) FILTER (WHERE btrim(backup_codes_hashed) LIKE '["%'),
       count(*) FILTER (WHERE mfa_enabled)
FROM "user";
SQL
)
read -r v2_truoc legacy_truoc mfa_truoc <<<"$TRUOC"
printf 'truoc: v2=%s legacy=%s mfa_bat=%s\n' "$v2_truoc" "$legacy_truoc" "$mfa_truoc"
[ -n "$v2_truoc" ] && [ -n "$legacy_truoc" ] && [ -n "$mfa_truoc" ] \
    || { echo "DUNG LAI: không đọc được baseline — đừng bật cờ khi chưa có mốc so."; exit 1; }

# 1. Sửa .env.production
#    MFA_BACKUP_CODE_V2_WRITER_ENABLED=true

# 2. DỰNG LẠI các service đọc Settings — `restart` KHÔNG nạp lại env_file;
#    biến được nướng vào container lúc TẠO.
#
#    ⚠️ PHẢI chặn lỗi tường minh. Không có `|| exit 1`, một lượt `up --wait`
#    hỏng (image thiếu, healthcheck không đạt, container chết ngay) vẫn để khối
#    chạy tiếp — và bước 3 sẽ đọc cờ trên những container CŨ còn sống, thấy
#    `true`, rồi đi thẳng tới bước phát mã v2. Đo được: Compose trả 42 mà khối
#    vẫn in `=true` cho cả ba và chạy tới baseline sau.
docker compose -f docker-compose.yml --env-file .env.production --profile production \
    up -d --no-deps --wait backend celery-worker celery-beat \
    || { echo "DUNG LAI: up --wait hỏng — KHÔNG kiểm cờ trên container cũ."; exit 1; }

# 3. KIỂM CỜ ĐÃ NƯỚNG VÀO CẢ BA container — không suy từ việc `up -d` trả 0.
#    Compose chỉ recreate service nào có model lệch; một service không recreate
#    sẽ giữ writer=false trong khi hai service kia đã bật. Hệ quả là ghi legacy
#    hay v2 tuỳ tiến trình nào phục vụ — lệch âm thầm, không log nào báo.
#
#    ⚠️ PHẢI so GIÁ TRỊ, không chỉ tìm TÊN BIẾN: `grep '^VAR='` khớp cả `=false`.
#    Và phải `exit 1` — một dòng chữ "DỪNG LẠI" không dừng được gì; người trực
#    dán cả khối vào terminal thì lệnh sau vẫn chạy tiếp.
loi=0
for c in qlts-backend-1 qlts-celery-worker-1 qlts-celery-beat-1; do
    # Lưu output THÔ rồi đếm trên đó. Đếm sau khi đã tách giá trị là sai:
    # command substitution xoá newline cuối, và `grep -c .` bỏ dòng RỖNG — nên
    # một container có CẢ `VAR=true` LẪN `VAR=` cho ra `gt=true, so_dong=1` và
    # LỌT. Đã đo đúng cặp giá trị ấy.
    env_tho=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$c") \
        || { echo "DUNG LAI: không đọc được env của $c."; exit 1; }
    so_khai=$(printf '%s\n' "$env_tho" \
        | grep -c '^MFA_BACKUP_CODE_V2_WRITER_ENABLED=' || true)
    gt=$(printf '%s\n' "$env_tho" \
        | sed -n 's/^MFA_BACKUP_CODE_V2_WRITER_ENABLED=//p' | head -1)
    if [ "$so_khai" -ne 1 ]; then
        # 0 = container không có biến. >1 = khai TRÙNG, giá trị nào thắng là
        # tuỳ thứ tự nạp — không đoán, coi là hỏng.
        printf '%-24s THIEU/TRUNG (%s dòng khai)\n' "$c" "$so_khai"; loi=1
    elif [ "$gt" != "true" ]; then
        printf '%-24s = "%s" (phải là true)\n' "$c" "$gt"; loi=1
    else
        printf '%-24s = true\n' "$c"
    fi
done
[ "$loi" -eq 0 ] || { echo "DUNG LAI: cờ writer chưa đúng trên đủ ba container."; exit 1; }

# 4. Nghiệm thu bằng hành vi thật, không bằng exit code: cấp lại backup code cho
#    MỘT tài khoản thử, rồi kiểm bản ghi trong DB là list[dict] có khoá "v": 2.

# 5. BASELINE SAU — chạy LẠI đúng truy vấn ở bước 0 và so DELTA bằng máy.
#    Đọc hai bảng số bằng mắt là chỗ sai sót vào lúc 3 giờ sáng; ở đây để lệnh
#    tự kết luận. Kỳ vọng: v2 +1 · legacy −1 · mfa_bat không đổi.
SAU=$(docker exec -i qlts-postgres-1 psql -U qlts -d qlts_production -t -A -F' ' <<'SQL'
SELECT count(*) FILTER (WHERE btrim(backup_codes_hashed) LIKE '[{%'),
       count(*) FILTER (WHERE btrim(backup_codes_hashed) LIKE '["%'),
       count(*) FILTER (WHERE mfa_enabled)
FROM "user";
SQL
)
read -r v2_sau legacy_sau mfa_sau <<<"$SAU"
d_v2=$((v2_sau - v2_truoc)); d_legacy=$((legacy_sau - legacy_truoc)); d_mfa=$((mfa_sau - mfa_truoc))
printf 'delta: v2=%+d legacy=%+d mfa_bat=%+d\n' "$d_v2" "$d_legacy" "$d_mfa"
if [ "$d_v2" -ne 1 ] || [ "$d_legacy" -ne -1 ] || [ "$d_mfa" -ne 0 ]; then
    echo "DUNG LAI: delta khác (+1, -1, 0) — có đường ghi thứ hai, hoặc bước 4 chưa chạy."
    exit 1
fi
```

### Sau khi pha B đã phát mã

🔴 **CẤM rollback về ảnh trước reader-capable.** Ảnh đó sẽ ném lỗi khi gặp
`dict` trong danh sách, và mọi backup code v2 đã phát thành vô dụng.

**Thứ tự ưu tiên đường lùi — hai tiêu chí, không phải một:**

| Ưu tiên | Ảnh | Đọc v2 | Có bản vá race MFA (#576) |
|---|---|---|---|
| 1 | `…-811cdf17` **hoặc mới hơn** | ✅ | ✅ |
| 2 (chỉ khi bất khả kháng) | `…-e84e0cd8` | ✅ | ❌ **mở lại hai race** |
| ⛔ cấm | `…-953d6338` và cũ hơn | ❌ | ❌ |

Lùi về `e84e0cd8` là đổi một sự cố lấy hai lỗ đã vá ở #576 — TOTP replay và
`mfa_token` reuse, cả hai **fail-open khi Redis lỗi**. Nó vẫn nằm trong bảng vì
đọc được v2, nhưng chỉ dùng khi không còn ảnh nào mới hơn. Dù lùi tới đâu, đặt
lại `MFA_BACKUP_CODE_V2_WRITER_ENABLED=false` rồi dựng lại **cả ba** service và
kiểm cờ như bước 3 ở trên.

⇒ "Reader-capable" KHÔNG còn là tiêu chí đủ để chọn ảnh lùi. Phải hỏi thêm: ảnh
đó có mang bản vá bảo mật nào mà ta đang dựa vào không?

### Nếu buộc phải đổi pepper

Đổi `MFA_BACKUP_CODE_PEPPER` làm **mọi mã v2 đã phát thành vô dụng ngay lập
tức**: selector là `HMAC(pepper, code)`, không tính lại được từ hash đã lưu. Mã
legacy không ảnh hưởng (bcrypt thuần), nên thiệt hại đúng bằng tập người dùng đã
regenerate sau pha B.

Kế hoạch bắt buộc trước khi đổi:

1. **Đếm phạm vi** — ai đang giữ mã v2:
   `SELECT count(*) FROM "user" WHERE btrim(backup_codes_hashed) LIKE '[{%';`
2. **Thông báo trước** cho đúng tập ấy — sau khi đổi, mã in ra giấy của họ vô
   dụng mà không có thông báo lỗi nào nói rõ nguyên nhân.
3. **Đổi pepper + dựng lại ba service**, kiểm cờ như bước 3.
4. **Cấp lại mã** cho từng tài khoản trong tập đó (bản rõ chỉ hiện MỘT lần —
   không có đường phục hồi nếu người dùng không lưu).
5. **Nghiệm thu**: đếm lại v2, và với ít nhất một tài khoản, xác minh mã mới
   dùng được còn mã cũ thì không.

⚠️ Không có bước nào ở trên là tự động. Nếu chưa làm được bước 4 cho **toàn bộ**
tập ở bước 1 thì **đừng đổi pepper**.

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
