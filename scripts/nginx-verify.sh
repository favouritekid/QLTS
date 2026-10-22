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

# Không `| head -1`: dưới `pipefail`, đầu đọc thoát sớm làm đầu ghi nhận SIGPIPE
# và cả pipeline thành lỗi — lấy dòng đầu bằng mở rộng tham số, không pipeline.
MANG_TAT_CA=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' "$CT") \
    || MANG_TAT_CA=""
MANG="${MANG_TAT_CA%%$'\n'*}"
IP=$(docker inspect -f "{{(index .NetworkSettings.Networks \"$MANG\").IPAddress}}" "$CT")
# `{{.Image}}`, KHÔNG `{{.Config.Image}}`. Cái sau trả về TÊN:TAG mà container
# được yêu cầu chạy — một nhãn DI ĐỘNG: `nginx` và `nginx-candidate` dùng chung
# `qlts-nginx:local`, và tag ấy trôi sang bản build mới sau mỗi `compose build`.
# Lấy tên:tag để chạy probe nghĩa là probe có thể chạy trên MỘT BẢN ẢNH KHÁC với
# bản mà container đang đo thực sự đang chạy. `{{.Image}}` là sha256 bất biến
# của đúng bản ảnh ấy, và `docker run` nhận thẳng image id.
#
# Ở ĐÂY chỉ đòi KHÁC RỖNG. Bất biến "image id phải là một ID bất biến thật" có
# ĐÚNG MỘT tầng chủ sở hữu: `_anh_cua` trong `scripts/nginx-apply.sh` (cổng
# đồng nhất). Khai lại nó ở đây là hai tầng cùng canh một bất biến mà không
# tầng nào chịu trách nhiệm — CLAUDE.md §7.
IMAGE=$(docker inspect -f '{{.Image}}' "$CT" 2>/dev/null) || IMAGE=""
[ -n "$MANG" ]  || loi "container '$CT' không nối vào mạng nào"
[ -n "$IP" ]    || loi "không đọc được IP của '$CT' trên mạng '$MANG'"
# Thiếu phép kiểm này thì `docker run --entrypoint sh "" -c …` chạy một image
# rỗng và thông điệp hỏng nói về thứ khác hẳn.
[ -n "$IMAGE" ] || loi "không đọc được image của container '$CT'"

log "đo '$CT' tại $IP trên mạng '$MANG' (domain=$DOMAIN, strict_tls=$STRICT)"

# Chạy TỪ MỘT CONTAINER KHÁC trên cùng mạng — không phải từ trong chính nginx.
# Gọi từ bên trong thì mọi request đều là 127.0.0.1 và `allow 127.0.0.1` cho
# qua những thứ mà client thật không hề với tới được.
# Dùng lại đúng image của container đang đo: chắc chắn có sẵn, có curl thật
# (nginx:1.27-alpine đóng gói curl 8.12 + OpenSSL), không phải tải thêm gì.
KQ_CHUC_NANG=0
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
' || KQ_CHUC_NANG=$?

# --- Đầu dò TOKEN trong access log (V6) -------------------------------------
# BA đầu dò ĐỘC LẬP — mỗi đầu dò MỘT request, MỘT User-Agent mang nonce riêng,
# MỘT token GIẢ riêng, đặt ở đúng MỘT chỗ mà access log ghi lại:
#   đường dẫn — `GET /confirm/<giả>`
#   query     — `GET /login?token=<giả>&refresh_token=<giả>2`
#   Referer   — `GET /login`, Referer `…/magic-link/withdraw/<giả>?token=<giả>2`
# Gộp chung một request thì chỗ được che này có thể "che hộ" chỗ kia (`map
# $request` cắt từ dấu hiệu đầu tiên nuốt luôn query đứng sau) — tách ra để MỖI
# vị trí tự chứng minh. Mỗi đầu dò HAI vế, thiếu vế nào cũng ĐỎ:
#   (a) VẪN có dòng log cho request ấy. `access_log off` cũng cho "0 dòng lộ",
#       nên chỉ đếm "không lộ" là một phép kiểm xanh vô nghĩa;
#   (b) KHÔNG đâu trong access log chứa token giả của nó, và dòng ấy mang
#       dấu `<redacted>`.
# Nguồn `docker logs` phải THÀNH CÔNG: mã thoát của nó giữ TÁCH khỏi bộ lọc.
# Bản trước viết `docker logs … | grep … || true` — `|| true` nuốt mã thoát
# nguồn, nên docker in một dòng đã che rồi thoát lỗi vẫn ra ĐẠT (F36, cùng
# kiểu F29). Nguồn lỗi ⇒ ĐỎ dù có đầu ra.
# CHỈ in dòng của chính đầu dò (dữ liệu giả) — log của container đang phục vụ
# chứa traffic thật, không bao giờ in ra. `docker logs` lấy stdout = access log
# của ảnh nginx chính thức; stderr (`error_log`) bị bỏ qua — phần dư đã biết.
NONCE="$(date +%s)$$"
GIA_P="qltsgiap${NONCE}x"
GIA_Q="qltsgiaq${NONCE}x"
GIA_R="qltsgiar${NONCE}x"
UA_P="qlts-verify-dau-do-token-p/${NONCE}"
UA_Q="qlts-verify-dau-do-token-q/${NONCE}"
UA_R="qlts-verify-dau-do-token-r/${NONCE}"
docker run --rm --network "$MANG" \
    -e DOMAIN="$DOMAIN" -e IP="$IP" \
    -e GIA_P="$GIA_P" -e GIA_Q="$GIA_Q" -e GIA_R="$GIA_R" \
    -e UA_P="$UA_P" -e UA_Q="$UA_Q" -e UA_R="$UA_R" \
    --entrypoint sh "$IMAGE" -c '
