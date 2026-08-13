#!/usr/bin/env bash
# =============================================================================
# QLTS — áp cấu hình nginx: THỬ TRƯỚC, THAY SAU
# =============================================================================
# Usage: scripts/nginx-apply.sh <domain>
#
# Biến môi trường (chỉ để bài kiểm hồi quy trỏ script này vào một stack cô lập;
# bỏ trống là chạy đúng như prod):
#   QLTS_COMPOSE_ENV_FILE   mặc định `.env.production`
#   QLTS_COMPOSE_EXTRA      tham số compose thêm, tách theo khoảng trắng
#                           (vd: "-f tests-e2e/... -p qltsngx")
#
# Biến vận hành thật:
#   QLTS_NGINX_NO_DEPS      mặc định 1. Đặt 0 khi backend/frontend CHƯA chắc
#                           đang chạy — `scripts/setup-ssl.sh` trên một VPS mới
#                           là đúng ca đó. nginx phân giải hostname upstream
#                           NGAY LÚC NẠP CONFIG, nên `--no-deps` ở hoàn cảnh ấy
#                           cho `[emerg] host not found in upstream "backend"`.
#
# Vì sao tách khỏi `deploy.sh`: để bài kiểm hồi quy chạy ĐÚNG đoạn mã mà deploy
# sẽ chạy. Một bản chép lại trong test chỉ chứng minh giả định của người viết
# test — mà chính lớp sai ấy là thứ PR này ra đời để đóng.
#
# Ba nhịp:
#   1. dựng `nginx-candidate` — cùng image, cùng biến, cùng healthcheck, KHÔNG
#      publish cổng nào nên không tranh chấp với container đang phục vụ;
#   2. đo hành vi thật của nó (TLS + SNI thật, route backend, route frontend)
#      bằng `scripts/nginx-verify.sh`. Hỏng ⇒ thoát khác 0, và container đang
#      phục vụ CHƯA HỀ BỊ ĐỤNG TỚI;
#   3. đạt ⇒ `up -d` KHÔNG kèm `--force-recreate`.
#
# Vì sao KHÔNG `--force-recreate` vô điều kiện (nó từng nằm ở đây): lệnh ấy
# stop+remove container đang phục vụ TRƯỚC khi có bất kỳ thứ gì được kiểm.
# Template hỏng, chứng thư thiếu hay DOMAIN rỗng đều cho cùng một kết cục —
# :80 và :443 chết, `restart: unless-stopped` quay vòng, không đường lùi.
# Cấu hình nay nằm trong image (nginx/Dockerfile) nên đổi template là đổi image
# ID và Compose tự recreate; không đổi gì thì `up -d` là no-op thật.
# =============================================================================
set -euo pipefail

export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOMAIN="${1:?thiếu tham số: domain}"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
log() { echo -e "${GREEN}[NGINX]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }

_ENV_FILE="${QLTS_COMPOSE_ENV_FILE:-.env.production}"
read -r -a _EXTRA <<< "${QLTS_COMPOSE_EXTRA:-}"
_COMPOSE=(docker compose -f docker-compose.yml --env-file "$_ENV_FILE" "${_EXTRA[@]}")

_don_candidate() {
    "${_COMPOSE[@]}" --profile candidate rm -sfv nginx-candidate >/dev/null 2>&1 || true
}
trap _don_candidate EXIT

_nhat_ky() {
    "${_COMPOSE[@]}" --profile production --profile candidate logs --tail=60 "$1" 2>&1 || true
}

# Chờ một service tới trạng thái healthy.
#
# Vòng chờ cũ chỉ thoát sớm khi trạng thái đúng chữ "unhealthy" — mà đó KHÔNG
# phải ca hỏng thường gặp. nginx chết lúc nạp config thì container `exited`
# hoặc `restarting`, và `docker inspect` trả chuỗi rỗng hoặc "starting"; vòng
# lặp vì thế chạy hết ~120 giây với site đã chết rồi báo một câu vô nghĩa là
# "khong-doc-duoc". Nay mọi trạng thái kết thúc đều được nhận ra ngay.
_cho_healthy() {
    local ten="$1" han="${2:-120}" cid tt sk ma
    cid=$("${_COMPOSE[@]}" --profile production --profile candidate ps -aq "$ten" 2>/dev/null | head -1)
    if [ -z "$cid" ]; then
        log "  không thấy container nào cho service '$ten'"
        return 1
    fi
    local het=$((SECONDS + han))
    while [ "$SECONDS" -lt "$het" ]; do
        tt=$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo "")
        sk=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}khong-co-healthcheck{{end}}' "$cid" 2>/dev/null || echo "")
        case "$tt" in
            exited|dead)
                ma=$(docker inspect -f '{{.State.ExitCode}}' "$cid" 2>/dev/null || echo "?")
                log "  '$ten' đã DỪNG (status=$tt, exit=$ma) — không chờ thêm"
                return 1
                ;;
            restarting)
                log "  '$ten' đang quay vòng khởi động lại — cấu hình không nạp được"
                return 1
                ;;
        esac
        if [ "$sk" = "healthy" ]; then return 0; fi
        if [ "$sk" = "unhealthy" ]; then
            log "  '$ten' unhealthy"
            return 1
        fi
        sleep 3
    done
    log "  '$ten' quá hạn ${han}s (status=${tt:-?}, health=${sk:-?})"
    return 1
}

