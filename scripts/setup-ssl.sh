#!/usr/bin/env bash
# =============================================================================
# QLTS SSL Certificate Setup (First-time)
# =============================================================================
# Usage: ./scripts/setup-ssl.sh
# Prerequisites: .env.production with DOMAIN set, DNS pointing to this server
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[SSL]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Load environment
if [ ! -f .env.production ]; then
    error ".env.production not found"
fi

set -a
source .env.production
set +a

if [ -z "${DOMAIN:-}" ]; then
    error "DOMAIN is not set in .env.production"
fi

EMAIL="${CERTBOT_EMAIL:-admin@$DOMAIN}"

log "Setting up SSL for: $DOMAIN"
log "Certbot email: $EMAIL"

# =============================================================================
# Step 1+2: Nginx BOOTSTRAP tạm — HTTP-only, chỉ để ACME challenge đi qua
# =============================================================================
# Vì sao không dùng service `nginx` của compose: từ 12-08-2026 template được
# render TRONG container bởi entrypoint, và bản render đầy đủ tham chiếu
# chứng thư CHƯA tồn tại ở bước này ⇒ nginx sẽ không khởi động được. Trước đây
# script ghi đè `nginx/conf.d/default.conf` trên host để lách; chính lối đó đẻ
# ra tệp ngoài git đã làm site chết khi cutover từ checkout sạch.
#
# Bootstrap nay là một container RIÊNG, dựng từ config tạm trong thư mục tạm,
# không đụng gì trong repo.
log "Step 1+2: Starting bootstrap Nginx (HTTP only, ACME challenge)..."

BOOTSTRAP_DIR=$(mktemp -d)
trap 'rm -rf "$BOOTSTRAP_DIR"; docker rm -f qlts-nginx-bootstrap >/dev/null 2>&1 || true' EXIT

cat > "$BOOTSTRAP_DIR/default.conf" << EOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        return 200 'Waiting for SSL setup...';
        add_header Content-Type text/plain;
    }
}
EOF

# Dùng chung volume webroot với certbot của compose để challenge tới được.
WEBROOT_VOL="$(basename "$(pwd)")_certbot_www"
docker volume inspect "$WEBROOT_VOL" >/dev/null 2>&1 || WEBROOT_VOL="qlts_certbot_www"

docker rm -f qlts-nginx-bootstrap >/dev/null 2>&1 || true
docker run -d --name qlts-nginx-bootstrap \
    -p 80:80 \
    -v "$BOOTSTRAP_DIR/default.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "$WEBROOT_VOL:/var/www/certbot" \
    nginx:1.27-alpine \
    || error "Không dựng được nginx bootstrap"
sleep 3

# Step 3: Obtain certificate via ACME challenge
# =============================================================================
log "Step 3: Requesting SSL certificate from Let's Encrypt..."

# `--no-deps` là BẮT BUỘC: `certbot` khai `depends_on: nginx`, nên thiếu nó
# Compose sẽ kéo nginx PRODUCTION lên — tranh cổng 80 với container
# bootstrap đang chạy, và bản thân nó cũng chưa khởi động được vì chứng
# thư còn chưa tồn tại.
docker compose -f docker-compose.yml --profile production --env-file .env.production run --rm --no-deps --entrypoint certbot certbot \
    certonly \
    --non-interactive \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" \
    -d "www.$DOMAIN" \
    || error "Certbot failed. Ensure DNS A record points to this server."

# =============================================================================
# Step 4+5: Bàn giao cho service nginx thật
# =============================================================================
log "Step 4: Stopping bootstrap Nginx..."
docker rm -f qlts-nginx-bootstrap >/dev/null 2>&1 || true

log "Step 5: Starting production Nginx (template render trong container)..."
# KHÔNG `envsubst` trên host và KHÔNG `nginx -s reload`: entrypoint của image
# render template lúc khởi động, nên phải để nó khởi động mới.
docker compose -f docker-compose.yml --profile production --env-file .env.production \
    up -d --no-deps --force-recreate nginx \
    || error "Không khởi động được nginx production"

log "Chờ nginx healthy..."
NGINX_OK=0
for _ in $(seq 1 24); do
    H=$(docker inspect -f '{{.State.Health.Status}}' \
        "$(docker compose -f docker-compose.yml --profile production \
            --env-file .env.production ps -q nginx)" 2>/dev/null || echo "")
    [ "$H" = "healthy" ] && { NGINX_OK=1; break; }
    [ "$H" = "unhealthy" ] && break
    sleep 5
done
[ "$NGINX_OK" -eq 1 ] || error "nginx không healthy sau khi cấp chứng thư (trạng thái: ${H:-khong-doc-duoc})"

log "========================================="
log "SSL setup completed successfully!"
log "========================================="
log "Certificate: /etc/letsencrypt/live/$DOMAIN/"
log "Auto-renewal: handled by certbot container (every 12h)"
log ""
log "Test: curl -v https://$DOMAIN/health"
