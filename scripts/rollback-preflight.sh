#!/usr/bin/env bash
# =============================================================================
# QLTS — kiểm TÀI SẢN ROLLBACK trước khi chạm vào bất cứ thứ gì
# =============================================================================
# Usage: QLTS_ROLLBACK_TAG=pre-admission-cutover-20260501 scripts/rollback-preflight.sh
#
# Vì sao script này tồn tại (RUNBOOK §8.1, sửa 13-08-2026)
# --------------------------------------------------------
# Trình tự rollback cũ khôi phục CSDL TRƯỚC rồi mới đi tìm ảnh cũ. Nếu ảnh
# không còn trên máy — registry đã dọn, tag đã trôi, máy đã prune — thì lúc phát
# hiện ra, CSDL đã bị `pg_restore --clean` xoá và nạp lại bản cũ, còn mã đang
# chạy vẫn là mã MỚI. Đó là trạng thái tệ nhất có thể: không tiến được, không
# lùi được.
#
# Phép kiểm cũ cũng không phải phép kiểm:
#   * `docker pull ... || echo "DUNG LAI"` trả exit 0. Nó IN ra chữ "dừng lại"
#     rồi chạy tiếp.
#   * `config | grep -E 'image: qlts-(backend|celery-worker|celery-beat|frontend):'`
#     xanh khi chỉ MỘT trong bốn dòng khớp, và không nói gì về việc `build:` đã
#     biến mất hay chưa.
#
# Script này fail-closed ở mọi bước và chạy TRƯỚC khi CSDL bị đụng tới.
# =============================================================================
set -euo pipefail

export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
log() { echo -e "${GREEN}[ROLLBACK-PREFLIGHT]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }

TAG="${QLTS_ROLLBACK_TAG:?dat QLTS_ROLLBACK_TAG = tag da ghi o RUNBOOK 5.4}"
ENV_FILE="${QLTS_COMPOSE_ENV_FILE:-.env.production}"
read -r -a _EXTRA <<< "${QLTS_COMPOSE_EXTRA:-}"

DICH_VU=(backend celery-worker celery-beat frontend)
MANIFEST="${QLTS_ROLLBACK_MANIFEST:-rollback_manifest_${TAG}.txt}"

log "tag = $TAG"
log "manifest = $MANIFEST"

# --- 1. Manifest ------------------------------------------------------------
# Manifest ghi ID ảnh của container ĐANG CHẠY lúc T-1d, không phải một tag di
# động. Tag `:latest` có thể đã trôi sang bản khác giữa lúc tag và lúc rollback;
# ID ảnh thì không.
[ -f "$MANIFEST" ] || error "thiếu $MANIFEST — không có bằng chứng ảnh nào là ảnh cũ"

for S in "${DICH_VU[@]}"; do
    grep -qE "^${S}	" "$MANIFEST" \
        || error "$MANIFEST thiếu dòng cho service '$S' (phải đủ ${#DICH_VU[@]} service)"
done

# --- 2. Ảnh có mặt và ĐÚNG ID ----------------------------------------------
for S in "${DICH_VU[@]}"; do
    REF="qlts-${S}:${TAG}"
    ID_GHI=$(awk -F'\t' -v s="$S" '$1==s {print $3}' "$MANIFEST" | head -1)
    [ -n "$ID_GHI" ] || error "$MANIFEST không ghi image ID cho '$S'"

    if ! docker image inspect "$REF" >/dev/null 2>&1; then
        log "  $REF chưa có trên máy — thử pull..."
        docker pull "$REF" \
            || error "KHÔNG lấy được $REF. DỪNG LẠI — chưa đụng gì tới CSDL."
    fi

    ID_THAT=$(docker image inspect -f '{{.Id}}' "$REF")
    [ "$ID_THAT" = "$ID_GHI" ] \
        || error "$REF trỏ tới ảnh KHÁC với lúc tag.
    manifest: $ID_GHI
    hiện tại: $ID_THAT
  Tag đã trôi. DỪNG LẠI — chưa đụng gì tới CSDL."

    # Ảnh CÓ TRÊN MÁY NÀY không chứng minh còn rollback được sau khi mất máy.
    # Phép kiểm ở trên luôn ĐẠT nếu tag vừa được tạo cục bộ ở §5.4 — kể cả khi
    # mọi `docker push` đều hỏng. Hỏi thẳng registry bằng `manifest inspect`
    # (không tải ảnh về) mới biết tài sản có thật ở ngoài máy hay không.
    if [ "${QLTS_ROLLBACK_LOCAL_ONLY:-0}" = "1" ]; then
        warn "  ⚠ $REF: BỎ QUA kiểm registry (QLTS_ROLLBACK_LOCAL_ONLY=1) —"
        warn "     ảnh chỉ có TRÊN MÁY NÀY. Mất máy hoặc prune = KHÔNG rollback được."
    else
        docker manifest inspect "$REF" >/dev/null 2>&1 \
            || error "$REF KHÔNG có trên registry (chỉ tồn tại cục bộ).
  Nhiều khả năng một lần \`docker push\` ở RUNBOOK §5.4 đã hỏng mà bị nuốt.
  Rollback lúc này phụ thuộc hoàn toàn vào đĩa của máy chủ.
  Đẩy lại ảnh, hoặc chấp nhận rủi ro tường minh bằng QLTS_ROLLBACK_LOCAL_ONLY=1."
        log "  ✓ $REF có trên registry"
    fi
    log "  ✓ $REF khớp ID trong manifest"
done

# --- 3. Model Compose chọn ĐÚNG bốn ảnh ấy ---------------------------------
# `config --images` trả về đúng danh sách ảnh mà `up` sẽ dùng, nên không cần
# parse YAML: service nào còn `build:` mà thiếu `image:` sẽ hiện ra dưới tên mặc
# định `<project>-<service>` chứ không phải ref đã ghim.
ANH=$(docker compose -f docker-compose.yml -f docker-compose.rollback.yml \
    --env-file "$ENV_FILE" "${_EXTRA[@]}" --profile production config --images) \
    || error "không render được model Compose kèm docker-compose.rollback.yml"

for S in "${DICH_VU[@]}"; do
    REF="qlts-${S}:${TAG}"
    echo "$ANH" | grep -qxF "$REF" \
        || error "model Compose KHÔNG chọn $REF cho '$S'.
  Ảnh đang được chọn: $(echo "$ANH" | tr '\n' ' ')
  DỪNG LẠI — chưa đụng gì tới CSDL."
done
log "  ✓ model Compose chọn đủ ${#DICH_VU[@]} ảnh cũ"

# --- 4. Không service nào còn dựng lại từ mã MỚI ---------------------------
for S in "${DICH_VU[@]}"; do
    grep -qE "^\s+build: !reset null" <(awk -v s="  ${S}:" '
        $0==s {trong=1; next}
        /^  [a-z]/ {trong=0}
        trong {print}
    ' docker-compose.rollback.yml) \
        || error "docker-compose.rollback.yml: '$S' thiếu \`build: !reset null\` — \`up\` có thể dựng lại từ mã MỚI"
done
log "  ✓ cả ${#DICH_VU[@]} service đã gỡ \`build:\`"

log "ĐẠT — tài sản rollback sẵn sàng. Từ đây mới được chạm tới CSDL."
