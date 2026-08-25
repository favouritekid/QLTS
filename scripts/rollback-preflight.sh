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

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log() { echo -e "${GREEN}[ROLLBACK-PREFLIGHT]${NC} $1"; }
# `warn` từng được GỌI mà không được ĐỊNH NGHĨA: dưới `set -e` nhánh local-only
# chết bằng exit 127 trước khi kịp in gì. Không ai thấy vì nhánh ấy chưa từng
# được chạy — đúng loại đường thoát hiểm chỉ hỏng đúng lúc cần tới.
warn() { echo -e "${YELLOW}[WARN]${NC} $1" >&2; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; exit 1; }

# --- Tải bản kê offsite: nhận diện provider TỪ CHÍNH đường dẫn ---------------
#
# Vì sao không thêm biến `QLTS_OFFSITE_PROVIDER`: bản kê là thứ đi theo gói cứu
# hộ tới một máy trắng. Nếu provider nằm ở biến môi trường thì nó là mảnh thứ
# hai phải nhớ mang theo — và mảnh nào phải nhớ thì có ngày sẽ quên. Đường dẫn
# đã tự mô tả đủ: `s3://…` là AWS, `remote:path` là rclone.
#
# ⚠️ Thứ tự `case` là bản chất chứ không phải khẩu vị: `s3://x` cũng khớp mẫu
# `?*:*`, nên nếu để nhánh rclone trước thì mọi URL S3 sẽ bị gọi bằng rclone.
# Và `https://…` phải rơi vào "không nhận ra" chứ không được coi là rclone —
# đoán sai provider thì thông báo lỗi sẽ chỉ sai hướng đúng vào lúc 3 giờ sáng.
_OFFSITE_VI_SAO=""

_offsite_loai() {
    case "$1" in
        s3://*)  echo aws ;;
        *://*)   echo khong_ro ;;
        ?*:*)    echo rclone ;;
        *)       echo khong_ro ;;
    esac
}

