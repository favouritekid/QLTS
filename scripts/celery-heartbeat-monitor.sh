#!/usr/bin/env bash
# Giám sát Celery TỪ NGOÀI Celery.
#
# VÌ SAO PHẢI LÀ SCRIPT CỦA HOST, KHÔNG PHẢI MỘT TASK NỮA
# --------------------------------------------------------
# `lead_unassigned_watchdog_task` do Beat lên lịch và Worker thực thi, nên nó
# CHẾT CÙNG thứ nó đỡ: Celery hỏng thì watchdog hỏng theo, và chỉ báo tồn đọng
# SAU KHI hồi phục. `check-notification-alerts` cũng nằm trong Celery — đúng
# vòng luẩn quẩn ấy. Không có gì bên trong Celery báo được cái chết của chính nó.
#
# Ba lớp, mỗi lớp bắt cái chết của lớp bên trong:
#   (A) `celery_heartbeat_task` — Beat gửi, Worker chạy, ghi epoch vào Redis.
#       Một giá trị, hai bằng chứng: beat chết thì không ai gửi, worker chết thì
#       không ai chạy.
#   (B) Script này — cron của HOST đọc giá trị đó. Sống sót khi cả Celery chết.
#   (C) Dịch vụ dead-man bên ngoài (healthchecks.io) — kêu khi chính HOST/VPS im,
#       tức khi (B) cũng không chạy được nữa.
#
# Cài đặt (không thuộc phạm vi script này — xem ops/healthchecks.env.example):
#   */5 * * * * bash /opt/qlts/scripts/celery-heartbeat-monitor.sh >> /var/log/qlts-celery-monitor.log 2>&1
#
# NGƯỠNG — ba con số phải khớp nhau, có test ghim chéo:
#   heartbeat 300s  ·  script này 900s (= 3 nhịp lỡ)  ·  TTL Redis 1200s
#   900 < 1200 nên nhánh "cũ" LUÔN tới được trước khi khoá tự hết hạn; đảo lại
#   thì nhánh ấy là mã chết, và một worker im lặng chỉ còn hiện ra dạng "mất khoá".
#
# BÍ MẬT: xem scripts/lib/healthchecks.sh — URL ping chính là mật khẩu. Tệp bí
# mật phải là tệp thường (không symlink), thuộc chính người chạy, và mode 600
# hoặc 400; sai một điều là script DỪNG và không ping gì cả.
#
# MÃ THOÁT — mỗi con số một nguyên nhân, đừng gộp:
#   0  heartbeat tươi, đã ping success
#   1  heartbeat KHÔNG tươi, đã ping /fail (cảnh báo đã gửi đi được)
#   2  không có URL dùng được (thiếu, rỗng, hoặc không hợp lệ) — chưa cấu hình
#   3  đã có phán định nhưng KHÔNG gửi được ping
#   4  tệp bí mật không an toàn — không đọc URL, không ping
#   70 biến hook chỉ-dành-cho-test lọt vào môi trường chạy thật
set -euo pipefail

# shellcheck source=lib/healthchecks.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/healthchecks.sh"

TEP_BI_MAT="${QLTS_HEALTHCHECKS_FILE:-/etc/qlts/healthchecks.env}"
# Biến RIÊNG của check này. Backup dùng `HEALTHCHECK_PING_URL` — HAI check độc
# lập, HAI URL khác nhau. Dùng chung một URL thì một backup thành công lúc 03:00
# sẽ ping success và XOÁ trạng thái "Celery đã chết từ 23:00"; và ngược lại,
# Celery khoẻ sẽ che việc backup không chạy. Hai sự cố che lấp nhau — đúng thứ
# mà giám sát sinh ra để tránh. KHÔNG có fallback sang biến của script kia: thà
# TẮT hẳn và kêu, còn hơn giám sát nhầm đối tượng mà vẫn xanh.
TEN_BIEN="CELERY_HEARTBEAT_PING_URL"

REDIS_CONTAINER="${QLTS_REDIS_CONTAINER:-qlts-redis-1}"
# DB 1 = REDIS_URL của app (redis://redis:6379/1) — đúng DB mà task ghi vào.
REDIS_DB=1
HEARTBEAT_KEY="celery:heartbeat"

# 3 nhịp lỡ. Nhỏ hơn thì một lượt redeploy cũng kêu; lớn hơn TTL thì nhánh "cũ"
# thành mã chết.
NGUONG_CU_GIAY=900
# Dưới mốc này không phải "cũ" mà là RÁC (ghi cụt, 0 chưa khởi tạo, một bộ đếm
# bị nhầm là đồng hồ). Phải khớp MIN_PLAUSIBLE_EPOCH bên task.
EPOCH_TOI_THIEU=1600000000
# Một epoch ở TƯƠNG LAI xa làm "tuổi" thành ÂM ⇒ tươi vĩnh viễn, fail-open.
LECH_TUONG_LAI_GIAY=300

_URL=""

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S%z')] [CELERY-MON] $*"; }

