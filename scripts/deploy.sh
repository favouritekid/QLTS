#!/usr/bin/env bash
# =============================================================================
# QLTS Production Deployment Script
# =============================================================================
# Usage:
#   Routine deploy (default):
#     ./scripts/deploy.sh
#
#   Cold cutover (Phase 1 ship per RUNBOOK §7.2):
#     COLD_CUTOVER=true ./scripts/deploy.sh
#
# Cold cutover semantics (Phase1-Hotfix-4 / 2026-05-07):
#   * Skip Step 6 auto ``alembic upgrade head`` — operator runs manually
#     for stream-log + per-step checkpoint per RUNBOOK §7.2 T+1:30.
#   * Inject 3 entrypoint gate flags = false (RUN_MIGRATIONS_ON_STARTUP,
#     RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP, RUN_CASBIN_LOAD_ON_STARTUP)
#     so backend container starts without auto-running migration / sync /
#     Casbin policy load — those steps run manually post-deploy per
#     RUNBOOK §7.2 T+1:30 / T+3:00 / T+3:15 / T+3:30.
#   * Operator MUST follow RUNBOOK §7.2 sequence after this script
#     finishes Step 8 (container running but admin endpoints frozen via
#     ADMISSION_FROZEN + nginx block); script does NOT auto-execute the
#     manual cutover steps.
#   * Defensive default: only exact lowercase ``true`` triggers cutover
#     mode; any other value (TRUE/typo/unset) runs the routine flow.
#
# Routine deploy (COLD_CUTOVER unset or != "true"):
#   Flow unchanged from pre-Hotfix-4 — auto migration + sync + restart.
#
# =============================================================================
# 🚨 SELF-UPDATE CAVEAT (Phase1-Hotfix-7 / 2026-05-08, lesson from cutover
# ship 2026-05-07 22:18 UTC+7):
# =============================================================================
# When this script changes (e.g. new flag, new step, new env var) and the
# changes ship via main, invoking ``./scripts/deploy.sh`` directly on prod
# will run the OLD logic — bash loads the script into memory at invocation,
# then Step 2 ``git pull origin main`` updates the file ON DISK but the
# in-memory copy stays the OLD version. Result: any new flag/branch logic
# added in the latest commit will NOT execute on the FIRST deploy after
# merge. It only takes effect from the SECOND invocation onwards.
#
# This bit us during the admission cutover ship: ``COLD_CUTOVER=true ./
# scripts/deploy.sh`` ran the OLD pre-Hotfix-4 deploy.sh in memory which
# had no COLD_CUTOVER detection, so the routine flow auto-ran alembic +
# sync + Casbin instead of the operator-controlled sequence per RUNBOOK
# §7.2. End state was correct because all migrations + backfills are
# idempotent + apply cleanly, but the safety net (operator pause) was
# never engaged.
#
# **Mitigation for next cutover** — pre-stage the updated script BEFORE
# invoking, so bash loads the NEW version directly:
#
#   ssh prod
#   cd /opt/qlts
#   git fetch origin && git checkout main && git pull --ff-only origin main
#   # Copy NEW deploy.sh out of repo so future ``git pull`` (Step 2) cannot
#   # mutate the in-memory script:
#   cp scripts/deploy.sh /tmp/deploy_NEW.sh
#   chmod +x /tmp/deploy_NEW.sh
#   COLD_CUTOVER=true /tmp/deploy_NEW.sh
#
# The ``/tmp`` copy is loaded into bash memory; Step 2's git pull updates
# ``/opt/qlts/scripts/deploy.sh`` but our running invocation reads from
# ``/tmp/deploy_NEW.sh`` which we already loaded. Subsequent routine
# deploys (post-cutover) call ``./scripts/deploy.sh`` directly as usual
# because the on-disk and in-memory copies converge after the cutover
# merge propagates.
#
# Alternative: invoke via stdin to bypass the file-on-disk → memory race:
#   COLD_CUTOVER=true bash < scripts/deploy.sh
# (Less robust because positional args/relative paths break. Prefer cp.)
#
# Reference: ``Documents/ADMISSION_DAILY_LOG.md`` 2026-05-07 cutover entry +
# memory ``admission-cutover-shipped-2026-05-07``.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

cd "$PROJECT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# `echo -e` diễn giải escape TRONG NỘI DUNG THÔNG ĐIỆP, nên một chuỗi do người
# dùng cung cấp mà chứa hai ký tự `\` + `n` sẽ đẻ ra một DÒNG LOG GIẢ — dù nó
# không hề chứa ký tự newline thật. Phép kiểm "không có ký tự điều khiển" vì
# thế không đủ để bảo toàn tính toàn vẹn của log.
#
# `printf '%b…%s…'`: `%b` chỉ áp cho biến MÀU (vốn cần escape), còn `%s` in
# thông điệp NGUYÊN VĂN. Đã kiểm: 0 lời gọi log/warn/error/cutover trong tệp
# này dựa vào escape trong thông điệp, nên đổi là an toàn.
log() { printf '%b[DEPLOY]%b %s\n' "$GREEN" "$NC" "$1"; }
warn() { printf '%b[WARN]%b %s\n' "$YELLOW" "$NC" "$1"; }
error() { printf '%b[ERROR]%b %s\n' "$RED" "$NC" "$1"; exit 1; }
cutover() { printf '%b[CUTOVER]%b %s\n' "$YELLOW" "$NC" "$1"; }

# ============================================================================
# Cold cutover mode detection (Phase1-Hotfix-4 / 2026-05-07)
# ============================================================================
# Defensive parse — only exact lowercase ``true`` enables cutover mode.
# RUNBOOK §7.2 + memory ``solo-cutover-simple-data-import`` rationale.
COLD_CUTOVER="${COLD_CUTOVER:-false}"
if [ "${COLD_CUTOVER}" = "true" ]; then
    IS_CUTOVER=1
    cutover "============================================="
    cutover "COLD CUTOVER MODE ENABLED (per RUNBOOK §7.2)"
    cutover "============================================="
    cutover "* Step 6 auto-alembic: SKIP (operator runs manual)"
    cutover "* Step 8 container env: 3 cutover flags = false"
    cutover "* Operator MUST follow RUNBOOK §7.2 post-deploy:"
    cutover "  - T+1:30 manual ``alembic upgrade head``"
    cutover "  - T+3:00 manual backfill verify"
    cutover "  - T+3:15 dựng lại backend: up -d --no-deps --wait (Casbin reload)"
    cutover "  - T+3:30 manual ``sync_notification_rules``"
    cutover "============================================="
else
    IS_CUTOVER=0
fi

# =============================================================================
# Step 1: Pre-flight checks
# =============================================================================
log "Step 1/8: Pre-flight checks..."

command -v docker >/dev/null 2>&1 || error "Docker is not installed"
command -v docker compose >/dev/null 2>&1 || error "Docker Compose is not installed"

if [ ! -f .env.production ]; then
    error ".env.production not found. Copy from .env.production.example and fill in values."
fi

if grep -v '^\s*#' .env.production | grep -q "CHANGE_ME"; then
    error ".env.production contains CHANGE_ME placeholders. Update all values before deploying."
fi

# =============================================================================
# Chụp cổng thoát hiểm TRƯỚC khi nạp .env.production (vá 18-09-2026)
# =============================================================================
# `source .env.production` ngay dưới đây đưa MỌI biến trong tệp vào môi trường.
# Nếu ai đó viết `QLTS_SKIP_ROLLBACK_ASSET=1` vào tệp ấy một lần rồi quên, thì
# từ đó về sau MỌI deploy đều tự động bỏ qua tài sản rollback — trong khi hợp
# đồng của cổng này là "phải gõ tay MỖI LƯỢT". Một cờ khẩn cấp biến thành cấu
# hình thường trực là cách cổng tự tắt mà không ai nhận ra.
#
# Ba bước, theo đúng thứ tự: chụp giá trị từ môi trường THẬT → `unset` để phép
# hỏi sau `source` có nghĩa → nếu tệp tái khai báo thì DỪNG. Từ đây về sau chỉ
# dùng bản đã chụp, không đọc lại biến môi trường.
_RA_SKIP_CO=0
_RA_SKIP_GIATRI=""
_RA_REASON_CO=0
_RA_REASON_GIATRI=""
if [ "${QLTS_SKIP_ROLLBACK_ASSET+co}" = "co" ]; then
    _RA_SKIP_CO=1
    _RA_SKIP_GIATRI="$QLTS_SKIP_ROLLBACK_ASSET"
fi
if [ "${QLTS_SKIP_ROLLBACK_ASSET_REASON+co}" = "co" ]; then
    _RA_REASON_CO=1
    _RA_REASON_GIATRI="$QLTS_SKIP_ROLLBACK_ASSET_REASON"
fi
unset QLTS_SKIP_ROLLBACK_ASSET QLTS_SKIP_ROLLBACK_ASSET_REASON

# Load env vars for template substitution
set -a
source .env.production
set +a

# Hai biến này CHỈ được đến từ dòng lệnh. Có mặt sau `source` nghĩa là chúng
# vừa ra đời từ .env.production — từ chối, kể cả khi giá trị là "0": vấn đề là
# chúng NẰM TRONG TỆP, không phải giá trị chúng mang.
if [ "${QLTS_SKIP_ROLLBACK_ASSET+co}" = "co" ] \
   || [ "${QLTS_SKIP_ROLLBACK_ASSET_REASON+co}" = "co" ]; then
    error "QLTS_SKIP_ROLLBACK_ASSET / _REASON được khai báo trong .env.production.
       Cổng thoát hiểm phải là hành vi THỦ CÔNG TỪNG LƯỢT, không phải cấu hình
       thường trực. Gỡ chúng khỏi .env.production; muốn bỏ qua thì đặt ngay
       trên dòng lệnh của lượt deploy đó."
fi
unset QLTS_SKIP_ROLLBACK_ASSET QLTS_SKIP_ROLLBACK_ASSET_REASON

if [ -z "${DOMAIN:-}" ]; then
    error "DOMAIN is not set in .env.production"
fi

log "Pre-flight checks passed"

# =============================================================================
# Step 2: Pull latest code
# =============================================================================
log "Step 2/8: Pulling latest code..."

# L1 review FU (2026-05-14): snapshot the SHA we're moving from BEFORE the
# pull so we can print "commits since last successful deploy" — makes the
# concurrency cancel-in-progress + git-pull-HEAD pattern auditable. With
# multiple PR merges in close succession the deploy log used to be opaque
# about which commits actually rode this deploy (one run could ship 3 PRs
# via git pull catch-up). Now the operator sees exactly what landed.
_PRE_PULL_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")

