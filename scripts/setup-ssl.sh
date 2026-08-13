#!/usr/bin/env bash
# =============================================================================
# QLTS SSL Certificate Setup (lần đầu — và CHẠY LẠI ĐƯỢC)
# =============================================================================
# Usage: ./scripts/setup-ssl.sh
# Tiền đề: `.env.production` có DOMAIN, và bản ghi DNS A đã trỏ về máy này.
#
# Script này CÓ QUYỀN dừng service `nginx` trong lúc chạy: cổng 80 phải thuộc về
# container bootstrap thì ACME challenge mới tới được. Việc dừng ấy là CÓ CHỦ
# ĐÍCH và được ghi ở Step 1, chứ không phải một va chạm tình cờ như bản trước
# (`docker run -p 80:80` thẳng, chết với "port is already allocated" nếu nginx
# đang chạy hoặc đang quay vòng — và tiền đề "phải dừng nginx trước" thì không
# được ghi ở đâu cả).
#
# Chạy lại được: Step 3 dùng `--keep-until-expiring`, nên khi chứng thư đã tồn
# tại và chưa gần hết hạn thì certbot bỏ qua và trả 0. Bản trước không có cờ
# này: `certonly --non-interactive` gặp một lineage trùng khít sẽ rơi vào lời
# nhắc tương tác, `NoninteractiveDisplay` biến nó thành `MissingCommandlineFlag`
# — và người vận hành đọc thông điệp "Ensure DNS A record points to this server"
# rồi đi mò DNS, trong khi nguyên nhân thật là "bạn đã có chứng thư này rồi".
# Ca ấy rất dễ gặp, vì Step 5 nay là một cổng CỨNG: hỏng ở đó thì phản xạ tự
# nhiên là chạy lại script — và đó chính là lúc bản trước tự khoá mình.
# =============================================================================
set -euo pipefail

export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[SSL]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }

# Móc để bài kiểm hồi quy trỏ script này vào một stack cô lập; bỏ trống là chạy
# đúng như prod. Cùng bộ biến với `nginx-apply.sh` nên chúng lan xuống lời gọi
# lồng nhau. Không có móc này thì script dừng-nginx-rồi-cấp-chứng-thư là thứ
# KHÔNG THỂ diễn tập ở đâu ngoài chính máy chủ đang phục vụ.
_ENV_FILE="${QLTS_COMPOSE_ENV_FILE:-.env.production}"
read -r -a _EXTRA <<< "${QLTS_COMPOSE_EXTRA:-}"

if [ ! -f "$_ENV_FILE" ]; then
    error "$_ENV_FILE not found"
fi

set -a
# shellcheck disable=SC1091
source "$_ENV_FILE"
set +a

if [ -z "${DOMAIN:-}" ]; then
    error "DOMAIN is not set in .env.production"
fi

EMAIL="${CERTBOT_EMAIL:-admin@$DOMAIN}"

COMPOSE=(docker compose -f docker-compose.yml --env-file "$_ENV_FILE" "${_EXTRA[@]}")

log "Setting up SSL for: $DOMAIN"
log "Certbot email: $EMAIL"

_don_bootstrap() {
    "${COMPOSE[@]}" --profile bootstrap rm -sfv nginx-bootstrap >/dev/null 2>&1 || true
}

# =============================================================================
# Step 1: nhường cổng 80 cho bootstrap — CÓ CHỦ ĐÍCH, VÀ CÓ ĐƯỜNG LÙI
# =============================================================================
# Script này được chạy cả trên máy chủ ĐANG PHỤC VỤ (gia hạn tay, đổi tên miền,
# cấp lại chứng thư), không chỉ trên VPS mới. Ở đó, dừng nginx là dừng cả site.
#
# Bản trước chỉ đặt trap dọn bootstrap. Nghĩa là bootstrap hỏng, certbot hỏng,
# candidate hỏng hay bàn giao hỏng — bất kỳ cái nào — đều để lại một máy chủ
# KHÔNG có nginx nào chạy, và người vận hành phải tự đoán ra là mình cần bật
# lại. Trap dưới đây bật lại ĐÚNG container cũ (`docker start` theo ID, không
# phải `up -d` vốn có thể dựng một container khác từ cấu hình khác), rồi CHỨNG
# MINH nó phục vụ lại được.
log "Step 1: dừng service nginx để nhường cổng 80 (nếu đang chạy)..."

