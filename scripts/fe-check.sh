#!/usr/bin/env bash
# Chạy npm script của frontend (type-check, test, lint, build) trong một
# container dùng-một-lần, thay cho `docker compose exec`.
#
# ─────────────────────────────────────────────────────────────────────────────
# Vì sao container dùng-một-lần
#
#   `exec` dùng chung cgroup với Next.js dev server đang sống. Chạy tsc /
#   vitest / eslint ở đó đã OOM-kill PID 1 và làm trình duyệt nhận
#   `err_empty_response`. `run --rm --no-deps` có bộ nhớ riêng, tự xoá khi
#   xong.
#
# ─────────────────────────────────────────────────────────────────────────────
# 🔴 Vì sao BẮT BUỘC mount source, và vì sao mount thôi vẫn chưa đủ
#
#   Service `frontend` KHÔNG có bind mount: source nằm trong image, và
#   `develop.watch` chỉ sync `frontend/src` vào container dev ĐANG CHẠY. Một
#   container `run --rm` không có watch, nên nếu không mount thì nó chấm bài
#   trên source đã nướng vào image từ lần build cuối.
#
#   Hậu quả không trông giống lỗi: không dòng đỏ nào, không cảnh báo nào —
#   chỉ một lượt xanh mượt nói về code khác. Đã xảy ra: báo "210 tệp / 2227
#   test xanh" cho một commit mà container còn không có các tệp test mới;
#   mount vào thì ra 223 tệp / 2361 test.
#
#   Mount cũng có thể hỏng ÂM THẦM (Docker Desktop trên Windows từng cho ra
#   `/app/src` rỗng khi đường dẫn viết bằng dấu `\`), và khi đó tsc thoát 0
#   vì chẳng có gì để kiểm. Nên script tự CHỨNG MINH: băm cây source ở máy
#   thật, băm lại BÊN TRONG container, lệch một byte là dừng trước khi npm kịp
#   chạy. Một lượt xanh chỉ có giá trị khi kèm dòng attest ở đầu.
#
#   `node_modules` giữ nguyên của image (anonymous volume) vì bản trên máy là
#   junction của Windows và cài lại mỗi lượt thì quá chậm. `.next` cũng vậy —
#   giữ types đã sinh sẵn, tránh lỗi giả `TS1434/TS1128` từ route types.
#
# ─────────────────────────────────────────────────────────────────────────────
# Dùng:
#   scripts/fe-check.sh type-check
#   scripts/fe-check.sh test
#   scripts/fe-check.sh test:coverage
#   scripts/fe-check.sh lint
#   scripts/fe-check.sh build
#
# Mọi tham số sau tên script được chuyển thẳng cho `npm run <args...>`.

set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "Usage: $(basename "$0") <npm-script> [args...]" >&2
  echo "Example: $(basename "$0") type-check" >&2
  exit 64
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FE="$ROOT/frontend"

# Git Bash trên Windows biến `/app` trong `-v host:/app` thành đường dẫn
# Windows. Tắt phép biến đổi đó.
export MSYS_NO_PATHCONV=1

# Công thức băm CHUNG cho hai phía. Phải giống hệt từng ký tự, nếu không phép
# so trở thành vô nghĩa (luôn lệch ⇒ ai đó sẽ gỡ nó đi). `LC_ALL=C` vì thứ tự
# sort phụ thuộc locale, và locale của máy khác của container.
# `tr -d " *"` chuẩn hoá ĐỊNH DẠNG của `sha256sum`, không phải nội dung:
# bản Git Bash in `<hash> *<tệp>` (dấu sao = chế độ nhị phân), coreutils trong
# container in `<hash>  <tệp>` (hai khoảng trắng). Thiếu bước này thì hai phía
# luôn lệch dù từng tệp băm ra y hệt — và một phép kiểm luôn đỏ là một phép
# kiểm sắp bị gỡ. Xoá được an toàn vì cả `*` lẫn khoảng trắng đều không có
# trong đường dẫn nguồn ở đây (và `*` thì Windows cấm hẳn).
BAM='find src -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.js" -o -name "*.jsx" -o -name "*.json" -o -name "*.css" \) | LC_ALL=C sort | xargs sha256sum | tr -d " *" | sha256sum | cut -c1-16'
DEM='find src -type f \( -name "*.ts" -o -name "*.tsx" \) | wc -l'

HASH_MAY="$(cd "$FE" && eval "$BAM")"
SO_TEP_MAY="$(cd "$FE" && eval "$DEM" | tr -d ' ')"

# Nguồn gốc của source, để dòng attest gắn được vào một commit cụ thể. Cây bẩn
# thì nói ra — "xanh trên HEAD" và "xanh trên HEAD + 12 tệp đang sửa" là hai
# tuyên bố khác nhau.
GIT_SHA="$(cd "$ROOT" && git rev-parse --short HEAD 2>/dev/null || echo 'không-phải-git')"
if [[ -n "$(cd "$ROOT" && git status --porcelain -- frontend 2>/dev/null)" ]]; then
  SACH="CÂY BẨN (có thay đổi chưa commit trong frontend/)"
else
  SACH="sạch"
fi

echo "──────────────────────────────────────────────────────────────"
echo " fe-check  ·  npm run $*"
echo "   commit    : $GIT_SHA ($SACH)"
echo "   source    : $SO_TEP_MAY tệp .ts/.tsx  ·  hash $HASH_MAY"
echo "──────────────────────────────────────────────────────────────"

# `sh -c` bên trong: băm lại rồi mới gọi npm. Không tách thành hai lượt `run`
# — giữa hai container là một khe để mount hỏng mà lượt kiểm đã qua rồi.
exec docker compose run --rm --no-deps \
  -v "$FE:/app" \
  -v /app/node_modules \
  -v /app/.next \
  -e "QLTS_HASH_MONG_DOI=$HASH_MAY" \
  -e "QLTS_SO_TEP_MONG_DOI=$SO_TEP_MAY" \
  frontend sh -c "
    set -e
    THAT=\$($BAM)
    SO_TEP=\$($DEM | tr -d ' ')
    if [ \"\$THAT\" != \"\$QLTS_HASH_MONG_DOI\" ]; then
      echo '' >&2
      echo '🔴 CHẶN: source trong container KHÔNG phải source trên máy.' >&2
      echo \"   máy       : \$QLTS_SO_TEP_MONG_DOI tệp · hash \$QLTS_HASH_MONG_DOI\" >&2
      echo \"   container : \$SO_TEP tệp · hash \$THAT\" >&2
      echo '' >&2
      echo '   Mount hỏng (thường là đường dẫn Windows viết bằng dấu \\\\) hoặc' >&2
      echo '   image đang che source. Mọi kết quả sau dòng này sẽ nói về code' >&2
      echo '   KHÁC, nên dừng ở đây thay vì trả về một màu xanh vô nghĩa.' >&2
      exit 65
    fi
    echo \"   ✓ container khớp máy: \$SO_TEP tệp · hash \$THAT\"
    echo ''
    exec npm run \"\$@\"
  " sh "$@"