# =============================================================================
# CỔNG GHIM SHA (vá 09-09-2026) — đóng TOCTOU giữa deploy.yml và deploy.sh
# =============================================================================
# `deploy.yml` đã làm đúng phần của nó: fetch, so `FETCH_HEAD` với `$SHA_MONG_DOI`,
# `git merge --ff-only "$SHA_MONG_DOI"`, kiểm lại HEAD, RỒI mới `bash scripts/deploy.sh`.
# Nhưng Step 2 ở đây lại `git pull origin main` — kéo TIP nhánh, tức đẩy cây
# VƯỢT QUA đúng commit vừa được xác minh. Job dừng ở `environment: production`
# chờ duyệt, nên khoảng hở ấy dài bằng thời gian chờ người bấm approve: run mang
# metadata commit A, còn thứ thật sự lên production là commit B. Không log nào
# nói ra điều đó, vì cổng duy nhất nằm ở yml và đã bị `pull` này vô hiệu hoá.
#
# Fail-closed: có `SHA_MONG_DOI` thì TUYỆT ĐỐI không `pull`; chỉ xác nhận cây
# đang đứng đúng chỗ. Lệch ⇒ dừng TRƯỚC backup/build/mọi mutation runtime.
#
# BA trạng thái, BA lối đi — không được gộp:
#
#   1. KHÔNG HIỆN DIỆN  → chạy tay, đường manual (unpinned, có cảnh báo).
#   2. HIỆN DIỆN + RỖNG → LỖI. Đây là workflow đã forward biến nhưng giá trị
#      không tới nơi (`envs:` thiếu tên, secret rỗng, expression sai). Coi nó
#      là "chạy tay" thì đúng lúc cổng cần canh nhất, cổng lại tự tắt và
#      `git pull` kéo tip mới với RC=0 — im lặng hoàn toàn.
#   3. HIỆN DIỆN + CÓ GIÁ TRỊ → validate rồi ghim.
#
# `[ -n "${SHA_MONG_DOI:-}" ]` KHÔNG phân biệt được 1 với 2 (đã đo bằng bash:
# set-empty cho kết quả y hệt unset), nên nó KHÔNG được dùng làm cổng setness.
# `${VAR+co}` bung thành "co" khi biến CÓ MẶT, kể cả khi rỗng — đó mới là phép
# hỏi đúng câu.
if [ "${SHA_MONG_DOI+co}" = "co" ]; then
    if [ -z "$SHA_MONG_DOI" ]; then
        error "SHA_MONG_DOI CÓ MẶT nhưng RỖNG — biến đã được truyền vào mà giá trị không tới nơi.
       KHÔNG coi đây là chạy tay, KHÔNG \`git pull\`. Kiểm \`envs:\` trong deploy.yml
       và giá trị \${{ github.sha }} của run."
    fi

    # Đòi đúng 40 hex CHỮ THƯỜNG. `git rev-parse` in chữ thường, nên so bằng
    # `=` với một giá trị viết hoa sẽ luôn lệch — bắt ở đây để thông điệp nói
    # đúng nguyên nhân thay vì đổ cho "HEAD lệch".
    case "$SHA_MONG_DOI" in
        *[!0-9a-f]*)
            error "SHA_MONG_DOI không phải 40 hex chữ thường (có ký tự lạ) — từ chối deploy" ;;
    esac
    if [ "${#SHA_MONG_DOI}" -ne 40 ]; then
        error "SHA_MONG_DOI dài ${#SHA_MONG_DOI} ký tự, cần đúng 40 — từ chối deploy"
    fi

    if ! _HEAD_HIEN_TAI=$(git rev-parse HEAD 2>/dev/null); then
        error "không đọc được HEAD (git rev-parse thất bại) — từ chối deploy khi chưa biết cây đang ở đâu"
    fi

    if [ "$_HEAD_HIEN_TAI" != "$SHA_MONG_DOI" ]; then
        error "cây đang ở $_HEAD_HIEN_TAI nhưng run này được sinh cho $SHA_MONG_DOI.
       KHÔNG tự kéo tip mới. Chạy lại Deploy trên đúng commit cần lên."
    fi

    log "Cây đã ghim tại $SHA_MONG_DOI — BỎ QUA \`git pull\` (cổng SHA đạt)"
else
    # Đường MANUAL (chạy tay trên VPS, không qua workflow).
    #
    # ⚠️ Đường này KHÔNG có bảo đảm ghim của workflow. `git pull origin main`
    # kéo tip nhánh tại thời điểm chạy, nên thứ lên production là "main lúc này",
    # không phải một commit đã được xác minh trước. Cổng SHA ở trên KHÔNG áp
    # dụng cho nhánh này và bản vá 09-09-2026 KHÔNG tuyên bố đã đóng race ở đây.
    # Muốn có bảo đảm ghim thì đặt SHA_MONG_DOI=<40 hex> rồi tự đưa cây tới đó
    # trước khi gọi script, hoặc dùng workflow Deploy.
    warn "SHA_MONG_DOI KHÔNG HIỆN DIỆN — chạy đường MANUAL, KHÔNG có bảo đảm ghim SHA"
    git pull origin main
fi

_POST_PULL_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
if [ -n "$_PRE_PULL_SHA" ] && [ "$_PRE_PULL_SHA" != "$_POST_PULL_SHA" ]; then
  log "Commits picked up by this deploy ($_PRE_PULL_SHA..$_POST_PULL_SHA):"
  git log --oneline "$_PRE_PULL_SHA..$_POST_PULL_SHA" 2>/dev/null \
    | sed 's/^/  /' \
    || log "  (could not enumerate commit range — disregard)"
fi

# =============================================================================
# Step 3: Process Nginx template
# =============================================================================
log "Step 3/8: Processing Nginx template..."

# T0-3 admission cold-cutover freeze: default to "false" when unset so the
# template only blocks when ops explicitly set NGINX_ADMISSION_FROZEN=true
# (paired with backend ADMISSION_FROZEN=true per RUNBOOK §6.1).
export NGINX_ADMISSION_FROZEN="${NGINX_ADMISSION_FROZEN:-false}"

# Từ 12-08-2026 template KHÔNG còn được render trên host. Nó nằm ở
# `nginx/templates/` và entrypoint chính thức của image nginx render nó vào
# `/etc/nginx/conf.d/` NGAY TRONG container lúc khởi động. Render trên host là
# thứ đã sinh ra một `nginx/conf.d/default.conf` nằm ngoài git — và khi cutover
# chạy từ một checkout sạch (không có tệp đó) thì site chết.
#
# Ở đây chỉ còn việc kiểm biến, fail-closed TRƯỚC khi đụng gì:
if [ -z "${DOMAIN:-}" ]; then
    error "DOMAIN chưa được đặt trong .env.production — nginx sẽ render server_name rỗng"
fi
if [ ! -f nginx/templates/default.conf.template ]; then
    error "Thiếu nginx/templates/default.conf.template — entrypoint nginx sẽ không có gì để render"
fi
log "Nginx template sẽ được render TRONG container (domain=$DOMAIN, admission_frozen=$NGINX_ADMISSION_FROZEN)"

# =============================================================================
# Step 3b: TÀI SẢN ROLLBACK — tạo TRƯỚC build, fail-closed
# =============================================================================
# Vá 18-09-2026. Trước bản vá này, việc tạo tài sản rollback (tag ảnh cũ + bản
# kê) chỉ tồn tại ở `Documents/ADMISSION_PRODUCTION_REPLACEMENT_RUNBOOK.md`
# §5.4 — một thủ tục LÀM TAY. Đường tự động chưa từng gọi nó:
# `deploy.yml` và chính tệp này đều có `docker tag` = 0 lần. Hệ quả đo được:
# deploy `deffbf2b` ngày 18-09 chạy xong mà không sinh bộ tài sản nào, trong
# khi sáu deploy `success` trước đó đều có. Không cổng nào nhắc, không cổng nào
# chặn — nên nó sẽ lặp lại ở MỌI lần deploy sau.
#
# ⭐⭐ VÌ SAO KHÔNG DÙNG `$_PRE_PULL_SHA` LÀM `# git-rev`:
# `deploy.yml` đã `git merge --ff-only "$SHA_MONG_DOI"` TRƯỚC khi gọi script
# này. Nên tại đây HEAD — và do đó `_PRE_PULL_SHA` — đã là SHA MỚI. Lấy nó ghi
# vào bản kê nghĩa là dán nhãn "phiên bản cũ" lên đúng phiên bản sắp thay thế:
# tài sản rollback SAI ngay lúc sinh ra, và Step 5 của §8.1 sẽ checkout về đúng
# cái cây vừa gây sự cố. Không có gì phát hiện được điều đó về sau.
#
# Nguồn đúng phải BỀN và NGOÀI worktree: một marker ghi sau mỗi deploy thành
# công, chứa SHA đã deploy + image ID của MỌI container runtime nó tạo ra (danh
# sách dẫn xuất từ model Compose, hiện là năm). Marker chỉ đáng tin khi image ID
# của TẤT CẢ còn khớp với container ĐANG chạy — khớp thì SHA
# trong marker đúng là revision của ảnh đang phục vụ; lệch thì đã có ai đó thay
# container ngoài đường này và ta KHÔNG biết ảnh hiện tại từ commit nào.
#
# Fail-closed: thiếu marker, marker hỏng, hoặc lệch dù chỉ một service ⇒ DỪNG
# trước build và trước mọi thứ chạm CSDL. Không đoán, không suy, không "cảnh
# báo rồi chạy tiếp" — đó đúng là hình dạng `docker pull … || echo "DỪNG LẠI"`
# đã trả giá một lần.

_RA_OPS="${QLTS_ROLLBACK_OPS_DIR:-/opt/qlts-ops/rollback}"
_RA_MARKER="$_RA_OPS/last-deploy.marker"
# Xoa moi gia tri ke thua tu moi truong. `_ra_bao_dam_dich_vu` bo qua buoc dan
# xuat khi bien nay da co gia tri, nen mot `export _RA_DICH_VU=...` tu ben ngoai
# se thanh duong tat KHONG KHAI BAO vong qua model Compose — dung thu ma chu
# thich cua ham ay tuyen bo la khong ton tai.
_RA_DICH_VU=""
_RA_COMPOSE="docker compose -f docker-compose.yml --profile production --env-file .env.production"

# --- Danh sach service PHAI duoc ghim: DAN XUAT, khong chep tay -------------
# Ban chep tay truoc day la "backend celery-worker celery-beat frontend" —
# thieu `nginx`. Ma `build` thi dung CA nginx, nen moi lan deploy ghi de
# `qlts-nginx:local` trong khi khong tai san nao ghim anh cu. Anh dang phuc vu
# mat ten duy nhat cua no va thanh dangling: khong con duong lui.
#
# KHONG doc docker-compose.yml bang grep/awk: service `nginx` lay `build:` qua
# YAML anchor (`<<: *nginx-base`), nen moi phep doc VAN BAN deu KHONG thay no.
# Phai di qua bo render hieu anchor.
#
# `--no-interpolate --no-env-resolution`: `config` binh thuong render `env_file`
# ra plaintext — tu tao mot ban sao secret production tren stdout. Hai co nay
# giu ${VAR} nguyen van, nen ban render KHONG chua gia tri nao.
#
# Nhom theo ANH chu khong theo service: `nginx`, `nginx-bootstrap`,
# `nginx-candidate` dung CHUNG `qlts-nginx:local`. Dai dien = service co
# profile rong hoac chua `production`; hai service kia chi song trong luc ap
# cau hinh nen khong co container de doc image ID.
_ra_dan_xuat_dich_vu() {
    local _json _py
    _py=$(command -v python3 || command -v python) || return 11
    _json=$(docker compose -f docker-compose.yml --profile production config --no-interpolate --no-env-resolution --format json) || return 12
    printf %s "$_json" | "$_py" -c '
import json,sys
try:
    goc=json.load(sys.stdin) or {}
except Exception as e:
    print("khong doc duoc JSON model Compose: %r" % (e,), file=sys.stderr)
    sys.exit(5)
sv=goc.get("services") or {}
theo_anh={}
for ten,c in sv.items():
    b=c.get("build")
    if not b: continue
    anh=c.get("image") or ten
    ky=json.dumps(b,sort_keys=True)
    # `--no-interpolate` giu ${VAR} nguyen van. Placeholder trong TEN ANH nghia
    # la ta KHONG biet anh that su la gi — ghim theo chuoi do la ghim mot cai ten
    # khong ton tai. Fail-closed.
    #
    # KHONG cam placeholder trong `build`: build args HOP LE mang ${VAR}
    # (frontend co NEXT_PUBLIC_* dang do). Chung khong doi anh NAO bi ghi de; va
    # phep so ky ben duoi la so CHUOI, nen hai service dung chung mot bo args se
    # van khop nhau nguyen van.
    if "${" in anh:
        print("service %s co placeholder trong TEN ANH: %s" % (ten,anh), file=sys.stderr)
        sys.exit(6)
    theo_anh.setdefault(anh,{}).setdefault(ky,[]).append((ten, c.get("profiles") or []))
ra=[]
for anh,nhom in theo_anh.items():
    # Gom theo TEN ANH khong du: hai build KHAC NHAU cung ghi mot tag thi ghim
    # mot dai dien se che mat build con lai, va anh duoc ghim co the la anh cua
    # build kia. Cung anh ma khac cau hinh build ⇒ DUNG.
    if len(nhom)!=1:
        print("anh %s co %d cau hinh build KHAC NHAU" % (anh,len(nhom)), file=sys.stderr)
        sys.exit(4)
    ds=list(nhom.values())[0]
    dd=[t for t,p in ds if not p or "production" in p]
    if len(dd)!=1:
        print("anh %s co %d dai dien production" % (anh,len(dd)), file=sys.stderr)
        sys.exit(2)
    ra.append(dd[0])
if not ra:
    print("0 service co build", file=sys.stderr)
    sys.exit(3)
print(" ".join(sorted(ra)))
' || return 13
}
# Khoi tao LAZY, khong eager.
#
# Ban dau khoi nay chay o CAP CAO NHAT, ngay sau Step 1. Hau qua do duoc:
# `deploy.sh` chet ngay sau Step 1 trong MOI sandbox test khong mo hinh hoa
# `docker compose config` — 90 ca do trong ba bo guard, do bang phep so
# nen/current (nen: 251 collected, 0 failed; sau ban va: 90 failed).
#
# Sai lam: bat MOI buoc cua deploy.sh phu thuoc vao mot lenh chi can cho MOT
# khoi. Nay danh sach duoc tinh o lan dung dau tien, va CHI trong duong di
# cua tai san rollback.
#
# Fail-closed KHONG doi mot ly: moi phep kiem cu van o day, chi doi CHO chay.
# Khong bien bypass, khong fallback sang danh sach chep tay.
# `_RA_SO_DICH_VU` phai duoc dat trong MOI lan goi, khong chi lan dau.
#
# Ban truoc `return 0` ngay khi `_RA_DICH_VU` da co gia tri — nhung phep gan
# `_RA_SO_DICH_VU` nam SAU do. Hau qua: neu `_RA_DICH_VU` duoc ke thua tu moi
# truong thi (a) bo dan xuat bi bo qua hoan toan — tuc mot BIEN BYPASS khong khai
# bao, dung thu chu thich tren tuyen bo la khong co; va (b) `_RA_SO_DICH_VU`
# KHONG BAO GIO duoc dat. Voi `set -u`, moi cho doc no chet bang `unbound
# variable` — o duong bo qua tai san thi cho ay nam SAU `mv` cong bo marker.
#
# Dong `_RA_DICH_VU=""` o phan khai bao tren dau da xoa moi gia tri ke thua, nen
# cay nay chi con la phong thu chieu sau: tinh lai so luong o MOI lan goi thi
# bien dem khong the roi ra ngoai bat ky duong di nao.
_ra_bao_dam_dich_vu() {
    if [ -z "${_RA_DICH_VU:-}" ]; then
        if ! _RA_DICH_VU=$(_ra_dan_xuat_dich_vu); then
            error "khong dan xuat duoc danh sach service tu model Compose.
       Thieu python3/python, hoac 'docker compose config' that bai.
       DUNG — chep tay danh sach la dung loi da de lot nginx."
        fi
    fi
    [ -n "$_RA_DICH_VU" ] || error "danh sach service ghim RONG — fail-closed."
    _RA_SO_DICH_VU=$(printf %s "$_RA_DICH_VU" | wc -w)
    [ "$_RA_SO_DICH_VU" -ge 4 ] || error "chi dan xuat duoc $_RA_SO_DICH_VU service (toi thieu 4) — model Compose bat thuong."
}

