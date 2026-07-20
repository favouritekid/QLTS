#!/usr/bin/env bash
# Backup local (backup-cron.sh) + đẩy bản mã hoá lên Google Drive.
#
# NGUYÊN TẮC (review 2026-07-20): đây là đường cứu dữ liệu CUỐI CÙNG khi mất
# máy chủ. Nó phải HOẶC chạy đúng, HOẶC kêu to. Tuyệt đối không được thoát 0
# sau khi đã bỏ qua việc đẩy dữ liệu đi — cron hiểu "thoát 0" là thành công,
# và lớp offsite có thể chết hàng tháng mà không ai biết.
#
# Bản trước vi phạm đúng điều đó: `rclone` nằm trong phần điều kiện của `if`
# nên `set -e` bị vô hiệu; thiếu binary / mất config / sai HOME đều rơi vào
# nhánh `else`, in một dòng WARN rồi THOÁT 0.
set -euo pipefail

cd /opt/qlts

log() { echo "[$(date)] [OFFSITE] $*"; }
die() { log "FATAL: $*"; exit 1; }

bash scripts/backup-cron.sh

# `|| true` là cần thiết: `head -1` đóng pipe sớm nên `ls` có thể nhận SIGPIPE
# (mã 141) và `pipefail` sẽ giết script. Hiện chưa chạm ngưỡng (~1600 file)
# nhưng đây là mìn hẹn giờ khi số file backup tăng.
LATEST=$(ls -t backups/qlts_*.sql.gz 2>/dev/null | head -1 || true)
[ -n "$LATEST" ] || die "không tìm thấy file backup nào trong backups/"

# ── Cổng toàn vẹn: không đẩy rác lên rồi báo OK ─────────────────────────────
# rclone chỉ xác nhận "đã truyền đủ byte", KHÔNG xác nhận file là backup hợp
# lệ; trên remote crypt thì hash cũng không dùng được nên nó tụt xuống chỉ so
# kích thước. Vậy phải tự kiểm trước khi upload.
gunzip -t "$LATEST" 2>/dev/null \
  || die "$LATEST hỏng (gunzip -t thất bại) — KHÔNG upload"

SIZE=$(stat -c%s "$LATEST")
PREV=$(ls -t backups/qlts_*.sql.gz 2>/dev/null | sed -n 2p || true)
if [ -n "$PREV" ]; then
    PREV_SIZE=$(stat -c%s "$PREV")
    # Bắt kịch bản "pg_dump trúng DB rỗng/sai tên nhưng vẫn exit 0" — file sẽ
    # nhỏ bất thường. So với bản hôm trước thay vì đặt ngưỡng cứng, để khỏi
    # phải chỉnh tay khi dữ liệu lớn dần theo mùa tuyển sinh.
    if [ "$SIZE" -lt $(( PREV_SIZE / 2 )) ]; then
        die "$LATEST chỉ $SIZE byte, chưa tới 50% bản trước ($PREV_SIZE byte) — nghi dump hỏng, KHÔNG upload"
    fi
fi

# ── Thiếu công cụ/remote là LỖI, không phải "bỏ qua" ────────────────────────
command -v rclone >/dev/null 2>&1 \
  || die "không tìm thấy rclone — offsite KHÔNG chạy (kiểm PATH của cron)"
rclone listremotes | grep -q '^gdrive-crypt:' \
  || die "remote gdrive-crypt không tồn tại — offsite KHÔNG chạy (kiểm rclone.conf của user chạy cron)"

log "upload $(basename "$LATEST") ($SIZE byte) → gdrive-crypt:"
rclone copy "$LATEST" gdrive-crypt:
log "upload OK — bản hôm nay ĐÃ an toàn ngoài máy chủ"

# ── Dọn bản cũ: hỏng thì KÊU, không nuốt ────────────────────────────────────
# Trước đây là `2>/dev/null || true` — hết quota / token hết hạn / remote đổi
# tên đều biến mất không dấu vết, trong khi dòng "Offsite OK" vẫn in ra.
RETENTION_RC=0
rclone delete gdrive-crypt: --min-age 14d || RETENTION_RC=$?
if [ "$RETENTION_RC" -ne 0 ]; then
    log "WARN: dọn bản >14 ngày THẤT BẠI (mã $RETENTION_RC)."
    log "WARN: bản upload hôm nay VẪN AN TOÀN, nhưng nếu lỗi lặp lại thì Drive"
    log "WARN: sẽ đầy dần rồi chặn luôn đường upload. Cần xử sớm."
fi

# ── Công tắc người chết (tuỳ chọn, mặc định TẮT) ────────────────────────────
# Ba sửa đổi trên khiến script THẤT BẠI TO TIẾNG — nhưng tiếng đó rơi vào
# /var/log/qlts-backup.log, nơi không ai ngồi canh. Đặt HEALTHCHECK_PING_URL
# (healthchecks.io hoặc tương đương) để biến IM LẶNG thành CẢNH BÁO: dịch vụ
# sẽ chủ động báo khi quá hạn mà không nhận được ping.
# Ping ở đây nghĩa là "bản hôm nay đã nằm ngoài máy chủ", nên vẫn ping kể cả
# khi dọn dẹp lỗi — dữ liệu an toàn và dọn dẹp sạch là hai chuyện khác nhau.
if [ -n "${HEALTHCHECK_PING_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 "$HEALTHCHECK_PING_URL" >/dev/null \
      && log "đã ping healthcheck" \
      || log "WARN: ping healthcheck thất bại (backup vẫn OK)"
fi

# Thoát khác 0 nếu có bước nào không trọn vẹn — để cron/giám sát nhìn thấy.
[ "$RETENTION_RC" -eq 0 ] || exit 1
log "HOÀN TẤT"
