#!/usr/bin/env bash
# Wrapper BẮT BUỘC cho smoke-backend.py.
#
# Tồn tại vì các cờ an toàn quá dễ sót, và sót cái nào cũng im lặng:
#   --network none      thiếu ⇒ còn interface ngoài loopback, tức vẫn có đường
#                       ra mạng (qua compose thì chạm thẳng postgres/redis; qua
#                       `docker run` trần thì bridge mặc định, tên dịch vụ không
#                       phân giải nhưng egress vẫn mở). `smoke-backend.py` phát
#                       hiện bằng cách ĐẾM INTERFACE — hỏi DNS thì KHÔNG thấy.
#   --entrypoint python thiếu ⇒ `docker-entrypoint.sh` chạy `alembic upgrade
#                       head` (DDL) + `sync_notification_rules` (ghi) lên CSDL dev
#   DSN sentinel        thiếu ⇒ trỏ CSDL thật
#
# `smoke-backend.py` vẫn tự kiểm lại cả ba (fail-closed, exit 3) nên wrapper là
# lớp tiện lợi, KHÔNG phải lớp bảo đảm duy nhất.
#
# Env đều là giá trị giả: không mang theo secret thật nào vào tiến trình đo.
#
# Cách chạy, từ gốc kho:
#   bash tests-e2e/admission-freeze/run-smoke-backend.sh          # cả hai trạng thái
#   bash tests-e2e/admission-freeze/run-smoke-backend.sh true     # chỉ BẬT
set -euo pipefail

cd "$(dirname "$0")/../.."

ANH="${QLTS_BACKEND_IMAGE:-qlts-backend}"
[[ -f "$PWD/tests-e2e/admission-freeze/smoke-backend.py" ]] || {
    echo "KHONG THAY smoke-backend.py canh script nay"; exit 3; }

# Git Bash tren Windows tu doi doi so hinh duong dan: `-w /app` bien thanh
# `C:/Program Files/Git/app` va docker tu choi. Tat chuyen doi, va dua duong
# dan HOST ve dang Windows de docker hieu. Tren Linux khong co cygpath nen
# nhanh nay bi bo qua.
GOC_HOST="$PWD"
if command -v cygpath >/dev/null 2>&1; then
    GOC_HOST="$(cygpath -m "$PWD")"
    export MSYS_NO_PATHCONV=1
fi
SCRIPT="$GOC_HOST/tests-e2e/admission-freeze/smoke-backend.py"

if ! docker image inspect "$ANH" >/dev/null 2>&1; then
    echo "KHONG THAY ANH '$ANH'. Dung: docker compose build backend"
    echo "hoac dat QLTS_BACKEND_IMAGE=<ten-anh>."
    exit 3
fi

# Phải trùng NGUYÊN VĂN SENTINEL_DB / SENTINEL_REDIS trong smoke-backend.py.
SENTINEL_DB="postgresql+asyncpg://smoke:smoke@127.0.0.1:1/smoke"
SENTINEL_REDIS="redis://127.0.0.1:1/0"

TRANG_THAI=("${1:-true}")
[[ $# -eq 0 ]] && TRANG_THAI=(true false)

RC=0
for v in "${TRANG_THAI[@]}"; do
    [[ "$v" == "true" || "$v" == "false" ]] || { echo "Trang thai phai la true|false, nhan '$v'"; exit 3; }
    echo "############ ADMISSION_FROZEN=$v ############"
    docker run --rm -i \
        --network none \
        --entrypoint python \
        -e ADMISSION_FROZEN="$v" \
        -e DATABASE_URL="$SENTINEL_DB" \
        -e REDIS_URL="$SENTINEL_REDIS" \
        -e SECRET_KEY=smoke \
        -e JWT_SECRET_KEY=smoke \
        -e MAIL_FROM=smoke@example.invalid \
        -e MAIL_USERNAME=smoke \
        -e MAIL_PASSWORD=smoke \
        -e MAIL_SERVER=127.0.0.1 \
        -e PYTHONPATH=/app \
        -v "$GOC_HOST/Backend_FastAPI:/app" \
        -v "$SCRIPT:/tmp/smoke-backend.py:ro" \
        -w /app \
        "$ANH" /tmp/smoke-backend.py || RC=$?
    echo
done
exit "$RC"
