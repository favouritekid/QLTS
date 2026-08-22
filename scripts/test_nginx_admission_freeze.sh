#!/usr/bin/env bash
# scripts/test_nginx_admission_freeze.sh
# T0-3 NGINX_ADMISSION_FROZEN test harness (cặp defense-in-depth với T0-2).
#
# ⚠️ Bản trước GIỮ BẢN SAO RIÊNG của regex ba tiền tố ở cả ba lớp, và không lớp
# nào đọc template. Hậu quả: nó vẫn báo PASS sau khi các router `/api/v2/` ra
# đời mà template không phủ — 39 đường ghi thoát khỏi cần gạt ở CẢ hai tầng
# trong khi harness "chứng nhận" là ổn. Riêng lớp 1 còn tệ hơn: grep không neo
# cuối dòng nên chuỗi ba tiền tố vẫn là TIỀN TỐ của dòng mười tiền tố ⇒ khớp,
# ⇒ xanh, kể cả khi v2 bị gỡ đi.
#
# Bản này KHÔNG giữ bản sao nào. Mọi thứ rút ra từ hai nguồn thật:
#   - `Backend_FastAPI/app/middleware/admission_freeze.py` → FROZEN_PREFIXES
#   - `nginx/templates/default.conf.template`             → khối `location ~`
# và lớp 1 đòi hai bên khớp NGUYÊN VĂN.
#
# Ba lớp:
#   1. Render — envsubst template thật; dòng `location` phải bằng đúng dòng
#      dựng lại từ FROZEN_PREFIXES.
#   2. Syntax — `nginx -t` trong container tạm, dùng chính dòng location TRÍCH
#      TỪ template (không viết lại).
#   3. Regex  — mô phỏng khớp URI bằng bash ERE, ca kiểm SINH RA từ danh sách
#      tiền tố nên thêm tiền tố là tự có ca.
#
# Smoke HTTP thật (POST → 503, GET → đi tiếp, ngoài miền không đụng) nằm ở
# `tests-e2e/admission-freeze/` — chạy được ngay, không cần SSL/upstream thật.
set -euo pipefail

cd "$(dirname "$0")/.."

MW=Backend_FastAPI/app/middleware/admission_freeze.py
TPL=nginx/templates/default.conf.template
PASS=0
FAIL=0

assert() {
    local desc="$1"
    if eval "$2" >/dev/null 2>&1; then
        echo "  ✓ $desc"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $desc"
        FAIL=$((FAIL + 1))
    fi
}

# --- Nguồn chuẩn: FROZEN_PREFIXES trong middleware ------------------------
[[ -f "$MW" ]]  || { echo "KHONG THAY $MW";  exit 3; }
[[ -f "$TPL" ]] || { echo "KHONG THAY $TPL"; exit 3; }

