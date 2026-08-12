# E2E: đóng gói cấu hình Nginx

Cổng **tự động** của việc này là `Backend_FastAPI/tests/unit/test_nginx_template_packaging.py`
(chạy trong CI, lát Tier 5). Thư mục này là phần **E2E chạy tay** — nó dựng nginx thật từ
`docker-compose.yml` production và chứng minh bằng request thật, gồm cả bốn ca hồi quy.

## Vì sao tồn tại

Sự cố 12-08-2026: một clean checkout chỉ có `nginx/conf.d/default.conf.template`, trong
khi `nginx/nginx.conf` chỉ `include /etc/nginx/conf.d/*.conf` và entrypoint chính thức của
nginx **chỉ** render template ở `/etc/nginx/templates/`. Template không bao giờ được
render ⇒ nginx chạy **không có server block nào**. Production sống sót nhờ một
`default.conf` đã render nằm ngoài git (`.gitignore` loại nó).

Triệu chứng đánh lừa: `nginx -t` báo *syntax is ok*, container `Up`, Docker publish
80/443 — nhưng từ ngoài là `ECONNREFUSED`.

## Chuẩn bị fixture (không commit — sinh tại chỗ)

```bash
cd <repo>
D=nginx-test.local
mkdir -p nginx-test-certs/live/$D
docker run --rm -v "$PWD/nginx-test-certs/live/$D:/c" alpine/openssl \
  req -x509 -nodes -newkey rsa:2048 -days 30 \
  -keyout /c/privkey.pem -out /c/fullchain.pem \
  -subj "/CN=$D" -addext "subjectAltName=DNS:$D,DNS:www.$D"
cp nginx-test-certs/live/$D/fullchain.pem nginx-test-certs/live/$D/chain.pem

cat > nginx-test.env <<EOF
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
cp nginx-test.env .env.production   # compose khai env_file này
```

## Chạy

```bash
DC="docker compose -f docker-compose.yml \
  -f tests-e2e/nginx-packaging/docker-compose.nginx-test.yml \
  --profile production --env-file nginx-test.env -p qltsngx"

$DC up -d postgres redis && $DC up -d backend frontend && $DC up -d nginx
docker inspect -f '{{.State.Health.Status}}' qltsngx-nginx-1   # phải healthy
```

Năm phép kiểm chức năng (cổng loopback `18443`):

| # | Lệnh | Mong đợi |
|---|---|---|
| 1 | `curl -k --resolve nginx-test.local:18443:127.0.0.1 https://nginx-test.local:18443/health` | 200 |
| 2 | `… /login` | 200 |
| 3 | `… /api/payments/1` | 401 |
| 4 | `… '/socket.io/?EIO=4&transport=polling'` | 200 |
| 5 | `--resolve la-hoac.example:18443:…` | TLS reject (`000`) |

## Bốn ca hồi quy — mỗi ca phải làm container **unhealthy**

```bash
# 1. bỏ mount template  → nginx -t VẪN xanh, healthcheck ĐỎ
$DC -f tests-e2e/nginx-packaging/kn1-bo-template.yml up -d --force-recreate nginx

# 2. DOMAIN rỗng
$DC -f tests-e2e/nginx-packaging/kn2-bo-domain.yml up -d --force-recreate nginx

# 3. config hợp lệ cú pháp nhưng không phục vụ /health
$DC -f tests-e2e/nginx-packaging/kn3-config-rong.yml up -d --force-recreate nginx

# 4. thêm nginx/conf.d/default.conf untracked rồi chạy lại ca 1
#    → vẫn phải ĐỎ: sau bản vá compose không mount conf.d nữa, nên tệp ngoài
#      git KHÔNG thể làm phép kiểm xanh.
```

⚠️ Ca 3 cố ý dùng config tĩnh — **chỉ** để dựng trạng thái xấu. Các phép kiểm chức năng
thì luôn đi qua đúng template production; thay nó bằng config tĩnh sẽ khiến bài kiểm không
chứng minh được gì.
