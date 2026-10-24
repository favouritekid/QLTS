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
# đột biến cần bắt. Nên phép kiểm có HAI vế: token vắng mặt VÀ mỗi đầu dò (mã
# riêng trong User-Agent) để lại dòng có `<redacted>`. Có cả ca NHIỀU token trong
# một giá trị (F31) và lượt chạy chính `scripts/nginx-verify.sh` (đầu dò token
# của cổng deploy, mã V1).
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
# `/api/` trả 401 để phép kiểm #3 của scripts/nginx-verify.sh (chưa đăng nhập ⇒ 401) đúng ngữ nghĩa.
# N17.10: request có `GIAN17LOI` (đường dẫn HOẶC query) ⇒ `444` (đóng kết nối) ⇒ nginx trả 502 và ghi
# `upstream prematurely closed …, request: "…"` vào error_log — đúng ca rò token cần đo. `error_log /dev/null`
# để chính stub không ghi dòng nào lẫn vào phép đếm.
server { listen 127.0.0.1:8000; access_log off; error_log /dev/null; if ($request_uri ~ GIAN17LOI) { return 444; } location /api/ { return 401 "stub-401\n"; } location / { return 200 "stub-backend\n"; } }
server { listen 127.0.0.1:3000; access_log off; error_log /dev/null; if ($request_uri ~ GIAN17LOI) { return 444; } location / { return 200 "stub-frontend\n"; } }
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

goi() {  # goi <mã đầu dò> <URL> [Referer] — in header phản hồi; UA mang mã đầu dò
    if [ -n "${3:-}" ]; then
        docker exec "$CT" curl -sk -o /dev/null -D - -A "v6-e2e-$1" -H "Referer: $3" --resolve "$D:443:127.0.0.1" --resolve "$D:80:127.0.0.1" "$2"
    else
        docker exec "$CT" curl -sk -o /dev/null -D - -A "v6-e2e-$1" --resolve "$D:443:127.0.0.1" --resolve "$D:80:127.0.0.1" "$2"
    fi
}
rp() { tr -d '\r' | awk -F': ' 'tolower($1)=="referrer-policy"{print $2}' | sort -u | paste -sd, -; }

# Mỗi đầu dò một mã (đi vào User-Agent) ⇒ đối chiếu được TỪNG dòng log.
H1=$(goi a51 "https://$D/confirm/GIAV6TOKEN51" | rp)
H2=$(goi a52 "https://$D/api/admissions/confirm/GIAV6TOKEN52" | rp)
H3=$(goi a53 "https://$D/magic-link/withdraw/GIAV6TOKEN53" | rp)
H4=$(goi a54 "https://$D/api/v2/admissions/magic-link/confirm/GIAV6TOKEN54" | rp)
goi a55 "https://$D/_next/static/v6.js" "https://$D/confirm/GIAV6TOKEN55" >/dev/null
H6=$(goi a56 "https://$D/reset-password?token=GIAV6TOKEN56&lang=vi" | rp)
goi a57 "http://$D/confirm/GIAV6TOKEN57" >/dev/null
# F31: NHIỀU token trong một giá trị — ở $request lẫn $http_referer.
goi a58 "https://$D/confirm/GIAV6TOKEN58?token=GIAV6TOKEN59" >/dev/null
goi a60 "https://$D/reset-password?token=GIAV6TOKEN60&refresh_token=GIAV6TOKEN61" >/dev/null
goi a62 "https://$D/login" "https://$D/confirm/GIAV6TOKEN62?token=GIAV6TOKEN63" >/dev/null
goi a64 "https://$D/login" "https://$D/reset-password?token=GIAV6TOKEN64&refresh_token=GIAV6TOKEN65" >/dev/null
goi a66 "https://$D/login?next=%2Fconfirm%2FGIAV6TOKEN66" >/dev/null
goi a67 "https://$D/login?x=1&Access-Token=GIAV6TOKEN67" >/dev/null
H8=$(goi a80 "https://$D/login" | rp)

