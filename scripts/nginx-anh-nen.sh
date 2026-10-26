#!/usr/bin/env bash
# =============================================================================
# QLTS — ảnh NỀN của nginx/Dockerfile: suy từ FROM, chuẩn bị TRƯỚC build
# =============================================================================
# Usage:
#   scripts/nginx-anh-nen.sh in        in `<ảnh>[:tag]@sha256:<64 hex>` của dòng FROM duy nhất
#   scripts/nginx-anh-nen.sh chuan-bi  bảo đảm ảnh nền CÓ trong image store, đúng digest
#
# Vì sao có script này (run 40184923904, 25-10-2026): Step 8b dừng ở cổng nội
# dung G1 của `nginx-apply.sh`. Chiều ngược của G1 cần `docker image inspect
# <ảnh nền>`, nhưng trên image store containerd, BuildKit kéo lớp của ảnh nền
# để build mà KHÔNG để lại ảnh mang đúng tên tham chiếu. Build thành công, ảnh
# P2 đúng cấu hình, vậy mà G1 không có gì để so ⇒ không áp được.
#
# G1 KHÔNG đổi: nó vẫn từ chối kéo mạng giữa lúc áp (một cổng không được phụ
# thuộc mạng). Việc kéo dời lên ĐÂY, và `deploy.sh` gọi nó ở Step 4, ngay
# TRƯỚC build — SAU kiểm lại HEAD và SAU tài sản rollback (3b), TRƯỚC khi dừng
# ứng dụng (4c). Hỏng ở đây thì chưa build, chưa dừng gì, chưa chạm CSDL (tài
# sản 3b, nếu đã tạo, giữ nguyên như khi build hỏng).
#
# Vì sao BẮT BUỘC digest: kéo theo tag trôi thì thứ G1 đem so là "ảnh nền hôm
# nay" chứ không phải ảnh đã dựng nên image đang áp — đúng lớp sai mà cổng tồn
# tại để chặn. Luật phân tích FROM giống `_anh_nen` của nginx-apply.sh (đúng MỘT
# FROM, dạng `FROM <ảnh>`); test khoá hai bộ phân tích cho cùng kết quả.
#
# Biến:
#   QLTS_NGINX_NEN_NGAN_SACH  ngân sách TỔNG của `chuan-bi`, giây (mặc định 300):
#                             MỌI lời gọi Docker — đọc trước, kéo, đọc lại — kể
#                             cả ân hạn `-k` của chúng, kết thúc trong đó.
#                             deploy.sh truyền min(300, hạn động của phiên)
#   QLTS_NGINX_NEN_HAN_PULL   trần riêng của `docker pull`, giây (mặc định 300);
#                             hạn thật = min(trần này, phần còn lại của ngân sách)
#   QLTS_NGINX_DOCKERFILE     đường Dockerfile (để test trỏ vào sân khấu);
#                             mặc định nginx/Dockerfile cạnh thư mục scripts/
#
# Mã: 0 đạt
#     1 FROM không hợp lệ (không ghim digest · nhiều FROM · có --platform / AS),
#       hoặc hạn/ngân sách không phải số giây
#     2 KHÔNG đọc được ảnh nền (lỗi Docker KHÁC "No such image") — KHÔNG kéo
#     3 `docker pull` hỏng hoặc hết hạn — rc ≠ 0 là hỏng, kể cả khi đã in
#       "Downloaded newer image"
#     4 có ảnh mang tên ấy nhưng KHÔNG mang đúng digest, hoặc sau khi kéo vẫn
#       không có
#     5 HẾT HẠN: một lần `docker image inspect` bị cắt vì hết hạn, hoặc ngân
#       sách không còn đủ để BẮT ĐẦU lời gọi kế tiếp — trạng thái ảnh nền CHƯA
#       BIẾT. KHÔNG phải "không có ảnh" (3/4) và không đi tiếp (F101)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_DOCKERFILE="${QLTS_NGINX_DOCKERFILE:-$SCRIPT_DIR/../nginx/Dockerfile}"
_HAN_PULL="${QLTS_NGINX_NEN_HAN_PULL:-300}"
_NGAN_SACH="${QLTS_NGINX_NEN_NGAN_SACH:-300}"
_HAN_DOC=30   # trần riêng của MỘT lần `docker image inspect` (đọc cục bộ, thường < 1 s)
_HET=""       # mốc SECONDS hết ngân sách — đặt khi `chuan-bi` bắt đầu

