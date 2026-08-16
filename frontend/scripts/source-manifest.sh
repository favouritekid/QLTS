#!/bin/sh
# Manifest ĐẦU VÀO BUILD của frontend — băm TOÀN BỘ effective build context.
#
# Chạy TRONG Docker (stage `source` của `frontend/Dockerfile`), không chạy trên
# host. Đó là điểm mấu chốt của thiết kế: tập tệp được `.dockerignore` quyết
# định, nên cả lúc dựng ảnh lẫn lúc attest đều đi qua ĐÚNG một bộ lọc. Không có
# danh sách tệp viết tay nào để lệch khỏi `.dockerignore`.
#
# ------------------------------------------------------------------------
# Vì sao KHÔNG liệt kê đầu vào bằng tay (bản đầu đã sai đúng chỗ này)
# ------------------------------------------------------------------------
# Bản đầu liệt kê `src/**`, `public/**` và bốn tệp cấu hình. Nó bỏ sót
# `postcss.config.js` và `tailwind.config.ts` — hai thứ quyết định CSS trong
# bundle — cùng `components.json`, `eslint.config.mjs`. Manifest ấy vẫn "tự
# nhất quán" và vẫn PASS: một attestation xanh cho một ảnh có thể khác source.
# Danh sách tay là thứ sẽ trôi; effective context thì không.
#
# ------------------------------------------------------------------------
# Vì sao KHÔNG dùng `.next/build-manifest.json`
# ------------------------------------------------------------------------
# Tệp ấy ánh xạ route → chunk. Hai cây source khác nhau vẫn có thể cho cùng một
# build-manifest. Muốn chứng minh "ảnh dựng từ đúng cây này" thì phải băm ĐẦU VÀO.
#
# ------------------------------------------------------------------------
# Byte THÔ, không chuẩn hoá
# ------------------------------------------------------------------------
# Bản đầu bỏ CR trước khi băm để tránh lệch giả CRLF/LF. Nhưng phép ấy áp lên cả
# `public/**` — tức sửa byte của PNG, font, ico trước khi băm, và làm hai tệp nhị
# phân khác nhau có thể băm ra cùng giá trị. Nay băm nguyên byte. Không còn rủi
# ro CRLF vì cả hai phía đều đọc cùng một build context do Docker gửi.
#
# ------------------------------------------------------------------------
# Build arg cũng là ĐẦU VÀO
# ------------------------------------------------------------------------
# `NEXT_PUBLIC_*` bị Next.js NƯỚNG THẲNG vào bundle. Cùng source mà khác
# `NEXT_PUBLIC_API_URL` là hai ảnh khác nhau về hành vi: trình duyệt sẽ gọi sang
# backend của stack khác. Đó chính là lý do stack smoke phải build ảnh riêng —
# nên manifest chỉ băm tệp thì vẫn để lọt đúng rủi ro nó sinh ra để chặn.
# Vì vậy manifest có thêm một mục `__NEXT_PUBLIC_ARGS__`.
set -eu

GOC="${1:-.}"
cd "$GOC" || { echo "[CHẶN] không vào được $GOC" >&2; exit 2; }

TMP="$(mktemp)" || exit 2
TMP_ARG="$(mktemp)" || exit 2
trap 'rm -f "$TMP" "$TMP_ARG"' EXIT INT TERM

# --- 1. mọi tệp trong context, băm byte thô, đường dẫn tương đối ---
find . -type f | sed 's|^\./||' | LC_ALL=C sort > "$TMP_ARG"
[ -s "$TMP_ARG" ] || { echo "[CHẶN] context rỗng" >&2; exit 2; }

# Đường dẫn phải biểu diễn được trong JSON mà không cần thoát. JSON chỉ đòi thoát
# `"`, `\` và ký tự điều khiển — chỉ cấm đúng ba thứ đó, vì `(auth)`, `[id]`,
# `@slot` của Next.js App Router là tên thư mục hợp lệ và có thật trong cây này.
if LC_ALL=C grep -q '["\\]' "$TMP_ARG" || LC_ALL=C grep -q '[^[:print:]]' "$TMP_ARG"; then
    echo "[CHẶN] đường dẫn chứa dấu nháy kép, gạch chéo ngược hoặc ký tự không in được:" >&2
    LC_ALL=C grep -e '["\\]' -e '[^[:print:]]' "$TMP_ARG" | head -5 >&2
    exit 2
fi

while IFS= read -r f; do
    printf '%s  %s\n' "$(sha256sum "$f" | cut -d' ' -f1)" "$f"
done < "$TMP_ARG" > "$TMP"

# --- 2. build arg NEXT_PUBLIC_*, chuẩn hoá rồi băm ---
# Sắp theo LC_ALL=C để thứ tự biến môi trường không đổi kết quả. Một biến KHÔNG
# được khai sẽ vắng mặt — khác hẳn với khai rỗng, và khác biệt ấy phải lộ ra.
BAM_ARG="$(env | LC_ALL=C grep '^NEXT_PUBLIC_' | LC_ALL=C sort | sha256sum | cut -d' ' -f1)"
printf '%s  __NEXT_PUBLIC_ARGS__\n' "$BAM_ARG" >> "$TMP"
LC_ALL=C sort -o "$TMP" "$TMP"

# Đếm SAU khi đã thêm mục build arg và sort: đếm trước thì `so_tep` khai một số
# còn mảng `tep` mang một số khác, và bất kỳ ai kiểm chéo hai trường ấy cũng thấy
# manifest tự mâu thuẫn.
SO_TEP="$(wc -l < "$TMP" | tr -d ' ')"
VAN_TAY="$(sha256sum < "$TMP" | cut -d' ' -f1)"

if [ "${QLTS_MANIFEST_DANG:-json}" = "text" ]; then
    cat "$TMP"
    exit 0
fi

awk -v n="$SO_TEP" -v vt="$VAN_TAY" '
BEGIN { printf "{\n  \"schema\": 2,\n  \"so_tep\": %s,\n  \"van_tay\": \"%s\",\n  \"tep\": [\n", n, vt }
      { printf "%s    \"%s\"", (NR > 1 ? ",\n" : ""), $0 }
END   { printf "\n  ]\n}\n" }
' "$TMP"