# --- Cổng $OPS: chạy TRƯỚC lần ghi đầu tiên của CẢ Step 3b lẫn Step 8c ------
# Fail-closed, KHÔNG `mkdir -p`, KHÔNG `chmod` để "sửa hộ". Một đường dẫn
# không đáng tin thì phải DỪNG chứ không phải được vá cho hợp lệ: `chmod 700`
# lên một symlink do người khác đặt là tự tay trao quyền cho họ, và `mkdir -p`
# im lặng chấp nhận một thư mục CÓ SẴN rồi trả 0 — đúng cái cổng ta đang đi
# kiểm lại tự tạo ra thứ nó phải canh.
_ra_cong_ops() {
    local _n="$1" _q
    [ "$(id -u)" = "0" ] || error "[$_n] không phải root (uid=$(id -u)) — dừng trước mọi lần ghi."
    if [ -L "$_RA_OPS" ]; then
        error "[$_n] $_RA_OPS là SYMLINK — từ chối.
       Một dangling symlink còn lọt qua \`[ -e ]\`, nên phép kiểm phải là \`-L\`."
    fi
    [ -e "$_RA_OPS" ] || error "[$_n] $_RA_OPS KHÔNG tồn tại.
       Thư mục tài sản rollback phải được tạo và cấp quyền TRƯỚC bằng một thao
       tác có phê duyệt riêng."
    [ -d "$_RA_OPS" ] || error "[$_n] $_RA_OPS không phải thư mục."
    _q=$(stat -c '%a %U:%G' "$_RA_OPS") || error "[$_n] không đọc được quyền $_RA_OPS"
    [ "$_q" = "700 root:root" ] || error "[$_n] $_RA_OPS sai quyền/chủ sở hữu: $_q (cần 700 root:root)."
}

# --- Kiểm một tệp tạm vừa do mktemp tạo, TRƯỚC lần `printf` đầu tiên -------
_ra_kiem_tmp() {
    local _t="$1" _thumuc="$2" _mau="$3" _n="$4" _q
    [ -n "$_t" ] || error "[$_n] mktemp trả chuỗi RỖNG."
    [ "$(dirname -- "$_t")" = "$_thumuc" ] || error "[$_n] tệp tạm nằm NGOÀI $_thumuc: $_t"
    case "$(basename -- "$_t")" in
        $_mau) : ;;
        *) error "[$_n] tệp tạm sai tên: $(basename -- "$_t") (cần $_mau)" ;;
    esac
    [ -L "$_t" ] && error "[$_n] tệp tạm là SYMLINK — từ chối."
    [ -f "$_t" ] || error "[$_n] tệp tạm không phải regular file."
    _q=$(stat -c '%a %U:%G %s %h' "$_t") || error "[$_n] không đọc được thuộc tính tệp tạm"
    [ "$_q" = "600 root:root 0 1" ]         || error "[$_n] tệp tạm sai quyền/kích thước/link: $_q (cần '600 root:root 0 1')"
}

# --- Kiểm marker vừa dựng, TRƯỚC khi công bố ------------------------------
# Đếm trước, đọc sau — cùng luật mà Step 3b dùng để ĐỌC marker. Ghi ra một
# marker mà chính reader của lượt sau sẽ từ chối là tạo ra một quả mìn hẹn giờ
# ở đúng chỗ khó chẩn đoán nhất.
# So nội dung hiện tại với dấu niêm phong đã chốt TRƯỚC preflight.
_ra_kiem_hash_pf() {
    local _n="$1" _f="$2" _h
    [ -n "${_RA_H_PF:-}" ] || error "[$_n] chưa niêm phong hash bản kê."
    _h=$(sha256sum "$_f" | awk '{print $1}') || error "[$_n] không đọc được hash $_f"
    [ "$_h" = "$_RA_H_PF" ]         || error "[$_n] HASH LỆCH trên $_f (đang có=$_h niêm phong=$_RA_H_PF)."
}

# --- Đỏ SAU khi đã `ln`: bản kê bẩn đang mang TÊN CHÍNH THỨC ---------------
# Từ giây `ln` thành công, sự TỒN TẠI của tên chính thức LÀ bằng chứng "đã
# qua preflight" cho lượt sau. Thoát RC=1 mà để tệp đó nằm lại là biến một
# lỗi thành một lời nói dối bền vững.
# QUYỀN XOÁ phải dựa trên một DANH TÍNH ĐANG ĐƯỢC GHIM, không phải một con số.
#
# `dev:inode` KHÔNG phải danh tính bền: gỡ hardlink CUỐI CÙNG xong thì kernel
# được phép CẤP LẠI đúng số inode ấy cho một tệp hoàn toàn khác. Nhánh dọn dẹp
# tin vào con số đã chốt sẽ XOÁ NHẦM tệp của lượt khác — ABA thật, không phải
# TOCTOU lý thuyết: bỏ TMP → ai đó thay FINAL → kernel tái dùng inode → hash
# cuối báo lệch → dọn dẹp thấy 'khớp' và xoá tệp ngoại lai.
#
# Một file descriptor ĐANG MỞ trên TMP đóng cả hai vế cùng lúc:
#   - nó GIỮ chính inode đó sống ⇒ số inode ấy KHÔNG THỂ bị tái sử dụng;
#   - `/proc/$$/fd/<fd>` trỏ tới đúng inode đó, nên `-ef` (phép hỏi CỦA SHELL,
#     stat(2) trực tiếp, không gọi nhị phân `stat`) vẫn trả lời đúng cả khi
#     `stat` hỏng, cả sau khi TMP đã bị `rm`.
# `dev:inode` từ nay CHỈ dùng để chẩn đoán/ghi log — KHÔNG còn là quyền xoá.
_ra_loi_sau_ln() {
    local _f="$1" _fd="$2" _ino_t="$3" _ino_f _da _ghim
    shift 3
    _ino_f=$(stat -c '%d:%i' "$_f" 2>/dev/null || true)
    _da="KHÔNG GỠ (không chứng minh được là tệp của lượt này; dev:inode đang có=${_ino_f:-?} đã chốt=$_ino_t)"
    _ghim="/proc/$$/fd/$_fd"
    if [ ! -L "$_f" ] && [ -f "$_f" ] && [ -n "$_fd" ] && [ -e "$_ghim" ]; then
        if [ "$_f" -ef "$_ghim" ]; then
            rm -f -- "$_f" && _da="ĐÃ GỠ (same-file với FD đang ghim inode của lượt này)"
        fi
    fi
    error "$* [bản kê ở tên chính thức: $_da]"
}

_ra_kiem_hash_sau_ln() {
    local _n="$1" _f="$2" _fd="$3" _ino="$4" _h
    [ -n "${_RA_H_PF:-}" ]         || _ra_loi_sau_ln "$_f" "$_fd" "$_ino" "[$_n] chưa niêm phong hash bản kê."
    _h=$(sha256sum "$_f" | awk '{print $1}')         || _ra_loi_sau_ln "$_f" "$_fd" "$_ino" "[$_n] không đọc được hash $_f"
    [ "$_h" = "$_RA_H_PF" ]         || _ra_loi_sau_ln "$_f" "$_fd" "$_ino" "[$_n] HASH LỆCH trên $_f (đang có=$_h niêm phong=$_RA_H_PF)."
}

_ra_kiem_schema_marker() {
    local _f="$1" _n _v _sha _la _s _i _hex _c _can
    _n=$(grep -c "^# marker-version$(printf '	')" "$_f" || true)
    [ "$_n" -eq 1 ] || error "marker mới: có $_n dòng '# marker-version' (cần 1)."
    _v=$(awk -F"$(printf '	')" '$1=="# marker-version"{print $2}' "$_f")
    # Marker MỚI luôn là v2 (nó ghi đủ mọi image runtime bị build ghi đè, kể cả
    # nginx). Đọc thì chấp nhận cả v1 lẫn v2; GHI thì chỉ v2 — nên phép kiểm này
    # đòi đúng '2'. Nếu nó còn đòi '1' thì deploy đổ ở bước niêm phong, sau khi
    # mọi thứ khác đã xong.
    [ "$_v" = "2" ] || error "marker mới: marker-version='$_v' (cần '2')."
    _n=$(grep -c "^# deployed-sha$(printf '	')" "$_f" || true)
    [ "$_n" -eq 1 ] || error "marker mới: có $_n dòng '# deployed-sha' (cần 1)."
    _sha=$(awk -F"$(printf '	')" '$1=="# deployed-sha"{print $2}' "$_f")
    case "$_sha" in *[!0-9a-f]*) error "marker mới: deployed-sha có ký tự không phải hex thường." ;; esac
    [ "${#_sha}" -eq 40 ] || error "marker mới: deployed-sha dài ${#_sha} (cần 40)."
    # Đủ 40 hex CHƯA đủ: một SHA hợp lệ nhưng KHÁC HEAD vẫn qua mọi phép kiểm
    # hình dạng, rồi lượt sau ghim ảnh cũ theo một revision không đúng.
    [ "$_sha" = "$_RA_SHA_MOI" ]         || error "marker mới: deployed-sha='$_sha' KHÁC HEAD đang deploy ($_RA_SHA_MOI)."
    _n=$(grep -c "^# deployed-at$(printf '	')" "$_f" || true)
    [ "$_n" -eq 1 ] || error "marker mới: có $_n dòng '# deployed-at' (cần 1)."
    _n=$(( $(grep -c "^# asset-tag$(printf '	')" "$_f" || true) + $(grep -c "^# asset-skipped$(printf '	')" "$_f" || true) ))
    [ "$_n" -eq 1 ] || error "marker mới: có $_n dòng asset-tag/asset-skipped (cần đúng 1)."
    _la=$(awk -F"$(printf '	')" -v ds="$_RA_DICH_VU" '
        /^#/ {next} NF==0 {next}
        { ok=0; n=split(ds,a," "); for(i=1;i<=n;i++) if($1==a[i]) ok=1
          if(!ok) print $1 }' "$_f")
    [ -z "$_la" ] || error "marker mới: có dòng service LẠ: $(printf '%s' "$_la" | tr '
' ' ')"
    for _s in $_RA_DICH_VU; do
        _n=$(grep -c "^${_s}$(printf '	')" "$_f" || true)
        [ "$_n" -eq 1 ] || error "marker mới: service '$_s' xuất hiện $_n lần (cần 1)."
        _c=$(awk -F"$(printf '	')" -v s="$_s" '$1==s{print NF}' "$_f")
        [ "$_c" -eq 3 ] || error "marker mới: hàng '$_s' có $_c cột (cần 3)."
        _i=$(awk -F"$(printf '	')" -v s="$_s" '$1==s{print $2}' "$_f")
        case "$_i" in sha256:*) : ;; *) error "marker mới: image ID của '$_s' thiếu tiền tố sha256:" ;; esac
        _hex=${_i#sha256:}
        case "$_hex" in *[!0-9a-f]*) error "marker mới: image ID của '$_s' có ký tự lạ." ;; esac
        [ "${#_hex}" -eq 64 ] || error "marker mới: image ID của '$_s' dài ${#_hex} hex (cần 64)."
        _c=$(awk -F"$(printf '	')" -v s="$_s" '$1==s{print $3}' "$_f")
        [ -n "$_c" ] || error "marker mới: CID của '$_s' RỖNG."
        # Hợp đồng của production, KHÔNG phải của fixture: `docker compose ps -q`
        # và `docker inspect` trả ID ĐẦY ĐỦ 64 hex thường. Chấp nhận một chuỗi
        # bất kỳ miễn không có khoảng trắng là để lọt cả ID RÚT GỌN 12 ký tự —
        # thứ đem so bằng `=` với ID đầy đủ sẽ luôn LỆCH, và ta dừng vì lý do sai.
        case "$_c" in *[!0-9a-f]*) error "marker mới: CID của '$_s' có ký tự không phải hex thường." ;; esac
        [ "${#_c}" -eq 64 ] || error "marker mới: CID của '$_s' dài ${#_c} hex (cần 64)."
    done
    # Tổng dòng = (số dòng TIÊU ĐỀ) + (một dòng cho mỗi service).
    #
    # Con số 4 ở đây KHÔNG phải số service — nó là arity của khối `printf` ghi
    # tiêu đề, và đã được bốn phép kiểm ngay phía trên ép RIÊNG từng khoá
    # (`# marker-version`, `# deployed-sha`, `# deployed-at`, và đúng một trong
    # `# asset-tag`/`# asset-skipped`). Số service thì lấy từ `$_RA_SO_DICH_VU`,
    # tức CÙNG một `$_RA_DICH_VU` mà vòng lặp phía trên vừa duyệt — nên phép
    # kiểm này không đẻ ra nguồn chuẩn thứ hai. Nó là phép kiểm PHẦN DƯ: sau khi
    # mọi dòng hợp lệ đã được đếm riêng, không được còn dòng nào khác.
    #
    # Trước bản vá này dòng dưới là hằng `-eq 8` = 4 tiêu đề + BỐN service. Danh
    # sách nay được dẫn xuất từ model Compose và có NĂM (thêm `nginx`), nên marker
    # hợp lệ có 9 dòng và cổng này làm deploy ĐỔ ở bước niêm phong — sau khi đã
    # build, đã `up -d`, đã health-check. Cùng lớp lỗi mà phép kiểm
    # `marker-version` ngay trên đã vấp một lần: hai con số cách nhau ~750 dòng
    # trôi khỏi nhau. Vì thế con số này phải DẪN XUẤT, không được viết tay.
    _n=$(wc -l < "$_f")
    _can=$(( 4 + _RA_SO_DICH_VU ))
    [ "$_n" -eq "$_can" ] || error "marker mới: có $_n dòng (cần đúng $_can = 4 tiêu đề + $_RA_SO_DICH_VU hàng service)."
    _n=$(tr -dc '\r' < "$_f" | wc -c)
    [ "$_n" -eq 0 ] || error "marker mới: chứa $_n ký tự CR — phải LF thuần."
    _n=$(head -c3 "$_f" | od -An -tx1 | tr -d ' ')
    [ "$_n" != "efbbbf" ] || error "marker mới: có BOM."
}

