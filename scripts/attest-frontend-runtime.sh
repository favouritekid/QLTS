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
#   bash scripts/attest-frontend-runtime.sh          # toàn bộ đầu vào
#   bash scripts/attest-frontend-runtime.sh finance  # chỉ nhánh chứa "finance"
#   FE_CONTAINER=qltssmoke-frontend-1 bash scripts/attest-frontend-runtime.sh
#
# HAI hình dạng container, tự nhận dạng — xem `attest_standalone` bên dưới:
#
#   * dev (`npm run dev`)  : có `/app/src` ⇒ so nội dung TỪNG TỆP nguồn;
#   * standalone (prod)    : không có `src/` ⇒ so MANIFEST ĐẦU VÀO BUILD mà
#     stage builder nướng vào ảnh tại `/app/.qlts-source-manifest.json`.
#
# Nhánh thứ hai ra đời 16-08-2026: stack smoke bắt buộc dùng bản standalone
# (`NEXT_PUBLIC_API_URL` là build arg, bị nướng vào ảnh), và ở đó script bản đầu
# chỉ biết trả "không đo được" — đúng nhưng vô dụng, vì nó chặn luôn cả lượt smoke
# mà nó sinh ra để bảo vệ.
#
# Thoát 0 khi khớp, 1 khi lệch (in ra tối đa 20 tệp lệch đầu tiên), 2 khi không
# đo được — không đo được KHÔNG được coi là khớp.
set -uo pipefail

CONTAINER="${FE_CONTAINER:-qlts-frontend-1}"
LOC="${1:-}"

cd "$(dirname "$0")/.." || exit 2
GOC_KHO="$PWD"
[ -d frontend/src ] || { echo "[CHẶN] không thấy frontend/src — chạy từ gốc repo"; exit 2; }

if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
  echo "[CHẶN] container '$CONTAINER' không chạy — không có runtime nào để attest"
  exit 2
fi

loc_filter() { if [ -n "$LOC" ]; then grep -- "$LOC"; else cat; fi }

# ---------------------------------------------------------------------------
# Hai HÌNH DẠNG container, hai phép chứng minh khác nhau
# ---------------------------------------------------------------------------
# * dev (`npm run dev`)  — có `/app/src`, so nội dung TỪNG TỆP nguồn;
# * standalone (prod)    — KHÔNG có `src/` (chỉ `node_modules`, `package.json`,
#   `public`, `server.js`), nên không còn gì để so trực tiếp. Ở đó ta so
#   MANIFEST ĐẦU VÀO BUILD do stage builder nướng vào ảnh.
#
# Stack smoke bắt buộc dùng bản standalone (`NEXT_PUBLIC_API_URL` là build arg),
# nên nhánh thứ hai không phải trường hợp hiếm — nó là đường chính của smoke.
MANIFEST_TRONG_ANH=/app/.qlts-source-manifest.json

co_src_trong_container() {
  docker exec "$CONTAINER" sh -c 'test -d /app/src' 2>/dev/null
}
co_manifest_trong_container() {
  docker exec "$CONTAINER" sh -c "test -s $MANIFEST_TRONG_ANH" 2>/dev/null
}

# ---------------------------------------------------------------------------
# Parse + validate manifest: MỘT đường duy nhất, qua JSON parser thật
# ---------------------------------------------------------------------------
# Bản trước trích mảng `tep` bằng một biểu thức `sed` vừa PARSE vừa LỌC ĐỊNH
# DẠNG. Phần tử sai định dạng vì thế bị loại TRƯỚC KHI validator nhìn thấy, nên
# nhánh "mục sai định dạng" không có gì để bắt. Đã tái hiện trên chính manifest
# đang chạy: đổi `tep[0]` thành `"x"`, hạ `so_tep` xuống 1276, tính lại
# `van_tay` trên 1276 dòng còn được sed nhận ⇒ validator cũ PASS.
#
# Nay dùng `scripts/kiem-manifest.mjs`: nó chỉ in danh sách chuẩn hoá SAU KHI
# toàn bộ JSON đã hợp lệ, và cùng một validator ấy chạy cho cả manifest trong
# ảnh lẫn manifest dựng từ host.
kiem_manifest() {  # $1 = tệp JSON · $2 = nhãn; in danh sách chuẩn hoá ra stdout
  node "$GOC_KHO/scripts/kiem-manifest.mjs" "$1" "$2"
}