log() { printf '[NGINX-NEN] %s\n' "$1"; }
loi() { printf '[NGINX-NEN] ✗ %s\n' "$1" >&2; }

# Tham chiếu ảnh nền từ dòng FROM. Hai vế đầu là luật của `_anh_nen` trong
# nginx-apply.sh, nguyên văn về hành vi; vế digest là thứ script này thêm.
_tham_chieu() {
    local so dong
    so=$(grep -cE '^[[:space:]]*FROM[[:space:]]' "$_DOCKERFILE" 2>/dev/null || true)
    if [ "$so" != "1" ]; then
        loi "nginx/Dockerfile có ${so:-0} dòng FROM; chỉ mô hình hoá đúng MỘT"
        return 1
    fi
    dong=$(grep -E '^[[:space:]]*FROM[[:space:]]' "$_DOCKERFILE")
    dong="${dong%$'\r'}"
    set -f
    # shellcheck disable=SC2086
    set -- $dong
    set +f
    if [ "$#" -ne 2 ]; then
        loi "dòng FROM không phải dạng 'FROM <ảnh>' (có --platform hoặc AS?): $dong"
        return 1
    fi
    if ! [[ $2 =~ ^[^@[:space:]]+@sha256:[0-9a-f]{64}$ ]]; then
        loi "FROM không ghim digest: '$2' — cần dạng <ảnh>[:tag]@sha256:<64 hex>"
        return 1
    fi
    printf '%s\n' "$2"
}

# _han <trần riêng> <ân hạn -k> — in hạn cho MỘT lời gọi Docker = min(trần riêng,
# phần còn lại của ngân sách − ân hạn): lời gọi ấy, kể cả khi phải KILL sau
# `-k`, vẫn kết thúc trước hạn chót của bước. Còn chưa tới ân hạn + 1 s ⇒ trả 1,
# KHÔNG gọi. Không bao giờ in 0: `timeout 0` là TẮT hạn. SECONDS đếm giây
# nguyên ⇒ trễ < 1 s, nằm trong ân hạn 10 s deploy.sh giữ cho bước này.
_han() {
    local con=$(( _HET - SECONDS - $2 ))
    [ "$con" -ge 1 ] || return 1
    if [ "$1" -le "$con" ]; then printf '%s\n' "$1"; else printf '%s\n' "$con"; fi
}

# _co_mat <tham chiếu> <digest> <hạn giây> — rc 0 có VÀ mang đúng digest · 3
# daemon nói đúng "No such image" · 4 có nhưng không mang digest · 5 HẾT HẠN
# (trạng thái chưa biết) · 2 mọi lỗi đọc khác. Một lần đọc, CÓ HẠN (F101: đọc
# Docker treo trước đây vượt được ngân sách của bước), rc giữ riêng: rc ≠ 0 mà
# vẫn in ra thứ trông như một ID vẫn là LỖI, không phải "có". Đúng digest = ID
# bằng digest (store containerd: ID là digest của index) HOẶC một RepoDigest kết
# thúc bằng `@<digest>` (store cổ điển: ID là digest của config).
_co_mat() {
    local ra r id rd
    ra=$(timeout -k 2 "$3" docker image inspect -f '{{.Id}} {{join .RepoDigests " "}}' "$1" 2>&1) && r=0 || r=$?
    if [ "$r" != 0 ]; then
        # Xét hết hạn TRƯỚC: đầu ra dở dang của lời gọi bị cắt không phải câu trả lời.
        case "$r" in
            124|137) loi "docker image inspect HẾT HẠN sau ${3}s (rc=$r)"; return 5 ;;
        esac
        case "$ra" in *"No such image"*) return 3 ;; esac
        loi "docker image inspect rc=$r: ${ra:0:300}"
        return 2
    fi
    read -r id rd <<< "$ra"
    [[ $id =~ ^sha256:[0-9a-f]{64}$ ]] || { loi "ID ảnh nền không đúng dạng: '${id:0:80}'"; return 2; }
    [ "$id" = "$2" ] && return 0
    for r in $rd; do
        case "$r" in *"@$2") return 0 ;; esac
    done
    return 4
}