# Marker phải mô tả ĐÚNG tập container đang phục vụ, không chỉ đúng hình dạng.
# Tập ấy là `$_RA_DICH_VU` — dẫn xuất, không phải một con số viết tay.
_ra_kiem_marker_vs_live() {
    local _n="$1" _f="$2" _s _mi _mc _lc _li _st
    for _s in $_RA_DICH_VU; do
        _mi=$(awk -F"$(printf '	')" -v s="$_s" '$1==s{print $2}' "$_f")
        _mc=$(awk -F"$(printf '	')" -v s="$_s" '$1==s{print $3}' "$_f")
        _lc=$($_RA_COMPOSE ps -q "$_s" 2>/dev/null || true)
        [ -n "$_lc" ] || error "[$_n] không thấy container đang chạy cho '$_s'."
        [ "$_mc" = "$_lc" ] || error "[$_n] CID của '$_s' lệch container hiện hành (marker=$_mc live=$_lc)."
        _st=$(docker inspect -f '{{.State.Status}}' "$_lc" 2>/dev/null || true)
        [ "$_st" = "running" ] || error "[$_n] '$_s' không running (=$_st)."
        _li=$(docker inspect -f '{{.Image}}' "$_lc" 2>/dev/null || true)
        [ "$_mi" = "$_li" ] || error "[$_n] image của '$_s' lệch container hiện hành (marker=$_mi live=$_li)."
    done
}

# --- Cổng thoát hiểm: phải là hành vi THỦ CÔNG CÓ CHỦ ĐÍCH ------------------
# Hai biến, cả hai đều bắt buộc, và workflow KHÔNG forward chúng (`envs:` của
# deploy.yml chỉ có SHA_MONG_DOI). Một biến đơn lẻ quá dễ bấm; đòi thêm lý do
# viết ra bằng chữ buộc người gõ phải nói vì sao, và để lại vết trong log.
# Đọc BẢN ĐÃ CHỤP ở Step 1, không đọc biến môi trường: sau `source
# .env.production` thì biến môi trường không còn phân biệt được "người gõ" với
# "tệp cấu hình khai".
_RA_BO_QUA=0
if [ "$_RA_SKIP_CO" = "1" ]; then
    case "$_RA_SKIP_GIATRI" in
        0) : ;;
        1) _RA_BO_QUA=1 ;;
        *) error "QLTS_SKIP_ROLLBACK_ASSET='$_RA_SKIP_GIATRI' không hợp lệ — chỉ nhận '0' hoặc '1'.
       Giá trị lạ KHÔNG được hiểu là 'bật': một biến đặt sai chính tả mà được
       coi như bỏ qua là cách cổng tự tắt đúng lúc cần canh nhất." ;;
    esac
fi
if [ "$_RA_BO_QUA" = "1" ]; then
    if [ "$_RA_REASON_CO" != "1" ]; then
        error "QLTS_SKIP_ROLLBACK_ASSET=1 nhưng THIẾU QLTS_SKIP_ROLLBACK_ASSET_REASON.
       Bỏ qua tài sản rollback là quyết định phải ghi lại được — nêu lý do."
    fi
    if [ -z "$_RA_REASON_GIATRI" ]; then
        error "QLTS_SKIP_ROLLBACK_ASSET_REASON RỖNG — cần một lý do thật, không phải chuỗi trống."
    fi
    case "$_RA_REASON_GIATRI" in
        *[[:cntrl:]]*)
            error "QLTS_SKIP_ROLLBACK_ASSET_REASON chứa ký tự điều khiển (xuống dòng/tab/…).
       Lý do phải nằm trên MỘT dòng: nó sẽ đi vào log và marker, và một chuỗi
       nhiều dòng làm hỏng định dạng phân tách bằng tab của bản kê." ;;
        *\\*)
            # Phòng thủ hai lớp cùng với việc log đã chuyển sang `printf '%s'`:
            # một chuỗi chứa `\` + `n` (hai ký tự, KHÔNG phải newline) từng có
            # thể đẻ ra dòng log giả qua `echo -e`. Lý do là văn bản thuần.
            error "QLTS_SKIP_ROLLBACK_ASSET_REASON chứa dấu gạch chéo ngược.
       Lý do phải là văn bản thuần — chuỗi escape có thể giả mạo dòng log." ;;
    esac
    warn "BỎ QUA tạo tài sản rollback theo yêu cầu thủ công."
    warn "  lý do: $_RA_REASON_GIATRI"
    warn "  ⇒ deploy này sẽ KHÔNG có đường lùi được ghim. Tự chịu trách nhiệm."
