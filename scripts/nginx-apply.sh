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

# =============================================================================
# Cổng NỘI DUNG (G1) + cổng ĐỒNG NHẤT (G2)
# =============================================================================
# Khoảng trống mà hai cổng này đóng: script NÀY KHÔNG BUILD GÌ CẢ.
# `--profile candidate up -d --no-deps --force-recreate nginx-candidate` thay
# CONTAINER chứ không thay IMAGE, và `nginx` với `nginx-candidate` dùng chung
# đúng một tag (`qlts-nginx:local`, anchor `x-nginx-base`). Nên chuỗi này:
#     sửa nginx/templates/default.conf.template  →  bash scripts/nginx-apply.sh
# cho ra một candidate dựng từ ảnh CŨ, healthcheck xanh, `nginx-verify.sh` xanh
# (ảnh cũ phục vụ tốt — đó chính là vấn đề), rồi in "cấu hình mới đã được áp".
# Đường deploy chính build ở `scripts/deploy.sh` Step 7 nên không dính; hai
# người gọi KHÔNG qua build thì có: `scripts/setup-ssl.sh` và mọi lần gõ tay
# theo runbook.
#
# Chuỗi đúng là `Dockerfile COPY` → `compose build` → `compose up`: Compose
# recreate vì IMAGE ID đổi, không phải vì thấy tệp nguồn đổi.
#
# G1 so NGUỒN với BẢN TRONG CONTAINER ĐANG CHẠY ở đúng tầng mà COPY đặt chúng
# xuống — tức bản TRƯỚC render. `envsubst` của entrypoint chính thức biến
# `/etc/nginx/templates/*.template` thành `/etc/nginx/conf.d/*` (thay `${DOMAIN}`,
# `${NGINX_ADMISSION_FROZEN}`), nên so byte ở tầng `conf.d` là không thể. Ở tầng
# `/etc/nginx/templates/` thì `COPY` là phép chép NGUYÊN BYTE, so được chắc chắn.
#
# G1 đi CẢ HAI CHIỀU:
#   xuôi  nguồn → ảnh : mọi tệp nguồn phải có mặt trong ảnh, đúng từng byte;
#   ngược ảnh → nguồn : không tệp cấu hình QLTS nào được nằm lại trong ảnh sau
#                       khi đã bị xoá khỏi nguồn.
# Thiếu chiều ngược thì XOÁ một template khỏi nguồn mà chưa build lại sẽ lọt
# trọn vẹn: vòng duyệt chiều xuôi chỉ đi qua các tệp CÒN tồn tại ở nguồn, nên nó
# không thấy gì; entrypoint thì vẫn render tệp cũ trong ảnh thành
# `/etc/nginx/conf.d/*` và nginx vẫn `include` nó. Đúng lớp lỗi mà cổng này sinh
# ra để chặn, chỉ ở chiều ngược lại.
_HEX64='^[0-9a-f]{64}$'
_MOC_LIET_KE='__QLTS_HET__'
_GOC_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
_DOCKERFILE_NGINX="$_GOC_REPO/nginx/Dockerfile"

