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
# Step 1: Create temporary Nginx config (HTTP only)
# =============================================================================
log "Step 1: Creating temporary HTTP-only Nginx config..."

mkdir -p nginx/conf.d

cat > nginx/conf.d/default.conf << EOF
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

# =============================================================================
# Step 2: Start Nginx (HTTP only)
# =============================================================================
log "Step 2: Starting Nginx (HTTP only)..."
docker compose -f docker-compose.yml --profile production --env-file .env.production up -d nginx
sleep 3

# =============================================================================
# Step 3: Obtain certificate via ACME challenge
# =============================================================================
log "Step 3: Requesting SSL certificate from Let's Encrypt..."

docker compose -f docker-compose.yml --profile production --env-file .env.production run --rm certbot \
    certbot certonly \
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
# Step 4: Generate full Nginx config with SSL
# =============================================================================
log "Step 4: Generating full Nginx config with SSL..."
envsubst '${DOMAIN}' < nginx/conf.d/default.conf.template > nginx/conf.d/default.conf

# =============================================================================
# Step 5: Reload Nginx with SSL
# =============================================================================
log "Step 5: Reloading Nginx with SSL..."
docker compose -f docker-compose.yml --profile production exec nginx nginx -s reload

log "========================================="
log "SSL setup completed successfully!"
log "========================================="
log "Certificate: /etc/letsencrypt/live/$DOMAIN/"
log "Auto-renewal: handled by certbot container (every 12h)"
log ""
log "Test: curl -v https://$DOMAIN/health"