else
    log "Step 3b: tạo tài sản rollback (trước build)..."

    # Dan xuat TAI DAY — day la cho dau tien that su can danh sach.
    _ra_bao_dam_dich_vu

    # --- Đọc marker ---------------------------------------------------------
    if [ ! -f "$_RA_MARKER" ]; then
        error "THIẾU marker $_RA_MARKER — không biết ảnh đang chạy thuộc commit nào.
       Đây là lần đầu deploy.sh chạy với cổng này, hoặc marker đã bị xoá.
       KHÔNG đoán từ HEAD: tại đây HEAD đã là SHA MỚI (deploy.yml đã ff-merge).
       Cần một lần khởi tạo marker trên production, có phê duyệt riêng, rồi mới
       deploy tiếp. Muốn bỏ qua có chủ đích:
         QLTS_SKIP_ROLLBACK_ASSET=1 QLTS_SKIP_ROLLBACK_ASSET_REASON='...'"
    fi

    # ---- Marker phải ĐÚNG HÌNH DẠNG, không chỉ "có dòng ta cần" ------------
    # `head -1` là cái bẫy: một marker có HAI dòng `# deployed-sha` mâu thuẫn
    # nhau vẫn qua cổng, và ta ghim theo dòng đầu mà không biết dòng thứ hai
    # nói khác. Tương tự với một service khai hai lần bằng hai image ID.
    # Nên: đếm trước, đọc sau. Đếm khác 1 ⇒ dừng.
    _ra_dem() { grep -cE "$1" "$_RA_MARKER" || true; }

    _RA_N=$(_ra_dem '^# marker-version'$'\t')
    if [ "$_RA_N" -ne 1 ]; then
        error "marker: có $_RA_N dòng '# marker-version' (cần đúng 1) — marker hỏng."
    fi
    _RA_VER=$(awk -F'\t' '$1=="# marker-version"{print $2}' "$_RA_MARKER")
    case "$_RA_VER" in
        1|2) : ;;
        *) error "marker: marker-version='$_RA_VER', script này chỉ đọc được 1 hoặc 2.
       Không đoán định dạng lạ — một marker của phiên bản khác có thể xếp cột
       khác và ta sẽ ghim nhầm image ID." ;;
    esac
    # v1 chi ghi BON service ung dung. No khong the chung thuc anh nginx —
    # luc no duoc ghi, nginx chua tung duoc ghim. Nen: kiem dung nhung service
    # marker CO ghi, canh bao ro phan con lai, roi van ghim DU theo danh sach
    # dan xuat (Step 3b doc image ID TRUC TIEP tu container dang chay, khong
    # can marker biet truoc).
    # ⚠️ CỐ Ý KHÔNG dùng `tr` ở đây. `$(...)` đã gộp kết quả thành một chuỗi mà
    # `for` tự tách theo IFS (có sẵn newline), nên `tr` là thừa — và nó KHÔNG
    # vô hại: `test_aw_marker_cu_doi_giua_chung_thi_do` dựng một `tr` giả để
    # sửa marker ở ĐÚNG lần gọi `tr` đầu tiên, vốn nằm ở Step 8c. Thêm một lần
    # gọi `tr` tại Step 3b làm ca ấy nổ sớm, ở một chỗ hoàn toàn khác.
    _RA_MK_DICH_VU=$(awk -F"$(printf '	')" '/^#/{next} NF==0{next} {print $1}' "$_RA_MARKER" | sort)
    _RA_MK_N=$(printf %s "$_RA_MK_DICH_VU" | wc -w)
    # SÀN cứng: bốn service ứng dụng đã tồn tại từ trước mọi phiên bản marker.
    # Bỏ sàn này là để lọt marker 3/4 — đúng ca mà
    # `test_ra_marker_hong_thi_dung_truoc_build` canh, và là fail-open thật.
    [ "$_RA_MK_N" -ge 4 ] || error "marker chỉ ghi $_RA_MK_N service (tối thiểu 4).
       Một marker thiếu service thì không chứng thực được ảnh đang chạy của
       service đó — ghim theo nó là ghim một đường lùi khuyết."
    if [ "$_RA_VER" = "1" ]; then
        warn "marker LEGACY (version 1): no chi chung thuc $_RA_MK_N service.
       KHONG co image rollback cho service nam ngoai danh sach do — lan nay
       chung se duoc ghim lan dau. Marker moi se la version 2."
    fi

    _RA_N=$(_ra_dem '^# deployed-sha'$'\t')
    if [ "$_RA_N" -ne 1 ]; then
        error "marker: có $_RA_N dòng '# deployed-sha' (cần đúng 1) — không biết tin dòng nào."
    fi
    _RA_SRC=$(awk -F'\t' '$1=="# deployed-sha"{print $2}' "$_RA_MARKER")
    case "$_RA_SRC" in
        *[!0-9a-f]*) error "marker: deployed-sha '$_RA_SRC' có ký tự không phải hex thường" ;;
    esac
    if [ "${#_RA_SRC}" -ne 40 ]; then
        error "marker: deployed-sha dài ${#_RA_SRC} ký tự, cần đúng 40"
    fi

    # Mỗi service ĐÚNG MỘT dòng, và không có dòng service lạ. Một dòng thừa tên
    # `postgres` hay `nginx` nghĩa là marker được sinh bởi thứ khác — đừng đọc
    # tiếp một tệp ta không hiểu.
    # Lap theo service MA MARKER GHI, khong theo danh sach dan xuat: marker v1
    # khong co hang nginx, doi no la doi mot thu no chua bao gio hua.
    for _S in $_RA_MK_DICH_VU; do
        _RA_N=$(_ra_dem "^${_S}"$'\t')
        if [ "$_RA_N" -ne 1 ]; then
            error "marker: service '$_S' xuất hiện $_RA_N lần (cần đúng 1)."
        fi
    done
    _RA_LA=$(awk -F'\t' -v ds="$_RA_DICH_VU" '
        /^#/ {next} NF==0 {next}
        { ok=0; n=split(ds,a," "); for(i=1;i<=n;i++) if($1==a[i]) ok=1
          if(!ok) print $1 }' "$_RA_MARKER")
    if [ -n "$_RA_LA" ]; then
        error "marker có dòng service KHÔNG thuộc model Compose hiện hành: $(printf '%s' "$_RA_LA" | tr '\n' ' ')
       Marker này không do đường deploy sinh ra — từ chối dùng."
    fi

    # --- Đối chiếu marker với MỌI container runtime đang chạy ---------------
    # Không phải hai: compose đặt tên ảnh theo `<project>-<service>` nên
    # celery-worker/celery-beat có ảnh RIÊNG. Thiếu hai cái đó thì rollback lùi
    # backend mà để worker ở mã MỚI, chạy trên lược đồ CSDL đã lùi.
    for _S in $_RA_MK_DICH_VU; do
        _RA_CID=$($_RA_COMPOSE ps -q "$_S" 2>/dev/null || true)
        if [ -z "$_RA_CID" ]; then
            error "không thấy container đang chạy cho '$_S' — không thể ghim ảnh cũ.
       Đừng build đè lên một stack đang thiếu service."
        fi
        _RA_IMG=$(docker inspect -f '{{.Image}}' "$_RA_CID" 2>/dev/null || true)
        case "$_RA_IMG" in
            sha256:*) : ;;
            *) error "docker inspect '$_S' trả image ID không hợp lệ: '$_RA_IMG'
       (cần dạng sha256:…). Chuỗi rỗng hay định dạng lạ sẽ trôi qua mọi phép so
       và biến cổng này thành cổng xanh giả." ;;
        esac
        # Không `head -1`: phép đếm ở trên đã bảo đảm đúng một dòng. Dùng
        # `head -1` ở đây sẽ che mất đúng cái ta vừa đi kiểm.
        _RA_GHI=$(awk -F'\t' -v s="$_S" '$1==s {print $2}' "$_RA_MARKER")
        case "$_RA_GHI" in
            sha256:*) : ;;
            *) error "marker: image ID của '$_S' không có tiền tố sha256: ('$_RA_GHI')" ;;
        esac
        _RA_HEX=${_RA_GHI#sha256:}
        case "$_RA_HEX" in
            *[!0-9a-f]*) error "marker: image ID của '$_S' có ký tự không phải hex thường" ;;
        esac
        if [ "${#_RA_HEX}" -ne 64 ]; then
            error "marker: image ID của '$_S' dài ${#_RA_HEX} hex, cần đúng 64.
       Một chuỗi ngắn hơn có thể là tiền tố rút gọn — so tiền tố với ID đầy đủ
       sẽ luôn LỆCH, và ta sẽ dừng vì lý do sai."
        fi
        if [ "$_RA_GHI" != "$_RA_IMG" ]; then
            error "LỆCH marker ở '$_S':
         marker ghi : $_RA_GHI
         đang chạy  : $_RA_IMG
       Container đã bị thay ngoài đường deploy này, nên SHA trong marker KHÔNG
       còn mô tả đúng ảnh đang phục vụ. Ghim theo nó là tạo ra tài sản rollback
       sai. DỪNG trước build và trước CSDL."
        fi
    done
    _RA_MK_N=$(printf %s "$_RA_MK_DICH_VU" | wc -w)
    log "  ✓ marker khớp $_RA_MK_N/$_RA_MK_N container đang chạy — nguồn = $_RA_SRC"

    # --- Tên tag: không va chạm, không ghi đè -------------------------------
    if ! _RA_TGT=$(git rev-parse HEAD 2>/dev/null); then
        error "không đọc được HEAD để đặt tên tag rollback"
    fi
    _RA_TAG="pre-$(printf '%.8s' "$_RA_TGT")-from-$(printf '%.8s' "$_RA_SRC")-$(date -u +%Y%m%dT%H%M%SZ)"
    _RA_DIR="$_RA_OPS/$_RA_TAG"
    _RA_MANIFEST="$_RA_DIR/rollback_manifest_${_RA_TAG}.txt"

    if [ -e "$_RA_DIR" ]; then
        error "$_RA_DIR đã tồn tại — từ chối ghi đè một bộ tài sản có sẵn."
    fi
    for _S in $_RA_DICH_VU; do
        if docker image inspect "qlts-${_S}:${_RA_TAG}" >/dev/null 2>&1; then
            error "tag qlts-${_S}:${_RA_TAG} ĐÃ TỒN TẠI — từ chối ghi đè.
       Nếu đây là tàn dư của một lượt hỏng giữa chừng, dọn tay ĐÍCH DANH từng
       tag rồi chạy lại. Tuyệt đối không \`image prune\`."
        fi
    done

    # --- Tag từ `.Image` của container đang chạy, KHÔNG từ `:latest` --------
    # `qlts-<svc>:latest` là tag DI ĐỘNG: nó có thể đã trôi sang một bản build
    # khác từ trước khi ta chạm vào. `.Image` của container đang chạy là thứ duy
    # nhất chắc chắn đúng "phiên bản đang phục vụ".
    _ra_cong_ops "step3b"

    # `mkdir` KHÔNG `-p`: đó mới là no-clobber thật. `mkdir -p` trả 0 trên một
    # thư mục CÓ SẴN, nên cổng "$_RA_DIR đã tồn tại" ở trên bị vô hiệu ngay khi
    # có race giữa hai lệnh.
    # `-m 700` NGAY lúc tạo: không còn cửa sổ giữa `mkdir` và `chmod` mà thư
    # mục nằm đó với quyền mặc định. Và KHÔNG `chmod` một path SAU khi đã kiểm
    # symlink — giữa hai lệnh đó đường dẫn vẫn có thể bị thay.
    mkdir -m 700 -- "$_RA_DIR"         || error "không tạo được $_RA_DIR (đã tồn tại hoặc không ghi được) — từ chối ghi đè."
    [ -L "$_RA_DIR" ] && error "$_RA_DIR là SYMLINK — từ chối."
    [ -d "$_RA_DIR" ] || error "$_RA_DIR không phải thư mục sau khi tạo."
    _RA_QD=$(stat -c '%a %U:%G' "$_RA_DIR")
    [ "$_RA_QD" = "700 root:root" ] || error "$_RA_DIR sai quyền/chủ: $_RA_QD"

    # `mktemp` dùng O_EXCL|O_CREAT: không theo symlink, không ghi đè, tên không
    # đoán được. Tên theo `$$` + `: >` thì một dangling symlink đặt sẵn ở đúng
    # đường đó làm `[ -e ]` trả FALSE và lệnh cắt trắng GHI XUYÊN ra ngoài.
    _RA_TMP=$(mktemp "$_RA_DIR/.manifest.XXXXXXXXXX")         || error "không tạo được tệp tạm nguyên tử trong $_RA_DIR"
    _ra_kiem_tmp "$_RA_TMP" "$_RA_DIR" '.manifest.*' "manifest"
    {
        # schema-version 2 = ban ke ghi DU moi image runtime bi build ghi de,
        # ke ca nginx. Ban ke v1 (khong co dong nay) chi co bon service ung
        # dung — rollback-preflight doc duoc nhung PHAI canh bao ro.
        printf '# schema-version\t2\n'
        printf '# scope\tLOCAL-ONLY - chua publish GHCR/offsite\n'
        printf '# git-rev\t%s\n'    "$_RA_SRC"
        printf '# target-rev\t%s\n' "$_RA_TGT"
        printf '# created\t%s\n'    "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf '# marker\t%s\n'     "$_RA_MARKER"
    } >> "$_RA_TMP"

    for _S in $_RA_DICH_VU; do
        _RA_CID=$($_RA_COMPOSE ps -q "$_S")
        _RA_IMG=$(docker inspect -f '{{.Image}}' "$_RA_CID")
        # Tag ghim phai DUY NHAT. Neu no da ton tai va tro vao mot anh KHAC thi
        # `docker tag` se am tham cuop ten: ban ke lan truoc tro vao mot anh khong
        # con mang ten do nua, va rollback theo tag se lay nham anh. Fail-closed.
        _RA_CU=$(docker image inspect -f '{{.Id}}' "qlts-${_S}:${_RA_TAG}" 2>/dev/null || true)
        if [ -n "$_RA_CU" ] && [ "$_RA_CU" != "$_RA_IMG" ]; then
            error "tag qlts-${_S}:${_RA_TAG} DA TON TAI va tro vao anh khac:
       dang co = $_RA_CU
       sap ghim = $_RA_IMG
       Ghi de la cuop ten khoi mot ban ke cu. DUNG truoc build."
        fi
        docker tag "$_RA_IMG" "qlts-${_S}:${_RA_TAG}"
        printf '%s\t%s\t%s\t%s\t%s\n' \
            "$_S" "$_RA_CID" "$_RA_IMG" "qlts-${_S}:${_RA_TAG}" "PENDING_DIGEST" >> "$_RA_TMP"
    done

    # Chỉ xuất bản bản kê khi TẤT CẢ tag đã xong. `set -e` cắt ngang ở trên thì
    # `$_RA_MANIFEST` không bao giờ xuất hiện — preflight của lượt sau sẽ thấy
    # thiếu bản kê và dừng, thay vì đọc một bản kê nửa vời.
    log "  ✓ đã ghim $_RA_SO_DICH_VU ảnh vào tag $_RA_TAG"

    # Niêm phong TRƯỚC preflight. Không có mốc này thì "đã qua preflight" chỉ
    # nói về MỘT nội dung nào đó tại MỘT thời điểm nào đó: một byte đổi sau
    # preflight vẫn được công bố và không gì phát hiện ra.
    _RA_H_PF=$(sha256sum "$_RA_TMP" | awk '{print $1}')         || error "không đọc được hash bản kê tạm để niêm phong"

    # --- Preflight NGAY, local-only, TRÊN TỆP TẠM ---------------------------
    # Thứ tự ở đây là toàn bộ vấn đề. Bản trước `mv` sang tên chính thức RỒI
    # mới chạy preflight: preflight đỏ thì một bản kê TRÔNG HOÀN CHỈNH vẫn nằm
    # lại, không mang dấu nào cho biết nó chưa đạt — và lượt sau (hoặc người
    # trực lúc 3 giờ sáng) sẽ tin nó. Nay preflight đọc chính tệp tạm; chỉ khi
    # RC=0 mới đặt tên chính thức. Đỏ ⇒ xoá tạm, không để lại gì.
    #
    # Local-only vì đẩy GHCR đòi credential ghi registry — một cổng riêng,
    # không nhét vào đường deploy routine.
    if ! QLTS_ROLLBACK_LOCAL_ONLY=1 \
         QLTS_ROLLBACK_TAG="$_RA_TAG" \
         QLTS_ROLLBACK_MANIFEST="$_RA_TMP" \
         bash "$SCRIPT_DIR/rollback-preflight.sh"; then
        rm -f -- "$_RA_TMP"
        error "rollback-preflight ĐỎ trên tài sản vừa tạo ($_RA_TAG).
       Bản kê KHÔNG được xuất bản — không có tệp nửa vời nào nằm lại.
       Tài sản không dùng được thì deploy này không có đường lùi. DỪNG trước
       build và trước CSDL."
    fi

    # ĐẠT rồi mới đặt tên chính thức. Từ giây này trở đi, sự tồn tại của
    # `$_RA_MANIFEST` LÀ bằng chứng "đã qua preflight".
    # Công bố no-clobber: `mv` GHI ĐÈ. `ln` dùng link(2) → EEXIST nếu đích
    # xuất hiện đồng thời, nên không có đường nào đè lên một bản kê có sẵn.
    _ra_kiem_hash_pf "sau-preflight" "$_RA_TMP"

    [ -L "$_RA_MANIFEST" ] && error "bản kê đích là SYMLINK — từ chối."
    [ -e "$_RA_MANIFEST" ] && error "bản kê đích xuất hiện trước khi công bố — từ chối ghi đè."
    # Lấy inode TRƯỚC, so hash SAU: phép so hash phải là LỆNH NGOÀI CUỐI
    # CÙNG trước `ln`. Bản trước đặt `stat` xen vào giữa hash và `ln`, nên
    # một thay đổi phát sinh trong chính lệnh `stat` ấy chỉ bị bắt SAU khi
    # đã công bố — bản kê bẩn đã mang tên chính thức rồi mới báo đỏ.
    # GHIM danh tính TMP bằng một file descriptor ĐỌC, mở TRƯỚC `ln`. `exec`
    # là builtin nên nó KHÔNG phá bất biến 'hash là lệnh ngoài cuối trước ln'.
    exec {_RA_FD}< "$_RA_TMP"         || error "không mở được file descriptor ghim trên $_RA_TMP"
    _RA_INO_T=$(stat -c '%d:%i' "$_RA_TMP")
    _ra_kiem_hash_pf "truoc-ln" "$_RA_TMP"
    ln "$_RA_TMP" "$_RA_MANIFEST"         || error "ln thất bại — đích đã tồn tại hoặc khác filesystem. KHÔNG ghi đè.
       TMP còn nguyên tại $_RA_TMP để điều tra."
    # Mọi lệnh ngoài từ đây trở xuống PHẢI đi qua nhánh dọn dẹp. Một `stat`
    # KHÔNG ĐỌC ĐƯỢC metadata nguy hiểm y như metadata SAI: gán trần thì
    # `set -e` cho nó thoát thẳng với mã thoát của chính `stat`, không thông
    # điệp, không dọn dẹp — và tên chính thức nằm lại nguyên vẹn.
    _RA_INO_F=$(stat -c '%d:%i' "$_RA_MANIFEST")         || _ra_loi_sau_ln "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T" "sau ln: KHÔNG ĐỌC ĐƯỢC dev:inode của bản kê."
    [ "$_RA_INO_T" = "$_RA_INO_F" ]         || _ra_loi_sau_ln "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T" "sau ln: TMP và bản kê KHÁC dev:inode ($_RA_INO_T vs $_RA_INO_F)."
    _RA_LINK=$(stat -c '%h' "$_RA_MANIFEST")         || _ra_loi_sau_ln "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T" "sau ln: KHÔNG ĐỌC ĐƯỢC link count của bản kê."
    [ "$_RA_LINK" -ge 2 ] || _ra_loi_sau_ln "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T" "sau ln: link count = $_RA_LINK (cần >= 2)."
    [ -L "$_RA_MANIFEST" ] && _ra_loi_sau_ln "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T" "sau ln: bản kê là SYMLINK — bất thường."
    [ -f "$_RA_MANIFEST" ] || _ra_loi_sau_ln "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T" "sau ln: bản kê không phải regular file."
    _RA_QF=$(stat -c '%a %U:%G' "$_RA_MANIFEST")         || _ra_loi_sau_ln "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T" "sau ln: KHÔNG ĐỌC ĐƯỢC quyền/chủ của bản kê."
    [ "$_RA_QF" = "600 root:root" ] || _ra_loi_sau_ln "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T" "sau ln: bản kê sai quyền/chủ: $_RA_QF"
    _ra_kiem_hash_sau_ln "sau-ln-tren-FINAL" "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T"
    # Bỏ TMP được, vì danh tính đã nằm ở FD chứ không ở tên tệp. FD giữ inode
    # sống xuyên qua `rm`, nên phép kiểm cuối vẫn có mốc để so.
    rm -f -- "$_RA_TMP"
    _ra_kiem_hash_sau_ln "sau-bo-TMP" "$_RA_MANIFEST" "$_RA_FD" "$_RA_INO_T"
    # Mọi hậu kiểm ĐÃ ĐẠT ⇒ mới thả ghim. Đỏ ở bất kỳ bước nào phía trên thì
    # `error` thoát process và kernel tự đóng FD — không có đường nào thả ghim
    # sớm hơn, nên nhánh dọn dẹp luôn còn mốc để so.
    exec {_RA_FD}<&-
    log "  ✓ preflight ĐẠT (local-only) — có đường lùi về $_RA_SRC"
    log "  ✓ bản kê: $_RA_MANIFEST"
fi

# =============================================================================
# Step 4: Build Docker images
# =============================================================================
log "Step 4/8: Building Docker images..."

# Kiểm lại HEAD ngay TRƯỚC build: đây là biên cuối cùng còn rẻ. Step 3 chỉ đọc
# biến và kiểm tệp template, nhưng nó vẫn là một khoảng thời gian trong đó một
# tiến trình khác (cron, người trực gõ tay, một lượt deploy chồng) có thể đã
# dịch cây. Build từ cây đã trôi = ảnh không khớp SHA mà run này khai.
#
# Dùng cùng phép hỏi setness với Step 2 (`${VAR+co}`), không phải `-n`: tới đây
# thì ca "có mặt nhưng rỗng" đã bị chặn ở trên, nhưng để hai cổng hỏi CÙNG MỘT
# câu thì sau này sửa một chỗ không làm chỗ kia lệch nghĩa trong im lặng.
if [ "${SHA_MONG_DOI+co}" = "co" ]; then
    if ! _HEAD_TRUOC_BUILD=$(git rev-parse HEAD 2>/dev/null); then
        error "không đọc được HEAD trước khi build — từ chối build khi chưa biết cây đang ở đâu"
    fi
    if [ "$_HEAD_TRUOC_BUILD" != "$SHA_MONG_DOI" ]; then
        error "cây đã DỊCH giữa Step 2 và Step 4: HEAD=$_HEAD_TRUOC_BUILD, chờ $SHA_MONG_DOI.
       KHÔNG build từ cây trôi. Chưa chạm CSDL, chưa dựng ảnh nào."
    fi
fi

docker compose -f docker-compose.yml --profile production --env-file .env.production build --parallel

# =============================================================================
# Step 4b: Config preflight (ẢNH VỪA BUILD, TRƯỚC KHI CHẠM CSDL)
# =============================================================================
# Vá 24-08-2026. Thứ tự cũ là: build → pg_dump → alembic → pre_deploy_check.
# ``alembic upgrade head`` import ``app.config``, nên MỘT biến môi trường thiếu
# làm ``Settings()`` raise BÊN TRONG Step 6 — nơi mọi mã thoát khác 0 bị phân
# loại là "Migration failed" và kích hoạt replay bản sao lên CSDL production.
#
# Tức là một lỗi CHÍNH TẢ trong `.env.production` kéo theo một lượt khôi phục
# CSDL hoàn toàn không cần thiết, lên một cơ sở dữ liệu CHƯA HỀ thay đổi. Và
# nếu chính lượt restore ấy vấp thì rơi vào trạng thái "schema nửa cũ nửa mới"
# mà Step 6 tự mô tả là không tiến không lùi. Cổng cấu hình DUY NHẤT trước đây
# (`pre_deploy_check.py`) lại nằm ở Step 7, tức SAU cả hai.
#
# Đặt ở đây vì đây là điểm sớm nhất mà phép kiểm còn có nghĩa: phải sau build
# (kiểm đúng ẢNH sắp chạy, không phải ảnh cũ) và trước ``pg_dump`` (hỏng thì
# chưa có bản sao nào được tạo, chưa migration nào chạy, và nhánh restore không
# bao giờ được chạm tới).
#
# ``--entrypoint python`` — cùng lý do với Step 6 và Step 7: `docker compose run`
# KHÔNG đè ENTRYPOINT, nên thiếu cờ này thì chính bước preflight sẽ chạy trọn
# ``alembic upgrade head`` + ``sync_notification_rules`` trước khi tới script,
# tức gây ra đúng thứ nó sinh ra để ngăn.
#
# Không có ``|| warn``: ``set -e`` ở đầu tệp để mã thoát khác 0 tự dừng deploy.
log "Step 4b/8: Config preflight (candidate image)..."
docker compose -f docker-compose.yml --profile production --env-file .env.production \
    run --rm --no-deps --entrypoint python backend -m scripts.preflight_config
log "Config preflight passed — CSDL chưa bị chạm"

# =============================================================================
# Step 5: Database backup (before migration)
# =============================================================================
log "Step 5/8: Backing up database..."
mkdir -p "$BACKUP_DIR"

# Review 2026-07-20: ba sửa đổi, cùng một gốc — bản backup này là đường
# rollback DUY NHẤT của Step 6 nên nó phải hoặc dùng được, hoặc biến mất
# hẳn; tuyệt đối không được tồn tại ở dạng "có file nhưng vô dụng".
#   1. Bỏ ``2>/dev/null``: trước đây lý do pg_dump chết bị nuốt sạch, vận
#      hành chỉ thấy "may be first deploy" — câu chẩn đoán sai hướng.
#   2. ``--clean --if-exists``: dump cũ KHÔNG có DROP nên khi Step 6 phát
#      lại lên DB còn nguyên object thì mọi câu lệnh lỗi "already exists".
#      Tức đường rollback trước đây KHÔNG THỂ khôi phục kể cả với file dump
#      hoàn hảo. Có DROP thì replay mới thực sự đưa DB về trạng thái cũ.
#   3. Xoá xác file khi dump fail: phép chuyển hướng ``>`` tạo file NGAY CẢ
#      khi pg_dump chết, để lại file 0 byte. Cổng ``[ -s ]`` ở Step 6 đã
#      chặn được, nhưng dọn luôn cho khỏi ai nhặt nhầm sau này.
#   4. Vá 13-08-2026 — FAIL-CLOSED. Ba nhánh dưới đây trước đây đều chỉ
#      ``warn`` rồi để script đi tiếp vào Step 6, tức deploy vẫn chạy
#      migration khi KHÔNG có đường lùi. Nay cả ba đều ``error``.
#      Riêng nhánh "PostgreSQL không sẵn sàng" trước đây đoán là "first
#      deploy?" — một suy đoán nguy hiểm: nó không phân biệt nổi máy trắng
#      với **sự cố của một CSDL đang có dữ liệu**, mà ca thứ hai thì đi
#      tiếp là hỏng nặng. Bootstrap máy trắng, nếu cần, phải là một mode
#      RIÊNG (``INITIAL_DEPLOY=true``) có guard chứng minh chưa hề có
#      DB/volume — cố tình KHÔNG mở lối bỏ backup chung ở đây.
_BAN_SAO="$BACKUP_DIR/pre_deploy_${TIMESTAMP}.sql"
if ! docker compose -f docker-compose.yml --env-file .env.production exec -T postgres pg_isready -U "${POSTGRES_USER:-qlts}" >/dev/null 2>&1; then
    error "PostgreSQL không sẵn sàng — KHÔNG sao lưu được, nên KHÔNG đi tiếp vào migration.
       Đây có thể là sự cố của một CSDL đang có dữ liệu, không phải lần cài đầu.
       Kiểm tra: docker compose -f docker-compose.yml --profile production ps postgres"
fi

if ! docker compose -f docker-compose.yml --env-file .env.production exec -T postgres pg_dump \
    --clean --if-exists \
    -U "${POSTGRES_USER:-qlts}" \
    "${POSTGRES_DB:-qlts_production}" \
    > "$_BAN_SAO"; then
    rm -f "$_BAN_SAO"
    error "pg_dump THẤT BẠI — deploy dừng tại đây, KHÔNG chạy migration khi không có đường lùi."
fi

# ``>`` tạo tệp kể cả khi pg_dump chết giữa chừng, nên kích thước là phép
# kiểm cuối trước khi coi bản sao là dùng được.
if [ ! -s "$_BAN_SAO" ]; then
    rm -f "$_BAN_SAO"
    error "Bản sao lưu RỖNG — deploy dừng tại đây, KHÔNG chạy migration khi không có đường lùi."
fi

log "Database backup saved: pre_deploy_${TIMESTAMP}.sql"

# =============================================================================
# Step 6: Start infrastructure & run migrations
# =============================================================================
log "Step 6/8: Starting infrastructure & running migrations..."

# Start infra services first (always — postgres + redis needed both modes)
docker compose -f docker-compose.yml --profile production --env-file .env.production up -d postgres redis
log "Waiting for PostgreSQL to be healthy..."
sleep 5

if [ "${IS_CUTOVER}" -eq 1 ]; then
    # Cold cutover: skip auto-alembic. Operator runs ``alembic upgrade head``
    # manually post-deploy per RUNBOOK §7.2 T+1:30 to stream log per
    # migration step + checkpoint mid-flow. Auto-rollback path also
    # disabled here because cutover scenario uses snapshot-restore (not
    # in-place SQL replay) per RUNBOOK §8.1.
    cutover "Step 6: SKIP auto-alembic (cutover mode)"
    cutover "Operator runs manually post-deploy:"
    cutover "  docker compose -f docker-compose.yml --profile production exec backend alembic upgrade head"
else
    # Routine deploy: auto-migrate with built-in rollback on failure.
    #
    # ``--entrypoint`` là BẮT BUỘC (vá 13-08-2026): ảnh backend khai
    # ENTRYPOINT ["/app/docker-entrypoint.sh"], mà ``docker compose run`` chỉ
    # đè CMD chứ KHÔNG đè ENTRYPOINT. Thiếu nó thì one-off này chạy TRỌN
    # entrypoint — `alembic upgrade head` + `sync_notification_rules` — rồi
    # mới chạy tới lệnh mình gọi, tức migrate hai lượt cho một lần deploy.
    # ``--no-deps`` vì postgres/redis vừa được dựng ngay phía trên.
    docker compose -f docker-compose.yml --profile production --env-file .env.production \
        run --rm --no-deps --entrypoint alembic backend upgrade head \
        && log "Migrations completed successfully" \
        || {
            warn "Migration failed! Rolling back..."
            # Review 2026-07-20: cổng này trước đây NÓI DỐI theo hai cách.
            #   1. ``[ -f ]`` chỉ hỏi "file có tồn tại", mà Step 5 tạo file
            #      kể cả khi pg_dump chết ⇒ luôn TRUE ⇒ phát lại 0 byte.
            #      Nay ``[ -s ]`` đòi file KHÁC RỖNG.
            #   2. psql không có ``ON_ERROR_STOP=1`` nên chạy tiếp qua mọi
            #      lỗi rồi thoát 0 ⇒ dòng "Database restored" in ra vô điều
            #      kiện, kể cả khi không một câu lệnh nào chạy được. Nay
            #      psql dừng ở lỗi đầu tiên và ta CHỈ báo đã khôi phục khi
            #      psql thực sự thành công.
            # Trạng thái tệ nhất (migration hỏng VÀ restore hỏng) giờ được
            # nói thẳng kèm đường dẫn file, thay vì bị che bằng lời trấn an.
            #
            # ⚠️ GIỚI HẠN ĐÃ ĐO (diễn tập 2026-07-20, postgres 16.13):
            # dump chỉ DROP những object nó BIẾT, tức những gì tồn tại lúc
            # chụp ở Step 5. Bảng/kiểu do migration hỏng tạo ra SAU đó sẽ
            # SỐNG SÓT qua restore. Dữ liệu, cột, index và alembic_version
            # đều về đúng bản cũ (đã kiểm), nhưng "restored" KHÔNG đồng
            # nghĩa "sạch như chưa từng deploy" — kiểm object thừa bằng
            # ``\dt`` trước khi deploy lại.
            if [ -s "$BACKUP_DIR/pre_deploy_${TIMESTAMP}.sql" ]; then
                if docker compose -f docker-compose.yml --env-file .env.production exec -T postgres psql \
                    -v ON_ERROR_STOP=1 \
                    -U "${POSTGRES_USER:-qlts}" \
                    "${POSTGRES_DB:-qlts_production}" \
                    < "$BACKUP_DIR/pre_deploy_${TIMESTAMP}.sql"; then
                    error "Migration failed. Database restored from backup."
                fi
                error "Migration failed AND restore FAILED. DB có thể đang ở trạng thái LAI (schema nửa cũ nửa mới). KHÔNG deploy tiếp. Khôi phục tay từ: $BACKUP_DIR/pre_deploy_${TIMESTAMP}.sql"
            fi
            error "Migration failed. No backup available to restore."
        }
fi

# =============================================================================
# Step 7: Pre-deploy checks (Casbin policies)
# =============================================================================
log "Step 7/8: Running pre-deploy checks..."

# Vá 13-08-2026: bỏ nhánh ``|| warn``. `pre_deploy_check.py` TỰ phân loại
# rồi mới chọn mã thoát — thiếu WARNING_POLICIES hay thiếu kế thừa vai trò
# thì in cảnh báo và vẫn exit 0; chỉ thiếu CRITICAL_POLICIES (hoặc không nối
# được CSDL) mới exit 1 kèm "CRITICAL: DEPLOY BLOCKED". Nhánh ``|| warn`` cũ
# đã nuốt đúng cái mã thoát ấy, biến một cổng chặn thành một dòng chữ vàng:
# script vẫn đi tiếp sang Step 8 và mở traffic vào một hệ thống mà chính nó
# vừa tuyên bố là UNUSABLE. Nay để mã thoát khác 0 tự chặn deploy
# (``set -e`` ở đầu tệp).
# ``--entrypoint python`` — cùng lý do với Step 6, nhưng ở đây hậu quả nặng
# hơn: bước này chạy TRƯỚC Step 8, tức trước chỗ cold cutover export ba cờ =
# false. Thiếu override thì ngay cả `COLD_CUTOVER=true` cũng tự migrate + sync
# tại đây, phá đúng lời hứa "operator chạy tay" mà RUNBOOK §7.2 dựa vào.
docker compose -f docker-compose.yml --profile production --env-file .env.production \
    run --rm --no-deps --entrypoint python backend scripts/pre_deploy_check.py
log "Pre-deploy checks passed"

# =============================================================================
# Step 8: Rolling restart
# =============================================================================
log "Step 8/8: Rolling restart..."

if [ "${IS_CUTOVER}" -eq 1 ]; then
    # Cold cutover: inject 3 entrypoint gate flags = false so backend
    # container starts without auto-running migration / sync / Casbin
    # policy load. Operator runs those steps manually per RUNBOOK §7.2.
    # Defensive: explicit ``false`` lowercase per docker-entrypoint.sh
    # parse contract (any other value = run as usual).
    cutover "Step 8: Backend env: 3 cutover flags = false (operator manual sequence)"
    export RUN_MIGRATIONS_ON_STARTUP="false"
    export RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP="false"
    export RUN_CASBIN_LOAD_ON_STARTUP="false"
fi

# Start backend + celery (env flags propagate via process env when cutover mode;
# routine mode = unset → entrypoint defaults to ``true`` = auto-run as before)
docker compose -f docker-compose.yml --profile production --env-file .env.production up -d \
    backend celery-worker celery-beat

# =============================================================================
# CỔNG HEALTH (vá 09-09-2026) — MỘT helper cho cả backend lẫn frontend
# =============================================================================
# Bản cũ có hai vòng lặp chép tay, và cả hai đọc health bằng
# `docker compose ps <svc> | grep -q "healthy"`. Hai lỗi chồng nhau:
#
#   1. `grep` khớp SUBSTRING. Cột STATUS in `Up 30 seconds (unhealthy)` — chuỗi
#      đó CHỨA "healthy" ⇒ `break` ngay vòng đầu ⇒ `timeout` vẫn 60 ⇒ cổng
#      `[ $timeout -le 0 ]` KHÔNG BAO GIỜ đúng. Container unhealthy mà deploy
#      báo "completed successfully".
#   2. Bất đối xứng: backend có nhánh timeout, frontend KHÔNG có gì cả — hết
#      60 giây là rơi thẳng xuống nginx-apply rồi in dòng thành công.
#
# Vá bằng CẤU TRÚC, không bằng cách nhớ thêm một `if`: một hàm duy nhất phục vụ
# cả hai service, nên không còn chỗ cho hai đường xử lý lệch nhau.
#
# NGUỒN CHUẨN: `scripts/nginx-apply.sh:_cho_healthy`. Bản này khác 4 điểm CÓ CHỦ
# Ý: (a) không kéo `--profile candidate` (deploy.sh không dựng container ứng
# viên); (b) `error`/`exit 1` thay vì `return 1` — deploy.sh không có bước dọn
# nào sau đó, và `return 1` trong thân `if` sẽ bị `set -e` bỏ qua, đúng loại
# fail-open đang vá; (c) CHẶN khi có nhiều container thay vì `| head -1` chọn
# bừa; (d) chặn NGAY khi service không khai healthcheck thay vì chờ hết hạn.
_HAN_HEALTH="${QLTS_HEALTH_TIMEOUT:-60}"
case "$_HAN_HEALTH" in
    ''|*[!0-9]*) error "QLTS_HEALTH_TIMEOUT phải là số nguyên, nhận: '$_HAN_HEALTH'" ;;
esac
if [ "$_HAN_HEALTH" -lt 1 ] || [ "$_HAN_HEALTH" -gt 600 ]; then
    error "QLTS_HEALTH_TIMEOUT ngoài khoảng 1..600: '$_HAN_HEALTH'"
fi

# Chờ MỘT service tới đúng trạng thái `healthy`. Mọi kết cục khác đều exit 1.
_cho_healthy_dv() {
    local ten="$1" han="$2"
    local ds so cid tt sk ma het

    # `ps -aq` trả ID, không trả chữ — cắt hẳn đường đọc health bằng cách grep
    # một dòng văn bản dành cho người đọc.
    if ! ds=$(docker compose -f docker-compose.yml --profile production \
                  --env-file .env.production ps -aq "$ten" 2>/dev/null); then
        error "không liệt kê được container của service '$ten' (docker compose ps -aq thất bại)"
    fi
    so=$(printf '%s\n' "$ds" | grep -c '[^[:space:]]' || true)
    if [ "$so" -eq 0 ]; then
        error "không thấy container nào cho service '$ten' — KHÔNG có gì để nghiệm thu"
    fi
    if [ "$so" -gt 1 ]; then
        error "service '$ten' đang có $so container — MƠ HỒ, không đoán bừa.
       Dọn container thừa rồi deploy lại: docker compose -f docker-compose.yml ps -a $ten"
    fi
    cid=$(printf '%s\n' "$ds" | grep -m1 '[^[:space:]]')

    het=$((SECONDS + han))
    while [ "$SECONDS" -lt "$het" ]; do
        if ! tt=$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null); then
            error "docker inspect THẤT BẠI khi đọc State.Status của '$ten' (cid=$cid)"
        fi
        # `{{else}}` biến "không khai healthcheck" thành một giá trị NÓI ĐƯỢC
        # THÀNH LỜI, thay vì chuỗi rỗng trôi qua mọi phép so mà không ai thấy.
        if ! sk=$(docker inspect \
                    -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}khong-co-healthcheck{{end}}' \
                    "$cid" 2>/dev/null); then
            error "docker inspect THẤT BẠI khi đọc State.Health.Status của '$ten' (cid=$cid)"
        fi

        case "$tt" in
            exited|dead)
                ma=$(docker inspect -f '{{.State.ExitCode}}' "$cid" 2>/dev/null || echo "?")
                error "'$ten' đã DỪNG (status=$tt, exit=$ma) — KHÔNG deploy tiếp" ;;
            restarting)
                error "'$ten' đang quay vòng khởi động lại — KHÔNG deploy tiếp" ;;
        esac

        # So BẰNG NHAU trên chuỗi đầy đủ. Không grep, không `case *healthy*`.
        # Đây là lối ra xanh DUY NHẤT của hàm.
        if [ "$sk" = "healthy" ]; then
            return 0
        fi
        if [ "$sk" = "unhealthy" ]; then
            error "'$ten' UNHEALTHY — KHÔNG deploy tiếp"
        fi
        if [ "$sk" = "khong-co-healthcheck" ]; then
            error "'$ten' KHÔNG khai healthcheck — không có gì để nghiệm thu"
        fi
        sleep 2
    done
    error "'$ten' quá hạn ${han}s (status=${tt:-?}, health=${sk:-?}) — KHÔNG deploy tiếp"
}

log "Waiting for backend to be healthy..."
_cho_healthy_dv backend "$_HAN_HEALTH"
log "Backend healthy"

# Start frontend + certbot. nginx CỐ Ý không nằm ở đây.
#
# Trước bản vá này dòng dưới là `up -d frontend nginx certbot`, rồi Step 8b
# `--force-recreate` lại chính container ấy khoảng 60 giây sau. Mỗi lần deploy
# có đụng khai báo nginx là HAI vòng đời container và HAI khe từ chối kết nối,
# cho một thay đổi cấu hình duy nhất.
#
# `--no-deps` là BẮT BUỘC ở đây: `certbot` khai `depends_on: nginx`, nên thiếu
# nó Compose kéo nginx lên bất kể ta đã bỏ tên nginx khỏi dòng lệnh.
# backend/frontend đã được khởi động và chờ healthy ngay phía trên.
docker compose -f docker-compose.yml --profile production --env-file .env.production up -d \
    --no-deps frontend certbot

log "Waiting for frontend to be healthy..."
_cho_healthy_dv frontend "$_HAN_HEALTH"
log "Frontend healthy"

# =============================================================================
# Step 8b: áp cấu hình nginx — THỬ TRƯỚC, THAY SAU
# =============================================================================
# Toàn bộ nhịp nằm ở `scripts/nginx-apply.sh`: dựng `nginx-candidate`, đo hành
# vi thật của nó (TLS + SNI thật, route backend, route frontend), CHỈ KHI ĐẠT
# mới đụng tới container đang phục vụ. Tách ra tệp riêng để bài kiểm hồi quy
# chạy được ĐÚNG đoạn mã này thay vì một bản chép lại trong test.
log "Step 8b: áp cấu hình nginx (thử trên candidate trước)..."
bash "$SCRIPT_DIR/nginx-apply.sh" "$DOMAIN"     || error "không áp được cấu hình nginx — xem log phía trên"


# =============================================================================
# Step 8c: ghi marker cho lần deploy SAU
# =============================================================================
# Đặt ở đây, sau khi mọi cổng health đã đạt, vì marker tuyên bố "các container
# NÀY đang phục vụ commit NÀY". Ghi sớm hơn là tuyên bố một điều chưa đúng.
#
# Nguyên tử: viết tệp tạm rồi `mv`. Một marker bị cắt ngang giữa chừng còn tệ
# hơn không có marker — Step 3b của lượt sau sẽ đọc được vài dòng đầu, thấy đủ
# `# deployed-sha`, rồi lệch ở service thứ ba và dừng với thông điệp sai
# nguyên nhân. `mv` trên cùng filesystem là atomic, nên marker hoặc là bản cũ
# nguyên vẹn, hoặc là bản mới nguyên vẹn, không có trạng thái thứ ba.
log "Step 8c: ghi marker deploy..."