# Bảng suy TỪ CHÍNH `nginx/Dockerfile`, không chép tay (CLAUDE.md §6). Hai loại
# dòng, cùng một lần đọc — MỘT nguồn chuẩn cho cả hai chiều của cổng (§7):
#
#   F<TAB><nguồn tuyệt đối><TAB><đường trong container>   một tệp được COPY
#   D<TAB><thư mục trong container>                       một ĐÍCH dạng thư mục
#
# Dòng `D` phát cho MỌI `COPY` có `<đích>` kết thúc bằng `/`, kể cả khi nguồn là
# một tệp đơn (`COPY bootstrap/default.conf.template /etc/nginx/templates-bootstrap/`):
# thư mục ấy vẫn là nơi một tệp mồ côi có thể nằm lại và vẫn được envsubst render.
#
# Chỉ mô hình hoá dạng `COPY <nguồn> <đích>` hai tham số, không cờ, không ký tự
# đại diện. Gặp dạng khác thì TRẢ LỖI chứ không bỏ qua: một `COPY --chown=…` mới
# thêm mà cổng lặng lẽ không soi thì cổng ấy đang xanh giả.
_bang_tep_trong_anh() {
    local dong src dst nguon base f rel
    if [ ! -f "$_DOCKERFILE_NGINX" ]; then
        echo "không đọc được $_DOCKERFILE_NGINX" >&2
        return 1
    fi
    # `ADD` ghi vào ảnh y như `COPY` nhưng cổng không mô hình hoá nó ⇒ một
    # `ADD templates/ …` sẽ đi vòng qua toàn bộ cổng này mà không ai thấy.
    # Từ chối thẳng thay vì bỏ qua im lặng.
    if grep -qE '^[[:space:]]*ADD[[:space:]]' "$_DOCKERFILE_NGINX"; then
        echo "nginx/Dockerfile có lệnh ADD — cổng nội dung chỉ mô hình hoá COPY" >&2
        return 1
    fi
    while IFS= read -r dong; do
        dong="${dong%$'\r'}"
        set -f
        # shellcheck disable=SC2086
        set -- $dong
        set +f
        if [ "$#" -ne 3 ]; then
            echo "COPY không phải dạng <nguồn> <đích> hai tham số: $dong" >&2
            return 1
        fi
        src="$2"; dst="$3"
        case "$src$dst" in
            *'--'*|*'*'*|*'?'*|*'['*|*'$'*|*'|'*)
                echo "COPY mang cờ hoặc ký tự đại diện, cổng nội dung không mô hình hoá được: $dong" >&2
                return 1
                ;;
        esac
        case "$dst" in
            /*) ;;
            *) echo "COPY có đích không tuyệt đối: $dong" >&2; return 1 ;;
        esac
        case "$dst" in
            */) printf 'D\t%s\n' "$dst" ;;
        esac
        if [ "${src%/}" != "$src" ]; then
            case "$dst" in
                */) ;;
                *) echo "COPY thư mục nhưng đích không kết thúc bằng '/': $dong" >&2; return 1 ;;
            esac
            base="$_GOC_REPO/nginx/${src%/}"
            if [ ! -d "$base" ]; then
                echo "thiếu thư mục nguồn $base" >&2
                return 1
            fi
            while IFS= read -r f; do
                rel="${f#"$base"/}"
                printf 'F\t%s\t%s\n' "$f" "$dst$rel"
            done < <(find "$base" -type f | LC_ALL=C sort)
        else
            nguon="$_GOC_REPO/nginx/$src"
            if [ ! -f "$nguon" ]; then
                echo "thiếu tệp nguồn $nguon" >&2
                return 1
            fi
            case "$dst" in
                */) printf 'F\t%s\t%s\n' "$nguon" "$dst$(basename "$src")" ;;
                *)  printf 'F\t%s\t%s\n' "$nguon" "$dst" ;;
            esac
        fi
    done < <(grep -E '^[[:space:]]*COPY[[:space:]]' "$_DOCKERFILE_NGINX")
}

# Ảnh NỀN mà `nginx/Dockerfile` khai ở `FROM` — suy từ chính Dockerfile, cùng lý
# do như bảng COPY. Nhiều `FROM` (multi-stage) hay `FROM x AS y` thì cổng KHÔNG
# mô hình hoá được ⇒ TRẢ LỖI, không đoán.
_anh_nen() {
    local so dong
    so=$(grep -cE '^[[:space:]]*FROM[[:space:]]' "$_DOCKERFILE_NGINX" 2>/dev/null || true)
    if [ "$so" != "1" ]; then
        echo "nginx/Dockerfile có ${so:-0} dòng FROM; cổng chỉ mô hình hoá đúng MỘT" >&2
        return 1
    fi
    dong=$(grep -E '^[[:space:]]*FROM[[:space:]]' "$_DOCKERFILE_NGINX")
    dong="${dong%$'\r'}"
    set -f
    # shellcheck disable=SC2086
    set -- $dong
    set +f
    if [ "$#" -ne 2 ]; then
        echo "dòng FROM không phải dạng 'FROM <ảnh>' (có --platform hoặc AS?): $dong" >&2
        return 1
    fi
    printf '%s\n' "$2"
}

# Liệt kê tệp trong các thư mục ĐÍCH — kết bằng một MỐC.
#
# Vì sao phải có mốc: `docker exec`/`docker run` có thể trả 0 với đầu ra CỤT
# (mạng đứt giữa chừng, container bị giết). Một danh sách cụt trông y hệt một
# danh sách "không có tệp thừa nào" — tức lỗi đọc hoá thành "đạt". Thiếu mốc
# ⇒ ĐỎ.
_liet_ke_trong_container() {
    local cid="$1"; shift
    docker exec "$cid" sh -c \
        'for d in "$@"; do find "$d" -type f 2>/dev/null; done; echo '"$_MOC_LIET_KE" \
        sh "$@" 2>/dev/null
}

