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

# =============================================================================
# KHOÁ VPS (vòng 7b, N10) — MỘT lượt deploy tại một thời điểm, fail-closed
# =============================================================================
# `cancel-in-progress: false` (7a) chỉ chặn GitHub huỷ một run đang chạy. Nó KHÔNG
# biết gì về tiến trình trên VPS: phiên SSH bị cắt (command_timeout, mạng) mà bash
# từ xa SỐNG TIẾP thì với GitHub run ấy đã xong, run kế được chạy — và hai lượt
# deploy cùng ghi một cây/CSDL. Khoá `flock` ở đây là lớp chủ sở hữu của bất biến
# "một lượt tại một thời điểm" trên VPS; nhóm concurrency là lớp phía GitHub.
#
# Lấy NGAY ĐẦU, trước mọi thay đổi (cây, ảnh, container, CSDL) và trước khi nạp
# .env.production. deploy.yml lấy khoá TRƯỚC `git fetch`/`git merge` rồi để fd 9
# kế thừa xuống đây (QLTS_KHOA_DEPLOY_FD=9): kiểm fd ấy trỏ ĐÚNG tệp khoá và đang
# giữ khoá. Chạy tay: tự lấy. Không chờ (`-n`): đang có lượt khác ⇒ DỪNG ngay.
# Khoá theo fd ⇒ được giữ tới khi tiến trình (kể cả trap) và mọi tiến trình con
# còn giữ fd thoát — một `docker compose run` migration sống sót sau SIGKILL vẫn
# giữ khoá, nên lượt sau không chen vào giữa migration. Đường dẫn đổi được qua
# QLTS_KHOA_DEPLOY (sân khấu test); deploy.yml dùng ĐÚNG giá trị mặc định (test khoá).
_KHOA_DEPLOY="${QLTS_KHOA_DEPLOY:-/run/lock/qlts-deploy.lock}"
command -v flock >/dev/null 2>&1 \
    || error "thiếu lệnh 'flock' (util-linux) — không lấy được khoá deploy $_KHOA_DEPLOY. DỪNG trước mọi thay đổi."
if [ "${QLTS_KHOA_DEPLOY_FD+co}" = "co" ]; then
    [ "$QLTS_KHOA_DEPLOY_FD" = "9" ] \
        || error "QLTS_KHOA_DEPLOY_FD='$QLTS_KHOA_DEPLOY_FD' — chỉ nhận 9 (khoá kế thừa từ deploy.yml). DỪNG trước mọi thay đổi."
    { [ -e /proc/self/fd/9 ] && [ /proc/self/fd/9 -ef "$_KHOA_DEPLOY" ]; } \
        || error "khoá kế thừa: fd 9 KHÔNG trỏ tới $_KHOA_DEPLOY — DỪNG trước mọi thay đổi."
    flock -n 9 \
        || error "khoá kế thừa: fd 9 trỏ đúng tệp nhưng KHÔNG giữ được khoá $_KHOA_DEPLOY — DỪNG trước mọi thay đổi."
    log "Khoá deploy: kế thừa từ workflow (fd 9 → $_KHOA_DEPLOY)"
else
    exec 9>>"$_KHOA_DEPLOY" \
        || error "không mở được tệp khoá $_KHOA_DEPLOY — DỪNG trước mọi thay đổi."
    flock -n 9 \
        || error "một lượt deploy KHÁC đang giữ khoá $_KHOA_DEPLOY — DỪNG trước mọi thay đổi (cây, ảnh, container, CSDL chưa bị đụng).
       Có thể là lượt trước mất SSH mà bash trên VPS vẫn chạy tiếp. Xem: fuser -v $_KHOA_DEPLOY ; ps -ef | grep -E 'deploy.sh|docker compose'"
    log "Khoá deploy: đã lấy $_KHOA_DEPLOY"
fi

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

# Vòng 4 (F40): hai biến của đường ĐI TIẾP SAU MIGRATION ĐỎ — cùng luật với cổng
# thoát hiểm ở trên: chỉ được đến từ DÒNG LỆNH của đúng lượt đó, chụp TRƯỚC khi
# nạp .env.production, và có mặt trong tệp ấy ⇒ DỪNG (xem ngay sau `source`).
_DT_CO=0
_DT_CO_GIATRI=""
_DT_TU=0
_DT_TU_GIATRI=""
if [ "${QLTS_DI_TIEP_SAU_MIGRATE_DO+co}" = "co" ]; then
    _DT_CO=1
    _DT_CO_GIATRI="$QLTS_DI_TIEP_SAU_MIGRATE_DO"
fi
if [ "${QLTS_DI_TIEP_TU+co}" = "co" ]; then
    _DT_TU=1
    _DT_TU_GIATRI="$QLTS_DI_TIEP_TU"
fi
unset QLTS_DI_TIEP_SAU_MIGRATE_DO QLTS_DI_TIEP_TU

# Vòng 7d: biến PHIÊN (độ dài phiên SSH, mốc bắt đầu, bốn hạn đo trên VPS) chỉ đến từ
# deploy.yml qua môi trường của lượt — cùng luật với hai nhóm trên: chụp TRƯỚC khi nạp
# .env.production, tệp ấy khai lại ⇒ DỪNG, rồi trả lại đúng giá trị đã chụp.
_PH_DS="QLTS_PHIEN_GIAY QLTS_PHIEN_BAT_DAU QLTS_HAN_PG_DUMP QLTS_HAN_MIGRATION QLTS_HAN_BUOC7_8 QLTS_HAN_NGINX_APPLY"
declare -A _PH_CHUP=()
for _PH_V in $_PH_DS; do
    if [ "${!_PH_V+co}" = "co" ]; then _PH_CHUP[$_PH_V]="${!_PH_V}"; fi
    unset "$_PH_V"
done

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
if [ "${QLTS_DI_TIEP_SAU_MIGRATE_DO+co}" = "co" ] || [ "${QLTS_DI_TIEP_TU+co}" = "co" ]; then
    error "[đi tiếp] QLTS_DI_TIEP_SAU_MIGRATE_DO / QLTS_DI_TIEP_TU nằm trong .env.production — từ chối.
       Đường đi tiếp sau migration đỏ là thao tác THỦ CÔNG TỪNG LƯỢT, không phải cấu
       hình thường trực. Gỡ chúng khỏi .env.production; đặt trên dòng lệnh của lượt đó."
fi
unset QLTS_DI_TIEP_SAU_MIGRATE_DO QLTS_DI_TIEP_TU
for _PH_V in $_PH_DS; do
    [ "${!_PH_V+co}" != "co" ] || error "[phiên] $_PH_V nằm trong .env.production — biến phiên chỉ đến từ deploy.yml (một nguồn với command_timeout). Gỡ khỏi tệp. DỪNG."
done
for _PH_V in "${!_PH_CHUP[@]}"; do export "$_PH_V=${_PH_CHUP[$_PH_V]}"; done
_PH_CO=0
_PH_BAT_DAU=""
if [ "${_PH_CHUP[QLTS_PHIEN_GIAY]+co}" = "co" ] || [ "${_PH_CHUP[QLTS_PHIEN_BAT_DAU]+co}" = "co" ]; then
    { [ "${_PH_CHUP[QLTS_PHIEN_GIAY]+co}" = "co" ] && [ "${_PH_CHUP[QLTS_PHIEN_BAT_DAU]+co}" = "co" ]; } \
        || error "[phiên] chỉ có MỘT trong hai QLTS_PHIEN_GIAY / QLTS_PHIEN_BAT_DAU — deploy.yml truyền thiếu. DỪNG trước mọi thay đổi."
    _PH_CO=1
    _PH_BAT_DAU="${_PH_CHUP[QLTS_PHIEN_BAT_DAU]}"
fi

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
# Đọc Docker CÓ HẠN, phân biệt "KHÔNG TỒN TẠI" với "KHÔNG ĐỌC ĐƯỢC" (vòng 5, F43)
# =============================================================================
# Lỗi đọc (daemon mất kết nối, lệnh treo) KHÔNG phải bằng chứng container đã biến
# mất. `docker inspect` lỗi chỉ được hiểu là "không tồn tại" khi phép liệt kê
# `docker ps -a --filter id=…` CHẠY ĐƯỢC (rc 0) và trả RỖNG; mọi trường hợp khác
# là KHÔNG ĐỌC ĐƯỢC. Mỗi lệnh đọc có hạn riêng (QLTS_HAN_LENH_DOCKER, mặc định
# 10 s): daemon kẹt không được giữ trap / hướng dẫn / vòng chờ mãi.
# Vòng 6b (F45, owner chốt): KHÔI PHỤC 10 s. Vòng 6 hạ xuống 5 s chỉ để trần trap < 20 phút —
# lý do không đủ: `command_timeout: 20m` là của CẢ phiên SSH, không phải phần còn lại cho trap.
_DCG_HAN_LENH="${QLTS_HAN_LENH_DOCKER:-10}"
case "$_DCG_HAN_LENH" in
    ''|*[!0-9]*) error "QLTS_HAN_LENH_DOCKER phải là số nguyên giây, nhận: '$_DCG_HAN_LENH'" ;;
esac
{ [ "$_DCG_HAN_LENH" -ge 1 ] && [ "$_DCG_HAN_LENH" -le 120 ]; } \
    || error "QLTS_HAN_LENH_DOCKER ngoài khoảng 1..120: '$_DCG_HAN_LENH'"
_DCG_HAN_PSQL="${QLTS_HAN_PSQL:-60}"
case "$_DCG_HAN_PSQL" in
    ''|*[!0-9]*) error "QLTS_HAN_PSQL phải là số nguyên giây, nhận: '$_DCG_HAN_PSQL'" ;;
esac
{ [ "$_DCG_HAN_PSQL" -ge 5 ] && [ "$_DCG_HAN_PSQL" -le 600 ]; } \
    || error "QLTS_HAN_PSQL ngoài khoảng 5..600: '$_DCG_HAN_PSQL'"
command -v timeout >/dev/null 2>&1 \
    || error "thiếu lệnh 'timeout' (coreutils) — không giới hạn được thời gian từng lệnh đọc Docker. DỪNG trước mọi thay đổi."
# Vòng 6b (F45): HẠN TỔNG của trap được THỰC THI, không chỉ so ở cuối. `_DCG_TRAP_HET` (mốc
# SECONDS) chỉ đặt khi trap bắt đầu = lúc bắt đầu + ngân sách của pha/chế độ. Trước MỖI bước:
# hạn của lệnh = min(hạn riêng, phần còn lại); hết ⇒ lệnh KHÔNG chạy (rc 124, "không đọc được").
# Lệnh GHI chỉ được BẮT ĐẦU khi phần còn lại ≥ hạn của nó + 5 s (-k) — không có tiến trình giám
# sát nào giết trap giữa một lệnh ghi. Ngoài trap: không giới hạn thêm.
_DCG_TRAP_HET=""
_dcg_con_lai() {
    local r
    if [ -z "${_DCG_TRAP_HET:-}" ]; then printf '%s\n' 999999; return 0; fi
    r=$((_DCG_TRAP_HET - SECONDS))
    [ "$r" -gt 0 ] || r=0
    printf '%s\n' "$r"
}
# _dcg_han_con <hạn riêng> — in min(hạn riêng, phần còn lại); trả 1 (in 0) khi ngân sách đã hết.
# KHÔNG bao giờ in 0 cho `timeout` (0 = TẮT hạn).
_dcg_han_con() {
    local r
    r=$(_dcg_con_lai)
    if [ "$r" -le 0 ]; then printf '0\n'; return 1; fi
    if [ "$1" -le "$r" ]; then printf '%s\n' "$1"; else printf '%s\n' "$r"; fi
}
# _dcg_du_ngan_sach <hạn lệnh ghi> <bước> — 0 nếu phần còn lại đủ cho hạn + 5 s; nếu không: báo,
# ghi `het_ngan_sach` vào tệp trạng thái, trả 1 (người gọi KHÔNG bắt đầu lệnh ghi).
_dcg_du_ngan_sach() {
    local r
    r=$(_dcg_con_lai)
    [ "$r" -ge $(( $1 + 5 )) ] && return 0
    warn "[trap] HẾT NGÂN SÁCH: còn ${r}s < $(( $1 + 5 ))s cần cho $2 — KHÔNG bắt đầu lệnh ghi; trạng thái CHƯA XÁC ĐỊNH"
    _dcg_ghi "het_ngan_sach" "${2// /_} con=${r}s" 2>/dev/null || true
    return 1
}
_dcg_dk() {
    local h
    h=$(_dcg_han_con "$_DCG_HAN_LENH") || { echo "hết ngân sách trap — không đọc Docker" >&2; return 124; }
    timeout -k 2 "$h" docker "$@"
}
# Vòng 6 (N21.07): hạn RIÊNG cho lệnh GHI và đầu dò của đường phục hồi — KHÔNG dùng chung
# hạn đọc trạng thái. Đo local 14-10 (Docker 29.8.0, `vong6/do-thoi-luong.log`): `docker
# start` ≈ 0,4–0,5 s · `docker restart -t 10` nginx ≈ 0,6–0,7 s · `docker run` đầu dò một
# curl ≈ 1 s · `docker inspect` ≈ 0,2–0,3 s. Mặc định = đo × biên rộng (VPS chậm hơn, ứng
# dụng thật khởi động lâu hơn alpine), và không nhỏ hơn trần nội tại của lệnh: restart có
# `-t 10`; đầu dò dịch vụ ≤ 6 curl × 8 s; nginx-verify ≤ 7 curl × 8 s.
_dcg_dat_han() {  # <biến đích> <biến môi trường> <mặc định> <min> <max>
    local gt="${!2:-$3}"
    case "$gt" in
        ''|*[!0-9]*) error "$2 phải là số nguyên giây, nhận: '$gt'" ;;
    esac
    { [ "$gt" -ge "$4" ] && [ "$gt" -le "$5" ]; } || error "$2 ngoài khoảng $4..$5: '$gt'"
    printf -v "$1" '%s' "$gt"
}
_dcg_dat_han _DCG_HAN_KHOI_DONG QLTS_HAN_KHOI_DONG 10 1 600
_dcg_dat_han _DCG_HAN_NGINX_RESTART QLTS_HAN_NGINX_RESTART 30 1 600
_dcg_dat_han _DCG_HAN_DO_SNI QLTS_HAN_DO_SNI 60 1 600
_dcg_dat_han _DCG_HAN_PII QLTS_HAN_PII 90 1 600
# Vòng 6b: ghi đè (chỉ HẠ) ngân sách tổng của trap — để diễn tập/kiểm hạn tổng; rỗng = theo bảng.
_DCG_TRAN_GHI_DE=""
if [ -n "${QLTS_TRAN_TRAP:-}" ]; then
    _dcg_dat_han _DCG_TRAN_GHI_DE QLTS_TRAN_TRAP 1 1 3600
fi
# Lệnh có hạn hết giờ: `timeout` trả 124 (TERM) hoặc 137 (KILL sau -k).
_dcg_het_han() { [ "$1" = "124" ] || [ "$1" = "137" ]; }
# Vòng 7d: các hạn/bảng mà kế hoạch ngân sách PHIÊN (ngay dưới) cần — DỜI LÊN ĐÂY NGUYÊN VĂN
# từ chỗ cũ (chờ healthy, one-off, phiên lạ, docker stop, thứ tự dịch vụ, trần trap).
_HAN_HEALTH="${QLTS_HEALTH_TIMEOUT:-60}"
case "$_HAN_HEALTH" in
    ''|*[!0-9]*) error "QLTS_HEALTH_TIMEOUT phải là số nguyên, nhận: '$_HAN_HEALTH'" ;;
esac
if [ "$_HAN_HEALTH" -lt 1 ] || [ "$_HAN_HEALTH" -gt 600 ]; then
    error "QLTS_HEALTH_TIMEOUT ngoài khoảng 1..600: '$_HAN_HEALTH'"
fi
_DCG_HAN_ONEOFF="${QLTS_HAN_CHO_ONEOFF:-60}"
case "$_DCG_HAN_ONEOFF" in
    ''|*[!0-9]*) error "QLTS_HAN_CHO_ONEOFF phải là số nguyên giây, nhận: '$_DCG_HAN_ONEOFF'" ;;
esac
[ "$_DCG_HAN_ONEOFF" -le 600 ] || error "QLTS_HAN_CHO_ONEOFF ngoài khoảng 0..600: '$_DCG_HAN_ONEOFF'"
_DCG_HAN_PHIEN="${QLTS_HAN_PHIEN_LA:-30}"
case "$_DCG_HAN_PHIEN" in
    ''|*[!0-9]*) error "QLTS_HAN_PHIEN_LA phải là số nguyên, nhận: '$_DCG_HAN_PHIEN'" ;;
esac
if [ "$_DCG_HAN_PHIEN" -lt 1 ] || [ "$_DCG_HAN_PHIEN" -gt 300 ]; then
    error "QLTS_HAN_PHIEN_LA ngoài khoảng 1..300: '$_DCG_HAN_PHIEN'"
fi
# Hạn `docker stop -t`: backend > graceful_timeout 30 của gunicorn; worker cho
# tác vụ đang chạy kết thúc (acks_late — bị giết thì chạy lại sau); beat thoát ngay.
_dcg_han_dung() {
    case "$1" in
        backend)       echo 35 ;;
        celery-worker) echo 60 ;;
        *)             echo 10 ;;
    esac
}
_DCG_DICH_VU="celery-beat backend celery-worker"      # thứ tự DỪNG
_DCG_THU_TU_MO="backend celery-worker celery-beat"    # thứ tự MỞ LẠI
# Vòng 6 (N21.07): TRẦN thời gian của trap theo pha = tổng hạn của MỌI bước trap có thể
# chạy (mỗi bước đều có hạn riêng ⇒ tổng là trần THỰC THI được, không phải ước lượng).
# Đơn vị đọc = hạn đọc + 2 s (-k); lệnh ghi/đầu dò = hạn riêng + 5 s (-k); chờ healthy =
# 1 lần liệt kê + hạn + vòng cuối (3 lần đọc + 2 s ngủ). In: "<tổng> <chi tiết>".
_dcg_ngan_sach_trap() {
    local L P K R D V H HD G O tong ct
    L=$((_DCG_HAN_LENH + 2)); P=$((_DCG_HAN_PSQL + 5))
    K=$((_DCG_HAN_KHOI_DONG + 5)); R=$((_DCG_HAN_NGINX_RESTART + 5))
    D=$((_DCG_HAN_DO_SNI + 5)); V=$((_DCG_HAN_PII + 5))
    H=$((L + _HAN_HEALTH + 3 * L + 2))
    # Hướng dẫn cuối: 3 × (mốc + liệt kê) + nginx + one-off (tra tên + 2 đọc) + vân tay.
    HD=$((10 * L + P))
    case "$_DCG_PHA" in
        dang_dong|da_dong)
            # (đường đi tiếp: trap chỉ in hướng dẫn, KHÔNG mở lại mã cũ)
            if [ "${_DCG_DI_TIEP:-0}" = "1" ]; then
                tong=$HD; ct="hướng_dẫn=$HD"
            else
                # mở lại: vân tay P · 3 × (start K + đo lại 4L) · healthy backend H + đo lại 4L ·
                # hậu kiểm 3 × (liệt kê L + ảnh 2L + trạng thái 2L) · IP 2L · nginx: mốc 2L + restart R + đo lại 2L + healthy H + đo lại 2L ·
                # SNI 3L + D · PII V · rồi hướng dẫn nếu không đạt.
                G=$((P + 3 * (K + 4 * L) + H + 4 * L + 15 * L + 2 * L + 2 * L + R + 2 * L + H + 2 * L + 3 * L + D + V))
                tong=$((G + HD))
                ct="mở_lại=$G(vân_tay=$P,start=3×$K,healthy=2×$H,sni=$D,pii=$V,đọc=${L}s/lần) + hướng_dẫn=$HD"
            fi ;;
        dang_migrate|migrate_do)
            # (cả hai chế độ) chờ one-off: tra tên L + hạn chờ + vòng cuối 2L + 1 s + chi tiết 2L + rm L.
            O=$((L + _DCG_HAN_ONEOFF + 2 * L + 1 + 2 * L + L))
            tong=$((O + HD)); ct="chờ_one-off=$O + hướng_dẫn=$HD" ;;
        chua_dong)
            # Vòng 6b (F45): đường đi tiếp vẫn IN hướng dẫn (đọc Docker/CSDL); đường thường không làm gì.
            if [ "${_DCG_DI_TIEP:-0}" = "1" ]; then
                tong=$HD; ct="đi_tiếp: hướng_dẫn=$HD"
            else
                tong=0; ct="không làm gì"
            fi ;;
        khong_ap_dung|buoc8|xong)
            tong=0; ct="không làm gì" ;;
        *)
            tong=$HD; ct="hướng_dẫn=$HD" ;;
    esac
    printf '%s %s\n' "$tong" "$ct"
}