# N17.10 B: upstream lỗi (502) ở MỌI dạng URL token — error_log KHÔNG được mang token.
E_TOKEN=(
    "e01 https://$D/confirm/GIAV6TOKEN81GIAN17LOI"
    "e02 https://$D/Confirm/GIAV6TOKEN82GIAN17LOI"
    "e03 https://$D/magic-link/withdraw/GIAV6TOKEN83GIAN17LOI"
    "e04 https://$D/reset-password?token=GIAV6TOKEN84GIAN17LOI"
    "e05 https://$D/lp/GIAV6TOKEN85GIAN17LOI"
    "e06 https://$D/r/GIAV6TOKEN86GIAN17LOI"
    "e07 https://$D/api/public/sms/landing/GIAV6TOKEN87GIAN17LOI"
    "e08 https://$D/api/admissions/confirm/GIAV6TOKEN88GIAN17LOI"
    "e09 https://$D/api/v2/admissions/magic-link/confirm/GIAV6TOKEN89GIAN17LOI"
)
for muc in "${E_TOKEN[@]}"; do goi "${muc%% *}" "${muc#* }" >/dev/null; done
# Đối chứng (location thường): PHẢI có dòng error_log — không có ⇒ error_log bị tắt toàn cục (lựa chọn C),
# hoặc stub không gây lỗi và E1 xanh vô nghĩa.
goi k01 "https://$D/dashboard/GIAN17LOI-K01" >/dev/null
goi k02 "https://$D/api/khong-token/GIAN17LOI-K02" >/dev/null

# Mục 5 (V6): đầu dò token của CHÍNH cổng deploy `scripts/nginx-verify.sh`.
VERIFY_OUT="$(NGINX_PROBE_STRICT_TLS=0 bash "$GOC/scripts/nginx-verify.sh" "$CT" "$D" 2>&1)"
VERIFY_RC=$?

# N17.10 B: `limit_req` từ chối (sau nginx-verify để không làm đỏ oan cổng deploy). Một tiến trình curl,
# glob 300 URL liên tiếp ⇒ vượt 50 r/s + burst 30 của zone `general`. Token: trang /confirm/; đối chứng: /dashboard/.
docker exec "$CT" sh -c "curl -sk -A v6-e2e-e10 --resolve '$D:443:127.0.0.1' 'https://$D/confirm/GIAV6TOKEN90RL[1-300]' >/dev/null 2>&1"
docker exec "$CT" sh -c "curl -sk -A v6-e2e-k10 --resolve '$D:443:127.0.0.1' 'https://$D/dashboard/GIAN17RL[1-300]' >/dev/null 2>&1"
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
for ma in a51 a52 a53 a54 a55 a56 a57 a58 a60 a62 a64 a66 a67; do
    dong=$(printf '%s\n' "$OUT" | grep -F -- "\"v6-e2e-$ma\"" || true)
    if [ -z "$dong" ]; then
        thieu="$thieu [$ma: KHÔNG có dòng]"
    elif ! grep -F -- "<redacted>" <<<"$dong" >/dev/null; then   # đọc HẾT, không `| grep -q` (SIGPIPE dưới pipefail)
        thieu="$thieu [$ma: dòng không mang <redacted>]"
    fi
done
kiem T2 "$([ -z "$thieu" ] && echo 1 || echo 0)" "mỗi đầu dò VẪN để lại dòng log đã che (thiếu:${thieu:- không})"

n_80=$(printf '%s\n' "$OUT" | grep -F '"v6-e2e-a57"' | grep -cF '" 301 ' || true)
kiem T4 "$([ "$n_80" -ge 1 ] && echo 1 || echo 0)" "cổng 80: dòng 301 của /confirm/<redacted> có mặt ($n_80)"

n_login=$(dem "$OUT" '"v6-e2e-a80"')
kiem T3 "$([ "$n_login" -ge 1 ] && echo 1 || echo 0)" "dòng đối chứng /login có mặt ($n_login)"

kiem R1 "$([ "$H1" = "no-referrer" ] && [ "$H3" = "no-referrer" ] && echo 1 || echo 0)" \
    "trang token: Referrer-Policy confirm='$H1' magic-link='$H3' (phải no-referrer)"
kiem R2 "$([ "$H2" = "no-referrer" ] && [ "$H4" = "no-referrer" ] && echo 1 || echo 0)" \
    "API token: Referrer-Policy confirm='$H2' magic-link='$H4' (phải no-referrer)"
