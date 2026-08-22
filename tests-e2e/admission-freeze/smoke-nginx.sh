#!/bin/sh
# Smoke B — đi QUA nginx thật, dùng NGUYÊN VĂN khối `location` freeze trích từ
# `nginx/templates/default.conf.template`.
#
# Không chép tay lại regex vào đây: chép thì phép đo chỉ chứng minh bản chép,
# không chứng minh thứ sẽ chạy thật. Đây là lý do lỗ hổng v2 sống được — mỗi
# tầng giữ một bản sao riêng và không ai đối chiếu.
#
# PHẠM VI: khối freeze + upstream giả. KHÔNG gồm TLS/domain/rate-limit thật của
# production; chỗ đó thuộc `scripts/nginx-apply.sh` + `scripts/nginx-verify.sh`.
#
# Cách chạy (từ gốc kho):
#   docker run --rm -i -e NGINX_ADMISSION_FROZEN=true \
#     -v "$PWD/nginx:/nginx:ro" \
#     -v "$PWD/tests-e2e/admission-freeze/smoke-nginx.sh:/tmp/smoke.sh:ro" \
#     nginx:1.27-alpine sh -c 'apk add --no-cache curl gettext >/dev/null && sh /tmp/smoke.sh'
# Chạy lại với NGINX_ADMISSION_FROZEN=false để đo chiều ngược.
set -e

TPL=/nginx/templates/default.conf.template
[ -f "$TPL" ] || { echo "KHONG THAY $TPL"; exit 3; }

# Trích khối: từ dòng `location ~ ^/api/(` tới dấu `}` đóng cùng mức thụt lề.
# `sub(/\r$/,"")` là bắt buộc: checkout trên Windows mang CRLF, khi đó
# `/^    }$/` không khớp và awk nuốt tới cuối tệp — vẫn "trích được", vẫn có
# nội dung, nhưng config sinh ra sai. Ràng buộc số dòng bên dưới chặn đúng ca đó.
awk '{sub(/\r$/,"")} /location ~ \^\/api\/\(/{co=1} co{print} co && /^    }$/{exit}' \
    "$TPL" > /tmp/block.conf

[ -s /tmp/block.conf ] || { echo "TRICH KHOI THAT BAI — khong khop dau khoi"; exit 3; }
DONG=$(wc -l < /tmp/block.conf)
[ "$DONG" -le 40 ] || { echo "TRICH KHOI HONG: $DONG dong (mong <=40)"; exit 3; }
echo "--- khoi freeze trich duoc ($DONG dong):"
head -1 /tmp/block.conf | cut -c1-220

cat > /tmp/nginx.conf.tpl <<'CONF'
events { worker_connections 64; }
http {
    limit_req_zone $binary_remote_addr zone=api:10m rate=1000r/s;
    upstream backend { server 127.0.0.1:8081; }

    server {
        listen 8081;
        location / { add_header Content-Type text/plain always; return 200 "UPSTREAM_OK"; }
    }

    server {
        listen 8080;
__BLOCK__
        location / { proxy_pass http://backend; }
    }
}
CONF

awk '/__BLOCK__/{while((getline l < "/tmp/block.conf")>0) print l; next} {print}' \
    /tmp/nginx.conf.tpl > /tmp/nginx.conf.rendered.tpl

# CHỈ thay NGINX_ADMISSION_FROZEN. `envsubst` trần sẽ nuốt luôn $request_method,
# $freeze_check, $binary_remote_addr — config thành vô nghĩa mà `nginx -t` vẫn
# sạch và reload vẫn rc=0.
envsubst '${NGINX_ADMISSION_FROZEN}' < /tmp/nginx.conf.rendered.tpl > /etc/nginx/nginx.conf
grep -q 'request_method' /etc/nginx/nginx.conf || { echo "envsubst DA NUOT bien nginx"; exit 3; }

nginx -t -c /etc/nginx/nginx.conf
nginx -c /etc/nginx/nginx.conf
sleep 1

ma() { curl -s -o /tmp/body -w '%{http_code}' -X "$1" "http://127.0.0.1:8080$2"; }

echo "=== NGINX_ADMISSION_FROZEN=$NGINX_ADMISSION_FROZEN ==="
LOI=0
kiem() {   # $1 method   $2 path   $3 mong: 503 | khac503
    C=$(ma "$1" "$2")
    if [ "$3" = "503" ]; then
        if [ "$C" = "503" ] && grep -q NGINX_ADMISSION_FROZEN /tmp/body; then
            R=DAT
        else
            R="LECH(mong 503+code)"
        fi
    else
        if [ "$C" != "503" ]; then R=DAT; else R="LECH(mong khac 503)"; fi
    fi
    printf '  %-6s %-62s -> %-3s %s\n' "$1" "$2" "$C" "$R"
    [ "$R" = "DAT" ] || LOI=$((LOI + 1))
}

if [ "$NGINX_ADMISSION_FROZEN" = "true" ]; then G=503; else G=khac503; fi

# --- đường GHI tuyển sinh: v2 (phần từng thoát) ---
kiem POST   /api/v2/admissions/1/choices                             "$G"
kiem POST   /api/v2/admissions/1/admin-rollback                      "$G"
kiem PATCH  /api/v2/admissions/1/priority-objects/DT01/verify        "$G"
kiem POST   /api/v2/admin/rounds/1/extend                            "$G"
kiem POST   /api/v2/admin/years/2026/rounds                          "$G"
kiem POST   /api/v2/admin/priority-config/clone                      "$G"
kiem PATCH  /api/v2/admin/admission-paths/1/quota                    "$G"
kiem POST   /api/v2/admin/admission-backfill-exceptions/bulk-resolve "$G"
kiem POST   /api/v2/admin/path-subject-group-configs/1/items         "$G"
kiem DELETE /api/v2/admin/path-subject-group-configs/1/items/2       "$G"
# --- v1: không được hồi quy ---
kiem POST   /api/admissions                                          "$G"
kiem POST   /api/admission-config/methods                            "$G"
# --- ĐỌC luôn phải đi tiếp, kể cả khi đóng băng ---
kiem GET    /api/v2/admissions/1/choices                             khac503
kiem GET    /api/admissions                                          khac503
# --- ngoài miền tuyển sinh: không được chạm ---
kiem POST   /api/leads                                               khac503
kiem POST   /api/v2/admin/casbin/reload                              khac503
kiem PATCH  /api/v2/admin/system-config/x                            khac503
kiem POST   /api/v2/admin/vn-school/schools                          khac503
# --- khớp theo ĐOẠN path, không phải startswith ---
kiem POST   /api/admissionsfoo                                       khac503
kiem POST   /api/v2/admin/roundsfoo                                  khac503

echo "=== LECH: $LOI ==="
nginx -s stop 2>/dev/null || true
[ "$LOI" -eq 0 ]