_RA_SHA_MOI=$(git rev-parse HEAD) || error "không đọc được HEAD để ghi marker"
_ra_cong_ops "step8c"

# Cùng một lớp lỗi như Step 3b: tên theo `$$` đoán được + `: >` ghi xuyên
# symlink. `mktemp` đóng cả hai.
_RA_MK_TMP=$(mktemp "$_RA_OPS/.last-deploy.XXXXXXXXXX")     || error "không tạo được tệp tạm marker nguyên tử trong $_RA_OPS"
_ra_kiem_tmp "$_RA_MK_TMP" "$_RA_OPS" '.last-deploy.*' "marker"

# Marker CŨ (nếu có) phải lành TRƯỚC khi thay. Nếu nó là symlink thì `mv -T`
# sẽ thay chính symlink — nhưng ta vẫn từ chối, vì một marker symlink nghĩa là
# đã có ai đó dựng sẵn đường ghi và ta không hiểu trạng thái đó.
_RA_MK_CU_HASH=""
if [ -L "$_RA_MARKER" ]; then
    rm -f -- "$_RA_MK_TMP"
    error "marker hiện tại là SYMLINK — từ chối thay thế."
fi
if [ -e "$_RA_MARKER" ]; then
    if [ ! -f "$_RA_MARKER" ]; then
        rm -f -- "$_RA_MK_TMP"
        error "marker hiện tại không phải regular file — từ chối thay thế."
    fi
    _RA_MK_Q=$(stat -c '%a %U:%G' "$_RA_MARKER")
    if [ "$_RA_MK_Q" != "600 root:root" ]; then
        rm -f -- "$_RA_MK_TMP"
        error "marker hiện tại sai quyền/chủ: $_RA_MK_Q — từ chối thay thế."
    fi
    _RA_MK_CU_HASH=$(sha256sum "$_RA_MARKER" | awk '{print $1}')
    _RA_MK_CU_INO=$(stat -c '%d:%i' "$_RA_MARKER")
