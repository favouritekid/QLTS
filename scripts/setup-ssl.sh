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

# =============================================================================
# Step 0: MỌI ẢNH CẦN SAU ĐIỂM DỪNG NGINX PHẢI CÓ SẴN — TRƯỚC cổng 80, TRƯỚC ACME
# =============================================================================
# Bản trước KHÔNG build bao giờ (`grep -c build scripts/setup-ssl.sh` = 0).
#
# Thứ hỏng vì thế KHÔNG phải hạn mức Let's Encrypt — `--keep-until-expiring` ở
# Step 3 đã lo đúng việc đó, chạy lại không đốt thêm suất duplicate-certificate.
# Thứ hỏng là ĐƯỜNG LÙI:
#
#   chứng thư đã cấp (Step 3) · bootstrap đã gỡ (Step 4) · Step 5 đỏ vì ảnh
#   nginx không có hoặc đã cũ · `_DA_BAN_GIAO` còn 0 ⇒ trap bật lại container
#   nginx CŨ. Trên một VPS MỚI thì KHÔNG CÓ container cũ nào — `_NGINX_DANG_CHAY`
#   bằng 0 nên trap lặng lẽ không làm gì. Kết quả: máy chủ không có nginx nào
#   chạy, cổng 443 câm, và người vận hành phải tự đoán ra rằng thứ còn thiếu là
#   một lệnh `compose build` mà không script nào nhắc tới.
#
# Vì sao BUILD chứ không phải một phép thẩm định thuần: trên VPS mới ảnh
# `qlts-nginx:local` CHƯA TỒN TẠI. Một phép kiểm chỉ biết báo đỏ sẽ chặn luôn
# cả lần cấp chứng thư đầu tiên — đúng cái việc script này sinh ra để làm.
# `build` vừa chữa ca ấy, vừa đặt CẢ BA container nginx lên CÙNG MỘT ảnh:
# `nginx-bootstrap` (Step 2), rồi `nginx-candidate` + `nginx` trong
# `nginx-apply.sh` (Step 5) đều `<<: *nginx-base` ⇒ cùng `build: ./nginx` ⇒ cùng
# `image: qlts-nginx:local`. Không build thì `up -d` ở Step 5 là no-op trên ảnh
# cũ: template mới KHÔNG lên mà mọi thứ vẫn trả 0.
#
# --- VÌ SAO KHÔNG CHỈ NGINX (vòng 2) -----------------------------------------
# Danh sách dưới đây KHÔNG suy từ "bốn service ứng dụng" mà suy từ những service
# THẬT SỰ được khởi động sau điểm dừng nginx. Đọc ngược từ mã:
#
#   Step 2  `--profile bootstrap up -d --no-deps nginx-bootstrap`  → qlts-nginx:local
#   Step 3  `--profile production run --rm --no-deps … certbot`    → certbot/certbot
#   Step 5  nginx-apply.sh, `QLTS_NGINX_NO_DEPS=0`:
#           Nhịp 0 `up -d --wait postgres redis backend frontend`
#                  → postgres:16-alpine · redis:7-alpine · ảnh build backend · frontend
#           Nhịp 1 `--profile candidate up -d … nginx-candidate` → qlts-nginx:local
#           Nhịp 3 `--profile production up -d nginx`            → qlts-nginx:local
#
# `celery-worker` / `celery-beat` KHÔNG có mặt trong danh sách ấy: không lệnh nào
# trong hai script khởi động chúng, và không `depends_on` nào dẫn tới chúng
# (chính CHÚNG mới `depends_on: backend`, chiều ngược lại). Nên chúng KHÔNG được
# build ở đây — mở rộng máy móc sang "bốn service ứng dụng" là bắt một VPS mới
# trả tiền cho hai ảnh không ai dùng trong luồng này.
#
# Hai nhóm, hai cách xử lý khác nhau:
#   * BUILD  — `nginx`, `backend`, `frontend`: ảnh của ta, dựng từ cây nguồn.
#              Thiếu chúng thì `up -d` ở Nhịp 0/Nhịp 3 sẽ TỰ build — đúng lúc
#              cổng 80 đã nhường và chứng thư đã cấp. Compose build ngầm trong
#              `up` KHÔNG hiện ra như một lệnh riêng, nên người vận hành chỉ
#              thấy `up` treo mười phút rồi đỏ vì một lý do chẳng liên quan.
#   * PULL   — `certbot`, `postgres`, `redis`: ảnh upstream, không có `build:`
#              nào để dựng. `--policy missing` nên đã có cục bộ thì không chạm
#              mạng. Không kéo trước thì lần chạm registry đầu tiên rơi vào
#              GIỮA lúc bootstrap đang giữ cổng 80 — mạng hỏng ở đó là hỏng với
#              một nginx đã bị dừng.
#
# Đặt ở ĐÂY chứ không ở Step 5: sau certbot thì mọi bản vá đều là vá nửa vời —
# cổng 80 đã bị lấy, nginx đang phục vụ đã bị dừng, chứng thư đã cấp.
#
# `COMPOSE` (khai ở trên) đã ghim sẵn `-f docker-compose.yml --env-file …`;
# thiếu `-f` là Compose tự nạp `docker-compose.override.yml` của DEV.
log "Step 0: xác minh cây nguồn, dựng ảnh, kéo ảnh mượn (trước khi chạm cổng 80)..."

