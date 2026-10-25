#!/usr/bin/env bash
# frontend-smoke-check.sh <base-url> <backend-log.jsonl> <out-dir>
#
# Đo bằng REQUEST THẬT rằng một bản build frontend đang chạy render được /login và
# /dashboard, và /dashboard lấy số liệu qua getCachedUserStatistics ('use cache')
# từ backend GIẢ (frontend-smoke-backend.js, đã chạy sẵn, ghi log vào
# <backend-log.jsonl>). Script KHÔNG biết gì về Docker: frontend-image-smoke.yml
# chạy ảnh production rồi gọi nó với URL của ảnh.
#
# MỌI request: curl PHẢI thoát 0 (truyền tải trọn vẹn) TRƯỚC khi xét mã HTTP hay
# nội dung. HTTP 200 và dấu dữ liệu vẫn có thể nằm trong một phản hồi truyền dở
# (curl 18) hoặc hết hạn (curl 28) — mã curl được giữ RIÊNG, không `|| true`.
#
#   R0 GET /login, không cookie   ⇒ 200 và <title> chứa "Login"
#   R1 GET /dashboard, token A    ⇒ 200, có dấu total_users 731 (chỉ backend giả trả
#                                   số này) và backend nhận /statistics của A
#   R2 lặp R1                     ⇒ 200 + dấu. IN số lần backend nhận /statistics
#                                   của A (1 = cache trúng) — GHI NHẬN, không chặn:
#                                   chưa có số đo nền để biết giá trị đúng.
#   R3 KIỂM NGƯỢC, token B        ⇒ backend giả trả 500 cho /statistics của B. Phải
#                                   đủ BA vế: HTTP ∈ {200, 500}, dấu VẮNG, backend
#                                   NHẬN /statistics của B. 200 = vỏ trang đã stream
#                                   trước rồi error boundary render trong luồng
#                                   (cacheComponents); 500 = lỗi trước byte đầu.
#                                   000, 3xx, 4xx đều HỎNG: trang không trả lời trọn
#                                   thì "dấu vắng" không chứng minh gì. Thiếu vế
#                                   backend thì "dấu vắng" chỉ chứng minh trang hỏng
#                                   ở chỗ khác. B khác A nên cũng khác khoá cache.
#   R4 GET /dashboard, không cookie ⇒ 3xx sang /session-refresh hoặc /login, không dấu
#
# Token là JWT GIẢ không chữ ký: proxy chỉ GIẢI MÃ để điều hướng (src/proxy.ts,
# usableAccessToken), backend thật sẽ từ chối nó. Đây là phép đo render, không
# phải phép đo xác thực.
#
# FRONTEND_SMOKE_MAX_TIME (giây, mặc định 60) = --max-time của mỗi request.
# Kết quả từng phép đo ghi vào <out-dir>/ket-qua.txt (cũng in ra stdout).
# Thoát: 0 khi R0–R4 đạt · 1 nếu một phép đo hỏng · 2 tham số/công cụ thiếu hoặc
# không đọc được tệp đầu ra / log backend.
set -euo pipefail

BASE="${1:-}"
BLOG="${2:-}"
OUT="${3:-}"
MAX_TIME="${FRONTEND_SMOKE_MAX_TIME:-60}"
if [ -z "$BASE" ] || [ -z "$BLOG" ] || [ -z "$OUT" ]; then
  echo "Usage: frontend-smoke-check.sh <base-url> <backend-log.jsonl> <out-dir>" >&2
  exit 2
fi
if ! [[ "$MAX_TIME" =~ ^[1-9][0-9]*$ ]]; then
  echo "FRONTEND_SMOKE_MAX_TIME phải là số nguyên dương, nhận '$MAX_TIME'" >&2
  exit 2
fi
for cong_cu in curl node grep; do
  command -v "$cong_cu" > /dev/null || { echo "thiếu $cong_cu" >&2; exit 2; }
done
mkdir -p "$OUT"
KQ="$OUT/ket-qua.txt"
: > "$KQ"
touch "$BLOG"
hong=0

ghi() { echo "$*" | tee -a "$KQ"; }
dat() { ghi "ĐẠT  $*"; }
truot() { ghi "HỎNG $*"; hong=1; }

token() {
  node -e '
    const b = (o) => Buffer.from(JSON.stringify(o)).toString("base64url");
    const exp = Math.floor(Date.now() / 1000) + 3600;
    console.log(b({ alg: "none", typ: "JWT" }) + "." +
      b({ sub: "1", type: "access", role: "admin", jti: process.argv[1], exp }) + ".khong-ky");
  ' "$1"
}
JTI_A=smoke-a
JTI_B=smoke-b-kiem-nguoc
TA=$(token "$JTI_A")
TB=$(token "$JTI_B")