fi
{
    printf '# marker-version\t2\n'
    printf '# deployed-sha\t%s\n' "$_RA_SHA_MOI"
    printf '# deployed-at\t%s\n'  "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if [ "$_RA_BO_QUA" = "1" ]; then
        printf '# asset-skipped\t%s\n' "$_RA_REASON_GIATRI"
    else
        printf '# asset-tag\t%s\n' "$_RA_TAG"
    fi
} >> "$_RA_MK_TMP"

# Duong BO QUA tai san (`QLTS_SKIP_ROLLBACK_ASSET=1`) khong di qua Step 3b,
# nhung marker van phai ghi du moi service. Goi lai o day — ham tu no-op neu
# da tinh roi.
_ra_bao_dam_dich_vu

for _S in $_RA_DICH_VU; do
    _RA_CID_MOI=$($_RA_COMPOSE ps -q "$_S" 2>/dev/null || true)
    if [ -z "$_RA_CID_MOI" ]; then
        rm -f -- "$_RA_MK_TMP"
        error "sau deploy vẫn không thấy container cho '$_S' — từ chối ghi marker nửa vời.
       Marker sai còn nguy hiểm hơn marker thiếu: lượt deploy sau sẽ ghim ảnh cũ
       theo một SHA không đúng."
    fi
    _RA_IMG_MOI=$(docker inspect -f '{{.Image}}' "$_RA_CID_MOI" 2>/dev/null || true)
    case "$_RA_IMG_MOI" in
        sha256:*) : ;;
        *) rm -f -- "$_RA_MK_TMP"
           error "image ID sau deploy của '$_S' không hợp lệ: '$_RA_IMG_MOI' — từ chối ghi marker." ;;
    esac
    printf '%s\t%s\t%s\n' "$_S" "$_RA_IMG_MOI" "$_RA_CID_MOI" >> "$_RA_MK_TMP"