_CID_NGINX_CU=$("${COMPOSE[@]}" --profile production ps -q nginx 2>/dev/null | head -1)
_NGINX_DANG_CHAY=0
if [ -n "$_CID_NGINX_CU" ]; then
    if [ "$(docker inspect -f '{{.State.Running}}' "$_CID_NGINX_CU" 2>/dev/null)" = "true" ]; then
        _NGINX_DANG_CHAY=1
        log "  nginx đang phục vụ (${_CID_NGINX_CU:0:12}) — sẽ bật lại nếu có bước nào hỏng"
    fi
fi
_DA_BAN_GIAO=0

_khoi_phuc_last_good() {
    local ma_thoat=$?
    _don_bootstrap
    if [ "$_DA_BAN_GIAO" = "1" ] || [ "$_NGINX_DANG_CHAY" != "1" ]; then
        return 0
    fi
    warn "có bước hỏng — bật lại container nginx last-good ${_CID_NGINX_CU:0:12}..."
    if ! docker start "$_CID_NGINX_CU" >/dev/null 2>&1; then
        echo -e "${RED}[ERROR]${NC} KHÔNG bật lại được nginx last-good ($_CID_NGINX_CU)." >&2
        echo -e "${RED}[ERROR]${NC} Site đang KHÔNG được phục vụ. Chạy tay:" >&2
        echo -e "${RED}[ERROR]${NC}   docker start $_CID_NGINX_CU" >&2
        return 0
    fi
    local het=$((SECONDS + 90)) sk=""
    while [ "$SECONDS" -lt "$het" ]; do
        sk=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$_CID_NGINX_CU" 2>/dev/null || echo "")
        [ "$sk" = "healthy" ] && break
        [ "$sk" = "unhealthy" ] && break
        sleep 3
    done
    if [ "$sk" = "healthy" ] \
        && bash "$SCRIPT_DIR/nginx-verify.sh" "$_CID_NGINX_CU" "$DOMAIN" >/dev/null 2>&1; then
        log "  last-good đã phục vụ trở lại (đã đo bằng request thật)"
    else
        echo -e "${RED}[ERROR]${NC} nginx last-good đã bật nhưng KHÔNG phục vụ được" >&2
        echo -e "${RED}[ERROR]${NC}   docker logs $_CID_NGINX_CU" >&2
    fi
    return $ma_thoat
}

"${COMPOSE[@]}" --profile production stop nginx >/dev/null 2>&1 || true
_don_bootstrap
trap _khoi_phuc_last_good EXIT

# =============================================================================
# Step 2: nginx bootstrap (HTTP thuần, chỉ để ACME challenge đi qua)
# =============================================================================
# Vì sao không dùng service `nginx` thật: template production tham chiếu chứng
# thư CHƯA tồn tại ở bước này ⇒ nginx [emerg], không khởi động nổi. Bản trước
# nữa thì ghi đè `nginx/conf.d/default.conf` trên host để lách — chính lối đó
# đẻ ra tệp ngoài git đã làm site chết khi cutover từ checkout sạch.
#
# `nginx-bootstrap` là một service của Compose (profile `bootstrap`), nên volume
# `certbot_www` được chính Compose phân giải theo project. Không còn chỗ nào
# phải đoán tên volume.
log "Step 2: dựng nginx bootstrap (HTTP, ACME challenge)..."
"${COMPOSE[@]}" --profile bootstrap up -d --no-deps nginx-bootstrap \
    || error "không dựng được nginx bootstrap (cổng 80 có thể đang bị chiếm bởi tiến trình ngoài Docker)"

