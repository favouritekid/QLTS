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

# --- Có CẤU HÌNH CREDENTIAL cho registry này không? ---------------------------
#
# Vì sao cần: package rollback của QLTS là PRIVATE trên GHCR. Chưa xác thực thì
# `docker manifest inspect` trả về CÙNG MỘT lỗi cho hai tình huống ngược hẳn
# nhau — "ảnh đã bị dọn mất" và "ảnh còn nguyên, chỉ là chưa đăng nhập".
# Gộp hai ca đó vào một thông báo là đẩy người trực lúc 3 giờ sáng tới kết luận
# tệ nhất có thể ("mất đường lùi") trong khi tài sản vẫn còn đủ.
#
# ⚠️ TÊN HÀM LÀ MỘT LỜI HỨA. Hàm này KHÔNG chứng minh "đã đăng nhập hợp lệ" — nó
# chỉ đọc `config.json` và trả lời "có cấu hình credential cho host này không".
# Token có thể đã hết hạn, thiếu scope `read:packages`, hoặc bị thu hồi; cả ba
# vẫn để lại nguyên khoá trong `auths`. Bản nháp đầu đặt tên `_da_dang_nhap` rồi
# suy ra "có khoá ⇒ đã đăng nhập ⇒ inspect hỏng nghĩa là ảnh mất" — tức tái tạo
# đúng kết luận sai mà cả phép kiểm này sinh ra để loại bỏ.
#
# Chỉ đọc tệp, không gọi mạng: phải chạy được cả khi registry đang sập.
_co_cau_hinh_credential() {   # $1 = registry host, vd ghcr.io
    local cfg="${DOCKER_CONFIG:-$HOME/.docker}/config.json"
    [ -f "$cfg" ] || return 1

    # ⚠️ `command -v python3` KHÔNG chứng minh python3 chạy được: trên Windows nó
    # trỏ tới stub Microsoft Store, có mặt trong PATH nhưng in "Python was not
    # found" và không thực thi gì. Phải thử chạy thật rồi mới tin.
    if python3 -c "pass" >/dev/null 2>&1; then
        python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    # Config KHÔNG ĐỌC ĐƯỢC: mã thoát 2 = 'không biết', khác hẳn 1 = 'chắc chắn
    # không có credential'. Gộp hai ca này là fail-open: một config.json hỏng sẽ
    # được đọc thành 'chưa đăng nhập' và che mất chính lỗi cần sửa.
    sys.exit(2)
host = sys.argv[2]
if not isinstance(d, dict):
    sys.exit(2)
co = (host in (d.get('auths') or {})
      or host in (d.get('credHelpers') or {})
      or bool(d.get('credsStore')))   # store toàn cục: credential nằm NGOÀI tệp
sys.exit(0 if co else 1)
" "$cfg" "$1" 2>/dev/null
        return $?
    fi

    # Fallback không cần python. Quét cả tệp chứ không riêng khối `auths`:
    # credential có thể nằm ở `credHelpers`/`credsStore` thay vì `auths`.
    grep -q "\"$1\"[[:space:]]*:" "$cfg" && return 0
    grep -q '"credsStore"[[:space:]]*:' "$cfg" && return 0

    # KHÔNG tìm thấy ⇒ trả 2 ("không biết"), KHÔNG trả 1 ("chắc chắn chưa cấu
    # hình"). `grep` không phân biệt được "JSON hợp lệ và thật sự không có
    # credential" với "JSON hỏng nên chuỗi không khớp". Nhận vơ chắc chắn ở đây
    # là fail-open: người trực sẽ đi đăng nhập lại trong khi lỗi thật là config
    # hỏng, và vòng lặp đó không bao giờ thoát.
    return 2
}

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

        # Chưa đăng nhập là ca RIÊNG, không được gộp vào "ảnh đã mất".
        # Package rollback là PRIVATE: chưa xác thực thì MỌI digest đều
        # "không phân giải được", kể cả ảnh còn nguyên vẹn trên registry.
        if ! docker manifest inspect "$DIGEST" >/dev/null 2>&1; then
            _REG="${REPO%%/*}"

            # Lệnh gợi ý xây bằng SINGLE QUOTES rồi mới ghép biến. Nhúng thẳng
            # vào chuỗi thông báo (double-quoted) là đi qua hai lớp escape, và
            # bản nháp đầu đã in ra `echo "\$PAT"` — người trực copy vào chạy sẽ
            # gửi CHUỖI `$PAT` làm mật khẩu, không phải token. Lệnh cứu hộ in sai
            # còn tệ hơn không in gì: nó thất bại theo cách trông như đã làm đúng.
            #
            # `printf %s` chứ không `echo`: `echo` của một số shell diễn giải
            # dấu gạch chéo ngược, làm hỏng token chứa chúng.
            # Tên tài khoản suy TỪ CHÍNH digest: `ghcr.io/<ns>/qlts-backend`
            # ⇒ `<ns>`. Placeholder kiểu `-u <user>` KHÔNG copy-paste được: bash
            # đọc `<` là chuyển hướng nhập, nên người trực nhận lỗi
            # "No such file or directory" thay vì một lệnh chạy được. Đã đo.
            _NS="${REPO#*/}"; _NS="${_NS%%/*}"
            # Lệnh phải FAIL-CLOSED. Hai bản trước đều không:
            #   `…; unset PAT`                      → unset luôn trả 0, nuốt lỗi login;
            #   `…; rc=$?; unset PAT; echo "rc=$rc"` → echo trả 0, cả dòng vẫn "thành công".
            # Người trực chạy trong script sẽ đi tiếp như thể đã đăng nhập.
            # Dạng `if … then … else rc=$?; …; exit "$rc"; fi` trả đúng mã lỗi,
            # và `unset PAT` nằm ở CẢ HAI nhánh — token không ở lại môi trường
            # dù login thành công hay thất bại.
            _GOI_Y='if read -rs PAT && printf %s "$PAT" | docker login '"$_REG"' -u '"$_NS"' --password-stdin; then unset PAT; else rc=$?; unset PAT; exit "$rc"; fi'

            # ⚠️ Script bật `set -euo pipefail`. Gọi helper TRẦN rồi đọc `$?` là
            # sai: mã thoát khác 0 giết shell NGAY, `case` không bao giờ chạy, và
            # đúng hai thông báo quan trọng nhất ("CHƯA CẤU HÌNH", "KHÔNG ĐỌC
            # ĐƯỢC") không bao giờ tới được người trực. Đã đo: với `set -e`,
            # helper trả 1 hoặc 2 ⇒ script im lặng chết, in ra RỖNG.
            #
            # `if ...; then` đặt lời gọi vào ngữ cảnh điều kiện — `set -e` không
            # can thiệp ở đó.
            if _co_cau_hinh_credential "$_REG"; then
                _CRED_RC=0
            else
                _CRED_RC=$?
            fi
            case "$_CRED_RC" in
            1)
                error "CHƯA CẤU HÌNH ĐĂNG NHẬP '$_REG' — KHÔNG kết luận được ảnh còn hay mất.

  Package rollback của QLTS là PRIVATE. Chưa xác thực thì mọi digest đều báo
  'không phân giải được', kể cả khi ảnh còn NGUYÊN VẸN trên registry.
  ĐÂY KHÔNG PHẢI 'mất đường lùi'.

  Đăng nhập bằng token scope \`read:packages\` (rollback chỉ ĐỌC;
  \`write:packages\` chỉ cần khi TẠO thế hệ mới ở §5.4) rồi chạy lại script này:

      $_GOI_Y

  \`read -rs\` không hiện ký tự và giá trị KHÔNG vào history vì nó không nằm
  trong dòng lệnh. Xong việc thì \`docker logout $_REG\` — token nằm base64
  KHÔNG mã hoá trong \$HOME/.docker/config.json."
                ;;
            2)
                error "KHÔNG ĐỌC ĐƯỢC \${DOCKER_CONFIG:-\$HOME/.docker}/config.json — KHÔNG kết luận được gì.

  Tệp tồn tại nhưng không phải JSON hợp lệ. Không biết máy này có credential cho
  '$_REG' hay không, nên KHÔNG được suy ra ảnh đã mất, cũng KHÔNG được suy ra
  chưa đăng nhập.

  Sửa hoặc xoá tệp config rồi đăng nhập lại:

      $_GOI_Y"
                ;;
            *)
                error "KHÔNG XÁC ĐỊNH được trạng thái của $DIGEST.

  Máy này CÓ credential cho '$_REG', nhưng \`docker manifest inspect\` vẫn thất
  bại. Ba nguyên nhân đều dẫn tới đúng lỗi này và KHÔNG phân biệt được từ đây:

    1. Token hết hạn, bị thu hồi, hoặc thiếu scope \`read:packages\`.
    2. Mạng hoặc registry đang lỗi.
    3. Ảnh cũ của '$S' đã bị dọn khỏi registry (push ở §5.4 hỏng, hoặc
       registry tự dọn theo chính sách lưu giữ).

  ⚠️ KHÔNG kết luận 'mất đường lùi' khi chưa loại trừ (1) và (2). Ảnh vẫn có thể
  còn đủ. Phân biệt bằng cách đăng nhập lại rồi chạy lại script này:

      $_GOI_Y

  Nếu sau khi đăng nhập lại vẫn lỗi thì mới là ca (3), và lúc đó rollback phụ
  thuộc hoàn toàn vào đĩa của máy chủ.

  DỪNG LẠI — chưa đụng gì tới CSDL."
                ;;
            esac
        fi
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
