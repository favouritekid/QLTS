#!/usr/bin/env bash
# =============================================================================
# QLTS — đo HÀNH VI THẬT của một container nginx
# =============================================================================
# Usage: scripts/nginx-verify.sh <container> <domain>
#
# Vì sao tồn tại
# --------------
# Sự cố 12-08-2026 để lại một bài học mà bản vá đầu chưa học hết: mọi bằng
# chứng "nginx ổn" mà ta có đều nằm CÁCH MỘT TẦNG so với thứ nó khẳng định.
#   * `nginx -t` nói về CÚ PHÁP, không nói về việc có ai được phục vụ không —
#     một config rỗng vẫn "syntax is ok".
#   * `grep server_name` nói về CHỮ trong bản render, không nói về hành vi —
#     đảo `www.${DOMAIN} ${DOMAIN}` là container ghim unhealthy dù phục vụ tốt.
#   * `wget --header "Host: ..." http://127.0.0.1/health` nói về CỔNG 80. Xoá
#     trọn khối HTTPS thì phép ấy vẫn rc=0 trong khi mọi client thật nhận
#     `Connection reset` — đã tái hiện bằng thực thi.
#
# Script này đo bằng đúng con đường của client thật: TLS trên 443 với SNI THẬT.
#
# Vì sao `--resolve` chứ không `--header "Host:"`
# ------------------------------------------------
# `curl --header "Host: $DOMAIN" https://127.0.0.1/...` gửi SNI = "127.0.0.1".
# Server block 443 có tên sẽ KHÔNG được chọn; catch-all `ssl_reject_handshake`
# trả lời. Phép đo ấy vừa sai vừa êm tai — chính nó đã làm cutover 12-08 tin
# rằng nginx còn phục vụ. `--resolve TÊN:CỔNG:IP` giữ nguyên tên trong URL (nên
# SNI và Host đều đúng) mà ép IP đích, nên nó đo được một container KHÔNG hề
# publish cổng nào ra host.
#
# Biến môi trường
# ---------------
#   NGINX_PROBE_STRICT_TLS=1  (mặc định) — thêm một phép kiểm chuỗi chứng thư
#     khớp tên miền. Đặt 0 cho stack E2E (chứng thư tự ký).
# =============================================================================
set -euo pipefail

# Git Bash trên Windows biến mọi tham số hình dạng đường dẫn (`/bin/sh`,
# `host:443:ip`) thành đường Windows trước khi `docker` nhìn thấy. Vô hại trên
# Linux (biến không được ai đọc), nhưng thiếu nó thì script chỉ chạy được trên
# prod chứ không chạy được ở máy người viết — tức không ai thử trước khi deploy.
export MSYS_NO_PATHCONV=1

CT="${1:?thiếu tham số: tên hoặc id container nginx}"
DOMAIN="${2:?thiếu tham số: domain}"
STRICT="${NGINX_PROBE_STRICT_TLS:-1}"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
loi() { echo -e "${RED}[VERIFY]${NC} $1" >&2; exit 1; }
log() { echo -e "${GREEN}[VERIFY]${NC} $1"; }

# --- Mạng + IP của container cần đo -----------------------------------------
# KHÔNG suy tên mạng từ thư mục hiện tại: đúng lối đoán đã làm `setup-ssl.sh`
# vớ nhầm volume của project khác khi chạy từ worktree.
TRANG_THAI=$(docker inspect -f '{{.State.Status}}' "$CT" 2>/dev/null) \
    || loi "không thấy container '$CT'"
[ "$TRANG_THAI" = "running" ] \
    || loi "container '$CT' đang ở trạng thái '$TRANG_THAI', không phải running"

MANG=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' "$CT" | head -1)
IP=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$MANG\").IPAddress}}" "$CT")
IMAGE=$(docker inspect -f '{{.Config.Image}}' "$CT")
[ -n "$MANG" ] || loi "container '$CT' không nối vào mạng nào"
[ -n "$IP" ]   || loi "không đọc được IP của '$CT' trên mạng '$MANG'"

log "đo '$CT' tại $IP trên mạng '$MANG' (domain=$DOMAIN, strict_tls=$STRICT)"

