#!/usr/bin/env bash
# Cổng chứng minh CONTAINER ĐANG PHỤC VỤ CHROME chạy đúng source của cây làm việc.
#
# Vì sao cần, dù `fe-check.sh` đã có attestation: hai thứ đó chứng minh hai
# điều khác nhau. `fe-check` dựng container dùng-một-lần và tự mount source vào
# đó, nên nó nói được "bộ test vừa chạy trên source này". Nó KHÔNG nói gì về
# `qlts-frontend-1` — container mà trình duyệt thật đang gọi. Frontend không có
# bind mount source; nó nhận source lúc `docker build`, và chỉ được đồng bộ
# tiếp nếu ai đó chạy `docker compose watch`. Không chạy watch thì container
# giữ nguyên source của lần build cuối, có thể cũ hàng tuần.
#
# Đã trả giá cho khoảng trống này: một lượt smoke kết luận "backend trả
# review_token nhưng giao diện không có đường xác nhận", rồi truy ngược qua
# handler, parser, reducer — tất cả đều đúng — trước khi phát hiện container
# đang chạy bản PaymentRecordDialog CHƯA HỀ có tính năng ấy. Mọi kết luận của
# lượt đó phải bỏ.
#
#   bash scripts/attest-frontend-runtime.sh          # toàn bộ src
#   bash scripts/attest-frontend-runtime.sh finance  # chỉ nhánh chứa "finance"
#
# Thoát 0 khi khớp, 1 khi lệch (in ra tối đa 20 tệp lệch đầu tiên), 2 khi không
# đo được — không đo được KHÔNG được coi là khớp.
set -uo pipefail

CONTAINER="${FE_CONTAINER:-qlts-frontend-1}"
LOC="${1:-}"

cd "$(dirname "$0")/.." || exit 2
[ -d frontend/src ] || { echo "[CHẶN] không thấy frontend/src — chạy từ gốc repo"; exit 2; }

if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
  echo "[CHẶN] container '$CONTAINER' không chạy — không có runtime nào để attest"
  exit 2
fi

loc_filter() { if [ -n "$LOC" ]; then grep -- "$LOC"; else cat; fi }

# Chuẩn hoá: bỏ CR để bản checkout CRLF trên Windows không tự tạo ra lệch giả.
bam_host() {
  ( cd frontend && find src -type f \( -name '*.ts' -o -name '*.tsx' \) | loc_filter | sort |
    while IFS= read -r f; do printf '%s %s\n' "$(tr -d '\r' < "$f" | sha256sum | cut -d' ' -f1)" "$f"; done )
}
bam_container() {
  docker exec "$CONTAINER" sh -c '
    cd /app 2>/dev/null || exit 3
    find src -type f \( -name "*.ts" -o -name "*.tsx" \) | sort |
    while IFS= read -r f; do printf "%s %s\n" "$(tr -d "\r" < "$f" | sha256sum | cut -d" " -f1)" "$f"; done
  ' 2>/dev/null | loc_filter
}

H=$(bam_host); C=$(bam_container)
[ -n "$C" ] || { echo "[CHẶN] không đọc được source trong container '$CONTAINER'"; exit 2; }

sh=$(printf '%s\n' "$H" | sha256sum | cut -c1-16)
sc=$(printf '%s\n' "$C" | sha256sum | cut -c1-16)
nh=$(printf '%s\n' "$H" | grep -c . ); nc=$(printf '%s\n' "$C" | grep -c . )

printf '  phạm vi   : %s\n' "${LOC:-toàn bộ src}"
printf '  host      : %s tệp · %s\n' "$nh" "$sh"
printf '  container : %s tệp · %s  (%s)\n' "$nc" "$sc" "$CONTAINER"

if [ "$sh" = "$sc" ]; then
  echo "  ✓ runtime KHỚP cây làm việc"
  exit 0
fi

echo
echo "[LỆCH] container KHÔNG chạy source hiện tại — mọi quan sát trên trình duyệt là VÔ HIỆU."
echo "Tệp khác nhau (tối đa 20):"
diff <(printf '%s\n' "$H") <(printf '%s\n' "$C") | grep -E '^[<>]' | awk '{print "  " $1 " " $3}' | sort -u -k2 | head -20
echo
echo "Chữa: docker compose build frontend && docker compose up -d --no-deps frontend"
echo "      (hoặc chạy 'docker compose watch' ở một terminal riêng để đồng bộ liên tục)"
exit 1