_offsite_lay() {   # $1 = đường dẫn nguồn, $2 = tệp đích
    local loai
    loai=$(_offsite_loai "$1")
    case "$loai" in
        aws)
            if ! command -v aws >/dev/null 2>&1; then
                _OFFSITE_VI_SAO="Đường dẫn là S3 nhưng máy này KHÔNG có \`aws\`.
  Cài aws CLI, hoặc chuyển bản kê sang một remote rclone (§5.4), hoặc khai rủi
  ro tường minh bằng QLTS_ROLLBACK_LOCAL_ONLY=1 (mất máy = mất đường lùi)."
                return 3
            fi
            _OFFSITE_VI_SAO="Object không tồn tại, đã bị dọn, hoặc không có quyền đọc."
            aws s3 cp "$1" "$2" >/dev/null 2>&1
            ;;
        rclone)
            if ! command -v rclone >/dev/null 2>&1; then
                _OFFSITE_VI_SAO="Đường dẫn là remote rclone nhưng máy này KHÔNG có \`rclone\`.
  Cài rclone và khôi phục cấu hình remote, hoặc khai rủi ro tường minh bằng
  QLTS_ROLLBACK_LOCAL_ONLY=1 (mất máy = mất đường lùi)."
                return 3
            fi
            # `copyto` chứ không phải `copy`: `copy` coi đích là THƯ MỤC và giữ
            # nguyên tên nguồn, nên tệp sẽ nằm ở "$2/<tên gốc>" và mọi phép đọc
            # sau đó trượt — im lặng, vì bản thân lệnh vẫn trả 0.
            _OFFSITE_VI_SAO="Object không tồn tại trên remote, hoặc cấu hình rclone
  trên máy này không giải mã / không truy cập được remote đó."
            rclone copyto "$1" "$2" >/dev/null 2>&1
            ;;
        *)
            _OFFSITE_VI_SAO="Không nhận ra loại đường dẫn offsite: chỉ hỗ trợ \`s3://…\`
  (aws) hoặc \`<remote>:<đường dẫn>\` (rclone)."
            return 4
            ;;
    esac
}

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

# --- 1b. Revision git phải kiểm TẠI ĐÂY, không đợi tới lúc restore ----------
# §8.1 Step 5 mới `git checkout "$PRE_SHA" -- nginx/`, mà Step 5 chạy SAU
# `pg_restore --clean`. Manifest hỏng hay commit đã biến mất (rebase, prune,
# clone nông) thì ta chỉ biết khi CSDL đã bị phá — không tiến được, không lùi
# được. Kiểm ở đây, trước khi chạm bất cứ thứ gì.
PRE_SHA=$(awk -F'\t' '$1=="# git-rev"{print $2}' "$MANIFEST" | head -1)
[ -n "$PRE_SHA" ] || error "$MANIFEST thiếu dòng '# git-rev' — Step 5 sẽ không biết checkout về đâu"
printf '%s' "$PRE_SHA" | grep -qE '^[0-9a-f]{40}$' \
    || error "git-rev trong manifest không phải SHA đầy đủ 40 ký tự: '$PRE_SHA'"
git cat-file -e "${PRE_SHA}^{commit}" 2>/dev/null \
    || error "commit $PRE_SHA KHÔNG tồn tại trong repo này.
  Manifest trỏ tới một revision đã biến mất (rebase / prune / clone nông).
  DỪNG LẠI — chưa đụng gì tới CSDL."
git cat-file -e "${PRE_SHA}:nginx" 2>/dev/null \
    || error "commit $PRE_SHA không có thư mục nginx/ — không khôi phục được cấu hình nginx"
log "  ✓ git-rev $PRE_SHA tồn tại và có nginx/"

for S in "${DICH_VU[@]}"; do
    grep -qE "^${S}	" "$MANIFEST" \
        || error "$MANIFEST thiếu dòng cho service '$S' (phải đủ ${#DICH_VU[@]} service)"
done

# --- 2. Ảnh có mặt và ĐÚNG ID ----------------------------------------------
for S in "${DICH_VU[@]}"; do
    REF="qlts-${S}:${TAG}"
    ID_GHI=$(awk -F'\t' -v s="$S" '$1==s {print $3}' "$MANIFEST" | head -1)
    [ -n "$ID_GHI" ] || error "$MANIFEST không ghi image ID cho '$S'"

    # Ảnh CÓ TRÊN MÁY NÀY không chứng minh còn rollback được sau khi mất máy:
    # phép so ID luôn ĐẠT nếu tag vừa được tạo cục bộ ở §5.4, kể cả khi mọi
    # `docker push` đều hỏng.
    #
    # Và "tag có trên registry" cũng chưa đủ — tag ở xa có thể đã bị đẩy đè bởi
    # một ảnh KHÁC. Thứ duy nhất bất biến là DIGEST.
    #
    # Vì thế mọi lần lấy ảnh về đều đi BẰNG DIGEST. Bản trước còn `docker pull
    # "$REF"`: host bị prune + tag registry đã trôi thì nó kéo về ảnh MỚI rồi
    # dừng vì ID lệch — trong khi ảnh cũ vẫn nằm nguyên ở đó dưới digest cũ.
    # Câu "tag trôi thành không liên quan" chỉ đúng khi không còn chỗ nào hỏi
    # registry bằng tag nữa.
    if [ "${QLTS_ROLLBACK_LOCAL_ONLY:-0}" = "1" ]; then
        warn "$REF: BỎ QUA kiểm registry (QLTS_ROLLBACK_LOCAL_ONLY=1)."
        warn "   Ảnh chỉ có TRÊN MÁY NÀY. Mất máy / prune = KHÔNG rollback được."
        docker image inspect "$REF" >/dev/null 2>&1 \
            || error "$REF không có trên máy, mà QLTS_ROLLBACK_LOCAL_ONLY=1 cấm
  đi tìm ở registry. Không còn nguồn nào lấy được ảnh cũ.
  DỪNG LẠI — chưa đụng gì tới CSDL."
    else
        DIGEST=$(awk -F'\t' -v s="$S" '$1==s {print $5}' "$MANIFEST" | head -1)
        [ -n "$DIGEST" ] \
            || error "$MANIFEST không ghi digest cho '$S'.
  Không có digest thì không chứng minh được ảnh ở registry đúng là ảnh cũ.
  Chạy lại §5.4 (nó ghi digest sau mỗi lần push), hoặc khai rủi ro tường minh
  bằng QLTS_ROLLBACK_LOCAL_ONLY=1."
        case "$DIGEST" in
            *@sha256:*) ;;
            *) error "digest của '$S' sai định dạng (cần repo@sha256:…): '$DIGEST'" ;;
        esac

        # Repo phải có namespace. `qlts-backend@sha256:…` được Docker phân giải
        # thành `docker.io/library/qlts-backend` — kho ảnh thư viện chính thức,
        # không phải kho của dự án. Một manifest ghi ref như thế nghĩa là §5.4
        # đã chạy bằng bản cũ (chưa có QLTS_ROLLBACK_REGISTRY) và ảnh KHÔNG hề
        # nằm ở đâu ngoài máy này.
        REPO="${DIGEST%%@*}"
        case "$REPO" in
            docker.io/library/*)
                error "digest của '$S' trỏ vào kho thư viện chính thức: '$REPO'.
  Đó không phải kho của dự án. Chạy lại §5.4 với QLTS_ROLLBACK_REGISTRY." ;;
            */*) ;;
            *)
                error "digest của '$S' không có namespace: '$REPO'.
  Docker sẽ hiểu là 'docker.io/library/$REPO'. Ref trỏ kho riêng phải là
  'namespace/repo' hoặc 'registry/namespace/repo'. Chạy lại §5.4 với
  QLTS_ROLLBACK_REGISTRY." ;;
        esac

        docker manifest inspect "$DIGEST" >/dev/null 2>&1 \
            || error "KHÔNG phân giải được $DIGEST trên registry.
  Ảnh cũ của '$S' không còn ở ngoài máy — nhiều khả năng một lần \`docker push\`
  ở §5.4 đã hỏng, hoặc registry đã dọn. Rollback lúc này phụ thuộc hoàn toàn
  vào đĩa của máy chủ. DỪNG LẠI — chưa đụng gì tới CSDL."
        log "  ✓ $S: digest ${DIGEST##*@} có thật trên registry"

        # Thiếu ảnh, HOẶC tag cục bộ đã trôi sang ID khác: cả hai ca đều lấy lại
        # bằng digest rồi tự đóng lại tag mà `docker-compose.rollback.yml` ghim.
        if ! docker image inspect "$REF" >/dev/null 2>&1 \
           || [ "$(docker image inspect -f '{{.Id}}' "$REF")" != "$ID_GHI" ]; then
            log "  $REF thiếu hoặc đã trôi — kéo lại BẰNG DIGEST..."
            docker pull "$DIGEST" \
                || error "KHÔNG kéo được $DIGEST. DỪNG LẠI — chưa đụng gì tới CSDL."
            docker tag "$DIGEST" "$REF" \
                || error "KHÔNG gắn được tag $REF cho $DIGEST."
        fi
    fi

    docker image inspect "$REF" >/dev/null 2>&1 \
        || error "$REF vẫn không có trên máy sau mọi cách lấy.
  DỪNG LẠI — chưa đụng gì tới CSDL."
    ID_THAT=$(docker image inspect -f '{{.Id}}' "$REF")
    [ "$ID_THAT" = "$ID_GHI" ] \
        || error "$REF trỏ tới ảnh KHÁC với lúc tag.
    manifest: $ID_GHI
    hiện tại: $ID_THAT
  DỪNG LẠI — chưa đụng gì tới CSDL."
    log "  ✓ $REF khớp ID trong manifest"
done

# --- 2b. Bản kê phải TỒN TẠI NGOÀI MÁY --------------------------------------
# Ảnh ở registry mà bản kê chỉ nằm trên host thì mất host = còn ảnh nhưng không
# biết ảnh nào là đúng. Bản kê phải đi cùng gói backup offsite (§5.3).
if [ "${QLTS_ROLLBACK_LOCAL_ONLY:-0}" != "1" ]; then
    OFFSITE=$(awk -F'\t' '$1=="# offsite"{print $2}' "$MANIFEST" | head -1)
    [ -n "$OFFSITE" ] \
        || error "$MANIFEST chưa ghi dòng '# offsite' — bản kê chỉ tồn tại trên máy này.
  Mất máy thì còn ảnh trên registry nhưng KHÔNG biết digest nào là ảnh cũ.
  Chép bản kê vào gói backup offsite (§5.3) rồi ghi lại đường dẫn đó vào manifest."

    # --- 2b-i. "Đã push ảnh nhưng chưa lưu bản kê" KHÔNG được coi là ĐẠT ----
    #
    # Hai nửa của tài sản rollback phải đi cùng nhau. Nửa vời theo BẤT KỲ chiều
    # nào đều là bẫy:
    #   * có `# offsite` mà thiếu digest ⇒ bản kê ngoài máy trỏ tới những ảnh ta
    #     không chứng minh được là đã ở registry;
    #   * có digest mà thiếu `# offsite` ⇒ ảnh ở ngoài nhưng không ai biết digest
    #     nào là đúng sau khi mất máy.
    # Nhánh đầu đã được vế `[ -n "$OFFSITE" ]` ở trên bắt. Nhánh còn lại là đây.
    thieu_digest=()
    for S in "${DICH_VU[@]}"; do
        d=$(awk -F'\t' -v s="$S" '$1==s {print $5}' "$MANIFEST" | head -1)
        [ -n "$d" ] || thieu_digest+=("$S")
    done
    [ ${#thieu_digest[@]} -eq 0 ] \
        || error "$MANIFEST có dòng '# offsite' nhưng THIẾU digest cho: ${thieu_digest[*]}
  Đó là trạng thái nửa vời: bản kê đã ra ngoài máy trong khi ta không chứng minh
  được những ảnh ấy đã lên registry. Chạy lại §5.4 cho trọn, đừng vá tay bản kê.
  DỪNG LẠI — chưa đụng gì tới CSDL."

    # Một chuỗi đường dẫn không rỗng KHÔNG chứng minh gì cả: object có thể chưa
    # bao giờ được upload, đã bị lifecycle dọn, hoặc không đọc lại được (thiếu
    # quyền, sai KMS key, sai bucket). Phải TẢI VỀ và so NỘI DUNG.
    #
    # Provider suy từ CHÍNH đường dẫn trong bản kê, không từ một biến môi trường
    # thứ hai: bản kê là thứ đi theo gói cứu hộ, nên nó phải tự mô tả đủ để một
    # máy trắng đọc được. Thêm một biến nữa là thêm một thứ có thể quên mang theo.
    TMP_OFFSITE=$(mktemp -d)
    trap 'rm -rf "$TMP_OFFSITE"' EXIT

    _offsite_lay "$OFFSITE" "$TMP_OFFSITE/manifest.txt" \
        || error "KHÔNG tải được bản kê offsite: $OFFSITE
  $_OFFSITE_VI_SAO
  DỪNG LẠI — chưa đụng gì tới CSDL."
    _offsite_lay "${OFFSITE}.sha256" "$TMP_OFFSITE/manifest.sha256" \
        || error "KHÔNG tải được checksum đi kèm: ${OFFSITE}.sha256
  $_OFFSITE_VI_SAO
  §5.4 phải upload cả tệp .sha256 — không có nó thì bản tải về không kiểm được."

    SUM_THAT=$(sha256sum "$TMP_OFFSITE/manifest.txt" | awk '{print $1}')
    SUM_GHI=$(awk '{print $1}' "$TMP_OFFSITE/manifest.sha256" | head -1)
    [ "$SUM_THAT" = "$SUM_GHI" ] \
        || error "bản kê offsite KHÔNG khớp checksum của chính nó.
    ghi:      $SUM_GHI
    tải về:   $SUM_THAT
  Object đã hỏng hoặc bị ghi đè. DỪNG LẠI — chưa đụng gì tới CSDL."

    # Bản offsite phải TỰ ĐỦ: khôi phục nó về một máy trắng rồi chạy chính
    # script này phải ĐẠT. Bản nháp trước upload bản kê ở trạng thái CHƯA có
    # dòng '# offsite' (copy trước, append sau) — tức bản cứu hộ tự làm mình đỏ.
    cmp -s "$TMP_OFFSITE/manifest.txt" "$MANIFEST" \
        || error "bản kê offsite KHÁC bản trên máy.
  Thường là do §5.4 copy TRƯỚC khi ghi đủ metadata. Bản đưa ra ngoài phải là
  bản HOÀN CHỈNH, nếu không thì khôi phục từ nó rồi chạy preflight sẽ tự đỏ."

    log "  ✓ bản kê offsite tải được, khớp checksum và khớp bản local: $OFFSITE"
fi

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