# =============================================================================
# Vòng 7d — NGÂN SÁCH CẢ PHIÊN SSH (một nguồn với `command_timeout` của deploy.yml)
# =============================================================================
# deploy.yml khai QLTS_PHIEN_GIAY một lần (cùng giá trị làm `command_timeout`) và ghi
# QLTS_PHIEN_BAT_DAU (epoch, dòng đầu của script SSH). Có QLTS_PHIEN_GIAY ⇒ ĐƯỜNG PHIÊN:
# hạn chót = BAT_DAU + GIAY − 30 s đệm đóng phiên (hằng THIẾT KẾ cho ân hạn -k của lệnh
# cuối và làm tròn giây — KHÔNG phải số đo). Không có ⇒ chạy TAY: không giới hạn phiên.
#
# Luật: TRƯỚC mỗi bước không đảo ngược được, phần còn lại của phiên phải ≥ hạn của bước
# + max(dự trữ trap của pha nếu bước ấy đỏ, phần cần cho MỌI bước sau nó) — tính ngược:
#   C_8b = H_8b + H_8c                          (sau 8b không còn nhánh lùi)
#   C_7  = H_78 + max(R(da_migrate), C_8b)
#   C_6  = H_6  + max(R(migrate_do), C_7)
#   C_5  = H_5  + max(R(da_dong), C_6)
#   C_4c = H_4c + max(R(da_dong), C_5)
# R(pha) = trần trap của pha (bảng `_dcg_ngan_sach_trap`, đã áp QLTS_TRAN_TRAP). Thiếu ⇒
# DỪNG đúng tại điểm an toàn ấy: `error` ⇒ trap của pha hiện tại, và phần còn lại vẫn ≥ dự
# trữ của nó vì cổng TRƯỚC đã giữ chỗ. Kế hoạch C_4c được kiểm NGAY ĐÂY (trước Step 3a/3b,
# trước mọi thay đổi trên đường phiên). Bước trước 4c (build, preflight 4b) giết được an toàn
# ⇒ hạn ĐỘNG = phần còn lại − C_4c − ân hạn -k. H_4c, H_8c tính từ hạn từng lệnh đã có
# (đếm lệnh theo mã tại commit này). Bốn hạn KHÔNG giết được giữa chừng — pg_dump (giết
# client không dừng server), Step 6 migration, Step 7+8 (`up -d` + chờ healthy), Step 8b
# nginx-apply (đang hoán container) — là hạn ĐO trên VPS khai trong deploy.yml, KHÔNG có mặc
# định: đường phiên thiếu một trong bốn ⇒ DỪNG. Lệnh chạy quá hạn đã khai là ĐIỂM CÒN CHẶN
# (cổng sau đo lại bằng thời gian THẬT, nhưng không cắt được lệnh đang chạy).
_PH_DEM_DONG=30
_PH_HET=""
_PH_BANG=""
if [ "$_PH_CO" = "1" ]; then
    _dcg_dat_han _PH_GIAY QLTS_PHIEN_GIAY 0 60 86400
    case "$_PH_BAT_DAU" in
        ''|*[!0-9]*) error "[phiên] QLTS_PHIEN_BAT_DAU phải là epoch giây (deploy.yml ghi ở dòng đầu script SSH), nhận: '$_PH_BAT_DAU' — DỪNG trước mọi thay đổi." ;;
    esac
    _PH_BAY_GIO=$(date +%s)
    { [ "$_PH_BAT_DAU" -le "$_PH_BAY_GIO" ] && [ "$_PH_BAT_DAU" -ge $((_PH_BAY_GIO - _PH_GIAY)) ]; } \
        || error "[phiên] QLTS_PHIEN_BAT_DAU=$_PH_BAT_DAU không nằm trong [bây giờ − ${_PH_GIAY}s, bây giờ] — đồng hồ lệch hoặc biến sai. DỪNG trước mọi thay đổi."
    for _PH_V in QLTS_HAN_PG_DUMP QLTS_HAN_MIGRATION QLTS_HAN_BUOC7_8 QLTS_HAN_NGINX_APPLY; do
        [ -n "${!_PH_V:-}" ] || error "[phiên] thiếu hạn ĐO trên VPS: $_PH_V (khai trong deploy.yml cạnh QLTS_PHIEN_GIAY) — không có hạn đo thì KHÔNG giữ chỗ được cho bước không giết được giữa chừng. DỪNG trước mọi thay đổi."
    done
    _dcg_dat_han _PH_H5 QLTS_HAN_PG_DUMP 0 1 7200
    _dcg_dat_han _PH_H6 QLTS_HAN_MIGRATION 0 1 7200
    _dcg_dat_han _PH_H78 QLTS_HAN_BUOC7_8 0 1 7200
    _dcg_dat_han _PH_H8B QLTS_HAN_NGINX_APPLY 0 1 7200
    [ "${IS_CUTOVER:-0}" -eq 0 ] || error "[phiên] COLD_CUTOVER qua workflow KHÔNG được hỗ trợ (cutover là thao tác TAY theo RUNBOOK §7.2). DỪNG."
    [ "$_DT_CO" = "0" ] || error "[phiên] đường ĐI TIẾP chỉ chạy TAY trên VPS (không qua workflow). DỪNG."
    _PH_HET=$((_PH_BAT_DAU + _PH_GIAY - _PH_DEM_DONG))
fi
_ph_con_lai() {
    local r
    if [ -z "$_PH_HET" ]; then printf '%s\n' 999999; return 0; fi
    r=$((_PH_HET - $(date +%s)))
    [ "$r" -gt 0 ] || r=0
    printf '%s\n' "$r"
}
# Trần trap của <pha> trên đường thường, đã áp QLTS_TRAN_TRAP (đúng thứ trap sẽ dùng).
_ph_tran_pha() {
    local ns
    ns=$(_DCG_PHA="$1"; _DCG_DI_TIEP=0; _dcg_ngan_sach_trap); ns=${ns%% *}
    if [ -n "$_DCG_TRAN_GHI_DE" ] && [ "$ns" -gt 0 ] && [ "$_DCG_TRAN_GHI_DE" -lt "$ns" ]; then
        ns=$_DCG_TRAN_GHI_DE
    fi
    printf '%s\n' "$ns"
}
_ph_max() { if [ "$1" -ge "$2" ]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi; }
# H_4c (cận trên, đếm theo mã Step 4c): đọc trước dừng 11 lần · 3 × `docker stop` (-t + hạn
# đọc + -k 5) · mốc 3 lần · đo cửa đóng 6 lần · phiên lạ (hạn chờ + 2 psql + 1 s) · vân tay ·
# bộ đếm T0. H_8c: liệt kê + ảnh × 5 service + 2 lượt đối chiếu marker × 5 × 3 lần đọc.
_ph_han_4c() {
    local L=$((_DCG_HAN_LENH + 2)) P=$((_DCG_HAN_PSQL + 5)) s d=0
    for s in $_DCG_DICH_VU; do d=$((d + $(_dcg_han_dung "$s") + _DCG_HAN_LENH + 5)); done
    printf '%s\n' $((11 * L + d + 3 * L + 6 * L + _DCG_HAN_PHIEN + 2 * P + 1 + 2 * P))
}
_ph_han_8c() { printf '%s\n' $((40 * (_DCG_HAN_LENH + 2))); }
# Phần cần (C_x) từ đầu bước <x> tới hết lượt — xem bảng ở đầu khối.
_ph_can() {
    local c8b c7 c6 c5
    c8b=$((_PH_H8B + $(_ph_han_8c)))
    c7=$((_PH_H78 + $(_ph_max "$(_ph_tran_pha da_migrate)" "$c8b")))
    c6=$((_PH_H6 + $(_ph_max "$(_ph_tran_pha migrate_do)" "$c7")))
    c5=$((_PH_H5 + $(_ph_max "$(_ph_tran_pha da_dong)" "$c6")))
    case "$1" in
        8b) printf '%s\n' "$c8b" ;;
        7)  printf '%s\n' "$c7" ;;
        6)  printf '%s\n' "$c6" ;;
        5)  printf '%s\n' "$c5" ;;
        4c) printf '%s\n' $(($(_ph_han_4c) + $(_ph_max "$(_ph_tran_pha da_dong)" "$c5"))) ;;
        *)  error "[phiên] bước '$1' không có trong kế hoạch ngân sách" ;;
    esac
}
# Cổng TRƯỚC bước không đảo ngược được: <bước> <mô tả>. Đường tay: luôn qua.
_ph_cong() {
    local can con
    [ -n "$_PH_HET" ] || return 0
    can=$(_ph_can "$1"); con=$(_ph_con_lai)
    if [ "$con" -lt "$can" ]; then
        _dcg_ghi "het_ngan_sach_phien" "buoc=$1 con=${con}s can=${can}s" 2>/dev/null || true
        error "[phiên] HẾT NGÂN SÁCH PHIÊN trước $2: còn ${con}s < cần ${can}s (hạn bước + phần sau / dự trữ trap) — DỪNG tại điểm an toàn này, KHÔNG bắt đầu bước."
    fi
    log "  [phiên] trước $2: còn ${con}s ≥ cần ${can}s"
}
# Hạn ĐỘNG cho bước giết được an toàn TRƯỚC 4c: <ân hạn -k> <mô tả>. Đặt `_PH_H_DONG` (giây);
# đường tay để rỗng (bước chạy không giới hạn như trước). Gọi TRỰC TIẾP (không trong `$(…)`)
# để `error` dừng đúng tiến trình deploy.
_PH_H_DONG=""
_ph_han_dong() {
    local h
    _PH_H_DONG=""
    [ -n "$_PH_HET" ] || return 0
    h=$(( $(_ph_con_lai) - $(_ph_can 4c) - $1 ))
    if [ "$h" -lt 1 ]; then
        error "[phiên] HẾT NGÂN SÁCH PHIÊN trước $2: phần còn lại $(_ph_con_lai)s không đủ cho kế hoạch từ Step 4c ($(_ph_can 4c)s) + ân hạn ${1}s — DỪNG, chưa đụng container/CSDL."
    fi
    _PH_H_DONG=$h
    log "  [phiên] $2: hạn ĐỘNG ${h}s (= còn $(_ph_con_lai)s − cần $(_ph_can 4c)s từ 4c − ân hạn ${1}s)"
}
if [ -n "$_PH_HET" ]; then
    _PH_BANG="phiên ${_PH_GIAY}s (đệm đóng ${_PH_DEM_DONG}s) · H_4c=$(_ph_han_4c) H_5=$_PH_H5 H_6=$_PH_H6 H_78=$_PH_H78 H_8b=$_PH_H8B H_8c=$(_ph_han_8c) · R(da_dong)=$(_ph_tran_pha da_dong) R(migrate_do)=$(_ph_tran_pha migrate_do) R(da_migrate)=$(_ph_tran_pha da_migrate) · C_4c=$(_ph_can 4c) C_5=$(_ph_can 5) C_6=$(_ph_can 6) C_7=$(_ph_can 7) C_8b=$(_ph_can 8b)"
    log "[phiên] ngân sách: $_PH_BANG"
    _PH_CON=$(_ph_con_lai)
    _PH_CAN=$(_ph_can 4c)
    if [ "$_PH_CON" -lt "$_PH_CAN" ]; then
        error "[phiên] KẾ HOẠCH KHÔNG VỪA PHIÊN: còn ${_PH_CON}s < cần ${_PH_CAN}s từ Step 4c (chưa kể build) — DỪNG TRƯỚC mọi thay đổi (chưa tag/build/dừng gì).
       KHÔNG hạ hạn Docker cho vừa phép cộng; nâng QLTS_PHIEN_GIAY (= command_timeout) theo số ĐO, hoặc đo lại các hạn trên VPS."
    fi
    log "[phiên] kế hoạch vừa: còn ${_PH_CON}s ≥ cần ${_PH_CAN}s từ Step 4c"
else
    warn "[phiên] KHÔNG có QLTS_PHIEN_GIAY — chạy TAY: không giới hạn phiên, KHÔNG có cổng ngân sách phiên."
fi
# _dcg_doc_ct <định dạng> <CID> — in kết quả `docker inspect -f`. Mã trả:
#   0 đọc được · 2 ĐÃ XÁC NHẬN không tồn tại · 1 KHÔNG ĐỌC ĐƯỢC (lỗi, hết hạn,
#   hoặc liệt kê vẫn thấy container mà inspect hỏng).
_dcg_doc_ct() {
    local ra ds
    if ra=$(_dcg_dk inspect -f "$1" "$2" 2>/dev/null); then
        printf '%s\n' "$ra"
        return 0
    fi
    ds=$(_dcg_dk ps -a -q --no-trunc --filter "id=$2" 2>/dev/null) || return 1
    [ -z "${ds//[[:space:]]/}" ] || return 1
    return 2
}
# _dcg_doc_anh <định dạng> <tham chiếu ẢNH> — như `_dcg_doc_ct` nhưng cho ảnh: 0 đọc được ·
# 2 ĐÃ XÁC NHẬN không có (`image ls -q` rc 0 + rỗng) · 1 KHÔNG ĐỌC ĐƯỢC. Vòng 6: phép "tag
# đã tồn tại chưa?" của Step 3b trước đây coi MỌI lỗi `image inspect` là "chưa có".
_dcg_doc_anh() {
    local ra ds
    if ra=$(_dcg_dk image inspect -f "$1" "$2" 2>/dev/null); then
        printf '%s\n' "$ra"
        return 0
    fi
    ds=$(_dcg_dk image ls -q --no-trunc "$2" 2>/dev/null) || return 1
    [ -z "${ds//[[:space:]]/}" ] || return 1
    return 2
}
# _dcg_cid_theo_ten <tên> — in CID 64 hex của container mang ĐÚNG tên ấy. Mã trả như
# `_dcg_doc_ct`: 0 thấy · 2 ĐÃ XÁC NHẬN không có · 1 KHÔNG ĐỌC ĐƯỢC.
_dcg_cid_theo_ten() {
    local ds
    ds=$(_dcg_dk ps -a -q --no-trunc --filter "name=^/?$1\$" 2>/dev/null) || return 1
    ds=${ds//[[:space:]]/}
    [ -n "$ds" ] || return 2
    case "$ds" in *[!0-9a-f]*) return 1 ;; esac
    [ "${#ds}" -eq 64 ] || return 1
    printf '%s\n' "$ds"
}

# =============================================================================
# Step 3a: ĐI TIẾP SAU MIGRATION ĐỎ (vòng 4, F40) — chỉ khi được CHO PHÉP tường minh
# =============================================================================
# Sau F28, migration đỏ để ba service (backend, celery-worker, celery-beat) NẰM
# DỪNG có chủ ý và CSDL giữ nguyên (có thể đã migrate dở). Deploy routine bình
# thường không chạy nổi từ trạng thái ấy: Step 3b đòi container ĐANG chạy để ghim
# ảnh cũ, Step 4c đòi đúng một container ĐANG chạy mỗi service. Bật mã cũ chỉ để
# vượt tiền kiểm là SAI — mã cũ trên lược đồ dở dang chính là điều F28 tránh.
#
# Đường này đi tiếp TỪ CHÍNH trạng thái dừng ấy:
#   QLTS_DI_TIEP_SAU_MIGRATE_DO=1  — cờ CHO PHÉP, mặc định tắt; chỉ nhận '0'/'1'
#   QLTS_DI_TIEP_TU=<backups/deploy_<TS>.trang-thai của lượt đỏ>  — tầng thứ hai
# Hai biến phải đi CÙNG nhau; chỉ có một ⇒ DỪNG. Trước MỌI mutation, đo trạng thái
# THẬT và đối chiếu với tệp trạng thái của lượt đỏ — lệch bất kỳ điểm nào ⇒ DỪNG,
# không đụng gì:
#   * pha cuối ∈ {dang_migrate, migrate_do, da_migrate} (dừng có chủ ý sau khi
#     migration đã chạm CSDL; pha trước đó thì trap đã/định mở lại mã cũ);
#   * ba service KHÔNG có container nào đang chạy;
#   * ba CID ghi nhận còn, `exited`, mốc vòng đời Status|StartedAt|FinishedAt
#     KHỚP đúng mốc ghi lúc đóng (không ai bật lại giữa chừng), ảnh = ảnh ghi nhận;
#   * nginx đang phục vụ đúng MỘT container, đúng CID ghi nhận;
#   * one-off alembic của lượt đỏ (CID ghi nhận) và MỌI one-off của service
#     backend trong cùng project đều KHÔNG còn chạy.
# Đạt thì: Step 3b ghim ảnh cũ từ ĐÚNG ba CID exited đã ghi nhận (không đoán từ
# tag, không từ HEAD); Step 4c KHÔNG dừng gì (đã dừng) mà đo lại cửa; Step 5 chụp
# bản sao MỚI; Step 6 migrate bằng mã SỬA; Step 8 dựng mã mới; sau Step 8b đo dịch
# vụ qua SNI thật (`_dcg_do_dich_vu_nginx`). Trap ở đường này KHÔNG BAO GIỜ mở lại
# mã cũ (lược đồ có thể đã migrate dở).
#
# Người vận hành gọi trên VPS (deploy.yml không forward hai biến này — cố ý):
#   cd /opt/qlts && <đưa cây tới commit SỬA> && \
#   SHA_MONG_DOI=<40 hex commit sửa> QLTS_DI_TIEP_SAU_MIGRATE_DO=1 \
#   QLTS_DI_TIEP_TU=backups/deploy_<TS>.trang-thai bash scripts/deploy.sh
# Trap của lượt đỏ in sẵn đúng lệnh này với đường dẫn thật.
_DI_TIEP=0
_DT_COMPOSE="docker compose -f docker-compose.yml --profile production --env-file .env.production"
_DT_TT_CU=""
_DT_NGINX=""
declare -A _DT_CID=() _DT_ANH=() _DT_MOC=()
if [ "$_DT_CO" = "1" ]; then
    case "$_DT_CO_GIATRI" in
        0) : ;;
        1) _DI_TIEP=1 ;;
        *) error "QLTS_DI_TIEP_SAU_MIGRATE_DO='$_DT_CO_GIATRI' không hợp lệ — chỉ nhận '0' hoặc '1'." ;;
    esac