case "${1:-}" in
    in)
        _tham_chieu
        ;;
    chuan-bi)
        [[ $_HAN_PULL =~ ^[1-9][0-9]{0,4}$ ]] || { loi "QLTS_NGINX_NEN_HAN_PULL không phải số giây: '$_HAN_PULL'"; exit 1; }
        [[ $_NGAN_SACH =~ ^[1-9][0-9]{0,4}$ ]] || { loi "QLTS_NGINX_NEN_NGAN_SACH không phải số giây: '$_NGAN_SACH'"; exit 1; }
        _HET=$(( SECONDS + _NGAN_SACH ))
        nen=$(_tham_chieu) || exit 1
        dg="${nen##*@}"
        h=$(_han "$_HAN_DOC" 2) || { loi "HẾT NGÂN SÁCH bước (${_NGAN_SACH}s) trước khi đọc ảnh nền — DỪNG"; exit 5; }
        _co_mat "$nen" "$dg" "$h" && r=0 || r=$?
        case "$r" in
            0) log "ảnh nền $nen ĐÃ CÓ trong image store, đúng digest — không kéo"
               exit 0 ;;
            3) h=$(_han "$_HAN_PULL" 10) || {
                   loi "ảnh nền $nen CHƯA CÓ nhưng HẾT NGÂN SÁCH bước (${_NGAN_SACH}s) trước khi kéo (cần còn ≥ 11 s) — KHÔNG kéo, DỪNG"
                   exit 5
               }
               log "ảnh nền $nen CHƯA CÓ (No such image) — kéo theo digest, hạn ${h}s" ;;
            4) loi "có ảnh mang tên $nen nhưng KHÔNG mang digest $dg — không kéo đè, DỪNG"
               exit 4 ;;
            5) loi "HẾT HẠN khi đọc ảnh nền TRƯỚC khi kéo (ngân sách bước ${_NGAN_SACH}s) — trạng thái CHƯA BIẾT, KHÔNG phải 'không có ảnh'; KHÔNG kéo, DỪNG"
               exit 5 ;;
            *) loi "KHÔNG đọc được ảnh nền (lỗi Docker khác 'No such image') — KHÔNG kéo, DỪNG"
               exit 2 ;;
        esac
        timeout -k 10 "$h" docker pull "$nen" && r=0 || r=$?
        if [ "$r" != 0 ]; then
            loi "docker pull rc=$r (124 = hết hạn ${h}s) — HỎNG dù đầu ra đã in gì"
            exit 3
        fi
        h=$(_han "$_HAN_DOC" 2) || { loi "HẾT NGÂN SÁCH bước (${_NGAN_SACH}s) SAU khi kéo — CHƯA đọc lại được ảnh nền, DỪNG"; exit 5; }
        _co_mat "$nen" "$dg" "$h" && r=0 || r=$?
        if [ "$r" = 5 ]; then
            loi "HẾT HẠN khi đọc lại ảnh nền SAU khi kéo (ngân sách bước ${_NGAN_SACH}s) — CHƯA xác nhận có ảnh, KHÔNG phải 'không có ảnh'; DỪNG"
            exit 5
        fi
        if [ "$r" != 0 ]; then
            loi "sau khi kéo, ảnh nền vẫn không đạt (mã đọc $r: 3 vắng · 4 sai digest · 2 lỗi đọc) — DỪNG"
            exit 4
        fi
        log "✓ ảnh nền $nen có trong image store, đúng digest"
        ;;
    *)
        loi "dùng: $0 <in|chuan-bi>"
        exit 64
        ;;
esac