log "  chờ bootstrap healthy..."
_CID_BOOTSTRAP=$("${COMPOSE[@]}" --profile bootstrap ps -aq nginx-bootstrap | head -1)
_HET=$((SECONDS + 60))
_OK=0
while [ "$SECONDS" -lt "$_HET" ]; do
    _TT=$(docker inspect -f '{{.State.Status}}' "$_CID_BOOTSTRAP" 2>/dev/null || echo "")
    case "$_TT" in
        exited|dead)
            "${COMPOSE[@]}" --profile bootstrap logs --tail=40 nginx-bootstrap || true
            error "nginx bootstrap đã dừng ngay khi khởi động"
            ;;
    esac
    _SK=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$_CID_BOOTSTRAP" 2>/dev/null || echo "")
    [ "$_SK" = "healthy" ] && { _OK=1; break; }
    [ "$_SK" = "unhealthy" ] && break
    sleep 2
done
if [ "$_OK" -ne 1 ]; then
    "${COMPOSE[@]}" --profile bootstrap logs --tail=40 nginx-bootstrap || true
    error "nginx bootstrap không healthy — ACME challenge sẽ không tới được"
fi

# =============================================================================
# Step 3: xin chứng thư
# =============================================================================
log "Step 3: xin chứng thư từ Let's Encrypt..."

# `--no-deps` là BẮT BUỘC ở ĐÂY (và chỉ ở đây): `certbot` khai `depends_on:
# nginx`, nên thiếu nó Compose sẽ kéo nginx PRODUCTION lên — tranh cổng 80 với
# bootstrap đang chạy, và bản thân nó cũng chưa khởi động được vì chứng thư còn
# chưa tồn tại.
# `--entrypoint certbot`: service này override entrypoint thành vòng lặp
# `certbot renew … sleep 12h`; `run` chỉ thay COMMAND chứ không thay ENTRYPOINT,
# nên thiếu cờ này thì `certonly …` chỉ là đối số không được thực thi.
# `--keep-until-expiring`: xem đầu tệp — đây là thứ làm script chạy lại được.
"${COMPOSE[@]}" --profile production run --rm --no-deps --entrypoint certbot certbot \
    certonly \
    --non-interactive \
    --keep-until-expiring \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" \
    -d "www.$DOMAIN" \
    || error "Certbot thất bại. Kiểm tra bản ghi DNS A của $DOMAIN có trỏ về máy này không, và cổng 80 có ra được Internet không."

# =============================================================================
# Step 4: trả cổng 80
# =============================================================================
log "Step 4: gỡ nginx bootstrap..."
_don_bootstrap

# =============================================================================
# Step 5: bàn giao cho nginx production
# =============================================================================
# `QLTS_NGINX_NO_DEPS=0`: lệnh `up -d nginx` ở đây KHÔNG được mang `--no-deps`.
# Bản trước mang, và đó là lỗi chí mạng đúng ở kịch bản script này sinh ra để
# phục vụ: `nginx/nginx.conf` khai `upstream backend { server backend:8000; }`
# và nginx phân giải hostname upstream NGAY LÚC NẠP CONFIG. Trên một VPS mới
# backend/frontend chưa chạy, `--no-deps` bảo Compose bỏ qua
# `depends_on: service_healthy`, và nginx chết với
# `[emerg] host not found in upstream "backend"`. Tệ hơn: `up -d` vẫn trả 0 nên
# `|| error` không nổ, `ps -q` trả rỗng cho container đã thoát, biến trạng thái
# không bao giờ khớp "unhealthy", và vòng chờ đốt trọn 120 giây trước khi báo
# một câu vô nghĩa. Chứng thư thì đã cấp rồi — nên mỗi lần thử lại là đốt một
# suất trong hạn mức duplicate-certificate của Let's Encrypt.
log "Step 5: khởi động nginx production (template render trong container)..."
QLTS_NGINX_NO_DEPS=0 bash "$SCRIPT_DIR/nginx-apply.sh" "$DOMAIN" \
    || error "nginx không phục vụ được sau khi cấp chứng thư — xem log phía trên"

# Chỉ từ đây trap mới thôi bật lại container cũ: `nginx-apply.sh` đã dựng và ĐO
# container mới bằng request thật, nên "last-good" bây giờ chính là nó.
_DA_BAN_GIAO=1

log "========================================="
log "SSL setup completed successfully!"
log "========================================="
log "Certificate: /etc/letsencrypt/live/$DOMAIN/"
log "Auto-renewal: certbot container (12h/lần)"
log ""
log "Đã được đo bằng request thật qua TLS/SNI ở Step 5; không cần smoke tay."