# --- Nhịp 0: bảo đảm upstream sẵn sàng (chỉ khi được yêu cầu) ---------------
# nginx phân giải `upstream backend { server backend:8000; }` NGAY LÚC NẠP
# CONFIG, vô điều kiện. Upstream chưa tồn tại ⇒ `[emerg] host not found in
# upstream "backend"` và container chết ngay — kể cả container candidate.
# Trong luồng deploy thì backend/frontend vừa được khởi động và chờ healthy ở
# Step 8, nên mặc định ta bỏ qua nhịp này. Trên một VPS mới (setup-ssl.sh) thì
# ngược lại: chưa có gì chạy cả.
if [ "${QLTS_NGINX_NO_DEPS:-1}" != "1" ]; then
    log "khởi động upstream trước (nginx phân giải hostname lúc nạp config)..."
    "${_COMPOSE[@]}" --profile production up -d --wait postgres redis backend frontend \
        || error "upstream không lên được — nginx sẽ không nạp nổi config"
fi

# --- Nhịp 1+2: dựng candidate rồi đo ----------------------------------------
log "dựng nginx-candidate để thử cấu hình mới..."
if ! "${_COMPOSE[@]}" --profile candidate up -d --no-deps --force-recreate nginx-candidate; then
    _nhat_ky nginx-candidate
    error "không dựng được nginx-candidate — cấu hình mới hỏng; container đang phục vụ giữ nguyên"
fi

if ! _cho_healthy nginx-candidate 90; then
    _nhat_ky nginx-candidate
    error "nginx-candidate không healthy — KHÔNG thay container đang phục vụ"
fi

_CID_CANDIDATE=$("${_COMPOSE[@]}" --profile candidate ps -q nginx-candidate | head -1)
if ! bash "$SCRIPT_DIR/nginx-verify.sh" "$_CID_CANDIDATE" "$DOMAIN"; then
    _nhat_ky nginx-candidate
    error "cấu hình mới không phục vụ được — KHÔNG thay container đang phục vụ (last-good vẫn chạy)"
fi
log "candidate đạt — chuyển sang container đang phục vụ"
_don_candidate

# --- Nhịp 3: áp vào container thật ------------------------------------------
# `--no-deps` (mặc định) để không kéo backend/frontend recreate theo — chúng vừa
# được khởi động và đang healthy ở bước trước của deploy. Nhưng nó SAI ở kịch
# bản VPS mới (setup-ssl.sh), nơi upstream chưa hề tồn tại: xem
# QLTS_NGINX_NO_DEPS ở đầu tệp.
_CO_NO_DEPS=()
if [ "${QLTS_NGINX_NO_DEPS:-1}" = "1" ]; then _CO_NO_DEPS=(--no-deps); fi
if ! "${_COMPOSE[@]}" --profile production up -d "${_CO_NO_DEPS[@]}" nginx; then
    _nhat_ky nginx
    error "không áp được cấu hình nginx"
fi

if ! _cho_healthy nginx 120; then
    _nhat_ky nginx
    error "nginx không healthy sau khi áp cấu hình — KHÔNG tuyên bố deploy thành công"
fi

# Đo lại trên CHÍNH container đang phục vụ. Candidate đã chứng minh cấu hình
# đúng, nhưng nó không chứng minh container THẬT đã nhận cấu hình ấy — đúng
# khoảng trống 12-08 đã rơi vào: đo một thứ rồi kết luận cho một thứ khác.
_CID_NGINX=$("${_COMPOSE[@]}" --profile production ps -q nginx | head -1)
if ! bash "$SCRIPT_DIR/nginx-verify.sh" "$_CID_NGINX" "$DOMAIN"; then
    _nhat_ky nginx
    error "nginx đang chạy nhưng KHÔNG phục vụ đúng — xem log phía trên"
fi
log "nginx healthy và đã được đo bằng request thật — cấu hình mới đã được áp"
