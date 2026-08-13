# E2E: đóng gói và ÁP cấu hình Nginx

Cổng **tự động** của việc này là `Backend_FastAPI/tests/unit/test_nginx_template_packaging.py`
(chạy trong CI, lát Tier 5). Thư mục này là phần **E2E chạy tay** — nó dựng nginx thật từ
`docker-compose.yml` production và chứng minh bằng request thật.

## Vì sao tồn tại

**Vòng một (12-08-2026)**: một clean checkout chỉ có `nginx/conf.d/default.conf.template`,
trong khi `nginx/nginx.conf` chỉ `include /etc/nginx/conf.d/*.conf` và entrypoint chính thức
của nginx **chỉ** render template ở `/etc/nginx/templates/`. Template không bao giờ được
render ⇒ nginx chạy **không có server block nào**. Production sống sót nhờ một
`default.conf` đã render nằm ngoài git (`.gitignore` loại nó).

**Vòng hai**: bản vá đầu chuyển template sang `nginx/templates/` rồi bind-mount thư mục đó.
Nhưng bind-mount một thư mục **không tồn tại** thì Docker daemon **tự tạo nó rỗng** — đo trên
Docker 29.7.2, `create_host_path: false` chỉ ngăn Compose tạo chứ không ngăn daemon, và `up`
vẫn exit 0. Nay cấu hình được **COPY vào image** (`nginx/Dockerfile`): thiếu template là
`docker build` đỏ.

Triệu chứng đánh lừa của cả hai vòng: `nginx -t` báo *syntax is ok*, container `Up`, Docker
publish 80/443 — nhưng từ ngoài là `ECONNREFUSED`.

## Chuẩn bị fixture (không commit — sinh tại chỗ)

```bash
cd <repo>
D=nginx-test.local
D_DIR=tests-e2e/nginx-packaging
mkdir -p $D_DIR/nginx-test-certs/live/$D
docker run --rm -v "$PWD/$D_DIR/nginx-test-certs/live/$D:/c" alpine/openssl \
  req -x509 -nodes -newkey rsa:2048 -days 30 \
  -keyout /c/privkey.pem -out /c/fullchain.pem \
  -subj "/CN=$D" -addext "subjectAltName=DNS:$D,DNS:www.$D"
cp $D_DIR/nginx-test-certs/live/$D/fullchain.pem $D_DIR/nginx-test-certs/live/$D/chain.pem

cat > $D_DIR/nginx-test.env <<EOF
QLTS_ENV_FILE=$D_DIR/nginx-test.env
POSTGRES_USER=ngxtest
POSTGRES_PASSWORD=$(openssl rand -hex 16)
POSTGRES_DB=ngxtest
DOMAIN=$D
NGINX_ADMISSION_FROZEN=false
NEXT_PUBLIC_API_URL=http://localhost:8000
SECRET_KEY=ngxtest-khong-phai-secret-0000000000
JWT_SECRET_KEY=ngxtest-khong-phai-secret-1111111111
MAIL_USERNAME=ngx
MAIL_PASSWORD=ngx
MAIL_FROM=ngx@example.invalid
MAIL_SERVER=localhost
TEST_BACKEND_IMAGE=<image backend đã build>
TEST_FRONTEND_IMAGE=<image frontend đã build>
EOF

# Ca 4 dựng từ CHÍNH template production, để nó không trôi lệch khỏi bản thật:
mkdir -p $D_DIR/khong-co-https
awk '/# --- HTTPS: Main server ---/{exit} {print}' \
  nginx/templates/default.conf.template > $D_DIR/khong-co-https/default.conf.template
```

> 🔒 **KHÔNG chép fixture đè `.env.production`.** Dòng `QLTS_ENV_FILE=` ở đầu tệp env là thứ
> làm việc đó không còn cần thiết: `docker-compose.yml` khai
> `env_file: - ${QLTS_ENV_FILE:-.env.production}`, nên đổi tệp env là đủ.
> Bản README trước hướng dẫn `cp nginx-test.env .env.production` — `.env.production` bị
> `.gitignore` loại, chứa `POSTGRES_PASSWORD` / `SECRET_KEY` / `JWT_SECRET_KEY`, và **không có
> bước sao lưu hay khôi phục nào**. Chạy nhầm trên `/opt/qlts` là mất sạch, và `deploy.sh`
> sau đó từ chối chạy vì tệp toàn giá trị giả.

## Chạy

```bash
export QLTS_ENV_FILE=tests-e2e/nginx-packaging/nginx-test.env
DC="docker compose -f docker-compose.yml \
  -f tests-e2e/nginx-packaging/docker-compose.nginx-test.yml \
  --profile production --env-file tests-e2e/nginx-packaging/nginx-test.env -p qltsngx"

$DC build nginx
$DC up -d postgres redis && $DC up -d backend frontend && $DC up -d nginx
docker inspect -f '{{.State.Health.Status}}' qltsngx-nginx-1   # phải healthy
```

