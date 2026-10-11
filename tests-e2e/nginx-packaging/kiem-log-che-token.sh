#!/usr/bin/env bash
# =============================================================================
# E2E chạy tay — V6: access log nginx CHE token nhưng VẪN GHI DÒNG; trang token
# trả `Referrer-Policy: no-referrer`.
# =============================================================================
# Dựng image nginx từ CHÍNH `nginx/Dockerfile` (cấu hình đi theo image như
# production), chạy với template thật + DOMAIN giả + chứng thư tự ký. Hai
# upstream `backend:8000` / `frontend:3000` trỏ về một server stub NGAY TRONG
# container (`--add-host … :127.0.0.1`), nên không cần ảnh backend/frontend.
# Đo bằng request thật qua TLS với SNI thật (`curl --resolve`), rồi đọc
# `docker logs` (access.log của image chính thức là symlink tới stdout).
#
# Vì sao không chỉ đếm "0 dòng chứa token": `access_log off` cũng cho 0 — đúng
# đột biến cần bắt. Nên phép kiểm có HAI vế: token vắng mặt VÀ mỗi đầu dò để
# lại đúng một dòng có `<redacted>`.
#
# Dùng:
#   bash tests-e2e/nginx-packaging/kiem-log-che-token.sh
#   NGINX_DIR=/duong/ban-sao-nginx-dot-bien bash …/kiem-log-che-token.sh   # chạy đột biến
# Mã thoát: 0 ĐẠT · 1 ĐỎ · 2 hạ tầng (build/run hỏng).
# Dữ liệu GIẢ: token `GIAV6TOKEN…`, tên miền `nginx-test.local`.
# =============================================================================
set -uo pipefail
export MSYS_NO_PATHCONV=1

GOC="$(cd "$(dirname "$0")/../.." && pwd)"
NGINX_DIR="${NGINX_DIR:-$GOC/nginx}"
D=nginx-test.local
TAG="qlts-nginx-v6-e2e:$$"
CT="qlts-nginx-v6-e2e-$$"
WORK="$(mktemp -d)"
win() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s' "$1"; fi; }

don() {
    docker rm -f "$CT" >/dev/null 2>&1
    docker image rm "$TAG" >/dev/null 2>&1
    # Chỉ xoá đúng thư mục tạm do mktemp tạo (không bao giờ một biến rỗng).
    case "$WORK" in
        */tmp.*) rm -rf -- "$WORK" ;;
    esac
}
trap don EXIT

ha_tang() { echo "E2E-V6 HA-TANG: $1"; echo "KET-LUAN=HA_TANG"; exit 2; }

docker build -q -t "$TAG" "$(win "$NGINX_DIR")" >/dev/null || ha_tang "docker build hỏng"

mkdir -p "$WORK/le/live/$D"
docker run --rm -v "$(win "$WORK/le/live/$D"):/c" alpine/openssl \
    req -x509 -nodes -newkey rsa:2048 -days 2 \
    -keyout /c/privkey.pem -out /c/fullchain.pem \
    -subj "/CN=$D" -addext "subjectAltName=DNS:$D" >/dev/null 2>&1 \
    || ha_tang "không sinh được chứng thư tự ký"
cp "$WORK/le/live/$D/fullchain.pem" "$WORK/le/live/$D/chain.pem"

cat > "$WORK/zz-v6-stub.conf" <<'EOF'
# Stub upstream CHỈ cho E2E — không phải cấu hình production.
server { listen 127.0.0.1:8000; access_log off; location / { return 200 "stub-backend\n"; } }
server { listen 127.0.0.1:3000; access_log off; location / { return 200 "stub-frontend\n"; } }
EOF

docker run -d --name "$CT" \
    --add-host backend:127.0.0.1 --add-host frontend:127.0.0.1 \
    -e DOMAIN="$D" -e NGINX_ADMISSION_FROZEN=false \
    -v "$(win "$WORK/le"):/etc/letsencrypt:ro" \
    -v "$(win "$WORK/zz-v6-stub.conf"):/etc/nginx/conf.d/zz-v6-stub.conf:ro" \
    "$TAG" >/dev/null || ha_tang "docker run hỏng"

for _ in $(seq 1 30); do
    if docker exec "$CT" curl -sk -o /dev/null --resolve "$D:443:127.0.0.1" "https://$D/nginx-alive" 2>/dev/null; then
        break
    fi
    sleep 1
done
[ "$(docker inspect -f '{{.State.Status}}' "$CT" 2>/dev/null)" = "running" ] \
    || { docker logs "$CT" 2>&1 | tail -20; ha_tang "container không chạy"; }