# Ảnh nền phải CÓ SẴN cục bộ — `_cong_noi_dung` kiểm bằng `docker image inspect`
# TRƯỚC khi gọi hàm này. `docker run` trên một tag vắng mặt sẽ đi KÉO TỪ MẠNG
# giữa lúc deploy, biến cổng thành phụ thuộc mạng.
_liet_ke_trong_anh_nen() {
    local nen="$1"; shift
    docker run --rm --entrypoint sh "$nen" -c \
        'for d in "$@"; do find "$d" -type f 2>/dev/null; done; echo '"$_MOC_LIET_KE" \
        sh "$@" 2>/dev/null
}

# Thư mục ĐÍCH mà CHÍNH ẢNH ĐANG CHẠY đã được COPY vào — đọc từ lịch sử build
# của nó, không từ `nginx/Dockerfile` hiện tại.
#
# Vì sao cần: `_bang_tep_trong_anh` chỉ phát dòng `D` cho các `COPY` CÒN TRONG
# Dockerfile. Xoá HẲN một dòng `COPY` (khác với xoá tệp nguồn) thì thư mục đích
# của nó biến mất khỏi tập cần soi ⇒ chiều ngược không bao giờ nhìn vào đó ⇒
# tệp cũ còn trong ảnh vẫn được entrypoint render/thi hành mà cổng vẫn xanh.
# Tập thư mục phải KHÔNG CO LẠI khi một dòng COPY biến mất.
#
# Ảnh mang sẵn câu trả lời: `docker history` in nguyên văn từng `COPY` đã dựng
# nên nó. Phần của ảnh NỀN nằm ở ĐUÔI và trùng khít lịch sử của chính ảnh nền,
# nên phần RIÊNG của QLTS = lịch sử ảnh trừ đi đuôi ấy. Không chép tay đường dẫn
# nào, và tự động đúng cho mọi `COPY` thêm về sau.
#
# Đuôi KHÔNG trùng ⇒ ảnh nền cục bộ không phải bản đã dựng ra ảnh này ⇒ cả phép
# trừ tập nền lẫn phép suy thư mục cũ đều mất cơ sở ⇒ TRẢ LỖI (fail-closed),
# không đoán.
_thu_muc_copy_trong_lich_su() {
    local anh="$1" nen="$2" ls_anh ls_nen so_anh so_nen duoi rieng dong dst
    ls_anh=$(docker history --no-trunc --format '{{.CreatedBy}}' "$anh" 2>/dev/null) || return 1
    ls_nen=$(docker history --no-trunc --format '{{.CreatedBy}}' "$nen" 2>/dev/null) || return 1
    [ -n "$ls_anh" ] && [ -n "$ls_nen" ] || return 1
    so_anh=$(printf '%s\n' "$ls_anh" | wc -l)
    so_nen=$(printf '%s\n' "$ls_nen" | wc -l)
    [ "$so_anh" -gt "$so_nen" ] || return 1
    duoi=$(printf '%s\n' "$ls_anh" | tail -n "$so_nen")
    [ "$duoi" = "$ls_nen" ] || return 1
    rieng=$(printf '%s\n' "$ls_anh" | head -n "$((so_anh - so_nen))")
    # Không một dòng `COPY ` nào trong phần riêng ⇒ ta KHÔNG đọc được định dạng
    # lịch sử (builder cổ ghi `/bin/sh -c #(nop) COPY dir:<hash> in <đích>`),
    # chứ không phải "ảnh này không COPY gì". Hai ca ấy trông giống hệt nhau và
    # ca sau là điểm mù — nên TRẢ LỖI thay vì trả về tập rỗng.
    if ! printf '%s\n' "$rieng" | grep -q '^COPY '; then
        return 1
    fi
    while IFS= read -r dong; do
        case "$dong" in
            COPY\ *) ;;
            *) continue ;;
        esac
        dong="${dong% # buildkit}"
        set -f
        # shellcheck disable=SC2086
        set -- $dong
        set +f
        [ "$#" -ge 3 ] || continue
        dst="${!#}"
        case "$dst" in
            /) continue ;;
            */) printf '%s\n' "$dst" ;;
        esac
    done <<< "$rieng"
}

