#!/usr/bin/env bash
# frontend-smoke-check.sh <base-url> <backend-log.jsonl> <out-dir>
#
# Đo bằng REQUEST THẬT rằng một bản build frontend đang chạy render được /login và
# /dashboard, và /dashboard lấy số liệu qua getCachedUserStatistics ('use cache')
# từ backend GIẢ (frontend-smoke-backend.js, đã chạy sẵn, ghi log vào
# <backend-log.jsonl>). Script KHÔNG biết gì về Docker: frontend-image-smoke.yml
# chạy ảnh production rồi gọi nó với URL của ảnh.
#
#   R0 GET /login, không cookie   ⇒ 200 và <title> chứa "Login"
#   R1 GET /dashboard, token A    ⇒ 200, có dấu total_users 731 (chỉ backend giả trả
#                                   số này) và backend nhận /statistics của A
#   R2 lặp R1                     ⇒ 200 + dấu. IN số lần backend nhận /statistics
#                                   của A (1 = cache trúng) — GHI NHẬN, không chặn:
#                                   chưa có số đo nền để biết giá trị đúng.
#   R3 KIỂM NGƯỢC, token B        ⇒ backend giả trả 500 cho /statistics của B, nên dấu
#                                   PHẢI vắng VÀ backend PHẢI nhận /statistics của B.
#                                   Thiếu vế sau thì "dấu vắng" chỉ chứng minh trang
#                                   hỏng ở chỗ khác, không chứng minh dấu đến từ
#                                   /statistics. B khác A nên cũng khác khoá cache.
#   R4 GET /dashboard, không cookie ⇒ 3xx sang /session-refresh hoặc /login, không dấu
#
# Token là JWT GIẢ không chữ ký: proxy chỉ GIẢI MÃ để điều hướng (src/proxy.ts,
# usableAccessToken), backend thật sẽ từ chối nó. Đây là phép đo render, không
# phải phép đo xác thực.
#
# Kết quả từng phép đo ghi vào <out-dir>/ket-qua.txt (cũng in ra stdout).
# Thoát: 0 khi R0–R4 đạt · 1 nếu một phép đo hỏng · 2 tham số/công cụ thiếu.
set -euo pipefail

BASE="${1:-}"
BLOG="${2:-}"
OUT="${3:-}"
if [ -z "$BASE" ] || [ -z "$BLOG" ] || [ -z "$OUT" ]; then
  echo "Usage: frontend-smoke-check.sh <base-url> <backend-log.jsonl> <out-dir>" >&2
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

# Dấu: RSC payload trong HTML escape dấu nháy (\"total_users\":731); đếm cả dạng
# không escape phòng khi số liệu nằm ở chỗ khác của trang.
# `|| true`: dưới pipefail, grep không khớp trả 1 và `set -e` sẽ giết cả script
# đúng ở ca dấu PHẢI vắng (R3, R4).
dau() {
  local a b
  a=$(grep -aoF 'total_users\":731' "$1" | wc -l || true)
  b=$(grep -aoF '"total_users":731' "$1" | wc -l || true)
  echo $((a + b))
}
# Số lần backend nhận /statistics mang đúng jti.
stats_cua() {
  grep -cF "\"path\":\"/api/admin/users/statistics\",\"jti\":\"$1\"" "$BLOG" || true
}
lay() { # <tệp-thân> <cookie|""> <url> → in mã HTTP
  : > "$1" # curl không tạo tệp khi thân rỗng (vd. 307) — dau() phải đọc được tệp
  if [ -n "${2:-}" ]; then
    curl -s --max-time 60 -o "$1" -w '%{http_code}' -H "Cookie: access_token=$2" "$3"
  else
    curl -s --max-time 60 -o "$1" -w '%{http_code}' "$3"
  fi
}

# R0
c=$(lay "$OUT/r0.html" "" "$BASE/login" || true)
tieu_de=$(grep -aoE '<title>[^<]*</title>' "$OUT/r0.html" | head -n 1 || true)
if [ "$c" = 200 ] && [[ "$tieu_de" == *Login* ]]; then
  dat "R0 /login: http=$c $tieu_de"
else
  truot "R0 /login: http=$c tiêu đề='${tieu_de}'"
fi

# R1
c=$(lay "$OUT/r1.html" "$TA" "$BASE/dashboard" || true)
d=$(dau "$OUT/r1.html")
n=$(stats_cua "$JTI_A")
if [ "$c" = 200 ] && [ "$d" -gt 0 ] && [ "$n" -ge 1 ]; then
  dat "R1 /dashboard token A: http=$c dấu=$d · backend nhận /statistics của A: $n"
else
  truot "R1 /dashboard token A: http=$c dấu=$d (phải >0) · backend nhận /statistics của A: $n (phải ≥1)"
fi

# R2
c=$(lay "$OUT/r2.html" "$TA" "$BASE/dashboard" || true)
d=$(dau "$OUT/r2.html")
n=$(stats_cua "$JTI_A")
me=$(grep -cF '"path":"/api/users/me"' "$BLOG" || true)
if [ "$c" = 200 ] && [ "$d" -gt 0 ]; then
  dat "R2 /dashboard token A lần 2: http=$c dấu=$d"
else
  truot "R2 /dashboard token A lần 2: http=$c dấu=$d (phải >0)"
fi
ghi "GHI  R2 sau hai trang của A: backend nhận /statistics $n lần (1 = 'use cache' trúng), /api/users/me $me lần"

# R3
c=$(lay "$OUT/r3.html" "$TB" "$BASE/dashboard" || true)
d=$(dau "$OUT/r3.html")
n=$(stats_cua "$JTI_B")
if [ "$d" = 0 ] && [ "$n" -ge 1 ]; then
  dat "R3 KIỂM NGƯỢC token B (statistics 500): http=$c dấu=$d · backend nhận /statistics của B: $n"
else
  truot "R3 KIỂM NGƯỢC token B (statistics 500): http=$c dấu=$d (phải 0) · backend nhận /statistics của B: $n (phải ≥1)"
fi

# R4
: > "$OUT/r4.html"
kq=$(curl -s --max-time 60 -o "$OUT/r4.html" -w '%{http_code} %{redirect_url}' "$BASE/dashboard" || true)
c=${kq%% *}
dich=${kq#* }
d=$(dau "$OUT/r4.html")
if [[ "$c" =~ ^30[1278]$ ]] && [[ "$dich" =~ ^https?://[^/]+/(session-refresh|login)([?#]|$) ]] && [ "$d" = 0 ]; then
  dat "R4 /dashboard không cookie: http=$c → $dich"
else
  truot "R4 /dashboard không cookie: http=$c → '${dich}' dấu=$d (phải 3xx sang /session-refresh hoặc /login, dấu 0)"
fi

if [ "$hong" = 0 ]; then ghi "KẾT QUẢ: ĐẠT"; else ghi "KẾT QUẢ: HỎNG"; fi
exit "$hong"