goi() {  # goi <đường dẫn đầy đủ> [Referer] — in header phản hồi
    if [ -n "${2:-}" ]; then
        docker exec "$CT" curl -sk -o /dev/null -D - -H "Referer: $2" --resolve "$D:443:127.0.0.1" --resolve "$D:80:127.0.0.1" "$1"
    else
        docker exec "$CT" curl -sk -o /dev/null -D - --resolve "$D:443:127.0.0.1" --resolve "$D:80:127.0.0.1" "$1"
    fi
}
rp() { tr -d '\r' | awk -F': ' 'tolower($1)=="referrer-policy"{print $2}' | sort -u | paste -sd, -; }

H1=$(goi "https://$D/confirm/GIAV6TOKEN51" | rp)
H2=$(goi "https://$D/api/admissions/confirm/GIAV6TOKEN52" | rp)
H3=$(goi "https://$D/magic-link/withdraw/GIAV6TOKEN53" | rp)
H4=$(goi "https://$D/api/v2/admissions/magic-link/confirm/GIAV6TOKEN54" | rp)
goi "https://$D/_next/static/v6.js" "https://$D/confirm/GIAV6TOKEN55" >/dev/null
goi "https://$D/reset-password?token=GIAV6TOKEN56&lang=vi" >/dev/null
goi "http://$D/confirm/GIAV6TOKEN57" >/dev/null
H8=$(goi "https://$D/login" | rp)
sleep 1

OUT="$(docker logs "$CT" 2>/dev/null)"
ERR="$(docker logs "$CT" 2>&1 >/dev/null)"

do_=0
kiem() {  # kiem <mã> <điều kiện 0/1> <mô tả>
    if [ "$2" = 1 ]; then echo "E2E-V6 $1 ĐẠT · $3"; else echo "E2E-V6 $1 ĐỎ · $3"; do_=1; fi
}
dem() { printf '%s\n' "$1" | grep -cF -- "$2"; }

n_token=$(dem "$OUT" GIAV6TOKEN)
kiem T1 "$([ "$n_token" -eq 0 ] && echo 1 || echo 0)" "access log: dòng chứa token giả = $n_token (phải 0)"

thieu=""
for mau in \
    '"GET /confirm/<redacted> ' \
    '"GET /api/admissions/confirm/<redacted> ' \
    '"GET /magic-link/withdraw/<redacted> ' \
    '"GET /api/v2/admissions/magic-link/confirm/<redacted> ' \
    '"https://nginx-test.local/confirm/<redacted>"' \
    '"GET /reset-password?token=<redacted>&lang=vi ' \
    ; do
    [ "$(dem "$OUT" "$mau")" -ge 1 ] || thieu="$thieu [$mau]"
done
n_80=$(printf '%s\n' "$OUT" | grep -F '"GET /confirm/<redacted> HTTP/1.1" 301' | wc -l)
[ "$n_80" -ge 1 ] || thieu="$thieu [cổng 80 → 301]"
kiem T2 "$([ -z "$thieu" ] && echo 1 || echo 0)" "mỗi đầu dò VẪN để lại dòng log đã che (thiếu:${thieu:- không})"

n_login=$(dem "$OUT" '"GET /login ')
kiem T3 "$([ "$n_login" -ge 1 ] && echo 1 || echo 0)" "dòng đối chứng /login có mặt ($n_login)"

kiem R1 "$([ "$H1" = "no-referrer" ] && [ "$H3" = "no-referrer" ] && echo 1 || echo 0)" \
    "trang token: Referrer-Policy confirm='$H1' magic-link='$H3' (phải no-referrer)"
kiem R2 "$([ "$H2" = "no-referrer" ] && [ "$H4" = "no-referrer" ] && echo 1 || echo 0)" \
    "API token: Referrer-Policy confirm='$H2' magic-link='$H4' (phải no-referrer)"
kiem R3 "$([ "$H8" = "strict-origin-when-cross-origin" ] && echo 1 || echo 0)" \
    "trang thường /login: Referrer-Policy='$H8' (phải strict-origin-when-cross-origin)"

# Không phải phép kiểm đạt/đỏ: error_log là PHẦN DƯ đã biết (log_format không chạm).
echo "E2E-V6 GHI-NHAN error_log: dòng chứa token giả = $(dem "$ERR" GIAV6TOKEN) (phần dư còn mở — chỉ ghi nhận)"

if [ "$do_" = 0 ]; then echo "KET-LUAN=DAT"; exit 0; fi
echo "--- access log (đuôi) ---"; printf '%s\n' "$OUT" | tail -15
echo "KET-LUAN=DO"; exit 1