# Chạy TỪ MỘT CONTAINER KHÁC trên cùng mạng — không phải từ trong chính nginx.
# Gọi từ bên trong thì mọi request đều là 127.0.0.1 và `allow 127.0.0.1` cho
# qua những thứ mà client thật không hề với tới được.
# Dùng lại đúng image của container đang đo: chắc chắn có sẵn, có curl thật
# (nginx:1.27-alpine đóng gói curl 8.12 + OpenSSL), không phải tải thêm gì.
docker run --rm --network "$MANG" \
    -e DOMAIN="$DOMAIN" -e IP="$IP" -e STRICT="$STRICT" \
    --entrypoint sh "$IMAGE" -c '
set -u
SO_HONG=0
C="curl --silent --show-error --output /dev/null --max-time 8 --retry 0"

kiem() {
    ten="$1"; mong="$2"; shift 2
    # KHÔNG dùng `|| echo 000`: khi bắt tay hỏng, curl vẫn IN "000" rồi mới
    # thoát khác 0, nên nhánh dự phòng sẽ nối thêm một "000" nữa và biến kết
    # quả thành "000000" — một phép kiểm không bao giờ khớp được kỳ vọng.
    thuc=$($C -w "%{http_code}" "$@" 2>/dev/null || true)
    [ -n "$thuc" ] || thuc="000"
    if [ "$thuc" = "$mong" ]; then
        echo "  ✓ $ten → $thuc"
    else
        echo "  ✗ $ten → $thuc (mong đợi $mong)"
        SO_HONG=$((SO_HONG+1))
    fi
}

echo "--- HTTPS, SNI thật = $DOMAIN ---"
# 1. Chứng minh CÙNG LÚC: bắt tay TLS chọn đúng server block có tên (catch-all
#    ssl_reject_handshake sẽ làm hỏng bắt tay), khối HTTPS còn nguyên, VÀ proxy
#    tới BACKEND còn sống — /health trong khối 443 là proxy_pass http://backend.
kiem "GET /health (proxy → backend)" 200 \
    --insecure --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/health"

# 2. Route đi FRONTEND (catch-all `location /` → proxy_pass http://frontend).
kiem "GET /login (proxy → frontend)" 200 \
    --insecure --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/login"

# 3. Đường /api/ có tới backend và backend còn cưỡng chế xác thực.
kiem "GET /api/payments/1 (proxy → backend, chưa đăng nhập)" 401 \
    --insecure --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/api/payments/1"

echo "--- phòng thủ ---"
# 4. SNI lạ phải bị catch-all từ chối bắt tay. `000` = không có phản hồi HTTP.
kiem "SNI lạ bị từ chối bắt tay" 000 \
    --insecure --resolve "khong-thuoc-ve.invalid:443:$IP" \
    "https://khong-thuoc-ve.invalid/health"

echo "--- cổng 80 ---"
# 5. Chuyển hướng HTTPS còn nguyên.
kiem "GET / trên cổng 80 chuyển hướng HTTPS" 301 \
    --resolve "$DOMAIN:80:$IP" "http://$DOMAIN/"

# 6. Đường ACME phải trả 404 TỪ WEBROOT, không phải 301 từ catch-all. Nếu nó
#    301 thì `location /.well-known/acme-challenge/` đã biến mất và certbot sẽ
#    gia hạn thất bại ÂM THẦM — chứng thư chỉ chết vào ngày hết hạn.
kiem "đường ACME còn sống (404 chứ không 301)" 404 \
    --resolve "$DOMAIN:80:$IP" \
    "http://$DOMAIN/.well-known/acme-challenge/qlts-probe-khong-ton-tai"

if [ "$STRICT" = "1" ]; then
    echo "--- chuỗi chứng thư ---"
    # Bỏ --insecure: chứng thư phải hợp lệ CHO ĐÚNG $DOMAIN. Với --resolve,
    # curl vẫn thẩm định theo tên trong URL chứ không theo IP.
    kiem "chứng thư khớp $DOMAIN" 200 \
        --resolve "$DOMAIN:443:$IP" "https://$DOMAIN/health"
fi

echo ""
if [ "$SO_HONG" -eq 0 ]; then
    echo "ĐẠT — nginx đang phục vụ thật qua TLS/SNI, cả backend lẫn frontend."
    exit 0
fi
echo "HỎNG — $SO_HONG phép kiểm không đạt."
exit 1
'