# --- 0a. Cây nào sẽ được build? ----------------------------------------------
# `build` dựng từ CÂY LÀM VIỆC, không từ một SHA. Cây đã trôi ⇒ Step 0 lặng lẽ
# đưa phần trôi ấy lên production và ảnh không còn khớp commit nào cả.
#
# Soi ĐÚNG những đường thật sự đi vào ba ảnh sắp build, không hơn: mỗi phần tử
# của `_DUONG_CAY_NGUON` là một `build.context` trong `docker-compose.yml`
#   nginx           → services.nginx.build.context          = ./nginx
#   Backend_FastAPI → services.backend.build.context        = ./Backend_FastAPI
#   frontend        → services.frontend.build.context       = ./frontend
# cộng thêm chính `docker-compose.yml` (nó khai context, tag ảnh, build args,
# biến render — đổi nó là đổi ảnh mà không đổi một byte nào trong context).
# `test_cong_cay_nguon_phu_dung_cac_build_context` khoá danh sách này vào
# compose theo CẢ HAI CHIỀU, nên đổi `build.context` mà quên cổng là test đỏ.
#
# Soi cả cây thì mọi sửa đổi vô can cũng làm cổng đỏ, mà một cổng đỏ oan là một
# cổng sẽ bị tắt. Chiều ngược lại — soi hụt — thì tệ hơn: nó xanh.
#
# ⚠️ Cổng này CỐ Ý over-inclusive ở một chỗ: `.dockerignore` loại bớt tệp khỏi
# build context (vd `Backend_FastAPI/tests/`), nên sửa một tệp bị loại vẫn làm
# cổng đỏ dù ảnh không đổi. Đọc `.dockerignore` cho đúng (phủ định, ký tự đại
# diện, thứ tự) là một bộ phân tích riêng; đoán sai theo chiều "bỏ qua" là mở
# một lỗ IM LẶNG. Fail-closed chọn phía ồn ào.
#
# Tệp CHƯA THEO DÕI (`??`) cũng tính: `COPY` của Docker đọc cả tệp chưa commit,
# và `nginx/conf.d/default.conf` nằm ngoài git CHÍNH LÀ thứ đã giữ production
# sống nhiều tuần rồi giết nó khi cutover từ checkout sạch (12-08-2026).
#
# CỐ Ý KHÔNG thêm biến kiểu `SHA_MONG_DOI` của `deploy.sh`: ở đó giá trị đến từ
# `github.sha` của run, tức có một bên sinh ra nó. Script này chạy TAY trên VPS
# mới, không ai biết trước SHA mong đợi — một biến không ai đặt là một cổng
# không bao giờ đóng. SHA vẫn được IN ra để vào log vận hành.
#
# BREAK-GLASS `QLTS_SSL_KIEM_CAY_NGUON=0`: đây là THAO TÁC CÓ CHỦ ĐÍCH CỦA
# OWNER, không phải đường đi thường. Nó nói "tôi biết trên đĩa có thứ chưa
# commit và tôi MUỐN chính thứ đó lên production" — ca thật duy nhất là vá nóng
# khi không push được. Biến này RIÊNG cho cổng cây nguồn: nó không tắt kèm bất
# cứ phép kiểm nào khác, và không phép kiểm nào khác tắt được nó. Dùng chung một
# cờ cho hai hàng rào là cách một hàng rào bị gỡ mà không ai định gỡ nó.
_DUONG_CAY_NGUON=(nginx Backend_FastAPI frontend docker-compose.yml)