C="curl --silent --output /dev/null --max-time 8 --retry 0 --insecure --resolve $DOMAIN:443:$IP"
$C --user-agent "$UA_P" "https://$DOMAIN/confirm/${GIA_P}" || true
$C --user-agent "$UA_Q" "https://$DOMAIN/login?token=${GIA_Q}&refresh_token=${GIA_Q}2" || true
$C --user-agent "$UA_R" --referer "https://$DOMAIN/magic-link/withdraw/${GIA_R}?token=${GIA_R}2" \
    "https://$DOMAIN/login" || true
' >/dev/null 2>&1 || true

# tim <mẫu> <văn bản> — 0: CÓ · 1: KHÔNG · 2: LỖI tìm kiếm.
# Đọc HẾT đầu vào (here-string + `grep -c`), KHÔNG `printf … | grep -q`: dưới
# `set -o pipefail`, `grep -q` thoát ngay ở dòng khớp đầu tiên, `printf` phía
# trước nhận SIGPIPE (141) và cả pipeline thành "không khớp" — token lộ SỚM
# trong một access log dài bị báo là KHÔNG lộ (F36 vòng 5). "Không khớp" chỉ
# được nhận khi grep đã chạy, đọc hết và ĐẾM 0; mọi trường hợp khác (grep hỏng
# rc ≥ 2, here-string không tạo được, số đếm lạ) là LỖI.
tim() {
    local n rc=0
    n="$(grep -cF -- "$1" <<<"$2")" || rc=$?
    case "$rc:$n" in
        0:[1-9]*) return 0 ;;
        1:0) return 1 ;;
        *) return 2 ;;
    esac
}

co_du_ba_dong() {
    tim "$UA_P" "$NHAT_KY" && tim "$UA_Q" "$NHAT_KY" && tim "$UA_R" "$NHAT_KY"
}
NHAT_KY=""
NHAT_KY_RC=0
for _ in 1 2 3 4 5; do
    NHAT_KY_RC=0
    NHAT_KY="$(docker logs --since 10m "$CT" 2>/dev/null)" || NHAT_KY_RC=$?
    if [ "$NHAT_KY_RC" -eq 0 ] && co_du_ba_dong; then
        break
    fi
    sleep 1
done

kiem_dau_do() {  # kiem_dau_do <tên> <User-Agent> <token giả> — 0 = đạt
    local ten="$1" ua="$2" gia="$3" dong r=0
    # Lọc dòng của đầu dò: grep KHÔNG -q nên đọc hết; rc 1 (0 dòng) là KẾT QUẢ,
    # rc ≥ 2 là LỖI — tách riêng, không gộp vào "không thấy".
    dong="$(grep -F -- "$ua" <<<"$NHAT_KY")" || r=$?
    if [ "$r" -ge 2 ]; then
        echo "  ✗ đầu dò token $ten: LỖI khi lọc access log (grep rc=$r)"
        return 1
    fi
    if [ -z "$dong" ]; then
        echo "  ✗ đầu dò token $ten: KHÔNG thấy dòng access log của request đầu dò (access_log off? log không ra stdout?)"
        return 1
    fi
    r=0; tim "$gia" "$NHAT_KY" || r=$?
    if [ "$r" -eq 0 ]; then
        echo "  ✗ đầu dò token $ten: access log LỘ token giả:"
        printf '%s\n' "$dong" | sed 's/^/      /'
        return 1
    elif [ "$r" -ne 1 ]; then
        echo "  ✗ đầu dò token $ten: LỖI khi tìm token giả trong access log — không kết luận được là không lộ"
        return 1
    fi
    r=0; tim "<redacted>" "$dong" || r=$?
    if [ "$r" -eq 1 ]; then
        echo "  ✗ đầu dò token $ten: dòng log của đầu dò không mang dấu <redacted> (khuôn log đã đổi?)"
        return 1
    elif [ "$r" -ne 0 ]; then
        echo "  ✗ đầu dò token $ten: LỖI khi tìm dấu <redacted> trong dòng của đầu dò"
        return 1
    fi
    echo "  ✓ đầu dò token $ten: có dòng access log, đã che, không lộ token giả"
    return 0
}

KQ_TOKEN=0
echo "--- đầu dò token trong access log ---"
if [ "$NHAT_KY_RC" -ne 0 ]; then
    echo "  ✗ đầu dò token: KHÔNG đọc được access log — docker logs rc=$NHAT_KY_RC (nguồn lỗi ⇒ ĐỎ dù có đầu ra)"
    KQ_TOKEN=1
fi
kiem_dau_do "đường dẫn" "$UA_P" "$GIA_P" || KQ_TOKEN=1
kiem_dau_do "query" "$UA_Q" "$GIA_Q" || KQ_TOKEN=1
kiem_dau_do "Referer" "$UA_R" "$GIA_R" || KQ_TOKEN=1

if [ "$KQ_CHUC_NANG" -eq 0 ] && [ "$KQ_TOKEN" -eq 0 ]; then
    exit 0
fi
echo "HỎNG — phép kiểm chức năng rc=$KQ_CHUC_NANG, đầu dò token rc=$KQ_TOKEN."
exit 1