# G1 — cổng NỘI DUNG. Mọi nhánh hỏng đều ĐỎ: không đọc được Dockerfile, bảng
# rỗng, không đọc được checksum ở một trong hai phía, hay checksum lệch. KHÔNG
# có nhánh nào biến "không đo được" thành "đạt" — đó đúng là lớp sai mà cả tệp
# này ra đời để đóng.
#
# CHIỀU NGƯỢC — phân biệt "tệp của QLTS" với "tệp của ảnh nền" thế nào
# --------------------------------------------------------------------------
# `/etc/nginx/templates/` và `/etc/nginx/templates-bootstrap/` là phát minh của
# ta (đo trên `nginx:1.27-alpine`: cả hai KHÔNG tồn tại), nhưng
# `/docker-entrypoint.d/` thì ảnh nền đã có sẵn bốn script chính thức. So NGUYÊN
# TẬP thư mục ở đó sẽ đỏ vĩnh viễn, nên cũng vô dụng như không so.
#
# Cách phân biệt: tập "thuộc QLTS" = (tệp trong ảnh) trừ (tệp có trong ẢNH NỀN),
# với ảnh nền lấy từ chính dòng `FROM` của `nginx/Dockerfile` — suy ra, không
# chép tay một danh sách bốn script (danh sách ấy sẽ trôi ngay lần nâng nginx
# kế tiếp; đo hôm nay đã cho `15-local-resolvers.envsh` và
# `10-listen-on-ipv6-by-default.sh`, không phải những cái tên người ta hay đoán).
#
# Tag `FROM` có thể đã trôi so với lúc build. Hai chiều trôi, cả hai đều AN TOÀN:
#   * nền có THÊM tệp  ⇒ tệp ấy không nằm trong ảnh ta, trừ đi vô hại;
#   * nền MẤT tệp      ⇒ tệp nền còn trong ảnh ta bị kêu là mồ côi ⇒ ĐỎ OAN.
# Để lọt một tệp mồ côi thì ảnh nền phải mọc ra đúng một tệp trùng tên với tệp
# QLTS vừa bị xoá. Chiều nguy hiểm không mở.
_cong_noi_dung() {
    local cid="$1" bang so=0 hong=0 loai nguon dich
    local hh hc nen dich_tm=() cho_phep="|" ds_anh ds_nen f thua=""
    local anh_ref roots_anh r d co
    if [ -z "$cid" ]; then
        log "  cổng nội dung: không có container để soi"
        return 1
    fi
    if ! bang=$(_bang_tep_trong_anh); then
        log "  cổng nội dung: không dựng được bảng tệp từ nginx/Dockerfile"
        return 1
    fi
    if [ -z "$bang" ]; then
        log "  cổng nội dung: nginx/Dockerfile không có COPY nào — cổng sẽ xanh vô nghĩa"
        return 1
    fi

    # --- chiều XUÔI: nguồn → ảnh ------------------------------------------
    while IFS=$'\t' read -r loai nguon dich; do
        if [ "$loai" = "D" ]; then
            # dòng thư mục: `nguon` giữ đường trong container, không có `dich`
            [ -n "$nguon" ] || { log "  cổng nội dung: dòng thư mục hỏng"; return 1; }
            dich_tm+=("$nguon")
            continue
        fi
        if [ "$loai" != "F" ] || [ -z "$nguon" ] || [ -z "$dich" ]; then
            log "  cổng nội dung: dòng bảng hỏng"
            return 1
        fi
        so=$((so + 1))
        cho_phep="$cho_phep$dich|"
        hh=$(sha256sum "$nguon" 2>/dev/null | cut -d' ' -f1) || hh=""
        hc=$(docker exec "$cid" sha256sum "$dich" 2>/dev/null | cut -d' ' -f1) || hc=""
        if ! printf '%s' "$hh" | grep -Eq "$_HEX64"; then
            log "  ✗ không đọc được checksum NGUỒN: $nguon"
            hong=$((hong + 1)); continue
        fi
        if ! printf '%s' "$hc" | grep -Eq "$_HEX64"; then
            log "  ✗ không đọc được checksum TRONG container ($cid): $dich"
            hong=$((hong + 1)); continue
        fi
        if [ "$hh" != "$hc" ]; then
            log "  ✗ LỆCH: $nguon ($hh)"
            log "         ≠ $dich ($hc)"
            hong=$((hong + 1))
        fi
    done <<< "$bang"
    if [ "$so" -eq 0 ]; then
        log "  cổng nội dung: 0 tệp được đối chiếu"
        return 1
    fi

    # --- chiều NGƯỢC: ảnh → nguồn -----------------------------------------
    if ! nen=$(_anh_nen); then
        log "  cổng nội dung: không suy được ảnh nền từ dòng FROM của nginx/Dockerfile"
        return 1
    fi
    if ! docker image inspect "$nen" >/dev/null 2>&1; then
        log "  cổng nội dung: ảnh nền '$nen' KHÔNG có sẵn cục bộ."
        log "                 Từ chối ở đây thay vì để docker run đi kéo từ mạng — chạy compose build trước."
        return 1
    fi

    # Tập thư mục cần soi = HỢP của (Dockerfile HIỆN TẠI) và (lịch sử của CHÍNH
    # ẢNH đang chạy). Chỉ lấy vế đầu thì xoá hẳn một dòng COPY là thư mục ấy
    # lặng lẽ rơi khỏi tầm soi — xem hợp đồng ở `_thu_muc_copy_trong_lich_su`.
    anh_ref=$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null) || anh_ref=""
    if [ -z "$anh_ref" ]; then
        log "  cổng nội dung: không đọc được ảnh của container $cid"
        return 1
    fi
    if ! roots_anh=$(_thu_muc_copy_trong_lich_su "$anh_ref" "$nen"); then
        log "  cổng nội dung: không suy được tập thư mục CŨ từ lịch sử build của ảnh."
        log "                 (lịch sử không đọc được, hoặc ảnh nền cục bộ không phải bản đã dựng ra ảnh này)"
        return 1
    fi
    while IFS= read -r r; do
        [ -n "$r" ] || continue
        co=0
        for d in "${dich_tm[@]}"; do
            if [ "$d" = "$r" ]; then co=1; break; fi
        done
        [ "$co" = "1" ] || dich_tm+=("$r")
    done <<< "$roots_anh"

    if [ "${#dich_tm[@]}" -eq 0 ]; then
        log "  cổng nội dung: không có thư mục đích nào để soi chiều ngược"
        return 1
    fi
    if ! ds_anh=$(_liet_ke_trong_container "$cid" "${dich_tm[@]}"); then
        log "  cổng nội dung: không liệt kê được thư mục đích trong container $cid"
        return 1
    fi
    if ! printf '%s\n' "$ds_anh" | grep -qxF "$_MOC_LIET_KE"; then
        log "  cổng nội dung: danh sách tệp trong container CỤT (thiếu mốc kết) — coi như không đọc được"
        return 1
    fi
    if ! ds_nen=$(_liet_ke_trong_anh_nen "$nen" "${dich_tm[@]}"); then
        log "  cổng nội dung: không liệt kê được tệp trong ảnh nền '$nen'"
        return 1
    fi
    if ! printf '%s\n' "$ds_nen" | grep -qxF "$_MOC_LIET_KE"; then
        log "  cổng nội dung: danh sách tệp của ảnh nền CỤT (thiếu mốc kết) — coi như không đọc được"
        return 1
    fi
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        [ "$f" != "$_MOC_LIET_KE" ] || continue
        case "$f" in
            *'|'*|*'*'*|*'?'*|*'['*)
                log "  ✗ đường dẫn trong ảnh mang ký tự cổng không so được: $f"
                hong=$((hong + 1)); continue
                ;;
        esac
        # thuộc ảnh nền ⇒ không phải tệp cấu hình của QLTS
        if printf '%s\n' "$ds_nen" | grep -qxF "$f"; then continue; fi
        # có trong bảng COPY ⇒ đã đối chiếu ở chiều xuôi
        case "$cho_phep" in *"|$f|"*) continue ;; esac
        log "  ✗ MỒ CÔI: $f còn trong ảnh nhưng KHÔNG còn ở cây nguồn"
        thua="$thua$f "
        hong=$((hong + 1))
    done <<< "$ds_anh"
    if [ -n "$thua" ]; then
        log "  cổng nội dung: tệp mồ côi vẫn được entrypoint render/thi hành: $thua"
    fi

    if [ "$hong" -ne 0 ]; then
        log "  cổng nội dung: $hong lỗi trên $so tệp nguồn + ${#dich_tm[@]} thư mục đích"
        return 1
    fi
    log "  cổng nội dung: $so/$so tệp khớp nguồn, ${#dich_tm[@]} thư mục đích không có tệp mồ côi"
    return 0
}

