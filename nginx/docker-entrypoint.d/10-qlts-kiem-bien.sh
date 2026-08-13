#!/bin/sh
# Chạy TRƯỚC `20-envsubst-on-templates.sh` (entrypoint chính thức duyệt
# `/docker-entrypoint.d/*.sh` theo `sort -V`).
#
# Entrypoint của image mở đầu bằng `set -e` và gọi thẳng từng script, nên một
# lần `exit 1` ở đây làm container DỪNG HẲN với thông điệp đọc được — thay vì
# khởi động rồi phục vụ sai. Đã đo: guard thoát 1 ⇒ `docker run` trả 1 và nginx
# không hề in "ready for start up".
#
# Mỗi phép kiểm dưới đây canh một ca đã thật sự xảy ra hoặc đã được tái hiện.
set -e

loi() {
    echo "=======================================================" >&2
    echo "[qlts-nginx] TỪ CHỐI KHỞI ĐỘNG: $1" >&2
    shift
    for d in "$@"; do echo "[qlts-nginx]   $d" >&2; done
    echo "=======================================================" >&2
    exit 1
}

# --- 1. DOMAIN ------------------------------------------------------------
# Ca thật: `docker compose --profile production up -d` mà QUÊN
# `--env-file .env.production`. Tệp env mặc định của Compose là `.env`, chỉ có
# POSTGRES_*; service nginx không khai `env_file` (cố ý — nó là container quay
# ra Internet, không được thấy SECRET_KEY/JWT/DB password). DOMAIN rỗng ⇒
# `ssl_certificate /etc/letsencrypt/live//fullchain.pem` ⇒ nginx [emerg].
# Không ngăn được cú trượt tay đó ở tầng Compose, nhưng đổi được thông điệp:
# một dòng nói đúng nguyên nhân thay vì một lỗi chứng thư khó lần.
if [ -z "${DOMAIN:-}" ]; then
    loi "biến DOMAIN rỗng" \
        "envsubst sẽ render server_name rỗng và trỏ chứng thư vào" \
        "  /etc/letsencrypt/live//fullchain.pem (không tồn tại)." \
        "Gần như luôn là do chạy compose thiếu --env-file:" \
        "  docker compose --env-file .env.production --profile production up -d"
fi
case "$DOMAIN" in
    *[!A-Za-z0-9.-]*)
        loi "DOMAIN chứa ký tự không hợp lệ: '$DOMAIN'" \
            "Chỉ chấp nhận chữ, số, dấu chấm và gạch nối."
        ;;
esac

# --- 2. NGINX_ADMISSION_FROZEN -------------------------------------------
# Cần cưỡng chế vì đây là CẦN GẠT AN TOÀN, và mặc định của nó fail-OPEN:
# template chỉ chặn khi giá trị đúng chuỗi "true", mọi giá trị khác (TRUE, 1,
# "true ", gõ nhầm) đều rơi xuống proxy_pass — tức người trực tưởng đã đóng
# băng tuyển sinh mà thật ra chưa. Bắt lỗi ngay ở đây thì cú gõ nhầm thành một
# container không khởi động (thấy ngay) thay vì một cần gạt câm.
case "${NGINX_ADMISSION_FROZEN:-}" in
    true|false) ;;
    *)
        loi "NGINX_ADMISSION_FROZEN='${NGINX_ADMISSION_FROZEN:-<rỗng>}' không hợp lệ" \
            "Chỉ chấp nhận đúng 'true' hoặc 'false' (chữ thường)." \
            "Template chỉ chặn khi khớp CHÍNH XÁC 'true'; mọi giá trị khác im" \
            "lặng cho traffic đi qua — cần gạt đóng băng sẽ không hề đóng."
        ;;
esac

# --- 3. Template ----------------------------------------------------------
# Template nay nằm TRONG image (xem nginx/Dockerfile), nên ca duy nhất còn lại
# là một mount đè `/etc/nginx/templates` bằng thư mục rỗng — đúng thứ Docker
# daemon tự tạo khi bind source không tồn tại trên host.
# Đọc ĐÚNG thư mục mà entrypoint sẽ quét: `20-envsubst-on-templates.sh` lấy
# `${NGINX_ENVSUBST_TEMPLATE_DIR}` rồi mới về mặc định `/etc/nginx/templates`.
# Container bootstrap dùng một thư mục khác, và guard phải đi theo nó — nếu
# đóng cứng đường production thì guard sẽ chặn nhầm chính bootstrap.
_TDIR="${NGINX_ENVSUBST_TEMPLATE_DIR:-/etc/nginx/templates}"
_T="$_TDIR/default.conf.template"
if [ ! -f "$_T" ]; then
    loi "thiếu $_T" \
        "Không có gì để render ⇒ include /etc/nginx/conf.d/*.conf khớp rỗng" \
        "⇒ nginx chạy mà KHÔNG một server block nào (nginx -t vẫn 'ok')." \
        "Nếu có mount đè /etc/nginx/templates thì hãy kiểm thư mục nguồn."
fi
if [ ! -s "$_T" ]; then
    loi "$_T rỗng"
fi
