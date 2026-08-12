#!/usr/bin/env bash
# scripts/test_nginx_admission_freeze.sh
# T0-3 NGINX_ADMISSION_FROZEN test harness (defense-in-depth pair with T0-2).
#
# Three layers of validation, all runnable on a Linux host with Docker:
#   1. Render layer  — envsubst against the real template; grep for the
#      structural markers that must appear after substitution.
#   2. Syntax layer  — nginx -t in a throw-away Docker container against an
#      isolated minimal config that mirrors the freeze location (no SSL, no
#      live upstream) so we get a clean grammar pass/fail.
#   3. Regex layer   — bash ERE simulation of the nginx PCRE pattern against
#      a representative URI table; locks in path-segment matching so the
#      lookalike `/api/admissionsfoo` and the legacy plural prefixes
#      (`/api/admission-configs`, `/api/admission-paths`) stay out.
#
# Live HTTP smoke (POST → 503, GET → pass-through, non-admission unaffected)
# is deferred to staging clone D12-D14 because it needs a live upstream and
# real SSL certs at the production cert path.
set -euo pipefail

cd "$(dirname "$0")/.."

PASS=0
FAIL=0

assert() {
    local desc="$1"
    if eval "$2" >/dev/null 2>&1; then
        echo "  ✓ $desc"
        PASS=$((PASS+1))
    else
        echo "  ✗ $desc"
        FAIL=$((FAIL+1))
    fi
}

# --- Layer 1: render layer ------------------------------------------------
test_render() {
    local label="$1" frozen_val="$2"
    local rendered
    rendered=$(mktemp)
    DOMAIN=example.test \
    NGINX_ADMISSION_FROZEN="$frozen_val" \
        envsubst '${DOMAIN} ${NGINX_ADMISSION_FROZEN}' \
            < nginx/templates/default.conf.template \
            > "$rendered"

    echo "=== Render: $label ==="
    assert "regex location for 3 admission prefixes present" \
        "grep -qE 'location ~ \\^/api/\\(admissions\\|admission-config\\|public/admissions\\)' '$rendered'"
    assert "set \$freeze_check directive present" \
        "grep -q 'set \$freeze_check' '$rendered'"
    assert "flag value '${frozen_val}' substituted into freeze_check" \
        "grep -q 'set \$freeze_check \"\$request_method:${frozen_val}\"' '$rendered'"
    assert "503 return defined" \
        "grep -q 'return 503' '$rendered'"
    assert "JSON code field NGINX_ADMISSION_FROZEN present" \
        "grep -q 'NGINX_ADMISSION_FROZEN' '$rendered'"
    rm -f "$rendered"
}

# --- Layer 2: syntax layer (isolated minimal config in Docker) -----------
test_syntax() {
    local label="$1" frozen_val="$2"
    echo "=== Syntax: $label ==="

    local tmpdir
    tmpdir=$(mktemp -d)
    cat > "$tmpdir/nginx.conf" <<NGINXCONF
events { worker_connections 16; }
http {
    upstream backend { server 127.0.0.1:8000; }

    server {
        listen 8080;
        server_name _;

        location ~ ^/api/(admissions|admission-config|public/admissions)(/.*)?\$ {
            set \$freeze_check "\$request_method:${frozen_val}";

            if (\$freeze_check ~ "^(POST|PUT|PATCH|DELETE):true\$") {
                add_header Content-Type application/json always;
                return 503 '{"detail":"frozen","code":"NGINX_ADMISSION_FROZEN"}';
            }

            proxy_pass http://backend;
        }

        location /api/ {
            proxy_pass http://backend;
        }
    }
}
NGINXCONF

    if docker run --rm \
            -v "$tmpdir/nginx.conf:/etc/nginx/nginx.conf:ro" \
            nginx:1.27-alpine nginx -t 2>&1 | grep -q "test is successful"; then
        echo "  ✓ nginx -t syntax PASS"
        PASS=$((PASS+1))
    else
        echo "  ✗ nginx -t syntax FAIL"
        docker run --rm \
            -v "$tmpdir/nginx.conf:/etc/nginx/nginx.conf:ro" \
            nginx:1.27-alpine nginx -t 2>&1 | sed 's/^/    /'
        FAIL=$((FAIL+1))
    fi
    rm -rf "$tmpdir"
}

# --- Layer 3: regex URI match simulation ---------------------------------
# The real nginx engine uses PCRE; bash regex (=~) is POSIX ERE. The pattern
# below uses only constructs common to both (^ $ ( ) | ? * .) so the result
# transfers. Lock-in cases come straight from the matrix in
# tests/middleware/test_admission_freeze.py.
PATTERN='^/api/(admissions|admission-config|public/admissions)(/.*)?$'

check_match() {
    local path="$1" expected="$2"
    local actual
    if [[ "$path" =~ $PATTERN ]]; then
        actual="MATCH"
    else
        actual="NO_MATCH"
    fi
    if [[ "$actual" == "$expected" ]]; then
        echo "  ✓ $path → $actual"
        PASS=$((PASS+1))
    else
        echo "  ✗ $path → $actual (expected $expected)"
        FAIL=$((FAIL+1))
    fi
}

test_regex() {
    echo "=== Regex URI match (bash ERE simulating nginx PCRE) ==="
    # Should match
    check_match "/api/admissions"                  "MATCH"
    check_match "/api/admissions/123"              "MATCH"
    check_match "/api/admissions/confirm/abc"      "MATCH"
    check_match "/api/admission-config"            "MATCH"
    check_match "/api/admission-config/policies"   "MATCH"
    check_match "/api/public/admissions"           "MATCH"
    check_match "/api/public/admissions/submit"    "MATCH"
    # Lookalikes — must NOT match
    check_match "/api/admissionsfoo"               "NO_MATCH"
    check_match "/api/admission"                   "NO_MATCH"
    check_match "/api/admission-configs"           "NO_MATCH"
    check_match "/api/admission-paths"             "NO_MATCH"
    # Non-admission baseline
    check_match "/api/leads/123"                   "NO_MATCH"
    check_match "/api/admin/users"                 "NO_MATCH"
    check_match "/health"                          "NO_MATCH"
}

# --- Driver ---------------------------------------------------------------
test_render "Default (frozen=false)" "false"
test_render "Cutover (frozen=true)"  "true"
test_render "Unset (deploy.sh defaults handle this)" ""

test_syntax "frozen=false (default)"        "false"
test_syntax "frozen=true (cutover)"         "true"
test_syntax "frozen=unset (empty literal)"  ""

test_regex

echo ""
echo "==========================================="
echo "Result: $PASS PASS, $FAIL FAIL"
echo "==========================================="
[[ $FAIL -eq 0 ]] || exit 1