# Image ID BẤT BIẾN của container. KHÔNG `{{.Config.Image}}`: cái đó trả về
# TÊN:TAG mà container được yêu cầu chạy, và `nginx` với `nginx-candidate` mang
# chung một tag — nên so hai `.Config.Image` luôn khớp kể cả khi tag đã trôi
# sang một bản build khác giữa hai lần đọc. `{{.Image}}` là `sha256:…` của bản
# ảnh container đang THỰC SỰ chạy.
_anh_cua() {
    local cid="$1" id
    [ -n "$cid" ] || return 1
    id=$(docker inspect -f '{{.Image}}' "$cid" 2>/dev/null) || return 1
    case "$id" in
        sha256:*)
            printf '%s' "$id" | grep -Eq '^sha256:[0-9a-f]{64}$' || return 1
            printf '%s\n' "$id"
            ;;
        *) return 1 ;;
    esac
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
[ -n "$_CID_CANDIDATE" ] || error "không lấy được container id của nginx-candidate"

# --- Cổng NỘI DUNG (G1), TRƯỚC phép đo hành vi -------------------------------
# Đặt trước `nginx-verify.sh` vì ca "template mới chưa vào image" là ca mà phép
# đo hành vi KHÔNG THỂ thấy: ảnh cũ phục vụ hoàn hảo, cả sáu phép kiểm đều xanh.
# Đo trước thì hỏng dừng sớm và thông điệp nói đúng nguyên nhân.
log "đối chiếu nội dung trong candidate với nguồn sẽ được áp..."
if ! _cong_noi_dung "$_CID_CANDIDATE"; then
    _nhat_ky nginx-candidate
    error "candidate KHÔNG mang cấu hình của cây nguồn hiện tại — script này không build.
       Dựng lại ảnh rồi chạy lại:
         docker compose -f docker-compose.yml --env-file \"$_ENV_FILE\" build nginx
         bash scripts/nginx-apply.sh \"$DOMAIN\"
       Container đang phục vụ CHƯA bị đụng tới."
