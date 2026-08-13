#!/bin/sh
# Chạy NGAY SAU `20-envsubst-on-templates.sh`, trước khi nginx được exec.
#
# Kiểm bản render — nhưng chỉ những tính chất mà bản render SAI thì nginx vẫn
# khởi động được. Cố ý KHÔNG grep `server_name <domain>`: phép kiểm ấy buộc
# sống chết của prod vào cách đánh máy template (đảo `www.${DOMAIN} ${DOMAIN}`
# là container ghim unhealthy vĩnh viễn dù đang phục vụ hoàn hảo — đã tái hiện).
# Bằng chứng "có phục vụ thật" thuộc về healthcheck (TLS + SNI thật) và cổng
# candidate trong scripts/deploy.sh.
set -e

loi() {
    echo "=======================================================" >&2
    echo "[qlts-nginx] TỪ CHỐI KHỞI ĐỘNG: $1" >&2
    shift
    for d in "$@"; do echo "[qlts-nginx]   $d" >&2; done
    echo "=======================================================" >&2
    exit 1
}

_ODIR="${NGINX_ENVSUBST_OUTPUT_DIR:-/etc/nginx/conf.d}"
_R="$_ODIR/default.conf"
[ -s "$_R" ] || loi "envsubst không tạo được $_R (hoặc tạo ra tệp rỗng)"

# envsubst chỉ thay biến CÓ trong môi trường; biến thiếu được giữ NGUYÊN dạng
# `${TEN}`. nginx sẽ hiểu đó là chuỗi thường và nuốt luôn, nên ca này không tự
# lộ ra ở đâu cả. Bản kiểm tĩnh trong pytest canh cùng bất biến ở phía repo;
# đây là lớp chạy thật cho ca ai đó thêm biến vào template mà quên compose.
if grep -q '\${[A-Za-z_][A-Za-z0-9_]*}' "$_R"; then
    _con=$(grep -o '\${[A-Za-z_][A-Za-z0-9_]*}' "$_R" | sort -u | tr '\n' ' ')
    loi "bản render còn biến chưa được thay: $_con" \
        "Biến này chưa được truyền vào container (mục environment của service" \
        "nginx trong docker-compose.yml). envsubst giữ nguyên chuỗi \${...} và" \
        "nginx sẽ coi nó là văn bản thường."
fi