fi
if [ "$_DI_TIEP" = "1" ]; then
    [ "$_DT_TU" = "1" ] && [ -n "$_DT_TU_GIATRI" ] || error "[đi tiếp] QLTS_DI_TIEP_SAU_MIGRATE_DO=1 nhưng THIẾU QLTS_DI_TIEP_TU (tệp trạng thái của lượt migration đỏ)."
    [ "${IS_CUTOVER}" -eq 0 ] || error "[đi tiếp] không dùng cùng COLD_CUTOVER."
    log "Step 3a: ĐI TIẾP sau migration đỏ — kiểm trạng thái THẬT trước mọi thay đổi..."
    case "$_DT_TU_GIATRI" in
        /*) _DT_TT_CU="$_DT_TU_GIATRI" ;;
        *)  _DT_TT_CU="$PROJECT_DIR/$_DT_TU_GIATRI" ;;
    esac
    case "$(basename -- "$_DT_TT_CU")" in
        deploy_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_[0-9][0-9][0-9][0-9][0-9][0-9].trang-thai) : ;;
        *) error "[đi tiếp] QLTS_DI_TIEP_TU phải là tệp deploy_<YYYYMMDD_HHMMSS>.trang-thai, nhận: '$_DT_TU_GIATRI'" ;;
    esac
    [ "$(cd "$(dirname -- "$_DT_TT_CU")" 2>/dev/null && pwd -P)" = "$(cd "$BACKUP_DIR" 2>/dev/null && pwd -P)" ] \
        || error "[đi tiếp] tệp trạng thái phải nằm trong $BACKUP_DIR, nhận: '$_DT_TU_GIATRI'"
    [ ! -L "$_DT_TT_CU" ] && [ -f "$_DT_TT_CU" ] || error "[đi tiếp] không có tệp trạng thái thường '$_DT_TT_CU'."
    _dt_doc() { awk -F'\t' -v k="$1" '$2 == k { print $3 }' "$_DT_TT_CU"; }
    _DT_PHA_CUOI=$(_dt_doc pha | tail -n 1)
    case "$_DT_PHA_CUOI" in
        dang_migrate|migrate_do|da_migrate) : ;;
        *) error "[đi tiếp] pha cuối của lượt trước là '${_DT_PHA_CUOI:-?}' — KHÔNG phải pha dừng-có-chủ-ý sau migration (dang_migrate/migrate_do/da_migrate). Từ chối." ;;
    esac
    for _S in celery-beat backend celery-worker; do
        _DT_DONG=$(_dt_doc cu | awk -v s="$_S" '$1 == s')
        [ "$(printf '%s\n' "$_DT_DONG" | grep -c '[^[:space:]]' || true)" -eq 1 ] \
            || error "[đi tiếp] tệp trạng thái không có ĐÚNG MỘT dòng 'cu' cho '$_S'."
        _CID=$(printf '%s\n' "$_DT_DONG" | awk '{ print $2 }')
        _ANH=$(printf '%s\n' "$_DT_DONG" | awk '{ print $3 }')
        case "$_CID" in ''|*[!0-9a-f]*) error "[đi tiếp] CID ghi nhận của '$_S' không hợp lệ: '$_CID'" ;; esac
        [ "${#_CID}" -eq 64 ] || error "[đi tiếp] CID ghi nhận của '$_S' dài ${#_CID} (cần 64 hex)."
        case "$_ANH" in sha256:*) : ;; *) error "[đi tiếp] ảnh ghi nhận của '$_S' không hợp lệ: '$_ANH'" ;; esac
        _DT_DONG=$(_dt_doc moc | awk -v s="$_S" '$1 == s')
        [ "$(printf '%s\n' "$_DT_DONG" | grep -c '[^[:space:]]' || true)" -eq 1 ] \
            || error "[đi tiếp] tệp trạng thái không có ĐÚNG MỘT dòng 'moc' cho '$_S'."
        _DT_CID[$_S]=$_CID
        _DT_ANH[$_S]=$_ANH
        _DT_MOC[$_S]=$(printf '%s\n' "$_DT_DONG" | awk '{ print $2 }')
        # Trạng thái THẬT — mọi phép đọc thất bại cũng là DỪNG.
        _DS=$(timeout -k 2 "$_DCG_HAN_LENH" $_DT_COMPOSE ps -q "$_S") || error "[đi tiếp] không liệt kê được container đang chạy của '$_S' (lỗi hoặc hết hạn Docker)."
        [ -z "${_DS//[[:space:]]/}" ] || error "[đi tiếp] '$_S' có container ĐANG CHẠY (${_DS//[[:space:]]/ }) — trạng thái không phải 'dừng sau migration đỏ'. Từ chối, không đụng gì."
        _M=$(_dcg_dk inspect -f '{{.State.Status}}|{{.State.StartedAt}}|{{.State.FinishedAt}}' "$_CID" 2>/dev/null) \
            || error "[đi tiếp] CID ghi nhận của '$_S' ($_CID) KHÔNG còn hoặc KHÔNG đọc được (lỗi/hết hạn Docker) — không ghim được ảnh cũ từ container đã ghi nhận. Từ chối."
        [ "${_M%%|*}" = "exited" ] || error "[đi tiếp] container ghi nhận của '$_S' đang '${_M%%|*}' (cần exited). Từ chối."
        [ "$_M" = "${_DT_MOC[$_S]}" ] || error "[đi tiếp] container ghi nhận của '$_S' ĐÃ CHẠY LẠI từ lúc đóng (mốc ghi=${_DT_MOC[$_S]} · đo=$_M). Từ chối."
        _M=$(_dcg_dk inspect -f '{{.Image}}' "$_CID" 2>/dev/null) || error "[đi tiếp] không đọc được ảnh của '$_S'."
        [ "$_M" = "$_ANH" ] || error "[đi tiếp] ảnh container '$_S' ($_M) KHÁC ảnh ghi nhận ($_ANH). Từ chối."
    done
    _DT_DONG=$(_dt_doc nginx)
    [ "$(printf '%s\n' "$_DT_DONG" | grep -c '[^[:space:]]' || true)" -eq 1 ] || error "[đi tiếp] tệp trạng thái không có ĐÚNG MỘT dòng 'nginx'."
    _DT_NGINX=${_DT_DONG//[[:space:]]/}
    _DS=$(timeout -k 2 "$_DCG_HAN_LENH" $_DT_COMPOSE ps -q nginx) || error "[đi tiếp] không liệt kê được container nginx (lỗi hoặc hết hạn Docker)."
    [ "${_DS//[[:space:]]/}" = "$_DT_NGINX" ] || error "[đi tiếp] nginx đang phục vụ (${_DS//[[:space:]]/ }) KHÁC CID ghi nhận ($_DT_NGINX). Từ chối."
    _M=$(_dcg_dk inspect -f '{{.State.Status}}' "$_DT_NGINX" 2>/dev/null) || _M="KHÔNG đọc được"
    [ "$_M" = "running" ] || error "[đi tiếp] nginx ghi nhận đang '$_M' (cần running). Từ chối."
    _DT_OO=$(cat "${_DT_TT_CU%.trang-thai}.oneoff-cid" 2>/dev/null) || _DT_OO=""
    if [ -n "$_DT_OO" ]; then
        # Vòng 5 (F43): đọc lỗi KHÔNG phải "đã hết" — chỉ exited/dead hoặc "ĐÃ XÁC NHẬN
        # không tồn tại" (`--rm` đã dọn) mới qua; KHÔNG đọc được ⇒ TỪ CHỐI.
        _M=$(_dcg_doc_ct '{{.State.Status}}' "$_DT_OO") && _KQ=0 || _KQ=$?
        case "$_KQ" in
            0) case "$_M" in exited|dead) : ;; *) error "[đi tiếp] one-off alembic của lượt đỏ ($_DT_OO) đang '$_M' — migration có thể VẪN chạy. Chờ nó kết thúc rồi chạy lại." ;; esac ;;
            2) : ;;
            *) error "[đi tiếp] KHÔNG ĐỌC ĐƯỢC trạng thái one-off alembic của lượt đỏ ($_DT_OO) (lỗi hoặc hết hạn Docker) — không chứng minh được migration đã dừng. Từ chối." ;;
        esac
    fi
    _DT_DU_AN=$(_dcg_dk inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "${_DT_CID[backend]}" 2>/dev/null) || _DT_DU_AN=""
    [ -n "$_DT_DU_AN" ] || error "[đi tiếp] không đọc được nhãn project Compose của backend ghi nhận."
    _DS=$(_dcg_dk ps -q --filter "label=com.docker.compose.project=$_DT_DU_AN" \
        --filter label=com.docker.compose.oneoff=True --filter label=com.docker.compose.service=backend) \
        || error "[đi tiếp] không liệt kê được one-off đang chạy (lỗi hoặc hết hạn Docker) — không chứng minh được migration đã dừng. Từ chối."
    [ -z "${_DS//[[:space:]]/}" ] || error "[đi tiếp] còn one-off của service backend ĐANG CHẠY (${_DS//[[:space:]]/ }) — có thể là migration. Chờ nó kết thúc rồi chạy lại."
    log "  ✓ [đi tiếp] trạng thái khớp lượt đỏ ($(basename -- "$_DT_TT_CU"), pha '$_DT_PHA_CUOI'): 3 CID exited đúng mốc, 0 container đang chạy, nginx đúng CID, 0 one-off đang chạy"
elif [ "$_DT_TU" = "1" ]; then
    error "QLTS_DI_TIEP_TU có mặt nhưng QLTS_DI_TIEP_SAU_MIGRATE_DO không phải '1' — ý định mâu thuẫn, DỪNG."
fi

# Container đang phục vụ của một service, cho Step 3b. Đường đi tiếp: ba service
# ghi lấy ĐÚNG CID exited đã ghi nhận và đã đo ở Step 3a (không đoán); còn lại
# (frontend, nginx) vẫn là container ĐANG chạy như mọi lượt.
_ra_cid_phuc_vu() {
    if [ "$_DI_TIEP" = "1" ] && [ -n "${_DT_CID[$1]:-}" ]; then
        printf '%s\n' "${_DT_CID[$1]}"
        return 0
    fi
    timeout -k 2 "$_DCG_HAN_LENH" $_RA_COMPOSE ps -q "$1"
}

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
    # Vòng 7c: có hạn (đọc cấu hình, giết an toàn — Step 3b, trước build).
    _json=$(timeout -k 2 "$_DCG_HAN_LENH" docker compose -f docker-compose.yml --profile production config --no-interpolate --no-env-resolution --format json) || return 12
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
        _lc=$(timeout -k 2 "$_DCG_HAN_LENH" $_RA_COMPOSE ps -q "$_s" 2>/dev/null || true)
        [ -n "$_lc" ] || error "[$_n] không thấy container đang chạy cho '$_s'."
        [ "$_mc" = "$_lc" ] || error "[$_n] CID của '$_s' lệch container hiện hành (marker=$_mc live=$_lc)."
        _st=$(_dcg_dk inspect -f '{{.State.Status}}' "$_lc" 2>/dev/null || true)
        [ "$_st" = "running" ] || error "[$_n] '$_s' không running (=$_st)."
        _li=$(_dcg_dk inspect -f '{{.Image}}' "$_lc" 2>/dev/null || true)
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
        _RA_CID=$(_ra_cid_phuc_vu "$_S" 2>/dev/null || true)
        if [ -z "$_RA_CID" ]; then
            error "không thấy container đang chạy cho '$_S' — không thể ghim ảnh cũ.
       Đừng build đè lên một stack đang thiếu service."
        fi
        _RA_IMG=$(_dcg_dk inspect -f '{{.Image}}' "$_RA_CID" 2>/dev/null || true)
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
    if [ "$_DI_TIEP" = "1" ]; then
        # Đường đi tiếp: ảnh của 3 service ghi đọc từ container EXITED đã ghi nhận
        # ở lượt đỏ (Step 3a đã đo), không phải container đang chạy.
        log "  ✓ marker khớp $_RA_MK_N/$_RA_MK_N container phục vụ (backend/celery-worker/celery-beat = container EXITED đã ghi nhận ở lượt đỏ) — nguồn = $_RA_SRC"
    else
        log "  ✓ marker khớp $_RA_MK_N/$_RA_MK_N container đang chạy — nguồn = $_RA_SRC"
    fi

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
        # Vòng 6: lỗi đọc KHÔNG phải "chưa có" — chỉ "ĐÃ XÁC NHẬN không có" mới qua.
        _dcg_doc_anh '{{.Id}}' "qlts-${_S}:${_RA_TAG}" >/dev/null && _RA_KQ=0 || _RA_KQ=$?
        if [ "$_RA_KQ" -eq 1 ]; then
            error "KHÔNG ĐỌC ĐƯỢC (lỗi hoặc hết hạn Docker) tag qlts-${_S}:${_RA_TAG} có tồn tại chưa — DỪNG trước build (không ghim mù)."
        fi
        if [ "$_RA_KQ" -eq 0 ]; then
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
        _RA_CID=$(_ra_cid_phuc_vu "$_S")
        _RA_IMG=$(_dcg_dk inspect -f '{{.Image}}' "$_RA_CID")
        # Tag ghim phai DUY NHAT. Neu no da ton tai va tro vao mot anh KHAC thi
        # `docker tag` se am tham cuop ten: ban ke lan truoc tro vao mot anh khong
        # con mang ten do nua, va rollback theo tag se lay nham anh. Fail-closed.
        # Vòng 6: KHÔNG ĐỌC ĐƯỢC ≠ "chưa có" ⇒ DỪNG.
        _RA_CU=$(_dcg_doc_anh '{{.Id}}' "qlts-${_S}:${_RA_TAG}") && _RA_KQ=0 || _RA_KQ=$?
        [ "$_RA_KQ" -ne 1 ] || error "KHÔNG ĐỌC ĐƯỢC tag qlts-${_S}:${_RA_TAG} trước khi ghim (lỗi hoặc hết hạn Docker) — DỪNG trước build."
        [ "$_RA_KQ" -eq 0 ] || _RA_CU=""
        if [ -n "$_RA_CU" ] && [ "$_RA_CU" != "$_RA_IMG" ]; then
            error "tag qlts-${_S}:${_RA_TAG} DA TON TAI va tro vao anh khac:
       dang co = $_RA_CU
       sap ghim = $_RA_IMG
       Ghi de la cuop ten khoi mot ban ke cu. DUNG truoc build."
        fi
        # Vòng 7c: có hạn (siêu dữ liệu ảnh, TRƯỚC build — giết an toàn; lượt sau kiểm lại tag trước khi ghim).
        timeout -k 2 "$_DCG_HAN_LENH" docker tag "$_RA_IMG" "qlts-${_S}:${_RA_TAG}" \
            || error "docker tag qlts-${_S}:${_RA_TAG} THẤT BẠI hoặc HẾT HẠN (hạn ${_DCG_HAN_LENH}s) — DỪNG trước build. Tag có thể ĐÃ hoặc CHƯA tạo: lượt sau kiểm tag trước khi ghim."
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

# Vòng 7d: đường phiên ⇒ build có hạn ĐỘNG (phần còn lại − kế hoạch từ 4c − ân hạn 30 s). Giết
# client build TRƯỚC 4c là an toàn: chưa dừng container nào, chưa chạm CSDL.
_ph_han_dong 30 "Step 4 (build)"
if [ -n "$_PH_H_DONG" ]; then
    timeout -k 30 "$_PH_H_DONG" docker compose -f docker-compose.yml --profile production --env-file .env.production build --parallel \
        || error "Step 4 build THẤT BẠI hoặc HẾT HẠN ĐỘNG (${_PH_H_DONG}s) — DỪNG trước 4c, chưa đụng container/CSDL."
else
docker compose -f docker-compose.yml --profile production --env-file .env.production build --parallel
fi

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
# (Vòng 3, 13-10-2026 — F28: Step 6 KHÔNG còn tự phát lại bản sao; migration
# đỏ ⇒ ứng dụng giữ DỪNG. Cổng này vẫn cần: lỗi cấu hình ở đây nay sẽ để
# ứng dụng nằm DỪNG chờ người, thay vì một lượt restore không cần thiết.)
#
# ``--entrypoint python`` — cùng lý do với Step 6 và Step 7: `docker compose run`
# KHÔNG đè ENTRYPOINT, nên thiếu cờ này thì chính bước preflight sẽ chạy trọn
# ``alembic upgrade head`` + ``sync_notification_rules`` trước khi tới script,
# tức gây ra đúng thứ nó sinh ra để ngăn.
#
# Không có ``|| warn``: ``set -e`` ở đầu tệp để mã thoát khác 0 tự dừng deploy.
log "Step 4b/8: Config preflight (candidate image)..."
# Vòng 7d: đường phiên ⇒ hạn ĐỘNG như build (chỉ đọc cấu hình, CSDL chưa bị chạm).
_ph_han_dong 10 "Step 4b (preflight)"
if [ -n "$_PH_H_DONG" ]; then
    timeout -k 10 "$_PH_H_DONG" docker compose -f docker-compose.yml --profile production --env-file .env.production \
        run --rm --no-deps --entrypoint python backend -m scripts.preflight_config \
        || error "Step 4b preflight THẤT BẠI hoặc HẾT HẠN ĐỘNG (${_PH_H_DONG}s) — DỪNG, CSDL chưa bị chạm."
else
docker compose -f docker-compose.yml --profile production --env-file .env.production \
    run --rm --no-deps --entrypoint python backend -m scripts.preflight_config
fi
log "Config preflight passed — CSDL chưa bị chạm"

# =============================================================================
# CỔNG HEALTH (vá 09-09-2026) — MỘT helper cho cả backend lẫn frontend
# =============================================================================
# Dời lên ĐÂY (vá 12-10-2026, đường A): nhánh migration ĐỎ của Step 6 phải
# chờ backend CŨ healthy sau `docker start`, mà bash chỉ biết một hàm SAU khi
# đã chạy qua dòng định nghĩa nó — để ở chỗ cũ (sau Step 8) thì nhánh ấy gọi
# một hàm chưa tồn tại. Thân hàm và phép kiểm `QLTS_HEALTH_TIMEOUT` KHÔNG đổi
# một ký tự; chỉ đổi CHỖ (nên giá trị hạn sai nay bị chặn sớm hơn, trước pg_dump).
#
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

# Chờ MỘT service tới đúng trạng thái `healthy`. Mọi kết cục khác đều exit 1.
_cho_healthy_dv() {
    local ten="$1" han="$2"
    local ds so cid tt sk ma het

    # `ps -aq` trả ID, không trả chữ — cắt hẳn đường đọc health bằng cách grep
    # một dòng văn bản dành cho người đọc.
    if ! ds=$(_dcg_dk compose -f docker-compose.yml --profile production \
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
        if ! tt=$(_dcg_dk inspect -f '{{.State.Status}}' "$cid" 2>/dev/null); then
            error "docker inspect THẤT BẠI (lỗi hoặc hết hạn) khi đọc State.Status của '$ten' (cid=$cid)"
        fi
        # `{{else}}` biến "không khai healthcheck" thành một giá trị NÓI ĐƯỢC
        # THÀNH LỜI, thay vì chuỗi rỗng trôi qua mọi phép so mà không ai thấy.
        if ! sk=$(_dcg_dk inspect \
                    -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}khong-co-healthcheck{{end}}' \
                    "$cid" 2>/dev/null); then
            error "docker inspect THẤT BẠI khi đọc State.Health.Status của '$ten' (cid=$cid)"
        fi

        case "$tt" in
            exited|dead)
                ma=$(_dcg_dk inspect -f '{{.State.ExitCode}}' "$cid" 2>/dev/null || echo "?")
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

# =============================================================================
# Step 4c: ĐÓNG CỬA GHI — PA1 + trap theo pha (vá 12-10-2026, F28/F32; vòng 2:
#          F35 vân tay lược đồ, F37 tệp trạng thái; vòng 3 13-10-2026: owner
#          chốt F28 BỎ TỰ PHÁT LẠI DUMP, F39 tách phục hồi dịch vụ khỏi kiểm PII,
#          dọn one-off alembic của chính lượt)
# =============================================================================
# Vì sao đóng cửa: bản sao Step 5 chỉ chứa những gì commit TRƯỚC lúc `pg_dump`
# bắt đầu. Trước vá 12-10, `backend`, `celery-worker`, `celery-beat` CŨ chạy
# suốt Step 5 → 7 và vẫn ghi (người dùng, webhook, `GET /r/{code}`, 27 lịch
# beat); nhánh migration ĐỎ khi ấy TỰ phát lại bản sao ⇒ XOÁ mọi ghi ấy, kể cả
# request đã nhận 2xx.
#
# VÒNG 3 — KHÔNG CÒN TỰ PHÁT LẠI (owner chốt F28, 13-10-2026). Migration đỏ ⇒
# ứng dụng giữ DỪNG, CSDL giữ NGUYÊN hiện trạng (kể cả phần migration đã
# AUTOCOMMIT) để phục hồi TAY có đối soát. Lý do: diễn tập vòng 2 đo được một
# phiên CSDL ngoài nối SAU T1, ghi 20 giao dịch rồi ngắt TRƯỚC bước (d) — lọt
# mọi lớp đo, và lượt tự phát lại xoá 20/20 giao dịch đã commit. Không hàng
# rào nào ở đây chặn được ca ấy một cách BẢO ĐẢM, nên script không được tự
# quyết thay người một thao tác phá dữ liệu.
#
# BẤT BIẾN (PA1): từ trước `pg_dump` tới hết deploy, KHÔNG container nào của ba
# service ấy chạy, TRỪ: (i) script mở lại ĐÚNG container cũ khi CSDL CHƯA bị
# migration chạm (pha `dang_dong`/`da_dong`), hoặc (ii) Step 8 dựng container
# MỚI sau migration XANH. Cửa đóng vẫn cần dù không còn tự phát lại: bản sao
# Step 5 khớp một mốc mà sau đó ỨNG DỤNG không ghi nữa (đối soát tay chỉ còn
# phải nhìn nguồn NGOÀI), và mã CŨ không ghi lên lược đồ đang bị migration sửa.
#
# Bước (d) + PA2 (bộ đếm `pg_stat_user_tables` T0/T1/T2) KHÔNG còn là CỔNG:
# không nhánh nào đổi hành vi theo kết quả của chúng. Ở nhánh đỏ chúng ĐO để IN
# cho người đối soát — cửa có còn được chứng minh là đóng, bảng nào có ghi
# trong cửa sổ dump. Hiệu = 0 vẫn KHÔNG chứng minh "0 ghi" (bộ đếm trễ, đệm,
# bị đặt lại); `pg_stat_database` T1→T2 lẫn phiên của healthcheck.
#
# Phạm vi: ĐÚNG ba container. `psql` tay… KHÔNG bị cửa này đóng; phép đo "0
# phiên lạ" ở 4c chỉ PHÁT HIỆN chúng tại đúng thời điểm đo (còn phiên lạ ⇒ DỪNG
# trước pg_dump). Kiểm kê cron VPS 13-10-2026: tác nhân định kỳ duy nhất chạm
# CSDL là `pg_dump` lúc 03:00 (`backup-cron.sh`, CHỈ ĐỌC) — nó là một "phiên lạ"
# ⇒ deploy trùng khung ~03:00 bị chặn ở 4c (đúng thiết kế: chọn giờ khác).
#
# VÂN TAY LƯỢC ĐỒ (F35): "revision cũ" KHÔNG chứng minh "lược đồ cũ" — alembic
# chạy AUTOCOMMIT nên DDL có thể đã commit trong khi `alembic_version` chưa đổi.
# Mở lại mã cũ (nay chỉ còn ở pha CHƯA migrate) đòi vân tay (bảng, cột, kiểu, mặc
# định, ràng buộc, index, trigger, kiểu tự định nghĩa, hàm, view, policy, event
# trigger, extension — đọc từ catalog) KHỚP từng dòng với bản chụp ở 4c. Ở nhánh
# đỏ, vân tay hiện tại được so và in để người đối soát biết lược đồ lệch tới đâu.
#
# Cách đóng / mở — đọc kỹ trước khi "đơn giản hoá":
#   * `docker stop <CID>` đúng container đã GHI LẠI. Không `compose stop`
#     (frontend/nginx `depends_on` backend — đừng để Compose suy ra phạm vi),
#     không `down`/`rm`: mất container CŨ là mất đường mở lại đúng ảnh cũ.
#   * `restart: unless-stopped` + dừng tay ⇒ dockerd không tự bật lại, kể cả
#     khi dockerd khởi động lại. Chính sách khác ⇒ DỪNG trước khi chạm gì.
#   * Mở lại bằng `docker start <CID cũ>`, KHÔNG `up -d`: `up -d` TẠO LẠI
#     container bằng ảnh MỚI vừa build ở Step 4. Sau khi mở, ĐO lại: CID đang
#     chạy = CID cũ, ảnh = ảnh cũ.
#   * `upstream backend { server backend:8000; }` của nginx phân giải tên MỘT lần
#     lúc nạp cấu hình. IP backend đổi sau `docker start` ⇒ khởi động lại ĐÚNG
#     container nginx đã ghi ở 4c (cùng ảnh, cùng cấu hình), rồi ĐO PHỤC HỒI
#     DỊCH VỤ (`_dcg_do_dich_vu_nginx`, BẮT BUỘC): TLS + SNI thật, route backend /
#     frontend / API, so THÂN `/health` qua nginx với thân lấy thẳng từ backend.
#     `nginx-verify.sh` (đi theo mã MỚI, gồm đầu dò token/PII) chạy SAU đó CHỈ ĐỂ
#     THÔNG TIN (F39): nginx đang đo ở đây là nginx CŨ — ảnh cũ ghi token thô —
#     và một đầu dò PII đỏ không nói gì về việc người dùng có tới được ứng dụng.
#     Đường deploy bản MỚI vẫn BẮT BUỘC kiểm PII: Step 8b `nginx-apply.sh` gọi
#     `nginx-verify.sh` trên candidate và chặn khi không đạt.
#
# Trap theo PHA (`_DCG_PHA`) — chạy ở MỌI lối ra (error/exit) và khi nhận
# HUP/INT/TERM/PIPE (runner bị `cancel-in-progress` giết, phiên SSH rớt ⇒ lần
# ghi stdout kế tiếp nhận SIGPIPE):
#   chua_dong                → không làm gì (chưa đụng container nào)
#   dang_dong, da_dong       → CSDL CHƯA bị migration chạm ⇒ mở lại ĐÚNG container
#                              cũ (qua cổng vân tay khi đã có bản chụp 4c)
#   dang_migrate             → dọn one-off alembic CỦA LƯỢT NÀY (chỉ khi exited);
#                              KHÔNG mở, KHÔNG phát lại; in hướng dẫn đối soát
#   migrate_do, da_migrate   → KHÔNG mở, KHÔNG phát lại; in trạng thái ĐO THẬT +
#                              hướng dẫn phục hồi có đối soát
#   buoc8, xong              → không làm gì
# SIGKILL không có trap: container nằm DỪNG (fail-closed). Pha cuối cùng đọc ở
# tệp trạng thái `$BACKUP_DIR/deploy_<TIMESTAMP>.trang-thai`.
#
# TỆP TRẠNG THÁI (F37): mỗi pha được in ra log deploy VÀ ghi vào tệp. Ghi tệp
# hỏng (hết đĩa, quyền) KHÔNG bị nuốt:
#   * trước khi migration chạy (chua_dong, dang_dong, da_dong, dang_migrate) ⇒
#     DỪNG deploy (fail-closed), trap mở lại đúng container cũ;
#   * sau khi migration đã chạy ⇒ cảnh báo to, pha vẫn còn trong log deploy, cờ
#     `_DCG_TT_HONG=1` được nhắc lại lúc thoát; nhánh sau migration chỉ còn ĐO
#     và IN (không ghi gì vào CSDL), nên không có gì để bẻ gãy giữa chừng.
#
# Chỉ áp ở chế độ ROUTINE. Cold cutover không tự migrate (Step 6 bỏ qua), nên
# không có đường mất ghi này; giữ nguyên hành vi cũ.
_DCG_PHA="khong_ap_dung"
_DCG_TIN_HIEU=""
_DCG_TT_HONG=0
_DCG_SO_PSQL=0
_DCG_NGINX_CID=""
_DCG_VT_4C_ND=""
_DCG_GIO_T0=""
_DCG_TT="$BACKUP_DIR/deploy_${TIMESTAMP}.trang-thai"
_DCG_DEM_T0="$BACKUP_DIR/deploy_${TIMESTAMP}.dem-T0"
_DCG_DEM_T1="$BACKUP_DIR/deploy_${TIMESTAMP}.dem-T1"
_DCG_DEM_T2="$BACKUP_DIR/deploy_${TIMESTAMP}.dem-T2"
_DCG_CSDL_T1=""
_DCG_PSQL_T1=0
_DCG_VT_4C="$BACKUP_DIR/deploy_${TIMESTAMP}.van-tay-4c"
_DCG_VT_SQL="$BACKUP_DIR/deploy_${TIMESTAMP}.van-tay.sql"
# One-off alembic của CHÍNH lượt này: tên riêng (thời điểm + PID) và CID được
# ghi nhận lúc nó xuất hiện. Dọn CHỈ theo CID ấy, CHỈ khi `exited`.
_DCG_ONEOFF_TEN="dcg-mig-${TIMESTAMP}-$$"
_DCG_ONEOFF_GHI="$BACKUP_DIR/deploy_${TIMESTAMP}.oneoff-cid"
_DCG_ONEOFF_THEO=""
_DCG_ONEOFF_XONG=0
# Vòng 4: trap CHỜ one-off của lượt kết thúc trong thời hạn hữu hạn rồi mới in
# trạng thái; hết hạn ⇒ báo "còn chạy / chưa xác định", KHÔNG dọn cưỡng bức, và
# mọi số đo in sau đó KHÔNG được gọi là trạng thái cuối (`_DCG_ONEOFF_CON_CHAY=1`).
_DCG_ONEOFF_CON_CHAY=0
# Vòng 5 (F43): lý do của trạng thái CHƯA XÁC ĐỊNH (còn chạy / KHÔNG ĐỌC ĐƯỢC Docker / CID hỏng).
_DCG_ONEOFF_LY_DO=""
# Vòng 6: nhánh mở lại container cũ kết thúc CHƯA XÁC ĐỊNH (lệnh ghi hết hạn / không đọc được).
_DCG_MO_CHUA_XD=0
# Vòng 4 (F40): lượt này là ĐƯỜNG ĐI TIẾP sau migration đỏ (đã kiểm ở Step 3a).
_DCG_DI_TIEP="$_DI_TIEP"
declare -A _DCG_CID=() _DCG_ANH=() _DCG_MOC=() _DCG_IP=()



# Tệp trạng thái — ghi theo từng pha để còn đọc được sau SIGKILL / mất log.
# Chỉ ghi CID, image ID, tên pha: không dữ liệu hàng, không biến môi trường.
# Ghi hỏng ⇒ BÁO (không nuốt) và trả ≠0; bên gọi quyết định theo pha.
_dcg_ghi() {
    local dong
    dong=$(printf '%s\t%s\t%s' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "${2:-}")
    if printf '%s\n' "$dong" >> "$_DCG_TT" 2>/dev/null; then
        return 0
    fi
    _DCG_TT_HONG=1
    warn "[trạng thái] KHÔNG ghi được $_DCG_TT (hết đĩa? quyền?) — dòng bị mất: $dong"
    return 1
}
_dcg_pha() {
    local truoc="$_DCG_PHA"
    [ "$truoc" = "khong_ap_dung" ] && return 0
    _DCG_PHA="$1"
    log "  [pha] $1"
    _dcg_ghi pha "$1" && return 0
    case "$1" in
        chua_dong|dang_dong|da_dong|dang_migrate)
            # Migration CHƯA chạy ⇒ lùi về pha trước rồi dừng: trap mở lại đúng
            # container cũ nếu đã dừng chúng.
            _DCG_PHA="$truoc"
            error "[trạng thái] tệp trạng thái KHÔNG ghi được TRƯỚC khi migration chạy — DỪNG (fail-closed). CSDL chưa bị migration chạm." ;;
        *)
            warn "[trạng thái] tiếp tục; pha '$1' chỉ còn trong log deploy này" ;;
    esac
}

# MỘT câu SQL chỉ đọc. `</dev/null`: `exec` của Compose gắn stdin theo mặc
# định — không được nuốt stdin của tiến trình gọi script.
_dcg_psql() {
    # Vòng 5 (F43): có hạn — daemon/CSDL kẹt không được giữ cổng hay trap mãi.
    local h
    h=$(_dcg_han_con "$_DCG_HAN_PSQL") || { echo "hết ngân sách trap — không hỏi CSDL" >&2; return 124; }
    timeout -k 5 "$h" $_RA_COMPOSE exec -T postgres psql -X -A -t -q -v ON_ERROR_STOP=1 \
        -U "${POSTGRES_USER:-qlts}" -d "${POSTGRES_DB:-qlts_production}" \
        -c "$1" </dev/null
}

# Phiên của chính lệnh đo bị loại bằng `pg_backend_pid()`. Chỉ in pid/user/
# application_name/state — KHÔNG in câu truy vấn (có thể chứa PII; log Actions
# của kho này là CÔNG KHAI).
_DCG_SQL_PHIEN="SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND backend_type = 'client backend' AND pid <> pg_backend_pid()"
_DCG_SQL_PHIEN_CT="SELECT pid || ' user=' || coalesce(usename, '?') || ' app=' || coalesce(nullif(application_name, ''), '-') || ' state=' || coalesce(state, '?') FROM pg_stat_activity WHERE datname = current_database() AND backend_type = 'client backend' AND pid <> pg_backend_pid() ORDER BY pid"
_DCG_SQL_DEM="SELECT schemaname || '.' || relname || '|' || (n_tup_ins + n_tup_upd + n_tup_del) FROM pg_stat_user_tables ORDER BY 1"
_DCG_SQL_CSDL="SELECT sessions || '|' || xact_commit || '|' || tup_inserted || '|' || tup_updated || '|' || tup_deleted FROM pg_stat_database WHERE datname = current_database()"
# Vân tay lược đồ: MỘT dòng cho mỗi object, sắp xếp, KHÔNG có attnum/oid (phát
# lại dump tạo lại bảng ⇒ số thứ tự cột/oid đổi mà lược đồ không đổi). Thân
# hàm/định nghĩa view lấy md5. Không có ký tự `"`, `$`, backtick trong câu này.
_DCG_SQL_VAN_TAY="WITH ns AS (
  SELECT oid, nspname FROM pg_namespace
  WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
    AND nspname NOT LIKE 'pg_temp_%' AND nspname NOT LIKE 'pg_toast_temp_%'
), rel AS (
  SELECT c.oid, n.nspname || '.' || c.relname AS ten, c.relkind
  FROM pg_class c JOIN ns n ON n.oid = c.relnamespace
  WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
), dong(l) AS (
  SELECT 'nsp|' || nspname FROM ns
  UNION ALL SELECT 'rel|' || ten || '|' || relkind::text FROM rel
  UNION ALL SELECT 'col|' || r.ten || '|' || a.attname || '|' || format_type(a.atttypid, a.atttypmod)
         || '|' || a.attnotnull::text || '|' || coalesce(pg_get_expr(d.adbin, d.adrelid), '')
    FROM rel r JOIN pg_attribute a ON a.attrelid = r.oid AND a.attnum > 0 AND NOT a.attisdropped
    LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
  UNION ALL SELECT 'con|' || r.ten || '|' || co.conname || '|' || co.contype::text || '|' || pg_get_constraintdef(co.oid)
    FROM pg_constraint co JOIN rel r ON r.oid = co.conrelid
  UNION ALL SELECT 'idx|' || r.ten || '|' || ic.relname || '|' || pg_get_indexdef(i.indexrelid)
    FROM pg_index i JOIN rel r ON r.oid = i.indrelid JOIN pg_class ic ON ic.oid = i.indexrelid
  UNION ALL SELECT 'trg|' || r.ten || '|' || t.tgname || '|' || pg_get_triggerdef(t.oid)
    FROM pg_trigger t JOIN rel r ON r.oid = t.tgrelid WHERE NOT t.tgisinternal
  UNION ALL SELECT 'vdef|' || ten || '|' || md5(pg_get_viewdef(oid)) FROM rel WHERE relkind IN ('v', 'm')
  UNION ALL SELECT 'typ|' || n.nspname || '.' || t.typname || '|' || t.typtype::text || '|'
         || coalesce(format_type(nullif(t.typbasetype, 0), t.typtypmod), '') || '|'
         || coalesce((SELECT string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder) FROM pg_enum e WHERE e.enumtypid = t.oid), '')
    FROM pg_type t JOIN ns n ON n.oid = t.typnamespace
    WHERE t.typtype IN ('e', 'd')
       OR (t.typtype = 'c' AND (SELECT k.relkind FROM pg_class k WHERE k.oid = t.typrelid) = 'c')
  UNION ALL SELECT 'dcon|' || n.nspname || '.' || t.typname || '|' || co.conname || '|' || pg_get_constraintdef(co.oid)
    FROM pg_constraint co JOIN pg_type t ON t.oid = co.contypid JOIN ns n ON n.oid = t.typnamespace
  UNION ALL SELECT 'fn|' || n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')|'
         || p.prokind::text || '|' || md5(coalesce(p.prosrc, ''))
    FROM pg_proc p JOIN ns n ON n.oid = p.pronamespace
  UNION ALL SELECT 'pol|' || r.ten || '|' || po.polname || '|' || po.polcmd::text || '|'
         || coalesce(pg_get_expr(po.polqual, po.polrelid), '') || '|' || coalesce(pg_get_expr(po.polwithcheck, po.polrelid), '')
    FROM pg_policy po JOIN rel r ON r.oid = po.polrelid
  UNION ALL SELECT 'evt|' || evtname || '|' || evtevent || '|' || evtenabled::text FROM pg_event_trigger
  UNION ALL SELECT 'ext|' || extname || '|' || extversion FROM pg_extension
)
SELECT translate(l, E'\r\n', '  ') FROM dong ORDER BY 1"

# Vân tay hiện tại ra stdout (≥1 dòng `rel|`, nếu không ⇒ ≠0). Luôn được gọi
# trong `$( )` ⇒ KHÔNG đếm `_DCG_SO_PSQL` ở đây (biến của subshell bị mất).
_dcg_van_tay() {
    local ra
    ra=$(_dcg_psql "$_DCG_SQL_VAN_TAY") || return 1
    case "$ra" in *"rel|"*) : ;; *) return 1 ;; esac
    printf '%s\n' "$ra"
}

# So vân tay bản 4c (bộ nhớ) với bản đo LẠI ngay bây giờ. 0 = khớp từng dòng;
# 3 = lệch (in tối đa 20 dòng khác: '-' chỉ có ở 4c, '+' chỉ có bây giờ);
# 4 = không đo được. KHÔNG ghi đĩa (đĩa đầy vẫn so được).
_dcg_so_van_tay() {
    local hien so
    if [ -z "$_DCG_VT_4C_ND" ]; then
        warn "[vân tay] KHÔNG có bản chụp 4c — không chứng minh được lược đồ tương thích"
        return 4
    fi
    if ! hien=$(_dcg_van_tay); then
        warn "[vân tay] KHÔNG đo được vân tay lược đồ hiện tại"
        return 4
    fi
    if [ "$hien" = "$_DCG_VT_4C_ND" ]; then
        log "  ✓ [vân tay] lược đồ KHỚP bản chụp 4c ($(printf '%s\n' "$hien" | wc -l) dòng)"
        return 0
    fi
    so=$(awk 'NR == FNR { a[$0] = 1; next } { b[$0] = 1; if (!($0 in a)) n++ } END { for (k in a) if (!(k in b)) n++; print n + 0 }' \
        <(printf '%s\n' "$_DCG_VT_4C_ND") <(printf '%s\n' "$hien"))
    warn "[vân tay] lược đồ LỆCH bản chụp 4c: $so dòng khác (tối đa 20 dòng dưới; '-' chỉ có ở 4c, '+' chỉ có bây giờ):"
    awk 'NR == FNR { a[$0] = 1; next } { b[$0] = 1; if (!($0 in a)) print "       + " $0 } END { for (k in a) if (!(k in b)) print "       - " k }' \
        <(printf '%s\n' "$_DCG_VT_4C_ND") <(printf '%s\n' "$hien") | awk 'NR <= 20' || true
    return 3
}

# Mốc vòng đời của MỘT container: Status|StartedAt|FinishedAt. Container bị bật
# rồi tắt lại giữa chừng vẫn `exited`, nhưng hai mốc thời gian đã đổi.
_dcg_moc() {
    _dcg_dk inspect -f '{{.State.Status}}|{{.State.StartedAt}}|{{.State.FinishedAt}}' "$1"
}
_dcg_ip() {
    _dcg_dk inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "$1"
}

# Đo cửa ghi phía CONTAINER. Trả ≠0 kèm lý do; không `error` ở đây — bên gọi
# quyết định (4c: dừng + mở lại; bước (d) ở nhánh đỏ: CHỈ in để đối soát).
# Hàm này được gọi trong ngữ cảnh `if`/`||` (set -e TẮT) nên mọi lệnh đều được
# kiểm tường minh.
_dcg_cua_dong() {
    local nhan="$1" s ds m
    for s in $_DCG_DICH_VU; do
        if ! ds=$(_dcg_dk ${_RA_COMPOSE#docker } ps -q "$s"); then
            warn "[$nhan] không liệt kê được container ĐANG CHẠY của '$s' (lỗi hoặc hết hạn Docker) — không đo được"
            return 1
        fi
        if [ -n "$ds" ]; then
            warn "[$nhan] '$s' có container ĐANG CHẠY: ${ds//[[:space:]]/ }"
            return 1
        fi
        if ! m=$(_dcg_moc "${_DCG_CID[$s]}"); then
            warn "[$nhan] không đọc được trạng thái container cũ của '$s'"
            return 1
        fi
        if [ "${m%%|*}" != "exited" ]; then
            warn "[$nhan] container cũ của '$s' ở trạng thái '${m%%|*}' (cần exited)"
            return 1
        fi
        if [ "$m" != "${_DCG_MOC[$s]}" ]; then
            warn "[$nhan] container cũ của '$s' ĐÃ CHẠY LẠI giữa chừng — mốc vòng đời đổi:
       lúc đóng: ${_DCG_MOC[$s]}
       bây giờ : $m"
            return 1
        fi
    done
    log "  ✓ [$nhan] 3 container ghi đều exited, mốc vòng đời không đổi, service không có container nào đang chạy"
}

# Đo cửa ghi phía CSDL: 0 phiên client nào khác trong CSDL đích. Chờ tối đa
# QLTS_HAN_PHIEN_LA giây (phiên của container vừa dừng cần một nhịp để rời đi).
_dcg_phien_la_bang_0() {
    local nhan="$1" n het
    het=$((SECONDS + _DCG_HAN_PHIEN))
    while :; do
        _DCG_SO_PSQL=$((_DCG_SO_PSQL + 1))
        if ! n=$(_dcg_psql "$_DCG_SQL_PHIEN"); then
            warn "[$nhan] KHÔNG đo được pg_stat_activity — coi như cửa CHƯA đóng"
            return 1
        fi
        case "$n" in
            ''|*[!0-9]*) warn "[$nhan] pg_stat_activity trả '$n' (không phải số) — không đo được"; return 1 ;;
        esac
        if [ "$n" = "0" ]; then
            log "  ✓ [$nhan] 0 phiên lạ trên CSDL"
            return 0
        fi
        [ "$SECONDS" -ge "$het" ] && break
        sleep 1
    done
    warn "[$nhan] còn $n phiên lạ trên CSDL sau ${_DCG_HAN_PHIEN}s:"
    _DCG_SO_PSQL=$((_DCG_SO_PSQL + 1))
    _dcg_psql "$_DCG_SQL_PHIEN_CT" | sed 's/^/       /' || true
    return 1
}

# Chụp bộ đếm ghi theo bảng (chỉ TÊN bảng + số đếm). Rỗng/sai dạng ⇒ ≠0.
_dcg_chup_dem() {
    local ra
    _DCG_SO_PSQL=$((_DCG_SO_PSQL + 1))
    ra=$(_dcg_psql "$_DCG_SQL_DEM") || return 1
    [ -n "$ra" ] || return 1
    # awk đọc HẾT đầu vào (không thoát sớm như `grep -q`) ⇒ không có SIGPIPE
    # nào biến pipeline thành "không khớp" dưới `pipefail`.
    printf '%s\n' "$ra" | awk -F'|' 'NF != 2 || $1 == "" || $2 !~ /^[0-9]+$/ { bad = 1 } END { exit bad }' \
        || return 1
    printf '%s\n' "$ra" > "$1" || return 1
}

# Số liệu toàn CSDL (phiên đã nối, commit, chèn/sửa/xoá) — CHỈ ĐỂ ĐỌC, ra stdout.
# Gọi trong `$( )` ⇒ bên gọi tự đếm `_DCG_SO_PSQL` nếu cần.
_dcg_chup_csdl() {
    local ra
    ra=$(_dcg_psql "$_DCG_SQL_CSDL") || return 1
    case "$ra" in *[!0-9\|]*|'') return 1 ;; esac
    printf '%s' "$ra"
}

# So hai lần chụp. In bảng có hiệu ≠ 0, bảng mới / biến mất. Trả 0 CHỈ khi
# cùng tập bảng và MỌI hiệu = 0 — mà như thế cũng KHÔNG chứng minh gì (PA2).
_dcg_so_dem() {
    awk -F'|' -v nhan="$3" '
        NR == FNR { a[$1] = $2; next }
        {
            seen[$1] = 1
            if (!($1 in a)) { print "       [" nhan "] bảng MỚI xuất hiện: " $1; bad = 1; next }
            d = $2 - a[$1]
            if (d != 0) { print "       [" nhan "] " $1 ": hiệu = " d; bad = 1 }
        }
        END {
            for (k in a) if (!(k in seen)) { print "       [" nhan "] bảng BIẾN MẤT: " k; bad = 1 }
            exit bad
        }' "$1" "$2"
}

# PA2 — CHỈ ĐO ĐỂ ĐỐI SOÁT (vòng 3: không còn là cổng của thao tác nào). Trả ≠0
# khi THẤY dấu hiệu ghi trong cửa sổ dump hoặc thiếu mốc; trả 0 KHÔNG chứng minh
# "0 ghi". Bên gọi chỉ in, không rẽ nhánh theo kết quả.
_dcg_pa2() {
    local ok=0 c2 so_tu_do
    log "[PA2] đo để ĐỐI SOÁT: hiệu bộ đếm T1−T0 ≠ 0 ⇒ có ghi trong cửa sổ dump (phát lại bản sao sẽ xoá chúng); = 0 KHÔNG chứng minh '0 ghi'"
    if [ ! -s "$_DCG_DEM_T0" ] || [ ! -s "$_DCG_DEM_T1" ]; then
        warn "[PA2] thiếu mốc T0/T1 — không đo được"
        return 1
    fi
    if ! _dcg_so_dem "$_DCG_DEM_T0" "$_DCG_DEM_T1" "T1-T0"; then
        warn "[PA2] có dấu hiệu ghi (hoặc bộ đếm bị đặt lại) trong cửa sổ dump"
        ok=1
    fi
    if _dcg_chup_dem "$_DCG_DEM_T2"; then
        log "[PA2] T2−T1 (lẫn ghi của chính migration AUTOCOMMIT và mọi ghi ngoài SAU T1):"
        _dcg_so_dem "$_DCG_DEM_T1" "$_DCG_DEM_T2" "T2-T1" || true
    else
        warn "[PA2] không chụp được T2"
    fi
    # pg_stat_database T1→T2: phiên deploy tự mở trong khoảng này được đếm;
    # alembic ≥ 1 phiên; healthcheck postgres cũng có thể đếm là phiên.
    so_tu_do=$((_DCG_SO_PSQL - _DCG_PSQL_T1 + 1))
    if [ -n "$_DCG_CSDL_T1" ] && c2=$(_dcg_chup_csdl); then
        awk -F'|' -v a="$_DCG_CSDL_T1" -v b="$c2" -v t="$so_tu_do" 'BEGIN {
            split(a, x, "|"); split(b, y, "|")
            printf "       [T2-T1 pg_stat_database] phiên +%d (deploy tự mở %d phiên đo; alembic ≥1; healthcheck) · commit +%d · chèn +%d · sửa +%d · xoá +%d\n",
                y[1]-x[1], t, y[2]-x[2], y[3]-x[3], y[4]-x[4], y[5]-x[5] }'
    else
        warn "[PA2] không chụp được pg_stat_database T1/T2"
    fi
    return "$ok"
}

# PHỤC HỒI DỊCH VỤ qua nginx ĐANG PHỤC VỤ — BẮT BUỘC ở nhánh lùi (F39). Đo bằng
# đường của client thật, từ MỘT container khác trên cùng mạng (ảnh của chính
# nginx ấy, có curl): TLS + SNI thật (`--resolve`, không `Host:`), /health →
# backend 200 và THÂN trùng thân lấy thẳng từ backend (một 200 từ catch-all sẽ
# lệch thân), /login → frontend 200, /api/ còn cưỡng chế xác thực (401), và khi
# NGINX_PROBE_STRICT_TLS=1 (mặc định, như nginx-verify.sh) chứng thư hợp lệ cho
# đúng $DOMAIN. Tầng chủ sở hữu của "người dùng tới được ứng dụng cũ" là HÀM
# NÀY — không phải `nginx-verify.sh` (xem `_dcg_thong_tin_pii_nginx`).
# Trả: 0 ĐẠT · 1 KHÔNG ĐẠT (đo được, sai) · 5 CHƯA XÁC ĐỊNH (vòng 6: không đọc được nginx,
# hoặc đầu dò HẾT HẠN — dịch vụ CHƯA được chứng minh theo chiều nào).
_dcg_do_dich_vu_nginx() {
    local mang ipn anh ra a b strict rong mh ml mp mc kq
    rong=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
    strict="${NGINX_PROBE_STRICT_TLS:-1}"
    mang=$(_dcg_dk inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' "$_DCG_NGINX_CID" \
        | awk 'NF && !x { print; x = 1 }') || mang=""
    [ -n "$mang" ] || { warn "[nginx · dịch vụ] KHÔNG ĐỌC ĐƯỢC mạng của nginx — dịch vụ CHƯA XÁC ĐỊNH"; return 5; }
    ipn=$(_dcg_dk inspect -f "{{(index .NetworkSettings.Networks \"$mang\").IPAddress}}" "$_DCG_NGINX_CID") || ipn=""
    anh=$(_dcg_dk inspect -f '{{.Image}}' "$_DCG_NGINX_CID") || anh=""
    [ -n "$ipn" ] && [ -n "$anh" ] || { warn "[nginx · dịch vụ] KHÔNG ĐỌC ĐƯỢC IP/ảnh của nginx — dịch vụ CHƯA XÁC ĐỊNH"; return 5; }
    # `docker run` THƯỜNG (không phải one-off Compose): `--entrypoint sh` tường
    # minh; không có khái niệm `--no-deps`. Mỗi phép đo in MỘT dòng `NHÃN giá-trị`.
    # Vòng 6: hạn RIÊNG `QLTS_HAN_DO_SNI` (≥ 6 curl × 8 s bên trong + dựng container).
    kq=$(_dcg_han_con "$_DCG_HAN_DO_SNI") \
        || { warn "[nginx · dịch vụ] HẾT NGÂN SÁCH trap trước đầu dò — dịch vụ CHƯA ĐƯỢC CHỨNG MINH (CHƯA XÁC ĐỊNH)"; return 5; }
    ra=$(timeout -k 5 "$kq" docker run --network "$mang" --rm -e DOMAIN="$DOMAIN" -e IPN="$ipn" -e STRICT="$strict" \
        --entrypoint sh "$anh" -c '
ma() { c=$(curl -sS -o /dev/null -w "%{http_code}" --max-time 8 --retry 0 "$@" 2>/dev/null || true); echo "${c:-000}"; }
echo "MA-HEALTH $(ma --insecure --resolve "$DOMAIN:443:$IPN" "https://$DOMAIN/health")"
echo "MA-LOGIN $(ma --insecure --resolve "$DOMAIN:443:$IPN" "https://$DOMAIN/login")"
echo "MA-API $(ma --insecure --resolve "$DOMAIN:443:$IPN" "https://$DOMAIN/api/payments/1")"
if [ "$STRICT" = "1" ]; then echo "MA-CHUNG-THU $(ma --resolve "$DOMAIN:443:$IPN" "https://$DOMAIN/health")"; else echo "MA-CHUNG-THU bo-qua"; fi
a=$(curl -sS --max-time 8 --insecure --resolve "$DOMAIN:443:$IPN" "https://$DOMAIN/health" 2>/dev/null | sha256sum | cut -d" " -f1)
b=$(curl -sS --max-time 8 http://backend:8000/health 2>/dev/null | sha256sum | cut -d" " -f1)
echo "THAN-NGINX $a"
echo "THAN-BACKEND $b"' 2>/dev/null) && kq=0 || kq=$?
    if _dcg_het_han "$kq"; then
        warn "[nginx · dịch vụ] đầu dò SNI HẾT HẠN (hạn ${_DCG_HAN_DO_SNI}s, còn ngân sách trap $(_dcg_con_lai)s) — dịch vụ CHƯA ĐƯỢC CHỨNG MINH (CHƯA XÁC ĐỊNH, không phải ĐẠT)"
        return 5
    fi
    mh=$(printf '%s\n' "$ra" | awk '$1 == "MA-HEALTH" { print $2 }')
    ml=$(printf '%s\n' "$ra" | awk '$1 == "MA-LOGIN" { print $2 }')
    mp=$(printf '%s\n' "$ra" | awk '$1 == "MA-API" { print $2 }')
    mc=$(printf '%s\n' "$ra" | awk '$1 == "MA-CHUNG-THU" { print $2 }')
    a=$(printf '%s\n' "$ra" | awk '$1 == "THAN-NGINX" { print $2 }')
    b=$(printf '%s\n' "$ra" | awk '$1 == "THAN-BACKEND" { print $2 }')
    log "  [nginx · dịch vụ] SNI=$DOMAIN → /health ${mh:-?} · /login ${ml:-?} · /api/payments/1 ${mp:-?} · chứng thư ${mc:-?}"
    if [ "$mh" != "200" ] || [ "$ml" != "200" ] || [ "$mp" != "401" ]; then
        warn "[nginx · dịch vụ] KHÔNG ĐẠT: cần /health 200, /login 200, /api/payments/1 401 qua SNI thật"
        return 1
    fi
    if [ "$strict" = "1" ] && [ "$mc" != "200" ]; then
        warn "[nginx · dịch vụ] KHÔNG ĐẠT: chứng thư không hợp lệ cho $DOMAIN (NGINX_PROBE_STRICT_TLS=1)"
        return 1
    fi
    if [ -z "$a" ] || [ "$a" = "$rong" ] || [ "$a" != "$b" ]; then
        warn "[nginx · dịch vụ] KHÔNG ĐẠT: thân /health qua nginx (SNI thật) KHÁC thân lấy thẳng từ backend (nginx=${a:-?} backend=${b:-?})"
        return 1
    fi
    log "  ✓ [nginx · dịch vụ] PHỤC HỒI DỊCH VỤ ĐẠT — TLS/SNI thật, route backend/frontend/API, thân /health qua nginx = thân từ backend"
}

# KIỂM PII trên nginx đang phục vụ — ở nhánh lùi CHỈ LÀ THÔNG TIN (F39). Chạy
# `nginx-verify.sh` của mã MỚI (gồm đầu dò token trong access log) lên nginx CŨ:
# ảnh cũ ghi `$request`/`$http_referer` THÔ nên đầu dò token đỏ là kết quả
# ĐÚNG về nginx cũ, không phải lỗi phục hồi. Luôn trả 0; kết quả ghi vào log
# deploy và tệp trạng thái để người vận hành biết nginx cũ còn lộ token.
_dcg_thong_tin_pii_nginx() {
    local rc=0
    log "  [nginx · PII — THÔNG TIN, KHÔNG chặn nhánh lùi] chạy nginx-verify.sh (mã mới) lên nginx CŨ đang phục vụ..."
    # Vòng 6: có hạn RIÊNG (`QLTS_HAN_PII`); `timeout` cắt cả nhóm tiến trình (bash + docker).
    local h
    if ! h=$(_dcg_han_con "$_DCG_HAN_PII"); then
        warn "[nginx · PII — THÔNG TIN, KHÔNG chặn] HẾT NGÂN SÁCH trap — BỎ kiểm PII. Kết quả phục hồi dịch vụ ở trên KHÔNG đổi (F39)."
        _dcg_ghi "pii_nginx_cu" "BO_QUA het_ngan_sach" || true
        return 0
    fi
    timeout -k 5 "$h" bash "$SCRIPT_DIR/nginx-verify.sh" "$_DCG_NGINX_CID" "$DOMAIN" || rc=$?
    if _dcg_het_han "$rc"; then
        warn "[nginx · PII — THÔNG TIN, KHÔNG chặn] nginx-verify.sh HẾT HẠN (${_DCG_HAN_PII}s) — chưa biết nginx cũ có lộ token. Kết quả phục hồi dịch vụ ở trên KHÔNG đổi (F39)."
        _dcg_ghi "pii_nginx_cu" "HET_HAN ${_DCG_HAN_PII}s" || true
        return 0
    fi
    if [ "$rc" -eq 0 ]; then
        log "  [nginx · PII — THÔNG TIN] nginx-verify.sh ĐẠT trên nginx cũ"
        _dcg_ghi "pii_nginx_cu" "dat" || true
    else
        warn "[nginx · PII — THÔNG TIN, KHÔNG chặn] nginx-verify.sh KHÔNG ĐẠT (rc=$rc) trên nginx CŨ — ảnh nginx cũ có thể ghi token THÔ vào access log (F39). Dịch vụ đã được đo RIÊNG ở trên; lộ token chỉ hết khi bản mới qua Step 8b."
        _dcg_ghi "pii_nginx_cu" "KHONG_DAT rc=$rc" || true
    fi
    return 0
}

# Vòng 6 (N21.07): ĐO LẠI sau một lệnh GHI (`docker start` / `docker restart`), bất kể mã
# trả: hết hạn KHÔNG chứng minh thao tác đã bị huỷ (daemon có thể vẫn làm), và rc 0 cũng
# chưa chứng minh nó có hiệu lực. KHÔNG BAO GIỜ tự chạy lại lệnh ghi.
#   <nhãn> <CID> <StartedAt TRƯỚC lệnh, rỗng nếu chưa biết> <ảnh mong đợi> <rc của lệnh ghi>
# Trả: 0 thao tác ĐÃ có hiệu lực (đúng CID, đúng ảnh, running, LẦN KHỞI ĐỘNG MỚI) ⇒ đi tiếp
#        hậu kiểm (CHƯA phải thành công — chỉ hậu kiểm SNI/vân tay mới kết luận);
#      1 KHÔNG mở được (đã dừng / ĐÃ XÁC NHẬN không tồn tại / ảnh khác);
#      5 CHƯA XÁC ĐỊNH (không đọc được; còn chạy LẦN CŨ — có thể restart chưa xong; trạng
#        thái trung gian; hoặc lệnh báo lỗi mà container lại đang chạy lần mới).
_dcg_sau_lenh_ghi() {
    local nhan="$1" cid="$2" truoc="$3" anh_mong="$4" rc="$5" m kq st bd anh
    m=$(_dcg_doc_ct '{{.State.Status}}|{{.State.StartedAt}}|{{.State.FinishedAt}}' "$cid") && kq=0 || kq=$?
    case "$kq" in
        2) warn "[$nhan] sau lệnh (rc=$rc): $cid ĐÃ XÁC NHẬN không tồn tại — KHÔNG mở được"; return 1 ;;
        0) : ;;
        *) warn "[$nhan] sau lệnh (rc=$rc): KHÔNG ĐỌC ĐƯỢC trạng thái $cid — CHƯA XÁC ĐỊNH (không chạy lại lệnh)"; return 5 ;;
    esac
    st=${m%%|*}; bd=${m#*|}; bd=${bd%%|*}
    if [ -n "$anh_mong" ]; then
        anh=$(_dcg_doc_ct '{{.Image}}' "$cid") && kq=0 || kq=$?
        case "$kq" in
            0) [ "$anh" = "$anh_mong" ] || { warn "[$nhan] sau lệnh: ảnh $anh KHÁC ảnh ghi nhận $anh_mong — KHÔNG mở được"; return 1; } ;;
            2) warn "[$nhan] sau lệnh: $cid ĐÃ XÁC NHẬN không tồn tại — KHÔNG mở được"; return 1 ;;
            *) warn "[$nhan] sau lệnh: KHÔNG ĐỌC ĐƯỢC ảnh của $cid — CHƯA XÁC ĐỊNH"; return 5 ;;
        esac
    fi
    case "$st" in
        running)
            if [ -n "$truoc" ] && [ "$bd" = "$truoc" ]; then
                warn "[$nhan] sau lệnh (rc=$rc): $cid running nhưng VẪN lần khởi động CŨ (StartedAt=$bd) — thao tác CHƯA hoàn tất, CHƯA XÁC ĐỊNH"
                return 5
            fi
            if [ "$rc" != "0" ] && ! _dcg_het_han "$rc"; then
                warn "[$nhan] lệnh báo lỗi (rc=$rc) mà $cid lại running lần MỚI — CHƯA XÁC ĐỊNH"
                return 5
            fi
            _dcg_het_han "$rc" && warn "[$nhan] lệnh HẾT HẠN (rc=$rc) nhưng ĐO LẠI: đúng CID, đúng ảnh, running, LẦN KHỞI ĐỘNG MỚI (StartedAt=$bd) ⇒ đi tiếp hậu kiểm (chưa kết luận thành công)"
            return 0 ;;
        exited|dead)
            warn "[$nhan] sau lệnh (rc=$rc): $cid đang '$st' — KHÔNG mở được"
            return 1 ;;
        *)
            warn "[$nhan] sau lệnh (rc=$rc): $cid đang '$st' (trung gian) — CHƯA XÁC ĐỊNH"
            return 5 ;;
    esac
}

# Vòng 6: nginx DỪNG hoặc trạng thái chưa rõ sau khi khởi động lại ⇒ cảnh báo rõ + phục hồi
# TAY theo ĐÚNG CID. <lý do> <StartedAt trước khởi động lại>
_dcg_nginx_tay() {
    warn "[nginx] ⚠ nginx $_DCG_NGINX_CID: $1 — NGƯỜI DÙNG CÓ THỂ KHÔNG TỚI ĐƯỢC DỊCH VỤ. Phục hồi TAY theo ĐÚNG CID (không dựng container mới):"
    warn "   a. docker inspect -f '{{.State.Status}} {{.State.StartedAt}}' $_DCG_NGINX_CID   (mốc TRƯỚC khởi động lại: ${2:-?}; StartedAt khác mốc ⇒ đã có lần khởi động mới)"
    warn "   b. 'exited' ⇒ docker start $_DCG_NGINX_CID   (KHÔNG compose up — nó dựng container MỚI từ ảnh/biến hiện hành)"
    warn "   c. đo qua SNI thật: curl --resolve $DOMAIN:443:<IP nginx> https://$DOMAIN/health và /login (IP: docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' $_DCG_NGINX_CID)"
    _dcg_ghi "nginx_tay" "$_DCG_NGINX_CID ${1// /_}" || true
}

# Mở lại ĐÚNG container cũ đã ghi ở 4c — CHỈ ở pha CHƯA migrate (CSDL chưa bị
# migration chạm). Thứ tự: CỔNG VÂN TAY (F35) → docker start → đo CID/ảnh/running
# → IP đổi thì khởi động lại đúng nginx cũ → ĐO PHỤC HỒI DỊCH VỤ (bắt buộc) →
# kiểm PII (thông tin). Trả: 0 đạt · 3 vân tay lệch (CHƯA bật gì) · 4 không đo
# được vân tay (CHƯA bật gì) · 1 KHÔNG mở được / KHÔNG đạt · 5 CHƯA XÁC ĐỊNH (vòng 6:
# lệnh hết hạn hoặc không đọc được — xem `_dcg_sau_lenh_ghi`). Không `error` trực
# tiếp — `_cho_healthy_dv` (vốn exit) chạy trong subshell riêng rồi được PHÂN LOẠI lại.
_dcg_mo_lai_cu() {
    local s live anh st ip kq vt="lược đồ khớp 4c" truoc m
    if [ "$_DCG_PHA" = "dang_dong" ] && [ -z "$_DCG_VT_4C_ND" ]; then
        vt="CSDL chưa bị chạm, chưa có vân tay 4c"
        log "  (chưa chụp vân tay 4c và CSDL chưa bị chạm — mở lại không qua cổng vân tay)"
    else
        if _dcg_so_van_tay; then kq=0; else kq=$?; fi
        if [ "$kq" -ne 0 ]; then
            warn "KHÔNG mở lại: chưa có BẰNG CHỨNG lược đồ tương thích với mã cũ (revision cũ KHÔNG đủ — AUTOCOMMIT)"
            return "$kq"
        fi
    fi
    for s in $_DCG_THU_TU_MO; do
        # Mốc StartedAt lúc ĐÓNG (4c): sau `start` phải thấy LẦN KHỞI ĐỘNG MỚI. Chưa có
        # mốc (bị ngắt giữa `docker stop`) ⇒ container có thể chưa từng dừng: running là đủ.
        truoc=${_DCG_MOC[$s]:-}; truoc=${truoc#*|}; truoc=${truoc%%|*}
        _dcg_du_ngan_sach "$_DCG_HAN_KHOI_DONG" "mở lại · $s (docker start)" || return 5
        timeout -k 5 "$_DCG_HAN_KHOI_DONG" docker start "${_DCG_CID[$s]}" >/dev/null && kq=0 || kq=$?
        if [ "$kq" -ne 0 ]; then
            warn "docker start container cũ của '$s' THẤT BẠI/HẾT HẠN (rc=$kq, hạn ${_DCG_HAN_KHOI_DONG}s) — ĐO LẠI, KHÔNG chạy lại lệnh"
        fi
        _dcg_sau_lenh_ghi "mở lại · $s" "${_DCG_CID[$s]}" "$truoc" "${_DCG_ANH[$s]}" "$kq" || return $?
        if [ "$s" = "backend" ]; then
            if ! ( _cho_healthy_dv backend "$(_dcg_han_con "$_HAN_HEALTH")" ); then
                # Không healthy: container còn chạy lần mới ⇒ KHÔNG đạt; không đọc được ⇒ CHƯA XÁC ĐỊNH.
                _dcg_sau_lenh_ghi "mở lại · backend (sau chờ healthy)" "${_DCG_CID[backend]}" "$truoc" "${_DCG_ANH[backend]}" 0 || return $?
                warn "'backend' không tới healthy — KHÔNG đạt"
                return 1
            fi
        fi
    done
    for s in $_DCG_THU_TU_MO; do
        if ! live=$(_dcg_dk ${_RA_COMPOSE#docker } ps -q "$s"); then
            warn "KHÔNG ĐỌC ĐƯỢC container đang chạy của '$s' sau khi mở lại (lỗi hoặc hết hạn) — CHƯA XÁC ĐỊNH"
            return 5
        fi
        if [ "$live" != "${_DCG_CID[$s]}" ]; then
            warn "'$s': container đang chạy ($live) KHÁC container cũ (${_DCG_CID[$s]})"
            return 1
        fi
        anh=$(_dcg_doc_ct '{{.Image}}' "$live") && kq=0 || kq=$?
        case "$kq" in
            0) : ;;
            2) warn "'$s': $live ĐÃ XÁC NHẬN không tồn tại sau khi mở lại"; return 1 ;;
            *) warn "KHÔNG ĐỌC ĐƯỢC ảnh của '$s' sau khi mở lại — CHƯA XÁC ĐỊNH"; return 5 ;;
        esac
        if [ "$anh" != "${_DCG_ANH[$s]}" ]; then
            warn "'$s': ảnh đang chạy $anh KHÁC ảnh cũ ${_DCG_ANH[$s]}"
            return 1
        fi
        st=$(_dcg_doc_ct '{{.State.Status}}' "$live") && kq=0 || kq=$?
        case "$kq" in
            0) : ;;
            2) warn "'$s': $live ĐÃ XÁC NHẬN không tồn tại sau khi mở lại"; return 1 ;;
            *) warn "KHÔNG ĐỌC ĐƯỢC trạng thái '$s' sau khi mở lại — CHƯA XÁC ĐỊNH"; return 5 ;;
        esac
        if [ "$st" != "running" ]; then
            warn "'$s' sau khi mở lại ở trạng thái '$st' (cần running)"
            return 1
        fi
    done
    ip=$(_dcg_doc_ct '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "${_DCG_CID[backend]}") && kq=0 || kq=$?
    if [ "$kq" -ne 0 ]; then
        warn "KHÔNG ĐỌC ĐƯỢC IP backend sau khi mở lại — CHƯA XÁC ĐỊNH (không đụng nginx khi Docker không trả lời)"
        return 5
    fi
    if [ "$ip" != "${_DCG_IP[backend]}" ]; then
        warn "IP backend ĐỔI sau khi mở lại (trước='${_DCG_IP[backend]}' sau='$ip') — khởi động lại ĐÚNG container nginx cũ ($_DCG_NGINX_CID) để nó phân giải lại upstream"
        # Khởi động lại ĐÚNG container nginx đã ghi ở 4c (theo CID) — CỐ Ý giữ NGUYÊN
        # ảnh, biến môi trường và bản render; mục đích DUY NHẤT là để nginx phân giải
        # lại tên upstream. KHÔNG phải cách áp cấu hình mới (việc đó chỉ đi qua
        # scripts/nginx-apply.sh) — và kết quả được ĐO ngay dưới qua SNI thật.
        # Đây là lời gọi DUY NHẤT được guard "lệnh đã chết" miễn trừ (khai đúng dòng
        # trong test_nginx_template_packaging.py); thêm một lời gọi khác ⇒ guard đỏ.
        # Vòng 6: chụp mốc khởi động TRƯỚC — running thôi chưa đủ: lần chạy CŨ còn sống có
        # thể là restart chưa hoàn tất. Không đọc được mốc ⇒ không restart (không chứng
        # minh được lần khởi động mới).
        truoc=$(_dcg_doc_ct '{{.State.StartedAt}}' "$_DCG_NGINX_CID") \
            || { warn "[nginx] KHÔNG ĐỌC ĐƯỢC mốc khởi động nginx TRƯỚC khi khởi động lại — KHÔNG khởi động lại; CHƯA XÁC ĐỊNH"; return 5; }
        _dcg_du_ngan_sach "$_DCG_HAN_NGINX_RESTART" "khởi động lại nginx" || return 5
        timeout -k 5 "$_DCG_HAN_NGINX_RESTART" docker restart -t 10 "$_DCG_NGINX_CID" >/dev/null && kq=0 || kq=$?
        if [ "$kq" -ne 0 ]; then
            warn "[nginx] khởi động lại container nginx cũ THẤT BẠI/HẾT HẠN (rc=$kq, hạn ${_DCG_HAN_NGINX_RESTART}s) — ĐO LẠI, KHÔNG chạy lại lệnh"
        fi
        _dcg_sau_lenh_ghi "nginx" "$_DCG_NGINX_CID" "$truoc" "" "$kq" && kq=0 || kq=$?
        if [ "$kq" -ne 0 ]; then
            [ "$kq" -eq 5 ] && _dcg_nginx_tay "CHƯA XÁC ĐỊNH sau khởi động lại" "$truoc" || _dcg_nginx_tay "DỪNG / KHÔNG mở được sau khởi động lại" "$truoc"
            return "$kq"
        fi
        if ! ( _cho_healthy_dv nginx "$(_dcg_han_con "$_HAN_HEALTH")" ); then
            _dcg_sau_lenh_ghi "nginx (sau chờ healthy)" "$_DCG_NGINX_CID" "$truoc" "" 0 && kq=1 || kq=$?
            [ "$kq" -eq 5 ] && _dcg_nginx_tay "CHƯA XÁC ĐỊNH sau chờ healthy" "$truoc" || _dcg_nginx_tay "không tới healthy" "$truoc"
            return "$kq"
        fi
    fi
    _dcg_do_dich_vu_nginx && kq=0 || kq=$?
    [ "$kq" -eq 0 ] || return "$kq"
    _dcg_thong_tin_pii_nginx
    _dcg_ghi "mo_lai_cu" "dat" || true
    log "  ✓ đã mở lại 3 container CŨ — cùng CID, cùng ảnh, $vt, phục hồi dịch vụ qua SNI thật ĐẠT (đã đo)"
}

# Ghi nhận CID one-off alembic của CHÍNH lượt này ngay khi nó xuất hiện. Chạy
# NỀN trong lúc `compose run` (tiền cảnh) làm việc: tiền cảnh giữ nguyên ngữ
# nghĩa tín hiệu (trap chạy SAU khi `compose run` trả về). Tên riêng của lượt
# (`$_DCG_ONEOFF_TEN`) không bao giờ trùng tên lượt khác; CID 64 hex được ghi
# vào `$_DCG_ONEOFF_GHI` — tệp RIÊNG, không chen vào tệp trạng thái.
_dcg_theo_oneoff() {
    local i=0 cid
    # Vòng 5 (F43): mỗi lần tra có hạn (`_dcg_dk`). Tra lỗi ở đây KHÔNG kết luận gì —
    # chỉ là chưa ghi được; người KẾT LUẬN là `_dcg_don_oneoff`/hướng dẫn, và chúng
    # tra lại theo tên, phân biệt "ĐÃ XÁC NHẬN không có" với "KHÔNG ĐỌC ĐƯỢC".
    while [ "$i" -lt 600 ]; do
        cid=$(_dcg_dk inspect -f '{{.Id}}' "$_DCG_ONEOFF_TEN" 2>/dev/null) || cid=""
        case "$cid" in
            ''|*[!0-9a-f]*) : ;;
            *)
                if [ "${#cid}" -eq 64 ]; then
                    printf '%s\n' "$cid" > "$_DCG_ONEOFF_GHI"
                    return 0
                fi ;;
        esac
        i=$((i + 1))
        sleep 0.2
    done
}
_dcg_dung_theo_oneoff() {
    [ -n "$_DCG_ONEOFF_THEO" ] || return 0
    kill "$_DCG_ONEOFF_THEO" 2>/dev/null || true
    wait "$_DCG_ONEOFF_THEO" 2>/dev/null || true
    _DCG_ONEOFF_THEO=""
}

# Vòng 5 (F43): đánh dấu trạng thái one-off CHƯA XÁC ĐỊNH — mọi số đo in sau đó
# KHÔNG được gọi là trạng thái cuối. <lý do> <giá trị dòng 'oneoff' của tệp trạng thái>
_dcg_oneoff_chua_xd() {
    _DCG_ONEOFF_CON_CHAY=1
    _DCG_ONEOFF_LY_DO="$1"
    _dcg_ghi "oneoff" "$2" || true
}

# Dọn one-off alembic CỦA CHÍNH LƯỢT NÀY: CHỈ theo CID đã ghi nhận, CHỈ khi
# container ấy mang đúng tên của lượt, nhãn one-off của service backend, và đang
# `exited`. Đang chạy / không khớp ⇒ KHÔNG đụng (alembic có thể VẪN đang chạy).
# `docker rm` không `-f`. Không bao giờ dọn theo nhãn chung: one-off của lượt
# khác (hoặc của người vận hành) không thuộc quyền lượt này.
_dcg_don_oneoff() {
    local cid tt het da_bao=0 nguon=ghi_nhan kq
    _DCG_ONEOFF_XONG=1
    _dcg_dung_theo_oneoff
    cid=$(cat "$_DCG_ONEOFF_GHI" 2>/dev/null) || cid=""
    case "$cid" in
        '')
            # Vòng 5 (F43): CHƯA ghi nhận CID KHÔNG có nghĩa là không có one-off — bộ
            # theo dõi nền có thể đã đọc lỗi trong khi migration chạy. Tra theo TÊN
            # riêng của lượt: chỉ ĐO (không bao giờ dọn theo tên — chỉ dọn CID ghi nhận).
            cid=$(_dcg_cid_theo_ten "$_DCG_ONEOFF_TEN") && kq=0 || kq=$?
            case "$kq" in
                0)
                    nguon=theo_ten
                    log "  [one-off] chưa ghi nhận CID, nhưng tra theo tên $_DCG_ONEOFF_TEN thấy $cid — chỉ ĐO, KHÔNG dọn (chỉ dọn CID đã ghi nhận)" ;;
                2)
                    log "  [one-off] chưa ghi nhận CID; tra theo tên: ĐÃ XÁC NHẬN không có container nào tên $_DCG_ONEOFF_TEN — không dọn gì"
                    _dcg_ghi "oneoff" "- khong_co_theo_ten" || true
                    return 0 ;;
                *)
                    warn "[one-off] chưa ghi nhận CID và KHÔNG ĐỌC ĐƯỢC Docker khi tra theo tên $_DCG_ONEOFF_TEN (lỗi hoặc hết hạn) — one-off CÓ THỂ VẪN CHẠY: CHƯA XÁC ĐỊNH. KHÔNG dọn; mọi số đo in sau đây KHÔNG phải trạng thái cuối."
                    _dcg_oneoff_chua_xd "chưa ghi nhận CID, tra theo tên KHÔNG ĐỌC ĐƯỢC" "- khong_doc_duoc_theo_ten"
                    return 1 ;;
            esac ;;
        *[!0-9a-f]*)
            warn "[one-off] CID ghi nhận có ký tự lạ ('$cid') — KHÔNG dọn; trạng thái one-off CHƯA XÁC ĐỊNH"
            _dcg_oneoff_chua_xd "CID ghi nhận hỏng" "- cid_hong"
            return 1 ;;
    esac
    if [ "${#cid}" -ne 64 ]; then
        warn "[one-off] CID ghi nhận dài ${#cid} (cần 64 hex) — KHÔNG dọn; trạng thái one-off CHƯA XÁC ĐỊNH"
        _dcg_oneoff_chua_xd "CID ghi nhận hỏng" "- cid_hong"
        return 1
    fi
    # Vòng 4 (owner chốt): CHỜ one-off kết thúc trong thời hạn HỮU HẠN. Đo được:
    # bị ngắt giữa migrate thì alembic CHẠY TIẾP sau khi deploy.sh thoát — in trạng
    # thái lúc ấy là in một ảnh chụp giữa chừng. Hết hạn ⇒ KHÔNG dọn cưỡng bức.
    # Vòng 5 (F43): mỗi lần đọc có hạn (`_dcg_doc_ct`); đọc lỗi KHÔNG thoát vòng —
    # thử lại tới hết hạn rồi báo CHƯA XÁC ĐỊNH. Chỉ "ĐÃ XÁC NHẬN không tồn tại" mới
    # được gọi là `--rm` đã dọn.
    het=$((SECONDS + _DCG_HAN_ONEOFF))
    while :; do
        tt=$(_dcg_doc_ct '{{.State.Status}}' "$cid") && kq=0 || kq=$?
        if [ "$kq" -eq 2 ]; then
            log "  [one-off] $cid không còn (\`--rm\` đã dọn — ĐÃ XÁC NHẬN: docker ps -a không thấy) — không dọn gì"
            _dcg_ghi "oneoff" "$cid khong_con" || true
            return 0
        fi
        if [ "$kq" -eq 0 ]; then
            case "$tt" in
                running|restarting|created|paused|removing) : ;;
                *) break ;;
            esac
        else
            tt="KHÔNG ĐỌC ĐƯỢC"
        fi
        if [ "$(_dcg_con_lai)" -le 0 ]; then
            warn "[one-off] HẾT NGÂN SÁCH trap khi chờ one-off alembic ($cid) — CHƯA XÁC ĐỊNH, KHÔNG dọn; mọi số đo in sau đây KHÔNG phải trạng thái cuối."
            _dcg_oneoff_chua_xd "HẾT NGÂN SÁCH trap khi chờ" "$cid het_ngan_sach"
            return 1
        fi
        if [ "$SECONDS" -ge "$het" ]; then
            if [ "$kq" -ne 0 ]; then
                warn "[one-off] KHÔNG ĐỌC ĐƯỢC trạng thái one-off alembic của lượt này ($cid) trong ${_DCG_HAN_ONEOFF}s (lỗi hoặc hết hạn Docker) — CHƯA XÁC ĐỊNH, có thể VẪN chạy. KHÔNG dọn; mọi số đo in sau đây KHÔNG phải trạng thái cuối."
                _dcg_oneoff_chua_xd "KHÔNG ĐỌC ĐƯỢC Docker trong ${_DCG_HAN_ONEOFF}s" "$cid khong_doc_duoc_sau_${_DCG_HAN_ONEOFF}s"
                return 1
            fi
            _DCG_ONEOFF_CON_CHAY=1
            warn "[one-off] one-off alembic của lượt này ($cid) VẪN '$tt' sau ${_DCG_HAN_ONEOFF}s chờ — CÒN CHẠY / CHƯA XÁC ĐỊNH. KHÔNG dọn cưỡng bức; mọi số đo in sau đây KHÔNG phải trạng thái cuối."
            _DCG_ONEOFF_LY_DO="VẪN '$tt' sau ${_DCG_HAN_ONEOFF}s chờ"
            _dcg_ghi "oneoff" "$cid con_chay_sau_${_DCG_HAN_ONEOFF}s" || true
            return 1
        fi
        if [ "$da_bao" = "0" ]; then
            log "  [one-off] one-off alembic của lượt này ($cid) đang '$tt' — CHỜ tối đa ${_DCG_HAN_ONEOFF}s cho nó kết thúc (không dọn cưỡng bức)..."
            da_bao=1
        fi
        sleep 1
    done
    tt=$(_dcg_doc_ct '{{.Name}}|{{index .Config.Labels "com.docker.compose.oneoff"}}|{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Status}}' "$cid") && kq=0 || kq=$?
    case "$kq" in
        0) : ;;
        2)
            log "  [one-off] $cid không còn (\`--rm\` đã dọn — ĐÃ XÁC NHẬN: docker ps -a không thấy) — không dọn gì"
            _dcg_ghi "oneoff" "$cid khong_con" || true
            return 0 ;;
        *)
            warn "[one-off] KHÔNG ĐỌC ĐƯỢC chi tiết one-off $cid (lỗi hoặc hết hạn Docker) — CHƯA XÁC ĐỊNH. KHÔNG dọn; mọi số đo in sau đây KHÔNG phải trạng thái cuối."
            _dcg_oneoff_chua_xd "KHÔNG ĐỌC ĐƯỢC chi tiết one-off" "$cid khong_doc_duoc"
            return 1 ;;
    esac
    if [ "$nguon" = "theo_ten" ]; then
        log "  [one-off] (tra theo tên) $cid đo: '${tt##*|}' — KHÔNG dọn (CID chưa được ghi nhận)"
        _dcg_ghi "oneoff" "$cid theo_ten ${tt##*|}" || true
        return 0
    fi
    case "$tt" in
        "/$_DCG_ONEOFF_TEN|True|backend|exited")
            _dcg_du_ngan_sach "$_DCG_HAN_LENH" "dọn one-off $cid" || return 1
            if _dcg_dk rm "$cid" >/dev/null; then
                log "  ✓ [one-off] đã dọn one-off alembic của CHÍNH lượt này ($cid, exited)"
                _dcg_ghi "oneoff" "$cid da_don" || true
                return 0
            fi
            warn "[one-off] docker rm $cid THẤT BẠI"
            return 1 ;;
        "/$_DCG_ONEOFF_TEN|True|backend|"*)
            warn "[one-off] one-off alembic của lượt này ($cid) đang '${tt##*|}' — KHÔNG dọn (chỉ dọn khi exited). Alembic có thể VẪN đang chạy."
            _dcg_ghi "oneoff" "$cid giu ${tt##*|}" || true
            return 1 ;;
        *)
            warn "[one-off] $cid KHÔNG khớp one-off của lượt này (đo: '$tt') — KHÔNG dọn"
            return 1 ;;
    esac
}

_dcg_huong_dan() {
    local s m ds cid tt_nguon oo kq
    if [ -n "${_DCG_TRAP_HET:-}" ] && [ "$(_dcg_con_lai)" -le 0 ]; then
        # Vòng 6b: HẾT ngân sách ⇒ in NGẮN, KHÔNG đọc Docker/CSDL.
        warn "[cửa ghi] $1"
        warn "  ⚠ HẾT NGÂN SÁCH trap — KHÔNG đo thêm Docker/CSDL: trạng thái container/one-off/lược đồ CHƯA XÁC ĐỊNH; daemon có thể VẪN đang làm lệnh cuối."
        warn "  pha=$_DCG_PHA · container ghi nhận: backend ${_DCG_CID[backend]:-?} · celery-worker ${_DCG_CID[celery-worker]:-?} · celery-beat ${_DCG_CID[celery-beat]:-?} · nginx ${_DCG_NGINX_CID:-?} · one-off: tên $_DCG_ONEOFF_TEN"
        warn "  Đo TAY theo tệp trạng thái $_DCG_TT; bản sao Step 5: ${_BAN_SAO:-CHƯA tạo} (KHÔNG phát lại tự động); vân tay 4c: $_DCG_VT_4C · câu SQL: $_DCG_VT_SQL"
        _dcg_ghi "het_ngan_sach" "huong_dan_ngan" || true
        return 0
    fi
    # Vòng 5 (F43): đo one-off của lượt TRƯỚC khi in đầu khối — còn chạy hoặc KHÔNG
    # ĐỌC ĐƯỢC thì cả khối là ảnh chụp giữa chừng. Lỗi đọc KHÔNG BAO GIỜ thành "không còn".
    cid=$(cat "$_DCG_ONEOFF_GHI" 2>/dev/null) || cid=""
    case "$_DCG_PHA" in
        chua_dong|dang_dong|da_dong) oo="migration CHƯA chạy ở lượt này" ;;
        *)
            if [ -z "$cid" ]; then
                cid=$(_dcg_cid_theo_ten "$_DCG_ONEOFF_TEN") && kq=0 || kq=$?
                case "$kq" in
                    0) oo="chưa ghi nhận CID · tra theo tên: $cid" ;;
                    2) oo="chưa ghi nhận CID · tra theo tên: KHÔNG có (ĐÃ XÁC NHẬN)"; cid="" ;;
                    *) oo="chưa ghi nhận CID · tra theo tên: KHÔNG ĐỌC ĐƯỢC"; cid=""
                       [ "$_DCG_ONEOFF_CON_CHAY" = "1" ] \
                           || _dcg_oneoff_chua_xd "tra theo tên KHÔNG ĐỌC ĐƯỢC lúc in hướng dẫn" "- khong_doc_duoc_luc_in" ;;
                esac
            else
                oo="CID ghi nhận $cid"
            fi
            if [ -n "$cid" ]; then
                m=$(_dcg_doc_ct '{{.State.Status}}' "$cid") && kq=0 || kq=$?
                case "$kq" in
                    0) oo="$oo · đo: $m"
                       case "$m" in
                           running|restarting|created|paused|removing)
                               [ "$_DCG_ONEOFF_CON_CHAY" = "1" ] \
                                   || _dcg_oneoff_chua_xd "đang '$m' lúc in hướng dẫn" "$cid ${m}_luc_in" ;;
                       esac ;;
                    2) oo="$oo · đo: không còn (ĐÃ XÁC NHẬN: docker ps -a không thấy)" ;;
                    *) oo="$oo · đo: KHÔNG ĐỌC ĐƯỢC (lỗi hoặc hết hạn Docker)"
                       [ "$_DCG_ONEOFF_CON_CHAY" = "1" ] \
                           || _dcg_oneoff_chua_xd "KHÔNG ĐỌC ĐƯỢC lúc in hướng dẫn" "$cid khong_doc_duoc_luc_in" ;;
                esac
            fi ;;
    esac
    warn "[cửa ghi] $1"
    if [ "${_DCG_MO_CHUA_XD:-0}" = "1" ]; then
        warn "  ⚠ trạng thái container sau lệnh mở lại CHƯA XÁC ĐỊNH (lệnh hết hạn / Docker không trả lời) — số đo dưới là LÚC IN, KHÔNG phải trạng thái cuối; daemon có thể VẪN đang thực hiện lệnh."
    fi
    if [ "$_DCG_ONEOFF_CON_CHAY" = "1" ]; then
        warn "  ⚠ one-off alembic của lượt này CÒN CHẠY / CHƯA XÁC ĐỊNH (${_DCG_ONEOFF_LY_DO:-?}) — số đo dưới là LÚC IN, KHÔNG phải trạng thái cuối; lược đồ có thể còn đang đổi."
    fi
    warn "  pha=$_DCG_PHA · tín hiệu=${_DCG_TIN_HIEU:--} · script KHÔNG tự mở ứng dụng và KHÔNG tự phát lại bản sao (F28). Trạng thái ĐO THẬT:"
    for s in $_DCG_THU_TU_MO; do
        m=$(_dcg_moc "${_DCG_CID[$s]:-khong-co}" 2>/dev/null) || m="KHÔNG đọc được"
        ds=$(_dcg_dk ${_RA_COMPOSE#docker } ps -q "$s" 2>/dev/null) || ds="KHÔNG ĐỌC ĐƯỢC"
        warn "  '$s': container cũ ${_DCG_CID[$s]:-?} · ảnh ${_DCG_ANH[$s]:-?} · đo: $m · container ĐANG CHẠY của service: [${ds//[[:space:]]/ }]"
    done
    m=$(_dcg_dk inspect -f '{{.State.Status}}' "${_DCG_NGINX_CID:-khong-co}" 2>/dev/null) || m="KHÔNG đọc được"
    warn "  'nginx': ${_DCG_NGINX_CID:-?} · đo: $m"
    warn "  one-off alembic của lượt này: tên $_DCG_ONEOFF_TEN · $oo"
    if [ -n "$_DCG_VT_4C_ND" ]; then
        _dcg_so_van_tay >/dev/null 2>&1
        case $? in
            0) warn "  vân tay lược đồ BÂY GIỜ: KHỚP bản 4c" ;;
            3) warn "  vân tay lược đồ BÂY GIỜ: LỆCH bản 4c — KHÔNG được bật mã cũ" ;;
            *) warn "  vân tay lược đồ BÂY GIỜ: KHÔNG đo được" ;;
        esac
    fi
    [ "$_DCG_TT_HONG" = "1" ] && warn "  ⚠ tệp trạng thái đã có lần KHÔNG ghi được — đọc pha ở log deploy này"
    warn "  bản sao Step 5 (chụp khi cửa ghi ĐÃ đóng, mốc T0 ${_DCG_GIO_T0:-?}): ${_BAN_SAO:-CHƯA tạo} · vân tay 4c: $_DCG_VT_4C · câu SQL vân tay: $_DCG_VT_SQL"
    warn "  bộ đếm T0/T1/T2: $_DCG_DEM_T0 · $_DCG_DEM_T1 · $_DCG_DEM_T2 · tệp trạng thái: $_DCG_TT"
    warn "  PHỤC HỒI CÓ ĐỐI SOÁT — theo thứ tự, KHÔNG bỏ bước. CSDL đang giữ MỌI ghi đã commit; đừng phá nó trước khi đối chiếu:"
    warn "   1. Chắc chắn KHÔNG còn migration nào chạy. One-off của lượt này: docker inspect -f '{{.State.Status}}' <CID ghi nhận ở trên>; CHỈ khi 'exited' mới docker rm <CID ấy>. KHÔNG dọn one-off nào khác (lượt khác / đang chạy)."
    warn "   2. So vân tay lược đồ với bản 4c (rỗng = KHỚP): docker compose -f docker-compose.yml --profile production --env-file .env.production exec -T postgres psql -X -A -t -q -U ${POSTGRES_USER:-qlts} -d ${POSTGRES_DB:-qlts_production} < $_DCG_VT_SQL | diff $_DCG_VT_4C -"
    case "$_DCG_PHA" in
        dang_migrate|migrate_do|da_migrate) tt_nguon="$_DCG_TT" ;;
        *) tt_nguon="${_DT_TT_CU:-}" ;;
    esac
    if [ -n "$tt_nguon" ]; then
        warn "   3. Ưu tiên ĐI TIẾP (KHÔNG bật mã cũ, CSDL giữ nguyên, KHÔNG mất ghi nào): sửa nguyên nhân, đưa cây tới commit SỬA, rồi TRÊN VPS chạy đúng lệnh:"
        warn "      SHA_MONG_DOI=<40 hex commit sửa> QLTS_DI_TIEP_SAU_MIGRATE_DO=1 QLTS_DI_TIEP_TU=$tt_nguon bash scripts/deploy.sh"
        warn "      Lệnh tự kiểm trước mọi thay đổi và TỪ CHỐI nếu: có container đang chạy, CID ghi nhận mất/không exited/đã chạy lại, one-off alembic còn chạy, pha không phải dừng-sau-migration, nginx khác CID ghi nhận."
    else
        warn "   3. Đường ĐI TIẾP KHÔNG áp dụng ở pha '$_DCG_PHA' (migration chưa chạy): điều tra theo trạng thái đo ở trên."
    fi
    warn "   4. Vân tay KHỚP chỉ nói về LƯỢC ĐỒ: migration dữ liệu đã AUTOCOMMIT vẫn có thể đã sửa hàng — đọc migration hỏng trước. Chỉ khi chắc mã cũ chạy đúng trên dữ liệu hiện tại: docker start đủ ba CID ở trên (backend trước; KHÔNG up -d — nó dựng ảnh MỚI)."
    warn "      Sau đó: IP backend đổi thì khởi động lại ĐÚNG CID nginx ở trên, rồi đo dịch vụ qua SNI thật (curl --resolve $DOMAIN:443:<IP nginx> https://$DOMAIN/health và /login)."
    warn "   5. Vân tay LỆCH: KHÔNG mở mã cũ. Nếu buộc phải LÙI bằng bản sao, ĐỐI SOÁT TRƯỚC: (a) mọi ghi commit SAU mốc T0 sẽ MẤT — so bộ đếm T0/T1/T2, xem phiên đã/đang nối (pg_stat_activity), tra các bảng có cột thời gian (created_at/updated_at > T0) để liệt kê TỪNG khoá; (b) có ghi ⇒ trích chúng ra TRƯỚC để nhập lại; (c) phát lại: docker compose -f docker-compose.yml --env-file .env.production exec -T postgres psql -v ON_ERROR_STOP=1 -U ${POSTGRES_USER:-qlts} ${POSTGRES_DB:-qlts_production} < bản sao; (d) dump --clean --if-exists KHÔNG xoá object migration hỏng tạo thêm (dòng '+' ở bước 2) — dọn có chủ đích; (e) so lại vân tay, CHỈ KHI KHỚP mới làm bước 4."
}


_dcg_bat_tin_hieu() {
    _DCG_TIN_HIEU="$1"
    exit "$2"
}

_dcg_khi_thoat() {
    local rc=$?
    trap - EXIT
    trap '' HUP INT TERM PIPE
    set +eu
    _dcg_ghi "thoat" "rc=$rc tin_hieu=${_DCG_TIN_HIEU:--} pha=$_DCG_PHA"
    # Vòng 6: trần thời gian — IN ngay đầu trap và GHI vào tệp trạng thái (nhật ký local);
    # cuối trap ĐO thời gian thật và so với trần.
    local ns ns_ct bd_trap kq
    ns=$(_dcg_ngan_sach_trap); ns_ct=${ns#* }; ns=${ns%% *}
    bd_trap=$SECONDS
    if [ "$ns" -gt 0 ]; then
        if [ -n "$_DCG_TRAN_GHI_DE" ] && [ "$_DCG_TRAN_GHI_DE" -lt "$ns" ]; then
            ns_ct="$ns_ct — GHI ĐÈ QLTS_TRAN_TRAP=${_DCG_TRAN_GHI_DE}s (bảng ${ns}s)"
            ns=$_DCG_TRAN_GHI_DE
        fi
        # Vòng 7d: trap KHÔNG được chạy quá hạn chót của PHIÊN (SSH sẽ cắt giữa lệnh) — tự dừng
        # trước, CHƯA XÁC ĐỊNH phần chưa làm. Cổng trước bước đã giữ chỗ ⇒ bình thường không chạm tới.
        local con_ph
        if [ -n "${_PH_HET:-}" ]; then
            con_ph=$(_ph_con_lai)
            if [ "$con_ph" -lt "$ns" ]; then
                ns_ct="$ns_ct — GIỚI HẠN bởi hạn chót PHIÊN (còn ${con_ph}s, bảng ${ns}s)"
                ns=$con_ph
                [ "$ns" -ge 1 ] || ns=1
            fi
        fi
        # Vòng 6b (F45): hạn chót THỰC THI — mọi bước sau đây lấy hạn = min(hạn riêng, phần còn lại).
        _DCG_TRAP_HET=$((bd_trap + ns))
        log "[trap] trần thời gian của trap (pha '$_DCG_PHA', đi tiếp=${_DCG_DI_TIEP:-0}): ${ns}s — $ns_ct"
        _dcg_ghi "tran_trap" "${ns}s pha=$_DCG_PHA bat_dau=$(date +%s) di_tiep=${_DCG_DI_TIEP:-0} phien_con=${con_ph:--}" || true
    fi
    case "$_DCG_PHA" in
        khong_ap_dung|buoc8|xong)
            : ;;
        chua_dong|dang_dong|da_dong)
            if [ "$_DCG_DI_TIEP" = "1" ]; then
                # Đường đi tiếp: ba service ĐÃ nằm dừng từ lượt đỏ và lược đồ có thể
                # đã migrate dở ⇒ KHÔNG BAO GIỜ mở lại mã cũ ở đây.
                _dcg_huong_dan "ĐI TIẾP dừng TRƯỚC migration (pha '$_DCG_PHA') — ứng dụng VẪN DỪNG như sau lượt đỏ; KHÔNG bật mã cũ (lược đồ có thể đã migrate dở)"
            elif [ "$_DCG_PHA" = "chua_dong" ]; then
                :
            else
            warn "[cửa ghi] deploy dừng ở pha '$_DCG_PHA' (rc=$rc, tín hiệu=${_DCG_TIN_HIEU:--}) — CSDL CHƯA bị migration chạm; thử mở lại ĐÚNG container cũ (qua cổng vân tay lược đồ)"
            ( _dcg_mo_lai_cu ) && kq=0 || kq=$?
            if [ "$kq" -eq 0 ]; then
                warn "[cửa ghi] ĐÃ mở lại container CŨ (đã đo — xem các dòng ✓ ngay trên). Deploy KHÔNG thành công."
            elif [ "$kq" -eq 5 ]; then
                # Vòng 6: lệnh hết hạn hoặc Docker không trả lời — KHÔNG kết luận phục hồi.
                _DCG_MO_CHUA_XD=1
                _dcg_ghi "mo_lai_cu" "CHUA_XAC_DINH"
                _dcg_huong_dan "mở lại container cũ CHƯA XÁC ĐỊNH — lệnh Docker hết hạn hoặc không đọc được; KHÔNG kết luận đã phục hồi, KHÔNG tự chạy lại"
            else
                _dcg_ghi "mo_lai_cu" "KHONG_DAT"
                _dcg_huong_dan "mở lại container cũ KHÔNG đạt / KHÔNG được phép"
            fi
            fi ;;
        dang_migrate)
            [ "$_DCG_ONEOFF_XONG" = "1" ] || _dcg_don_oneoff
            _dcg_huong_dan "bị ngắt khi migration ĐANG chạy — lược đồ CHƯA RÕ; KHÔNG tự mở ứng dụng, KHÔNG phát lại" ;;
        migrate_do)
            [ "$_DCG_ONEOFF_XONG" = "1" ] || _dcg_don_oneoff
            _dcg_huong_dan "migration ĐỎ — KHÔNG phát lại bản sao (F28); ứng dụng giữ DỪNG, CSDL giữ nguyên để đối soát" ;;
        *)
            _dcg_huong_dan "lược đồ đã MỚI hoặc chưa rõ — KHÔNG tự mở ứng dụng cũ" ;;
    esac
    [ "$_DCG_TT_HONG" = "1" ] && warn "[trạng thái] ⚠ tệp trạng thái $_DCG_TT đã có lần KHÔNG ghi được trong lượt này — log deploy là bản ghi pha đầy đủ."
    if [ "$ns" -gt 0 ]; then
        local da=$((SECONDS - bd_trap))
        _dcg_ghi "thoi_gian_trap" "${da}s/${ns}s" || true
        if [ "$da" -gt "$ns" ]; then
            warn "[trap] ⚠ trap chạy ${da}s — VƯỢT trần ${ns}s (phần vượt = ân hạn -k của lệnh cuối hoặc bước chưa tính)"
        else
            log "[trap] trap chạy ${da}s / trần ${ns}s"
        fi
    fi
    exit "$rc"
}

if [ "${IS_CUTOVER}" -eq 1 ]; then
    cutover "Step 4c: KHÔNG đóng cửa ghi (cutover không tự migrate)"
else
    log "Step 4c/8: Đóng cửa ghi (backend, celery-worker, celery-beat) trước pg_dump..."
    mkdir -p "$BACKUP_DIR"
    trap '_dcg_bat_tin_hieu HUP 129' HUP
    trap '_dcg_bat_tin_hieu INT 130' INT
    trap '_dcg_bat_tin_hieu TERM 143' TERM
    trap '_dcg_bat_tin_hieu PIPE 141' PIPE
    trap '_dcg_khi_thoat' EXIT
    _DCG_PHA="chua_dong"
    log "  [pha] chua_dong"
    _dcg_ghi pha chua_dong \
        || error "[trạng thái] tệp trạng thái KHÔNG ghi được — DỪNG trước khi dừng container nào (fail-closed)."
    # Vòng 7d: cổng ngân sách PHIÊN trước bước không đảo ngược được ĐẦU TIÊN (đóng cửa ghi).
    _ph_cong 4c "Step 4c (đóng cửa ghi)"

    if [ "$_DCG_DI_TIEP" = "1" ]; then
    # --- ĐI TIẾP (vòng 4, F40): cửa ghi ĐÃ đóng từ lượt đỏ — KHÔNG dừng gì ------
    # Ghi lại đúng ba CID exited + nginx đã đo ở Step 3a vào tệp trạng thái MỚI
    # (để chính lượt này, nếu lại đỏ sau migration, là nguồn hợp lệ cho lượt đi
    # tiếp kế), rồi ĐO LẠI mốc vòng đời ngay bây giờ: Step 3b → 4b có thể đã tốn
    # vài phút, đừng tin số đo ở Step 3a.
    _dcg_ghi "di_tiep_tu" "$_DT_TT_CU" || error "[trạng thái] KHÔNG ghi được tệp trạng thái — DỪNG."
    for _S in $_DCG_DICH_VU; do
        _DCG_CID[$_S]=${_DT_CID[$_S]}
        _DCG_ANH[$_S]=${_DT_ANH[$_S]}
        _dcg_ghi "cu" "$_S ${_DCG_CID[$_S]} ${_DCG_ANH[$_S]} restart=dung_tu_luot_truoc" \
            || error "[trạng thái] KHÔNG ghi được container cũ vào tệp trạng thái — DỪNG."
    done
    _DCG_NGINX_CID=$_DT_NGINX
    _dcg_ghi "nginx" "$_DCG_NGINX_CID" || error "[trạng thái] KHÔNG ghi được tệp trạng thái — DỪNG."
    for _S in $_DCG_DICH_VU; do
        _DCG_MOC[$_S]=$(_dcg_moc "${_DCG_CID[$_S]}") || error "[đi tiếp] không đọc được mốc vòng đời của '$_S'"
        [ "${_DCG_MOC[$_S]}" = "${_DT_MOC[$_S]}" ] || error "[đi tiếp] '$_S' ĐÃ CHẠY LẠI sau Step 3a (ghi=${_DT_MOC[$_S]} · đo=${_DCG_MOC[$_S]}) — DỪNG."
        _dcg_ghi "moc" "$_S ${_DCG_MOC[$_S]}" || error "[trạng thái] KHÔNG ghi được mốc vòng đời — DỪNG."
    done
    else
    # --- Ghi lại container CŨ: đúng MỘT container đang chạy mỗi service -------
    # Cùng hợp đồng với Step 3b (`ps -q` = container ĐANG chạy, ID đủ 64 hex).
    # Trước lệnh `stop` đầu tiên ⇒ mọi `error` ở đây để nguyên hiện trạng.
    for _S in $_DCG_DICH_VU; do
        _DS=$(timeout -k 2 "$_DCG_HAN_LENH" $_RA_COMPOSE ps -q "$_S") || error "[4c] không liệt kê được container của '$_S' (lỗi hoặc hết hạn) — chưa đụng gì, DỪNG."
        _SO=$(printf '%s\n' "$_DS" | grep -c '[^[:space:]]' || true)
        [ "$_SO" -eq 1 ] || error "[4c] '$_S' có $_SO container ĐANG CHẠY (cần đúng 1). Chưa đụng gì, DỪNG.
       PA1 phải biết CHÍNH XÁC container cũ để mở lại đúng ảnh cũ khi cần."
        _CID=${_DS//[[:space:]]/}
        case "$_CID" in *[!0-9a-f]*) error "[4c] CID của '$_S' có ký tự lạ: '$_CID'" ;; esac
        [ "${#_CID}" -eq 64 ] || error "[4c] CID của '$_S' dài ${#_CID} (cần 64 hex)"
        _ANH=$(_dcg_dk inspect -f '{{.Image}}' "$_CID") || error "[4c] không đọc được ảnh của '$_S' (lỗi hoặc hết hạn)"
        case "$_ANH" in sha256:*) : ;; *) error "[4c] ảnh của '$_S' không hợp lệ: '$_ANH'" ;; esac
        _CS=$(_dcg_dk inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$_CID") || error "[4c] không đọc được restart policy của '$_S' (lỗi hoặc hết hạn)"
        case "$_CS" in
            unless-stopped|no) : ;;
            *) error "[4c] '$_S' có restart policy '$_CS' — chỉ nhận 'unless-stopped' hoặc 'no'.
       Chính sách khác có thể làm dockerd TỰ BẬT LẠI container giữa cửa sổ dump → migrate." ;;
        esac
        _DCG_CID[$_S]=$_CID
        _DCG_ANH[$_S]=$_ANH
        _dcg_ghi "cu" "$_S $_CID $_ANH restart=$_CS" || error "[trạng thái] KHÔNG ghi được container cũ vào tệp trạng thái — DỪNG."
    done
    _DCG_IP[backend]=$(_dcg_ip "${_DCG_CID[backend]}") || error "[4c] không đọc được IP của backend"
    # Nhánh lùi cần ĐÚNG container nginx đang phục vụ để khởi động lại/đo qua SNI thật.
    _DS=$(timeout -k 2 "$_DCG_HAN_LENH" $_RA_COMPOSE ps -q nginx) || error "[4c] không liệt kê được container nginx (lỗi hoặc hết hạn) — chưa đụng gì, DỪNG."
    _SO=$(printf '%s\n' "$_DS" | grep -c '[^[:space:]]' || true)
    [ "$_SO" -eq 1 ] || error "[4c] 'nginx' có $_SO container ĐANG CHẠY (cần đúng 1). Chưa đụng gì, DỪNG.
       Nhánh lùi phải đo được đường của người dùng (nginx, SNI thật), không chỉ backend healthy."
    _DCG_NGINX_CID=${_DS//[[:space:]]/}
    _dcg_ghi "nginx" "$_DCG_NGINX_CID" || error "[trạng thái] KHÔNG ghi được tệp trạng thái — DỪNG."

    # --- Dừng ---------------------------------------------------------------
    _dcg_pha dang_dong
    for _S in $_DCG_DICH_VU; do
        log "  dừng '$_S' (docker stop -t $(_dcg_han_dung "$_S"))..."
        # Vòng 7c: hạn = -t + hạn đọc (phản hồi daemon) + -k 5. Hết hạn ⇒ trạng thái container CHƯA RÕ ⇒
        # `error` ⇒ trap pha dang_dong ĐO LẠI rồi mở lại; KHÔNG chạy lại `stop`.
        timeout -k 5 "$(( $(_dcg_han_dung "$_S") + _DCG_HAN_LENH ))" docker stop -t "$(_dcg_han_dung "$_S")" "${_DCG_CID[$_S]}" >/dev/null \
            || error "[4c] docker stop '$_S' THẤT BẠI hoặc HẾT HẠN (hạn $(( $(_dcg_han_dung "$_S") + _DCG_HAN_LENH ))s) — KHÔNG chạy lại; trap đo lại trạng thái"
    done
    for _S in $_DCG_DICH_VU; do
        _DCG_MOC[$_S]=$(_dcg_moc "${_DCG_CID[$_S]}") || error "[4c] không đọc được mốc vòng đời của '$_S'"
        _dcg_ghi "moc" "$_S ${_DCG_MOC[$_S]}" || error "[trạng thái] KHÔNG ghi được mốc vòng đời — DỪNG."
    done
    fi

    # --- Đo cửa đã đóng (container + CSDL), chụp vân tay + T0 ----------------
    _dcg_cua_dong "4c" || error "[4c] cửa ghi CHƯA đóng (phía container) — DỪNG trước pg_dump. CSDL chưa bị chạm."
    _dcg_phien_la_bang_0 "4c" || error "[4c] cửa ghi CHƯA đóng (còn phiên lạ trên CSDL) — DỪNG trước pg_dump. CSDL chưa bị chạm.
       Lưu ý: cron \`pg_dump\` 03:00 (backup-cron.sh) cũng là một phiên lạ — đừng deploy trong khung ~03:00."
    _DCG_VT_4C_ND=$(_dcg_van_tay) || error "[4c] không đo được vân tay lược đồ — DỪNG trước pg_dump. CSDL chưa bị chạm."
    printf '%s\n' "$_DCG_VT_4C_ND" > "$_DCG_VT_4C" \
        || error "[4c] không ghi được bản chụp vân tay $_DCG_VT_4C — DỪNG trước pg_dump."
    printf '%s;\n' "$_DCG_SQL_VAN_TAY" > "$_DCG_VT_SQL" \
        || error "[4c] không ghi được câu SQL vân tay $_DCG_VT_SQL — DỪNG trước pg_dump."
    log "  ✓ [4c] vân tay lược đồ: $(printf '%s\n' "$_DCG_VT_4C_ND" | wc -l) dòng → $_DCG_VT_4C"
    _dcg_chup_dem "$_DCG_DEM_T0" || error "[4c] không chụp được bộ đếm T0 (PA2) — DỪNG trước pg_dump. CSDL chưa bị chạm."
    _DCG_GIO_T0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    _dcg_ghi "T0" "$_DCG_GIO_T0" || error "[trạng thái] KHÔNG ghi được mốc T0 — DỪNG trước pg_dump."
    _dcg_pha da_dong
    log "  ✓ cửa ghi ĐÓNG — giữ đóng xuyên suốt dump → migrate → (nếu đỏ) ứng dụng giữ DỪNG"
fi

# =============================================================================
# Step 5: Database backup (before migration)
# =============================================================================
log "Step 5/8: Backing up database..."
# Vòng 7d: pg_dump KHÔNG bị giết giữa chừng (giết client `exec` không dừng pg_dump trong
# container) ⇒ CHẶN TRƯỚC khi bắt đầu theo hạn đo QLTS_HAN_PG_DUMP + phần sau.
_ph_cong 5 "Step 5 (pg_dump)"
mkdir -p "$BACKUP_DIR"

# Review 2026-07-20: ba sửa đổi, cùng một gốc — bản backup này là đường
# rollback DUY NHẤT của Step 6 nên nó phải hoặc dùng được, hoặc biến mất
# hẳn; tuyệt đối không được tồn tại ở dạng "có file nhưng vô dụng".
# (Vòng 3, 13-10-2026 — F28: nay là đường lùi TAY có đối soát; Step 6 KHÔNG
# còn tự phát lại. Nó vẫn bắt buộc phải có trước khi migration chạy.)
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
# Vòng 7d: migration KHÔNG bị giết giữa chừng (DDL/AUTOCOMMIT dở dang tệ hơn chờ) ⇒ CHẶN
# TRƯỚC theo hạn đo QLTS_HAN_MIGRATION + max(dự trữ trap migrate_do, phần sau).
_ph_cong 6 "Step 6 (migration)"

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
    # Routine deploy: auto-migrate. Đỏ ⇒ KHÔNG tự phát lại bản sao (vòng 3,
    # F28): ứng dụng giữ DỪNG, CSDL giữ nguyên, trap in hướng dẫn đối soát.
    #
    # ``--entrypoint`` là BẮT BUỘC (vá 13-08-2026): ảnh backend khai
    # ENTRYPOINT ["/app/docker-entrypoint.sh"], mà ``docker compose run`` chỉ
    # đè CMD chứ KHÔNG đè ENTRYPOINT. Thiếu nó thì one-off này chạy TRỌN
    # entrypoint — `alembic upgrade head` + `sync_notification_rules` — rồi
    # mới chạy tới lệnh mình gọi, tức migrate hai lượt cho một lần deploy.
    # ``--no-deps`` vì postgres/redis vừa được dựng ngay phía trên.
    #
    # Vá 12-10-2026 (đường A): mốc T1 chụp NGAY TRƯỚC migration — cửa ghi đã
    # đóng từ Step 4c và vẫn đóng ở đây. Không chụp được ⇒ dừng TRƯỚC khi chạm
    # lược đồ (pha `da_dong` ⇒ trap mở lại đúng container cũ).
    _dcg_chup_dem "$_DCG_DEM_T1" \
        || error "[PA2] không chụp được bộ đếm T1 — DỪNG trước migration. CSDL chưa bị ghi."
    # Số liệu toàn CSDL tại T1 — CHỈ ĐỂ ĐỌC (xem `_dcg_pa2`). Đếm phiên đo của chính
    # deploy ở NGOÀI `$( )` vì biến gán trong subshell bị mất.
    _DCG_SO_PSQL=$((_DCG_SO_PSQL + 1))
    _DCG_PSQL_T1=$_DCG_SO_PSQL
    _DCG_CSDL_T1=$(_dcg_chup_csdl) || { _DCG_CSDL_T1=""; warn "[PA2] không chụp được pg_stat_database T1 (chỉ để đọc)"; }
    _dcg_pha dang_migrate
    # Vòng 3: one-off mang tên RIÊNG của lượt (`--name`); `_dcg_theo_oneoff` (nền)
    # ghi nhận CID của nó ngay khi nó xuất hiện ⇒ bị ngắt trước khi `--rm` kịp
    # dọn thì trap dọn được ĐÚNG nó, và chỉ khi nó đã `exited`.
    _dcg_theo_oneoff </dev/null >/dev/null 2>&1 &
    _DCG_ONEOFF_THEO=$!
    if docker compose -f docker-compose.yml --profile production --env-file .env.production \
        run --rm --name "$_DCG_ONEOFF_TEN" --no-deps --entrypoint alembic backend upgrade head; then
        _dcg_dung_theo_oneoff
        _dcg_pha da_migrate
        log "Migrations completed successfully"
    else
        _RC_MIG=$?
        _dcg_dung_theo_oneoff
        _dcg_pha migrate_do
        warn "Migration failed (rc=$_RC_MIG)! KHÔNG tự phát lại bản sao — ứng dụng giữ DỪNG, CSDL giữ NGUYÊN hiện trạng."
        # =====================================================================
        # Vòng 3 (13-10-2026, owner chốt F28): BỎ TỰ PHÁT LẠI DUMP.
        # =====================================================================
        # Trước đây nhánh này `psql < $_BAN_SAO` (dump `--clean --if-exists`)
        # khi bước (d) + PA2 không thấy gì. Diễn tập vòng 2 chứng minh hàng rào
        # ấy KHÔNG bảo đảm: một phiên CSDL ngoài nối SAU T1, ghi 20 giao dịch rồi
        # ngắt TRƯỚC (d) lọt cả (d) lẫn PA2, và lượt phát lại XOÁ 20/20 giao
        # dịch đã commit. Không lớp đo nào ở đây chặn được ca ấy một cách đáng
        # tin (bộ đếm lẫn ghi của chính migration; phiên ngoài đã rời đi).
        #
        # Nay: migration đỏ ⇒ KHÔNG ghi gì thêm vào CSDL. Cửa ghi giữ ĐÓNG
        # (3 container cũ nằm dừng), CSDL giữ nguyên trạng thái hiện tại — mọi
        # ghi đã commit (kể cả từ nguồn ngoài) còn nguyên để đối soát. Bản sao
        # Step 5 VẪN được giữ, chỉ để phục hồi TAY có đối soát (hướng dẫn in ở
        # trap, pha `migrate_do`). Giới hạn đã đo của bản sao (diễn tập
        # 20-07-2026, đo lại 12-10-2026): dump chỉ DROP object nó BIẾT, nên
        # bảng/kiểu do migration hỏng tạo thêm SỐNG SÓT qua phát lại tay.
        #
        # (d) và PA2 không còn là CỔNG (không nhánh nào phụ thuộc kết quả của
        # chúng): chúng ĐO để IN cho người đối soát — cửa có còn đóng không,
        # bảng nào có ghi trong cửa sổ — tức bằng chứng cần có TRƯỚC khi ai đó
        # quyết định phát lại tay.
        _dcg_don_oneoff || true
        if [ -s "$_BAN_SAO" ]; then
            log "[đối soát] bản sao Step 5 còn nguyên: $_BAN_SAO ($(wc -c < "$_BAN_SAO") byte) — KHÔNG được phát lại tự động"
        else
            warn "[đối soát] bản sao Step 5 KHÔNG còn / RỖNG: $_BAN_SAO"
        fi
        _dcg_cua_dong "d" || warn "[đối soát] cửa ghi KHÔNG còn được chứng minh là đóng (xem dòng [d]) — container đã chạy lại giữa chừng?"
        _dcg_phien_la_bang_0 "d" || warn "[đối soát] còn phiên lạ trên CSDL ngay lúc này (xem dòng [d])."
        _dcg_pa2 || warn "[đối soát] PA2 THẤY dấu hiệu ghi trong cửa sổ dump (hoặc thiếu mốc) — phát lại bản sao sẽ XOÁ chúng."
        error "Migration failed. KHÔNG phát lại bản sao (F28): ứng dụng GIỮ DỪNG, CSDL giữ nguyên để đối soát — xem hướng dẫn phục hồi có đối soát ngay dưới."
    fi
fi

# =============================================================================
# Step 7: Pre-deploy checks (Casbin policies)
# =============================================================================
log "Step 7/8: Running pre-deploy checks..."
# Vòng 7d: từ đây KHÔNG còn nhánh lùi mở mã cũ ⇒ giữ chỗ cho CẢ đường tới hết lượt (7, 8, 8b, 8c).
_ph_cong 7 "Step 7–8 (kiểm trước + khởi động mã mới)"

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

# Từ dòng dưới, container CŨ bị thay bằng container ảnh MỚI ⇒ trap không còn
# gì để mở lại (pha `buoc8`). No-op ở cold cutover.
_dcg_pha buoc8
# Start backend + celery (env flags propagate via process env when cutover mode;
# routine mode = unset → entrypoint defaults to ``true`` = auto-run as before)
docker compose -f docker-compose.yml --profile production --env-file .env.production up -d \
    backend celery-worker celery-beat

# CỔNG HEALTH (`_HAN_HEALTH` + `_cho_healthy_dv`) nay được định nghĩa TRƯỚC
# Step 4c — nhánh lùi của Step 6 cần nó (vá 12-10-2026). Thân hàm không đổi.

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
# Vòng 7d: nginx-apply hoán container đang phục vụ — KHÔNG giết giữa chừng ⇒ chặn TRƯỚC.
_ph_cong 8b "Step 8b (nginx-apply)"
bash "$SCRIPT_DIR/nginx-apply.sh" "$DOMAIN"     || error "không áp được cấu hình nginx — xem log phía trên"

# Vòng 4 (F40): đường ĐI TIẾP kết thúc bằng phép đo DỊCH VỤ qua SNI thật trên
# container nginx ĐANG phục vụ sau Step 8b — ứng dụng đã nằm dừng từ lượt đỏ,
# "backend healthy" một mình không chứng minh người dùng tới được.
if [ "${_DCG_DI_TIEP:-0}" = "1" ]; then
    _DS=$(timeout -k 2 "$_DCG_HAN_LENH" $_RA_COMPOSE ps -q nginx) || error "[đi tiếp] không liệt kê được nginx sau Step 8b (lỗi hoặc hết hạn)."
    [ "$(printf '%s\n' "$_DS" | grep -c '[^[:space:]]' || true)" -eq 1 ] \
        || error "[đi tiếp] sau Step 8b 'nginx' không có ĐÚNG MỘT container đang chạy."
    _DCG_NGINX_CID=${_DS//[[:space:]]/}
    _dcg_do_dich_vu_nginx || error "[đi tiếp] hậu kiểm dịch vụ qua SNI thật KHÔNG ĐẠT sau Step 8b — xem dòng [nginx · dịch vụ] phía trên."
    log "  ✓ [đi tiếp] hậu kiểm dịch vụ qua SNI thật ĐẠT trên nginx $_DCG_NGINX_CID"
fi


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
    _RA_CID_MOI=$(timeout -k 2 "$_DCG_HAN_LENH" $_RA_COMPOSE ps -q "$_S" 2>/dev/null || true)
    if [ -z "$_RA_CID_MOI" ]; then
        rm -f -- "$_RA_MK_TMP"
        error "sau deploy vẫn không thấy container cho '$_S' — từ chối ghi marker nửa vời.
       Marker sai còn nguy hiểm hơn marker thiếu: lượt deploy sau sẽ ghim ảnh cũ
       theo một SHA không đúng."
    fi
    _RA_IMG_MOI=$(_dcg_dk inspect -f '{{.Image}}' "$_RA_CID_MOI" 2>/dev/null || true)
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

_dcg_pha xong

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