Kiểm rằng `certbot` **không** hề nằm trong stack (bẫy gộp `profiles`):

```bash
$DC config --services | grep -c certbot     # phải là 0
```

### Sáu phép kiểm chức năng

Chạy bằng đúng script mà deploy dùng — không có phiên bản chép tay thứ hai:

```bash
NGINX_PROBE_STRICT_TLS=0 bash scripts/nginx-verify.sh qltsngx-nginx-1 nginx-test.local
```

Nó đo từ một container khác trên cùng mạng, bằng `curl --resolve` (SNI thật):

| # | Đo gì | Mong đợi |
|---|---|---|
| 1 | `GET /health` qua TLS | 200 — TLS + SNI + khối HTTPS + **proxy tới backend** |
| 2 | `GET /login` | 200 — **proxy tới frontend** |
| 3 | `GET /api/payments/1` | 401 — proxy backend, backend còn cưỡng chế xác thực |
| 4 | SNI lạ | không có phản hồi HTTP (`000`) — catch-all từ chối bắt tay |
| 5 | `GET /` cổng 80 | 301 |
| 6 | `/.well-known/acme-challenge/…` | 404 (từ webroot) — **không** phải 301 |

> `NGINX_PROBE_STRICT_TLS=0` chỉ vì chứng thư ở đây tự ký. Trên prod để mặc định (`1`) thì
> có thêm một phép kiểm chuỗi chứng thư khớp `$DOMAIN`.

> ⚠️ Vì sao **không** dùng `curl --header "Host: …" https://127.0.0.1/…`: đặt Host mà nối tới
> `127.0.0.1` thì **SNI vẫn là `127.0.0.1`**, server block 443 có tên sẽ không được chọn, và
> catch-all `ssl_reject_handshake` trả lời. Đó đúng là phép đo sai đã làm cả kíp trực tin
> site còn sống hôm 12-08-2026.

## Bốn ca hồi quy

Cả bốn đều chạy trên **`nginx-candidate`** — container mà `scripts/nginx-apply.sh` dựng để
thử trước khi thay bản đang phục vụ. Nên mỗi ca vừa chứng minh guard bắt được, vừa chứng minh
container đang phục vụ **không hề bị đụng tới**.

Mỗi ca chạy qua **chính `scripts/nginx-apply.sh`** — đúng đoạn mã mà deploy chạy. Không có
vòng lặp `up -d` chép tay ở đây: một bản chép chỉ chứng minh giả định của người viết tài
liệu, mà đó đúng là lớp sai cả PR này ra đời để đóng. (`nginx-apply.sh` đã mang sẵn
`--no-deps` cho lệnh dựng candidate; thiếu nó thì tập `up` là {postgres, redis, backend,
frontend, nginx-candidate} và `--force-recreate` đụng tất — `backend` chạy lại
`alembic upgrade head` + nạp Casbin, và nếu nó không kịp `service_healthy` thì lệnh `up`
**bỏ dở trước khi chạm tới candidate**: container của ca TRƯỚC còn đứng nguyên, và người
chạy đọc trạng thái của nó rồi đánh dấu ca này PASS dù nó chưa hề chạy.)

```bash
for CA in kn1-thu-muc-template-rong kn2-bo-domain kn3-config-rong kn4-mat-khoi-https; do
  echo "=== $CA ==="
  TRUOC=$(docker inspect -f '{{.Id}}' qltsngx-nginx-1)

  QLTS_COMPOSE_ENV_FILE=tests-e2e/nginx-packaging/nginx-test.env \
  QLTS_COMPOSE_EXTRA="-f tests-e2e/nginx-packaging/docker-compose.nginx-test.yml \
                      -f tests-e2e/nginx-packaging/$CA.yml -p qltsngx" \
  NGINX_PROBE_STRICT_TLS=0 \
    bash scripts/nginx-apply.sh nginx-test.local > /tmp/$CA.log 2>&1
  echo "  cổng deploy: rc=$?  (phải KHÁC 0)"
  grep -m1 -E 'đã DỪNG|unhealthy' /tmp/$CA.log
  grep -m1 'TỪ CHỐI KHỞI ĐỘNG' /tmp/$CA.log || true

  SAU=$(docker inspect -f '{{.Id}}' qltsngx-nginx-1)
  [ "$TRUOC" = "$SAU" ] && echo "  ✓ container đang phục vụ: id KHÔNG đổi" \
                        || echo "  ✗ container đang phục vụ BỊ THAY"
  NGINX_PROBE_STRICT_TLS=0 bash scripts/nginx-verify.sh qltsngx-nginx-1 nginx-test.local \
    >/dev/null 2>&1 && echo "  ✓ last-good vẫn phục vụ" || echo "  ✗ last-good đã chết"
done
```

Kỳ vọng — **hai nhóm khác nhau, và sự khác nhau ấy là điều phải kiểm**:

| Ca | Trạng thái candidate | Vì sao |
|---|---|---|
| kn1 thư mục template rỗng | `exited (1)` + `TỪ CHỐI KHỞI ĐỘNG: thiếu …` | guard chặn TRƯỚC khi nginx chạy |
| kn2 DOMAIN rỗng | `exited (1)` + `TỪ CHỐI KHỞI ĐỘNG: biến DOMAIN rỗng` | như trên |
| kn3 config rỗng | `running` + `unhealthy` | cú pháp hợp lệ, nginx lên được, nhưng không phục vụ |
| kn4 mất khối HTTPS | `running` + `unhealthy` | chỉ healthcheck **trên HTTPS với SNI thật** mới thấy |

Mọi ca: container đang phục vụ **còn nguyên** và **vẫn phục vụ**.

> Đọc `docker inspect … | grep unhealthy` cho cả bốn ca là chưa đủ để tin: một ca không hề
> chạy vẫn có thể báo lại trạng thái `unhealthy` của ca trước. Vì thế mỗi ca đối chiếu
> **container ID** và **dòng log riêng** của nó.

## Cần gạt đóng băng tuyển sinh (RUNBOOK §6.1b)

Diễn tập được ở đây mà không đụng prod. Cặp 200 ↔ 503 mới là bằng chứng; `nginx -t` xanh và
`nginx -s reload` exit 0 thì **không**.

```bash
E=tests-e2e/nginx-packaging/nginx-test.env
IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' qltsngx-nginx-1)
goi() { docker run --rm --network qltsngx_default --entrypoint sh nginx:1.27-alpine -c \
  "curl -sk -o /dev/null -w '%{http_code}' -X $1 --resolve 'nginx-test.local:443:$IP' \
   'https://nginx-test.local$2'"; }

# --- đối chứng: ba lệnh mà runbook CŨ bảo dùng ---
# `CO-Y-LENH-CHET` là van thoát của guard
# `test_tai_lieu_van_hanh_khong_con_lenh_da_chet`: ở đây ta CỐ TÌNH chạy lệnh đã
# chết để chứng minh nó không làm gì. Mọi chỗ khác mà gõ lại chúng là CI đỏ.
sed -i 's/^NGINX_ADMISSION_FROZEN=.*/NGINX_ADMISSION_FROZEN=true/' $E
docker exec qltsngx-nginx-1 nginx -t                        # exit 0 — "syntax is ok"
docker exec qltsngx-nginx-1 nginx -s reload   # CO-Y-LENH-CHET  exit 0
$DC restart nginx                             # CO-Y-LENH-CHET  exit 0
goi POST /api/admissions/                    # vẫn 200 ⇒ CẦN GẠT CÂM

# --- quy trình đúng: HAI tầng, cả hai đều phải được DỰNG LẠI ---
# Tầng backend: `env_file` chỉ được đọc lúc container được TẠO, nên `restart`
# giữ nguyên ADMISSION_FROZEN cũ. Đã đo hai chiều trên stack này.
sed -i 's/^ADMISSION_FROZEN=.*/ADMISSION_FROZEN=true/' $E
$DC up -d --no-deps --wait backend

# Tầng nginx:
QLTS_COMPOSE_ENV_FILE=$E \
QLTS_COMPOSE_EXTRA="-f tests-e2e/nginx-packaging/docker-compose.nginx-test.yml -p qltsngx" \
NGINX_PROBE_STRICT_TLS=0 bash scripts/nginx-apply.sh nginx-test.local

goi POST /api/admissions/        # 503
goi GET  /api/admissions/        # KHÁC 503 — đọc vẫn mở
goi POST /api/payments/1         # KHÁC 503 — ngoài phạm vi
goi POST /api/admissionsfoo      # KHÁC 503 — lookalike không bị dính
```

Mở băng: đặt lại `false`, chạy lại `nginx-apply.sh`, và `POST /api/admissions/` phải **thôi**
trả 503.

## Bootstrap SSL (`scripts/setup-ssl.sh`)

```bash
# Cổng 80 đang bị nginx giữ ⇒ bootstrap PHẢI hỏng. Đây là tiền đề mà bản trước
# không ghi ở đâu cả, và người vận hành gặp "port is already allocated" giữa
# lúc đang cấp chứng thư.
$DC --profile bootstrap up -d --no-deps nginx-bootstrap   # Bind for …:18080 failed

# Step 1 của setup-ssl.sh làm đúng việc này, CÓ CHỦ ĐÍCH:
$DC stop nginx
$DC --profile bootstrap up -d --no-deps nginx-bootstrap
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/.well-known/acme-challenge/x  # 404
```

Bootstrap phải lên được **khi backend/frontend chưa hề chạy** — đó là cảnh một VPS mới. Thử
lại sau `$DC stop backend frontend postgres redis`: nó vẫn `healthy`, vì nó dùng
`nginx-bootstrap.conf` không khai `upstream` nào.

## Dọn

```bash
$DC --profile candidate --profile bootstrap down -v --remove-orphans
rm -rf tests-e2e/nginx-packaging/{nginx-test-certs,khong-co-https,nginx-test.env}
```
