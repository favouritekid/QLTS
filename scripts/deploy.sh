#!/usr/bin/env bash
# =============================================================================
# QLTS Production Deployment Script
# =============================================================================
# Usage: ./scripts/deploy.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

cd "$PROJECT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# =============================================================================
# Step 1: Pre-flight checks
# =============================================================================
log "Step 1/8: Pre-flight checks..."

command -v docker >/dev/null 2>&1 || error "Docker is not installed"
command -v docker compose >/dev/null 2>&1 || error "Docker Compose is not installed"

if [ ! -f .env.production ]; then
    error ".env.production not found. Copy from .env.production.example and fill in values."
fi

if grep -v '^\s*#' .env.production | grep -q "CHANGE_ME"; then
    error ".env.production contains CHANGE_ME placeholders. Update all values before deploying."
fi

# Load env vars for template substitution
set -a
source .env.production
set +a

if [ -z "${DOMAIN:-}" ]; then
    error "DOMAIN is not set in .env.production"
fi

log "Pre-flight checks passed"

# =============================================================================
# Step 2: Pull latest code
# =============================================================================
log "Step 2/8: Pulling latest code..."
git pull origin main

# =============================================================================
# Step 3: Process Nginx template
# =============================================================================
log "Step 3/8: Processing Nginx template..."

# T0-3 admission cold-cutover freeze: default to "false" when unset so the
# template only blocks when ops explicitly set NGINX_ADMISSION_FROZEN=true
# (paired with backend ADMISSION_FROZEN=true per RUNBOOK §6.1).
export NGINX_ADMISSION_FROZEN="${NGINX_ADMISSION_FROZEN:-false}"

envsubst '${DOMAIN} ${NGINX_ADMISSION_FROZEN}' < nginx/conf.d/default.conf.template > nginx/conf.d/default.conf
log "Nginx config generated (domain=$DOMAIN, admission_frozen=$NGINX_ADMISSION_FROZEN)"

# =============================================================================
# Step 4: Build Docker images
# =============================================================================
log "Step 4/8: Building Docker images..."
docker compose -f docker-compose.yml --profile production --env-file .env.production build --parallel

# =============================================================================
# Step 5: Database backup (before migration)
# =============================================================================
log "Step 5/8: Backing up database..."
mkdir -p "$BACKUP_DIR"

if docker compose -f docker-compose.yml --env-file .env.production exec -T postgres pg_isready -U "${POSTGRES_USER:-qlts}" >/dev/null 2>&1; then
    docker compose -f docker-compose.yml --env-file .env.production exec -T postgres pg_dump \
        -U "${POSTGRES_USER:-qlts}" \
        "${POSTGRES_DB:-qlts_production}" \
        > "$BACKUP_DIR/pre_deploy_${TIMESTAMP}.sql" 2>/dev/null \
        && log "Database backup saved: pre_deploy_${TIMESTAMP}.sql" \
        || warn "Database backup failed (may be first deploy)"
else
    warn "PostgreSQL not running, skipping backup (first deploy?)"
fi

# =============================================================================
# Step 6: Start infrastructure & run migrations
# =============================================================================
log "Step 6/8: Starting infrastructure & running migrations..."

# Start infra services first
docker compose -f docker-compose.yml --profile production --env-file .env.production up -d postgres redis
log "Waiting for PostgreSQL to be healthy..."
sleep 5

# Run Alembic migrations
docker compose -f docker-compose.yml --profile production --env-file .env.production run --rm backend \
    alembic upgrade head \
    && log "Migrations completed successfully" \
    || {
        warn "Migration failed! Rolling back..."
        if [ -f "$BACKUP_DIR/pre_deploy_${TIMESTAMP}.sql" ]; then
            docker compose -f docker-compose.yml --env-file .env.production exec -T postgres psql \
                -U "${POSTGRES_USER:-qlts}" \
                "${POSTGRES_DB:-qlts_production}" \
                < "$BACKUP_DIR/pre_deploy_${TIMESTAMP}.sql"
            error "Migration failed. Database restored from backup."
        fi
        error "Migration failed. No backup available to restore."
    }

# =============================================================================
# Step 7: Pre-deploy checks (Casbin policies)
# =============================================================================
log "Step 7/8: Running pre-deploy checks..."

docker compose -f docker-compose.yml --profile production --env-file .env.production run --rm backend \
    python scripts/pre_deploy_check.py \
    && log "Pre-deploy checks passed" \
    || warn "Pre-deploy checks had warnings (non-fatal)"

# =============================================================================
# Step 8: Rolling restart
# =============================================================================
log "Step 8/8: Rolling restart..."

# Start backend + celery
docker compose -f docker-compose.yml --profile production --env-file .env.production up -d \
    backend celery-worker celery-beat

log "Waiting for backend to be healthy..."
timeout=60
while [ $timeout -gt 0 ]; do
    if docker compose -f docker-compose.yml ps backend | grep -q "healthy"; then
        break
    fi
    sleep 2
    timeout=$((timeout - 2))
done

if [ $timeout -le 0 ]; then
    error "Backend failed to become healthy within 60s. Check logs: docker compose logs backend"
fi

# Start frontend + nginx + certbot
docker compose -f docker-compose.yml --profile production --env-file .env.production up -d \
    frontend nginx certbot

log "Waiting for frontend to be healthy..."
timeout=60
while [ $timeout -gt 0 ]; do
    if docker compose -f docker-compose.yml ps frontend | grep -q "healthy"; then
        break
    fi
    sleep 2
    timeout=$((timeout - 2))
done

# =============================================================================
# Done
# =============================================================================
log "========================================="
log "Deployment completed successfully!"
log "========================================="
log "Domain: https://$DOMAIN"
log "Health: https://$DOMAIN/health"
log ""
log "Useful commands:"
log "  docker compose -f docker-compose.yml --profile production logs -f       # Follow all logs"
log "  docker compose -f docker-compose.yml --profile production ps            # Service status"
log "  docker compose -f docker-compose.yml --profile production logs backend   # Backend logs"