# goi <tệp-thân> <cookie|""> <url> — đặt CURL_RC, HTTP, DICH (redirect_url).
goi() {
  local tep=$1 cookie=$2 url=$3 kq=""
  : > "$tep" # curl không tạo tệp khi thân rỗng (vd. 307)
  CURL_RC=0
  if [ -n "$cookie" ]; then
    kq=$(curl -s --max-time "$MAX_TIME" -o "$tep" -w '%{http_code} %{redirect_url}' \
      -H "Cookie: access_token=$cookie" "$url") || CURL_RC=$?
  else
    kq=$(curl -s --max-time "$MAX_TIME" -o "$tep" -w '%{http_code} %{redirect_url}' \
      "$url") || CURL_RC=$?
  fi
  HTTP=${kq%% *}
  DICH=${kq#* }
}

# dem <chuỗi-cố-định> <tệp> → số lần xuất hiện. grep: 0 = có, 1 = không có, ≥2 =
# không đọc được tệp ⇒ trả 2. KHÔNG được thành "0 lần": với R3/R4, 0 chính là
# điều kiện ĐẠT.
dem() {
  local ra rc=0
  ra=$(grep -aoF -- "$1" "$2") || rc=$?
  if [ "$rc" -gt 1 ]; then
    echo "không đọc được $2 (grep rc=$rc)" >&2
    return 2
  fi
  if [ -z "$ra" ]; then echo 0; else printf '%s\n' "$ra" | wc -l; fi
}

# Hai hàm dưới gọi Ở CẤP SCRIPT (không trong `$(…)`) và đặt biến toàn cục: bash tắt
# errexit trong command substitution, nên `exit` lồng trong `$(…)` sẽ bị nuốt.
#
# Dấu: RSC payload trong HTML escape dấu nháy (\"total_users\":731); đếm cả dạng
# không escape phòng khi số liệu nằm ở chỗ khác của trang.
dau() { # <tệp> → DAU
  local a b
  a=$(dem 'total_users\":731' "$1") || exit 2
  b=$(dem '"total_users":731' "$1") || exit 2
  DAU=$((a + b))
}
stats_cua() { # <jti> → NSTATS: số lần backend nhận /statistics mang đúng jti
  NSTATS=$(dem "\"path\":\"/api/admin/users/statistics\",\"jti\":\"$1\"" "$BLOG") || exit 2
}

# R0
goi "$OUT/r0.html" "" "$BASE/login"
tieu_de=$(grep -aoE '<title>[^<]*</title>' "$OUT/r0.html") || [ $? -eq 1 ] || exit 2
tieu_de=${tieu_de%%$'\n'*}
if [ "$CURL_RC" = 0 ] && [ "$HTTP" = 200 ] && [[ "$tieu_de" == *Login* ]]; then
  dat "R0 /login: curl=$CURL_RC http=$HTTP $tieu_de"
else
  truot "R0 /login: curl=$CURL_RC (phải 0) http=$HTTP tiêu đề='${tieu_de}'"
fi

# R1
goi "$OUT/r1.html" "$TA" "$BASE/dashboard"
dau "$OUT/r1.html"
stats_cua "$JTI_A"
if [ "$CURL_RC" = 0 ] && [ "$HTTP" = 200 ] && [ "$DAU" -gt 0 ] && [ "$NSTATS" -ge 1 ]; then
  dat "R1 /dashboard token A: curl=$CURL_RC http=$HTTP dấu=$DAU · backend nhận /statistics của A: $NSTATS"
else
  truot "R1 /dashboard token A: curl=$CURL_RC (phải 0) http=$HTTP dấu=$DAU (phải >0) · backend nhận /statistics của A: $NSTATS (phải ≥1)"
fi

# R2
goi "$OUT/r2.html" "$TA" "$BASE/dashboard"
dau "$OUT/r2.html"
stats_cua "$JTI_A"
me=$(dem '"path":"/api/users/me"' "$BLOG") || exit 2
if [ "$CURL_RC" = 0 ] && [ "$HTTP" = 200 ] && [ "$DAU" -gt 0 ]; then
  dat "R2 /dashboard token A lần 2: curl=$CURL_RC http=$HTTP dấu=$DAU"
else
  truot "R2 /dashboard token A lần 2: curl=$CURL_RC (phải 0) http=$HTTP dấu=$DAU (phải >0)"
fi
ghi "GHI  R2 sau hai trang của A: backend nhận /statistics $NSTATS lần (1 = 'use cache' trúng), /api/users/me $me lần"

# R3
goi "$OUT/r3.html" "$TB" "$BASE/dashboard"
dau "$OUT/r3.html"
stats_cua "$JTI_B"
if [ "$CURL_RC" = 0 ] && { [ "$HTTP" = 200 ] || [ "$HTTP" = 500 ]; } && [ "$DAU" = 0 ] && [ "$NSTATS" -ge 1 ]; then
  dat "R3 KIỂM NGƯỢC token B (statistics 500): curl=$CURL_RC http=$HTTP dấu=$DAU · backend nhận /statistics của B: $NSTATS"
else
  truot "R3 KIỂM NGƯỢC token B (statistics 500): curl=$CURL_RC (phải 0) http=$HTTP (phải 200|500) dấu=$DAU (phải 0) · backend nhận /statistics của B: $NSTATS (phải ≥1)"
fi

# R4
goi "$OUT/r4.html" "" "$BASE/dashboard"
dau "$OUT/r4.html"
if [ "$CURL_RC" = 0 ] && [[ "$HTTP" =~ ^30[1278]$ ]] && [[ "$DICH" =~ ^https?://[^/]+/(session-refresh|login)([?#]|$) ]] && [ "$DAU" = 0 ]; then
  dat "R4 /dashboard không cookie: curl=$CURL_RC http=$HTTP → $DICH"
else
  truot "R4 /dashboard không cookie: curl=$CURL_RC (phải 0) http=$HTTP → '${DICH}' dấu=$DAU (phải 3xx sang /session-refresh hoặc /login, dấu 0)"
fi

if [ "$hong" = 0 ]; then ghi "KẾT QUẢ: ĐẠT"; else ghi "KẾT QUẢ: HỎNG"; fi
exit "$hong"