if [ "${QLTS_SSL_KIEM_CAY_NGUON:-1}" = "1" ]; then
    if ! _SHA_SE_BUILD=$(git rev-parse HEAD 2>/dev/null); then
        error "không đọc được HEAD — từ chối build khi chưa biết mình sắp build cái gì. Đây có phải một checkout git không? Nếu CỐ Ý chạy ngoài git, đặt QLTS_SSL_KIEM_CAY_NGUON=0."
    fi
    if ! _CAY_BAN=$(git status --porcelain -- "${_DUONG_CAY_NGUON[@]}" 2>/dev/null); then
        error "không đọc được trạng thái cây nguồn (git status) — từ chối build."
    fi
    if [ -n "$_CAY_BAN" ]; then
        error "cây nguồn của các ảnh sắp build đã TRÔI khỏi $_SHA_SE_BUILD:
$_CAY_BAN
       Step 0 sẽ build CHÍNH những thay đổi đang nằm trên đĩa này lên production. Commit hoặc stash trước, hoặc đặt QLTS_SSL_KIEM_CAY_NGUON=0 nếu đó đúng là điều bạn muốn."
    fi
    log "  cây nguồn: $_SHA_SE_BUILD (${_DUONG_CAY_NGUON[*]} — sạch)"
else
    warn "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    warn "!!  BREAK-GLASS: QLTS_SSL_KIEM_CAY_NGUON=0 — CỔNG CÂY NGUỒN ĐÃ TẮT  !!"
    warn "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    warn "Đây là THAO TÁC CÓ CHỦ ĐÍCH CỦA OWNER, không phải đường đi thường."
    warn "Ảnh nginx/backend/frontend sắp lên production sẽ mang MỌI sửa đổi đang"
    warn "nằm trên đĩa máy này — kể cả tệp CHƯA COMMIT và tệp CHƯA THEO DÕI — và"
    warn "sẽ KHÔNG khớp commit nào. Không có cách nào dựng lại đúng ảnh ấy về sau."
    warn "Ghi lại vào sổ vận hành: ai bật, lúc nào, vì việc gì."
fi

"${COMPOSE[@]}" --profile production build nginx backend frontend \
    || error "không build được ảnh (nginx/backend/frontend) — DỪNG tại đây. Chưa dừng nginx nào, chưa chạm cổng 80, chưa gọi certbot: không có gì phải khôi phục. Đọc log build phía trên."

# --- 0c. Ảnh MƯỢN phải có mặt trước điểm dừng --------------------------------
# `--policy missing`: có sẵn cục bộ thì không chạm mạng, thiếu thì kéo NGAY BÂY
# GIỜ. Ba service này không có `build:` nào — `build` ở trên không đụng tới
# chúng, và Compose cũng không tự dựng được chúng. Lần chạm registry đầu tiên
# vì thế sẽ rơi vào Step 3 (certbot) hoặc Nhịp 0 của nginx-apply (postgres,
# redis) — tức SAU khi nginx đang phục vụ đã bị dừng và cổng 80 đã nhường.
# `--profile production` là bắt buộc để `certbot` được nhìn thấy (postgres và
# redis không khai profile nên luôn có mặt).
"${COMPOSE[@]}" --profile production pull --policy missing certbot postgres redis \
    || error "không bảo đảm được các ảnh mượn (certbot/postgres/redis) — DỪNG tại đây. Chưa dừng nginx nào, chưa chạm cổng 80, chưa gọi certbot: không có gì phải khôi phục."

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