# ── Phán định: HÀM THUẦN, không chạm mạng, không chạm Redis ─────────────────
# Tách ra để test gọi thẳng MÃ THẬT thay vì chép lại logic — một test chép lại
# phép so sánh sẽ vẫn xanh khi script trôi đi, đúng kiểu hỏng mà nó sinh ra để chặn.
#   $1 = mã thoát của lệnh đọc   $2 = chuỗi thô đọc được   $3 = epoch bây giờ
# In ra đúng một trong: fresh | stale | missing | malformed | read_error
phan_dinh() {
    local rc="$1" tho="$2" now="$3" gt tuoi

    [ "$rc" -eq 0 ] || { printf 'read_error\n'; return 0; }

    gt=$(printf '%s' "$tho" | tr -d '\r\n' \
         | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    [ -n "$gt" ] || { printf 'missing\n'; return 0; }

    [[ "$gt" =~ ^[0-9]+$ ]]                            || { printf 'malformed\n'; return 0; }
    [ "$gt" -ge "$EPOCH_TOI_THIEU" ]                   || { printf 'malformed\n'; return 0; }
    [ "$gt" -le $(( now + LECH_TUONG_LAI_GIAY )) ]     || { printf 'malformed\n'; return 0; }

    tuoi=$(( now - gt ))
    if [ "$tuoi" -gt "$NGUONG_CU_GIAY" ]; then
        printf 'stale\n'
    else
        printf 'fresh\n'
    fi
}

main() {
    local now tho rc ket_qua ly_do

    # Kiểm quyền TRƯỚC khi đọc — không nạp bí mật từ một tệp không đáng tin.
    #
    # Fail-closed và KHÔNG ping gì cả, kể cả `/fail`: nếu tệp đọc được bởi người
    # khác thì URL coi như đã lộ, mà URL chính là quyền ping. Người đó ping
    # success thay được và cảnh báo bị vô hiệu. Dùng tiếp một bí mật đã lộ chỉ
    # tạo cảm giác an toàn. Im lặng ở đây là AN TOÀN: dead-man bên ngoài không
    # nhận được ping nào và sẽ kêu, còn mã thoát 4 hiện ra ở log cron.
    # Tệp KHÔNG tồn tại là "chưa cấu hình" (mã 2, do nhánh đọc URL báo), không
    # phải "không an toàn" (mã 4). Gộp hai ca lại thì người đọc log cron không
    # phân biệt được "chưa ai cài" với "ai đó đã chạm vào tệp bí mật".
    if [ -e "$TEP_BI_MAT" ] || [ -L "$TEP_BI_MAT" ]; then
        if ! ly_do=$(hc_kiem_quyen "$TEP_BI_MAT"); then
            log "FATAL: tep bi mat khong an toan — ${ly_do}"
            log "FATAL: KHONG doc URL va KHONG ping. Sua: chown root:root + chmod 600."
            return 4
        fi
    fi

    if ! _URL=$(hc_doc_url "$TEN_BIEN" "$TEP_BI_MAT"); then
        # Không có địa chỉ để báo ⇒ KHÔNG ping được gì, kể cả /fail. Mã thoát
        # khác 0 là tín hiệu DUY NHẤT còn lại ở phía host. Thoát 0 ở đây nghĩa
        # là giám sát tự tắt trong im lặng — đúng trạng thái production đang mắc
        # trước bản vá này, và đúng kiểu "lệnh trả 0 mà việc không xảy ra".
        log "FATAL: khong co URL dung duoc cho ${TEN_BIEN} trong ${TEP_BI_MAT}"
        log "FATAL: (thieu, rong, hoac khong hop le — vi du khong phai https)"
        log "FATAL: giam sat Celery DANG TAT. Xem ops/healthchecks.env.example."
        return 2
    fi

    now=$(date +%s)
    tho=$(docker exec "$REDIS_CONTAINER" redis-cli -n "$REDIS_DB" GET "$HEARTBEAT_KEY" \
          </dev/null 2>/dev/null) && rc=0 || rc=$?

    ket_qua=$(phan_dinh "$rc" "$tho" "$now")

    if [ "$ket_qua" = "fresh" ]; then
        if hc_ping "$_URL"; then
            log "OK: heartbeat tuoi, da ping success"
            return 0
        fi
        log "WARN: heartbeat tuoi nhung KHONG ping duoc (curl tra khac 0)"
        return 3
    fi

    # Mọi thứ không phải `fresh` đều đi /fail — KỂ CẢ khi không đọc được. Redis
    # chết hay docker chết thì Celery cũng không còn chạy được; coi "không biết"
    # là "vẫn ổn" chính là định nghĩa của fail-open.
    log "CANH BAO: heartbeat = ${ket_qua} (nguong ${NGUONG_CU_GIAY}s) — dang ping /fail"
    if hc_ping "${_URL}/fail"; then
        return 1
    fi
    log "WARN: KHONG ping duoc /fail — canh bao chi con trong cho dead-man ben ngoai"
    return 3
}

if [ -n "${QLTS_HEARTBEAT_MONITOR_SOURCE_ONLY:-}" ]; then
    # Chỉ dành cho test: nạp hàm rồi dừng, để test gọi `phan_dinh` bằng MÃ THẬT.
    #
    # `return` thành công khi tệp được SOURCE và thất bại khi tệp được CHẠY như
    # một chương trình — nên nếu biến này lỡ lọt vào môi trường của cron, script
    # thoát 70 chứ KHÔNG thoát 0. Thoát 0 ở đây sẽ là một công tắc tắt giám sát
    # trong im lặng: cron xanh mỗi 5 phút trong khi không có ai đo gì cả.
    return 0 2>/dev/null || exit 70
fi

main || exit $?
exit 0