mapfile -t PREFIXES < <(
    sed -n '/^FROZEN_PREFIXES/,/^)/p' "$MW" | grep -oE '"/api/[^"]+"' | tr -d '"'
)
if [[ ${#PREFIXES[@]} -lt 3 ]]; then
    echo "TRICH FROZEN_PREFIXES THAT BAI (${#PREFIXES[@]} muc) — khong ket luan gi"
    exit 3
fi

ALT=""
for p in "${PREFIXES[@]}"; do
    [[ "$p" == /api/* ]] || { echo "TIEN TO LA: $p"; exit 3; }
    ALT+="${ALT:+|}${p#/api/}"
done
LOCATION_LINE="location ~ ^/api/(${ALT})(/.*)?\$ {"
PATTERN="^/api/(${ALT})(/.*)?\$"

echo "=== Nguon chuan: ${#PREFIXES[@]} tien to tu $MW ==="
printf '    %s\n' "${PREFIXES[@]}"

# --- Lớp 1: render + hai tầng phải khớp NGUYÊN VĂN ------------------------
test_render() {
    local label="$1" frozen_val="$2"
    local rendered
    rendered=$(mktemp)
    DOMAIN=example.test \
    NGINX_ADMISSION_FROZEN="$frozen_val" \
        envsubst '${DOMAIN} ${NGINX_ADMISSION_FROZEN}' < "$TPL" > "$rendered"

    echo "=== Render: $label ==="
    # grep -F + so khớp nguyên văn: đây là chỗ bản cũ để lọt, vì grep tiền tố
    # vẫn khớp một dòng dài hơn.
    assert "dong location khop DUNG FROZEN_PREFIXES (${#PREFIXES[@]} tien to)" \
        "grep -qF '$LOCATION_LINE' '$rendered'"
    assert "set \$freeze_check co mat" \
        "grep -q 'set \$freeze_check' '$rendered'"
    assert "gia tri co '${frozen_val}' duoc thay vao freeze_check" \
        "grep -q 'set \$freeze_check \"\$request_method:${frozen_val}\"' '$rendered'"
    assert "co return 503" "grep -q 'return 503' '$rendered'"
    assert "co truong code NGINX_ADMISSION_FROZEN" \
        "grep -q 'NGINX_ADMISSION_FROZEN' '$rendered'"
    assert "DUNG MOT khoi freeze" \
        "[[ \$(grep -c 'set \\\$freeze_check' '$rendered') -eq 1 ]]"
    rm -f "$rendered"
}

# --- Lớp 2: nginx -t trên khối TRÍCH TỪ template --------------------------
test_syntax() {
    local label="$1" frozen_val="$2"
    echo "=== Syntax: $label ==="

    local tmpdir
    tmpdir=$(mktemp -d)

    # Trích nguyên khối freeze; `sub(/\r$/,"")` cho checkout CRLF trên Windows.
    awk '{sub(/\r$/,"")} /location ~ \^\/api\/\(/{co=1} co{print} co && /^    }$/{exit}' \
        "$TPL" > "$tmpdir/block.conf"
    local dong
    dong=$(wc -l < "$tmpdir/block.conf")
    if [[ ! -s "$tmpdir/block.conf" || "$dong" -gt 40 ]]; then
        echo "  ✗ trich khoi freeze that bai ($dong dong)"
        FAIL=$((FAIL + 1))
        rm -rf "$tmpdir"
        return
    fi

    {
        echo 'events { worker_connections 16; }'
        echo 'http {'
        echo '    limit_req_zone $binary_remote_addr zone=api:10m rate=1000r/s;'
        echo '    upstream backend { server 127.0.0.1:8000; }'
        echo '    server {'
        echo '        listen 8080;'
        echo '        server_name _;'
        NGINX_ADMISSION_FROZEN="$frozen_val" \
            envsubst '${NGINX_ADMISSION_FROZEN}' < "$tmpdir/block.conf"
        echo '        location /api/ { proxy_pass http://backend; }'
        echo '    }'
        echo '}'
    } > "$tmpdir/nginx.conf"

    if ! grep -q 'request_method' "$tmpdir/nginx.conf"; then
        echo "  ✗ envsubst da nuot bien cua nginx"
        FAIL=$((FAIL + 1))
        rm -rf "$tmpdir"
        return
    fi

    if docker run --rm -v "$tmpdir/nginx.conf:/etc/nginx/nginx.conf:ro" \
            nginx:1.27-alpine nginx -t 2>&1 | grep -q "test is successful"; then
        echo "  ✓ nginx -t syntax PASS"
        PASS=$((PASS + 1))
    else
        echo "  ✗ nginx -t syntax FAIL"
        docker run --rm -v "$tmpdir/nginx.conf:/etc/nginx/nginx.conf:ro" \
            nginx:1.27-alpine nginx -t 2>&1 | sed 's/^/    /'
        FAIL=$((FAIL + 1))
    fi
    rm -rf "$tmpdir"
}

# --- Lớp 3: mô phỏng khớp URI, ca SINH RA từ danh sách tiền tố ------------
check_match() {
    local path="$1" expected="$2" actual
    if [[ "$path" =~ $PATTERN ]]; then actual="MATCH"; else actual="NO_MATCH"; fi
    if [[ "$actual" == "$expected" ]]; then
        echo "  ✓ $path → $actual"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $path → $actual (mong $expected)"
        FAIL=$((FAIL + 1))
    fi
}

test_regex() {
    echo "=== Regex URI match (bash ERE mo phong nginx PCRE) ==="
    # Sinh từ danh sách: thêm một tiền tố là tự có ba ca, không phải nhớ thêm.
    for p in "${PREFIXES[@]}"; do
        check_match "$p"        "MATCH"
        check_match "$p/1"      "MATCH"
        check_match "${p}foo"   "NO_MATCH"   # khớp theo ĐOẠN, không startswith
    done
    # Ngoài miền tuyển sinh — phải nằm ngoài
    check_match "/api/leads/123"                  "NO_MATCH"
    check_match "/api/admin/users"                "NO_MATCH"
    check_match "/api/v2/admin/casbin/reload"     "NO_MATCH"
    check_match "/api/v2/admin/system-config/x"   "NO_MATCH"
    check_match "/api/v2/admin/vn-school/schools" "NO_MATCH"
    check_match "/api/admission"                  "NO_MATCH"
    check_match "/api/admission-configs"          "NO_MATCH"
    check_match "/health"                         "NO_MATCH"
}

# --- Driver ---------------------------------------------------------------
test_render "Mac dinh (frozen=false)" "false"
test_render "Cutover (frozen=true)"   "true"
test_render "Khong dat (deploy.sh lo mac dinh)" ""

test_syntax "frozen=false (mac dinh)"      "false"
test_syntax "frozen=true (cutover)"        "true"
test_syntax "frozen=unset (chuoi rong)"    ""

test_regex

echo ""
echo "==========================================="
echo "Result: $PASS PASS, $FAIL FAIL"
echo "==========================================="
[[ $FAIL -eq 0 ]] || exit 1