attest_standalone() {
  TMP_OUT="$(mktemp -d)" || exit 2
  trap 'rm -rf "$TMP_OUT"' EXIT INT TERM

  # Manifest TRONG ẢNH: lấy ra tệp rồi validate trước khi tin một dòng nào.
  docker exec "$CONTAINER" sh -c "cat $MANIFEST_TRONG_ANH" >"$TMP_OUT/anh.json" 2>/dev/null
  C_LIST="$(kiem_manifest "$TMP_OUT/anh.json" "trong ảnh '$CONTAINER'")" || exit 2

  # Manifest của cây HIỆN TẠI được dựng bằng chính Docker, target `manifest` —
  # KHÔNG tự duyệt tệp trên host. Nhờ vậy tập tệp hai bên do cùng một
  # `.dockerignore` quyết định, không có danh sách tay nào để lệch.
  #
  # `NEXT_PUBLIC_*` phải truyền vào: chúng nằm trong manifest. Lấy từ môi trường
  # của người gọi — nạp env file trước khi chạy:
  #     set -a && . .env.smoke && set +a
  set -- --target manifest --output "type=local,dest=$TMP_OUT"
  for k in NEXT_PUBLIC_API_URL NEXT_PUBLIC_SOCKET_URL NEXT_PUBLIC_FF_PERMISSION_HOOK \
           NEXT_PUBLIC_FF_ERROR_HANDLER NEXT_PUBLIC_FF_STATUS_CONFIG \
           NEXT_PUBLIC_FF_STRICT_PERMISSIONS NEXT_PUBLIC_SENTRY_DSN; do
    eval "v=\${$k-}"
    if [ -n "${v:-}" ] || eval "[ \"\${${k}+co}\" = co ]"; then
      set -- "$@" --build-arg "$k=$v"
    fi
  done

  if ! docker build "$@" frontend >/dev/null 2>"$TMP_OUT/loi.txt"; then
    echo "[CHẶN] không dựng được manifest của cây hiện tại (target 'manifest'):"
    tail -5 "$TMP_OUT/loi.txt" | sed 's/^/       /'
    exit 2
  fi

  MF_HOST="$TMP_OUT/qlts-source-manifest.json"
  [ -s "$MF_HOST" ] || { echo "[CHẶN] target 'manifest' không sinh ra tệp nào"; exit 2; }

  # Manifest cây hiện tại cũng phải qua ĐÚNG validator ấy. Chỉ kiểm một phía là
  # để ngỏ ca "cả hai cùng hỏng theo cùng một kiểu" — hai rác khớp nhau.
  H_LIST="$(kiem_manifest "$MF_HOST" "cây hiện tại")" || exit 2

  # So ĐỦ 64 ký tự SHA-256. Rút gọn chỉ để HIỂN THỊ: so 16 ký tự là so 64 bit,
  # một cổng chống-va-chạm yếu hơn hẳn thứ nó tự nhận là đang canh.
  sh_=$(printf '%s\n' "$H_LIST" | sha256sum | cut -d' ' -f1)
  sc_=$(printf '%s\n' "$C_LIST" | sha256sum | cut -d' ' -f1)
  nh_=$(printf '%s\n' "$H_LIST" | grep -c .)
  nc_=$(printf '%s\n' "$C_LIST" | grep -c .)
  nhan=$(docker inspect -f '{{index .Config.Labels "org.qlts.git-sha"}}' "$CONTAINER" 2>/dev/null)

  printf '  hình dạng : standalone (manifest đầu vào build, gồm NEXT_PUBLIC_*)\n'
  printf '  cây hiện tại : %s mục · %s\n' "$nh_" "$sh_"
  printf '  trong ảnh    : %s mục · %s  (%s)\n' "$nc_" "$sc_" "$CONTAINER"
  [ -n "$nhan" ] && printf '  nhãn git     : %s  (truy vết, KHÔNG phải bằng chứng)\n' "$nhan"

  if [ "$sh_" = "$sc_" ]; then
    echo "  ✓ ảnh standalone dựng từ ĐÚNG cây làm việc và ĐÚNG build arg"
    exit 0
  fi

  echo
  echo "[LỆCH] ảnh KHÔNG dựng từ đầu vào hiện tại — mọi quan sát trên trình duyệt là VÔ HIỆU."
  echo "Mục khác nhau (tối đa 20; '<' = cây hiện tại, '>' = trong ảnh):"
  diff <(printf '%s\n' "$H_LIST") <(printf '%s\n' "$C_LIST") |
    grep -E '^[<>]' | awk '{print "  " $1 " " $3}' | sort -u -k2 | head -20
  echo
  echo "  __NEXT_PUBLIC_ARGS__ lệch nghĩa là ảnh được nướng build arg KHÁC —"
  echo "  cùng source vẫn là hai ảnh khác hành vi."
  echo
  echo "Chữa: docker compose … build frontend && docker compose … up -d --no-deps frontend"
  exit 1
}

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

# Chọn nhánh theo HÌNH DẠNG THẬT của container, không theo tên hay theo suy đoán.
if ! co_src_trong_container; then
  if co_manifest_trong_container; then
    attest_standalone
  fi
  echo "[CHẶN] container '$CONTAINER' không có /app/src LẪN $MANIFEST_TRONG_ANH"
  echo "       — không có gì để attest. Không đo được KHÔNG phải là khớp."
  exit 2
fi

H=$(bam_host); C=$(bam_container)
[ -n "$C" ] || { echo "[CHẶN] không đọc được source trong container '$CONTAINER'"; exit 2; }

# So ĐỦ 64 ký tự. Bản trước so `cut -c1-16` — tức 64 bit, một cổng chống va chạm
# yếu hơn hẳn thứ nó tự nhận là đang canh. Rút gọn CHỈ để hiển thị.
sh=$(printf '%s\n' "$H" | sha256sum | cut -d' ' -f1)
sc=$(printf '%s\n' "$C" | sha256sum | cut -d' ' -f1)
nh=$(printf '%s\n' "$H" | grep -c . ); nc=$(printf '%s\n' "$C" | grep -c . )

printf '  hình dạng : dev (so nội dung từng tệp nguồn)\n'
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