done

# Kiểm schema + niêm phong TRƯỚC khi công bố. Mọi lỗi tới đây đều để marker
# CŨ nguyên vẹn byte — ta chưa hề chạm vào nó.
_ra_kiem_schema_marker "$_RA_MK_TMP"
_ra_kiem_marker_vs_live "truoc-mv" "$_RA_MK_TMP"

# Niêm phong bản MỚI ở đây, TRƯỚC checkpoint marker cũ. Đặt nó SAU
# checkpoint là mở cho một lệnh ngoài xen vào giữa checkpoint và `mv`: thay
# đổi marker cũ phát sinh trong chính lệnh hash ấy sẽ lọt, vì không còn phép
# so nào chạy sau nó. Từ dòng này tới `mv` chỉ còn checkpoint đích.
_RA_MK_HASH=$(sha256sum "$_RA_MK_TMP" | awk '{print $1}')

# Checkpoint đích NGAY TRƯỚC `mv`: trạng thái đã xác minh ở đầu Step 8c có thể
# đã bị thay trong lúc ta dựng bản mới.
if [ -n "$_RA_MK_CU_HASH" ]; then
    [ -L "$_RA_MARKER" ] && error "ngay trước mv: marker hiện tại thành SYMLINK — từ chối."
    [ -f "$_RA_MARKER" ] || error "ngay trước mv: marker hiện tại không còn là regular file."
    _RA_MK_Q3=$(stat -c '%a %U:%G' "$_RA_MARKER")
    [ "$_RA_MK_Q3" = "600 root:root" ] || error "ngay trước mv: marker hiện tại sai quyền/chủ: $_RA_MK_Q3"
    _RA_MK_I3=$(stat -c '%d:%i' "$_RA_MARKER")
    [ "$_RA_MK_I3" = "$_RA_MK_CU_INO" ]         || error "ngay trước mv: marker hiện tại ĐỔI dev:inode ($_RA_MK_I3 ≠ $_RA_MK_CU_INO) — đã bị thay giữa chừng."
    _RA_MK_H3=$(sha256sum "$_RA_MARKER" | awk '{print $1}')
    [ "$_RA_MK_H3" = "$_RA_MK_CU_HASH" ]         || error "ngay trước mv: marker hiện tại ĐỔI nội dung — đã bị thay giữa chừng."
else
    [ -L "$_RA_MARKER" ] && error "ngay trước mv: marker XUẤT HIỆN dưới dạng symlink — từ chối."
    [ -e "$_RA_MARKER" ] && error "ngay trước mv: marker XUẤT HIỆN dù đầu lượt không có — từ chối."
fi

# `mv -T --`: đích là THƯ MỤC thì `mv src dst` trần sẽ CHUYỂN VÀO TRONG và trả
# 0 — một thành công giả để lại marker cũ nằm nguyên chỗ, còn bản mới biến mất
# vào một thư mục con. `-T` coi đích là TỆP nên ca đó đỏ đúng lúc.
mv -T -- "$_RA_MK_TMP" "$_RA_MARKER"     || error "không thay được marker: \`mv -T\` thất bại.
       KHÔNG khẳng định marker cũ còn nguyên — đích có thể đã bị thay (ví dụ
       thành thư mục) trong lúc chạy, và đó chính là lý do \`mv -T\` đỏ.
       TMP còn nguyên tại: $_RA_MK_TMP
       Hãy xem trạng thái thật của $_RA_MARKER trước khi làm gì tiếp.
       KHÔNG cleanup."

# Hậu kiểm: thứ vừa công bố đúng là thứ vừa validate.
[ -L "$_RA_MARKER" ] && error "sau công bố: marker là SYMLINK — bất thường."
[ -f "$_RA_MARKER" ] || error "sau công bố: marker không phải regular file."
_RA_MK_Q2=$(stat -c '%a %U:%G' "$_RA_MARKER")
[ "$_RA_MK_Q2" = "600 root:root" ] || error "sau công bố: marker sai quyền/chủ: $_RA_MK_Q2"
_RA_MK_HASH2=$(sha256sum "$_RA_MARKER" | awk '{print $1}')
[ "$_RA_MK_HASH2" = "$_RA_MK_HASH" ]     || error "sau công bố: marker KHÁC bản đã validate ($_RA_MK_HASH2 ≠ $_RA_MK_HASH)."
_ra_kiem_schema_marker "$_RA_MARKER"
_ra_kiem_marker_vs_live "sau-mv" "$_RA_MARKER"
log "  ✓ marker: $_RA_MARKER (sha=$_RA_SHA_MOI, $_RA_SO_DICH_VU/$_RA_SO_DICH_VU ảnh, hash=${_RA_MK_HASH:0:16}…)"

# =============================================================================
# Done
# =============================================================================
log "========================================="
log "Deployment completed successfully!"
log "========================================="
log "Domain: https://$DOMAIN"
log "Health: https://$DOMAIN/health"
log ""
log "Useful commands:"
log "  docker compose -f docker-compose.yml --profile production logs -f       # Follow all logs"
log "  docker compose -f docker-compose.yml --profile production ps            # Service status"
log "  docker compose -f docker-compose.yml --profile production logs backend   # Backend logs"