kiem R3 "$([ "$H8" = "strict-origin-when-cross-origin" ] && echo 1 || echo 0)" \
    "trang thường /login: Referrer-Policy='$H8' (phải strict-origin-when-cross-origin)"
kiem R4 "$([ "$H6" = "no-referrer" ] && echo 1 || echo 0)" \
    "trang /reset-password?token=…: Referrer-Policy='$H6' (phải no-referrer)"

# `(✓|✗)` chứ không `[✓✗]`: ngoặc vuông của grep khớp MỘT byte, ký tự nhiều byte không bao giờ khớp.
dong_v=$(printf '%s\n' "$VERIFY_OUT" | grep -E "^  (✓|✗) đầu dò token" | sed 's/^  //' | paste -sd'|' -)
kiem V1 "$([ "$VERIFY_RC" -eq 0 ] && echo 1 || echo 0)" \
    "scripts/nginx-verify.sh rc=$VERIFY_RC · ${dong_v:-<không có dòng đầu dò token>}"

# --- N17.10 B: error_log ---
n_err_token=$(dem "$ERR" GIAV6TOKEN)
kiem E1 "$([ "$n_err_token" -eq 0 ] && echo 1 || echo 0)" "error_log: dòng chứa token giả = $n_err_token (phải 0; 502 ở 9 dạng URL token + limit_req)"

n_k01=$(dem "$ERR" GIAN17LOI-K01); n_k02=$(dem "$ERR" GIAN17LOI-K02)
kiem E2 "$([ "$n_k01" -ge 1 ] && [ "$n_k02" -ge 1 ] && echo 1 || echo 0)" \
    "đối chứng: 502 ở location thường VẪN ghi error_log (/dashboard: $n_k01 · /api/: $n_k02; phải ≥1 mỗi bên)"

thieu_e=""
# e05–e07 (`/lp/`, `/r/`, SMS landing) vốn `access_log off` (test_access_log_off_khong_lan_sang_location_token) ⇒
# không có dòng để kiểm; error_log của chúng vẫn nằm trong E1 (bản phá gỡ error_log ở /lp/, /r/ ⇒ E1 ĐỎ).
for ma in e01 e02 e03 e04 e08 e09; do
    dong=$(printf '%s\n' "$OUT" | grep -F -- "\"v6-e2e-$ma\"" || true)
    if [ -z "$dong" ]; then
        thieu_e="$thieu_e [$ma: KHÔNG có dòng]"
    elif ! grep -F -- '" 502 ' <<<"$dong" >/dev/null || ! grep -F -- "<redacted>" <<<"$dong" >/dev/null; then
        thieu_e="$thieu_e [$ma: dòng không phải 502 có <redacted>]"
    fi
done
kiem E3 "$([ -z "$thieu_e" ] && echo 1 || echo 0)" "access log VẪN ghi 502 (đã che) cho mỗi URL token lỗi (thiếu:${thieu_e:- không})"

n_rl_tok=$(printf '%s\n' "$OUT" | grep -F '"v6-e2e-e10"' | grep -cF '" 503 ' || true)
n_rl_k=$(printf '%s\n' "$ERR" | grep -F 'limiting requests' | grep -cF GIAN17RL || true)
kiem E4 "$([ "$n_rl_tok" -ge 1 ] && [ "$n_rl_k" -ge 1 ] && echo 1 || echo 0)" \
    "limit_req THẬT SỰ từ chối: trang token 503 = $n_rl_tok dòng access log · đối chứng error_log 'limiting requests' = $n_rl_k (phải ≥1 mỗi bên)"

# Kích thước access log đã đọc (ghi nhận — ca đột biến đệm 4 MiB của vòng 5 cần thấy nó thật).
echo "E2E-V6 GHI-NHAN access log (stdout): ${#OUT} ký tự · error_log (stderr): ${#ERR} ký tự"

if [ "$do_" = 0 ]; then echo "KET-LUAN=DAT"; exit 0; fi
echo "--- access log (đuôi) ---"; printf '%s\n' "$OUT" | tail -15
echo "KET-LUAN=DO"; exit 1