fi

if ! bash "$SCRIPT_DIR/nginx-verify.sh" "$_CID_CANDIDATE" "$DOMAIN"; then
    _nhat_ky nginx-candidate
    error "cấu hình mới không phục vụ được — KHÔNG thay container đang phục vụ (last-good vẫn chạy)"
fi

# Ghim ảnh ĐÃ ĐƯỢC CHỨNG MINH — phải đọc TRƯỚC `_don_candidate`, vì sau đó
# container không còn để hỏi.
_ANH_DA_CHUNG_MINH=$(_anh_cua "$_CID_CANDIDATE") \
    || error "không đọc được image id bất biến của candidate — từ chối cutover khi không biết vừa chứng minh cho ảnh nào"

log "candidate đạt ($_ANH_DA_CHUNG_MINH) — chuyển sang container đang phục vụ"
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
[ -n "$_CID_NGINX" ] || error "không lấy được container id của nginx đang phục vụ"

# --- Cổng ĐỒNG NHẤT (G2) ----------------------------------------------------
# Candidate đã chứng minh cho MỘT bản ảnh cụ thể. Câu hỏi còn lại: container
# đang phục vụ có đang chạy ĐÚNG bản ảnh ấy không?
#
# So bằng `{{.Image}}` (sha256 bất biến), KHÔNG bằng `{{.Config.Image}}`: hai
# service dùng chung tag `qlts-nginx:local`, nên so theo tên:tag là so một
# hằng số với chính nó — luôn khớp, kể cả khi `up -d` không recreate gì và
# container đang phục vụ vẫn giữ bản ảnh của lần deploy trước.
_ANH_DANG_PHUC_VU=$(_anh_cua "$_CID_NGINX") \
    || error "không đọc được image id bất biến của nginx đang phục vụ — KHÔNG tuyên bố deploy thành công"
if [ "$_ANH_DANG_PHUC_VU" != "$_ANH_DA_CHUNG_MINH" ]; then
    _nhat_ky nginx
    error "nginx đang phục vụ BẢN ẢNH KHÁC với bản đã được chứng minh:
       đã chứng minh : $_ANH_DA_CHUNG_MINH
       đang phục vụ  : $_ANH_DANG_PHUC_VU
       Lệnh 'up -d' đã không recreate container. Đừng tuyên bố cấu hình mới đã được áp."
fi

if ! bash "$SCRIPT_DIR/nginx-verify.sh" "$_CID_NGINX" "$DOMAIN"; then
    _nhat_ky nginx
    error "nginx đang chạy nhưng KHÔNG phục vụ đúng — xem log phía trên"
fi
log "nginx healthy, chạy đúng ảnh đã chứng minh ($_ANH_DANG_PHUC_VU), và đã được đo bằng request thật — cấu hình mới đã được áp"
