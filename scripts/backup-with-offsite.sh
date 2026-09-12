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

# shellcheck source=lib/healthchecks.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/healthchecks.sh"

cd /opt/qlts

# Tệp bí mật chỉ-host, dùng CHUNG với scripts/celery-heartbeat-monitor.sh —
# nhưng BIẾN thì riêng, xem khối ping ở cuối tệp.
TEP_BI_MAT="${QLTS_HEALTHCHECKS_FILE:-/etc/qlts/healthchecks.env}"
TEN_BIEN_PING="HEALTHCHECK_PING_URL"

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
#
# PHẠM VI (sự cố 11-09-2026): lệnh này từng là `rclone delete gdrive-crypt:
# --min-age 14d` — KHÔNG có bộ lọc nào, nên nó quét TOÀN BỘ remote và xoá mọi
# object quá 14 ngày, kể cả bản kê rollback nằm trong `qlts-rollback/`. Đo
# được: hai bản kê thế hệ 27-08 bị chính dòng này xoá lúc 03:00 ngày 11-09.
# Bản kê là thứ DUY NHẤT ánh xạ tag rollback → digest ảnh trên GHCR; mất nó
# là mất đường lùi, trong khi ảnh vẫn còn nguyên trên registry.
#
# Hai hàng rào ĐỘC LẬP, dư thừa có chủ ý:
#   --include '/qlts_*.sql.gz'   dấu `/` đầu mẫu neo vào GỐC remote. Thiếu nó,
#                                mẫu khớp ở MỌI độ sâu — đã đo: xoá nhầm
#                                `qlts-rollback/qlts_old.sql.gz`.
#   --max-depth 1                chặn mọi thứ ngoài tầng gốc, nên kể cả khi ai
#                                đó lỡ bỏ dấu `/` thì thư mục con vẫn an toàn.
# KHÔNG dùng `--rmdirs`: đo trực tiếp thấy 1.60.1 và 1.74.4 hành xử KHÁC nhau,
# mà phiên bản rclone trên máy chủ thì không được ghim ở đâu cả.
RETENTION_RC=0
rclone delete gdrive-crypt: --min-age 14d --include '/qlts_*.sql.gz' --max-depth 1 || RETENTION_RC=$?
if [ "$RETENTION_RC" -ne 0 ]; then
    log "WARN: dọn bản >14 ngày THẤT BẠI (mã $RETENTION_RC)."
    log "WARN: bản upload hôm nay VẪN AN TOÀN, nhưng nếu lỗi lặp lại thì Drive"
    log "WARN: sẽ đầy dần rồi chặn luôn đường upload. Cần xử sớm."
fi

# ── Hậu kiểm: mã thoát 0 KHÔNG chứng minh đã xoá đúng ───────────────────────
# `rclone delete` trả 0 và im lặng khi bộ lọc không khớp gì (đo trên cả 1.60.1
# lẫn 1.74.4). Vậy một lỗi đánh máy trong mẫu — `.sql` thay vì `.sql.gz` — sẽ
# làm retention chết lặng còn Drive thì đầy dần: đúng kiểu hỏng mà cả tệp này
# được viết ra để chống.
#
# Nên hậu kiểm bằng CƠ CHẾ KHÁC: liệt kê tầng gốc rồi tự khớp bằng `grep -E`,
# KHÔNG dùng lại bộ lọc của rclone. Mẫu rclone sai thì phép này vẫn thấy phần
# còn sót; dùng lại chính mẫu ấy thì cả hai cùng trả rỗng và nó báo SẠCH cho
# một retention đã chết.
#
# Mẫu neo hai đầu và loại ký tự `/`, nên một tên có đường dẫn (tức nằm trong
# thư mục con) không bao giờ bị tính là bản dump ở tầng gốc — kể cả khi ai đó
# gỡ mất `--max-depth 1` của lệnh liệt kê.
#
# Cố ý KHÔNG dùng `while read` + here-string: `<<<` là bashism, mà kho không
# chứa crontab của máy chủ nên không có gì chứng minh cron gọi bằng `bash`. Nếu
# nó gọi bằng `sh`, script sẽ chết ngay ở thì phân tích cú pháp và `backup-cron.sh`
# ở dòng 19 KHÔNG BAO GIỜ CHẠY — mất luôn cả backup cục bộ, không chỉ offsite.
# Đừng đổi sang heredoc thường: dấu kết thúc trùng tên tệp trên remote sẽ cắt
# ngắn danh sách và làm phép kiểm fail-open.
RESIDUE_RC=0
CON_SOT=$(rclone lsf --files-only --max-depth 1 --min-age 14d gdrive-crypt:) || RESIDUE_RC=$?
if [ "$RESIDUE_RC" -ne 0 ]; then
    log "WARN: không liệt kê được tầng gốc để hậu kiểm dọn dẹp (mã $RESIDUE_RC)."
    [ "$RETENTION_RC" -ne 0 ] || RETENTION_RC="$RESIDUE_RC"
else
    CON_LAI=$(printf '%s\n' "$CON_SOT" | grep -E '^qlts_[^/]*\.sql\.gz$' | tr '\n' ' ' || true)
    if [ -n "$CON_LAI" ]; then
        log "WARN: hậu kiểm thấy bản dump >14 ngày VẪN CÒN ở gốc remote: $CON_LAI"
        log "WARN: nghi bộ lọc retention sai — kiểm '--include' của lệnh rclone delete."
        [ "$RETENTION_RC" -ne 0 ] || RETENTION_RC=1
    fi
fi

# ── Công tắc người chết (tuỳ chọn, mặc định TẮT) ────────────────────────────
# Ba sửa đổi trên khiến script THẤT BẠI TO TIẾNG — nhưng tiếng đó rơi vào
# /var/log/qlts-backup.log, nơi không ai ngồi canh. Đặt HEALTHCHECK_PING_URL
# trong tệp bí mật chỉ-host để biến IM LẶNG thành CẢNH BÁO: dịch vụ sẽ chủ động
# báo khi quá hạn mà không nhận được ping.
# Ping ở đây nghĩa là "bản hôm nay đã nằm ngoài máy chủ", nên vẫn ping kể cả
# khi dọn dẹp lỗi — dữ liệu an toàn và dọn dẹp sạch là hai chuyện khác nhau.
#
# HAI THAY ĐỔI so với bản trước, cả hai đều về nơi bí mật được phép tồn tại:
#   * Đọc từ tệp chỉ-host `600 root` chứ KHÔNG từ environment. Biến môi trường
#     đi theo mọi tiến trình con và lộ qua `/proc/<pid>/environ`; nếu ai đó đặt
#     nó vào `.env.production` cho tiện thì nó còn bị nướng vào container và lộ
#     qua `docker inspect .Config.Env`.
#   * URL vào curl qua STDIN (`--config -`), KHÔNG qua argv. Bản trước truyền
#     thẳng `"$HEALTHCHECK_PING_URL"` làm tham số ⇒ bất kỳ ai trên máy cũng đọc
#     được bằng `ps` trong lúc backup chạy. URL ping chính là mật khẩu: có nó
#     thì ping thay được, tức TẮT được cảnh báo.
#
# Biến RIÊNG, không dùng chung với `CELERY_HEARTBEAT_PING_URL` — xem
# ops/healthchecks.env.example, mục "HAI CHECK ĐỘC LẬP".
#
# VẪN LÀ TUỲ CHỌN, CÓ CHỦ Ý: bắt buộc hoá ở đây sẽ làm lượt backup đêm nay
# THOÁT KHÁC 0 chỉ vì bí mật chưa được cấu hình, tức biến một bản sao lưu thành
# công thành một báo động. Đó là quyết định vận hành riêng, không phải phần của
# bản vá này. `celery-heartbeat-monitor.sh` thì NGƯỢC LẠI — thiếu URL là fatal,
# vì ở đó ping LÀ toàn bộ sản phẩm của script.
#
# Quyền tệp bí mật: ở đây chỉ CẢNH BÁO rồi đi tiếp, khác với
# `celery-heartbeat-monitor.sh` vốn dừng hẳn. Lý do: với monitor thì ping LÀ
# toàn bộ sản phẩm, còn ở đây sản phẩm là bản sao lưu đã nằm ngoài máy chủ — từ
# chối ping không làm dữ liệu an toàn hơn, chỉ làm mất nốt tín hiệu cuối cùng.
CANH_BAO_QUYEN=$(hc_kiem_quyen "$TEP_BI_MAT") || log "WARN: tệp bí mật không an toàn — ${CANH_BAO_QUYEN}"
PING_URL_BACKUP=$(hc_doc_url "$TEN_BIEN_PING" "$TEP_BI_MAT") || PING_URL_BACKUP=""
if [ -n "$PING_URL_BACKUP" ]; then
    if hc_ping "$PING_URL_BACKUP"; then
        log "đã ping healthcheck"
    else
        log "WARN: ping healthcheck thất bại (backup vẫn OK)"
    fi
else
    log "WARN: chưa cấu hình ${TEN_BIEN_PING} trong ${TEP_BI_MAT} — backup KHÔNG có công tắc người chết"
fi

# Thoát khác 0 nếu có bước nào không trọn vẹn — để cron/giám sát nhìn thấy.
[ "$RETENTION_RC" -eq 0 ] || exit 1
log "HOÀN TẤT"
