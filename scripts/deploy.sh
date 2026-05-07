#!/usr/bin/env bash
# =============================================================================
# QLTS Production Deployment Script
# =============================================================================
# Usage:
#   Routine deploy (default):
#     ./scripts/deploy.sh
#
#   Cold cutover (Phase 1 ship per RUNBOOK §7.2):
#     COLD_CUTOVER=true ./scripts/deploy.sh
#
# Cold cutover semantics (Phase1-Hotfix-4 / 2026-05-07):
#   * Skip Step 6 auto ``alembic upgrade head`` — operator runs manually
#     for stream-log + per-step checkpoint per RUNBOOK §7.2 T+1:30.
#   * Inject 3 entrypoint gate flags = false (RUN_MIGRATIONS_ON_STARTUP,
#     RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP, RUN_CASBIN_LOAD_ON_STARTUP)
#     so backend container starts without auto-running migration / sync /
#     Casbin policy load — those steps run manually post-deploy per
#     RUNBOOK §7.2 T+1:30 / T+3:00 / T+3:15 / T+3:30.
#   * Operator MUST follow RUNBOOK §7.2 sequence after this script
#     finishes Step 8 (container running but admin endpoints frozen via
#     ADMISSION_FROZEN + nginx block); script does NOT auto-execute the
#     manual cutover steps.
#   * Defensive default: only exact lowercase ``true`` triggers cutover
#     mode; any other value (TRUE/typo/unset) runs the routine flow.
#
# Routine deploy (COLD_CUTOVER unset or != "true"):
#   Flow unchanged from pre-Hotfix-4 — auto migration + sync + restart.
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
cutover() { echo -e "${YELLOW}[CUTOVER]${NC} $1"; }

# ============================================================================
# Cold cutover mode detection (Phase1-Hotfix-4 / 2026-05-07)
# ============================================================================
# Defensive parse — only exact lowercase ``true`` enables cutover mode.
# RUNBOOK §7.2 + memory ``solo-cutover-simple-data-import`` rationale.
COLD_CUTOVER="${COLD_CUTOVER:-false}"
if [ "${COLD_CUTOVER}" = "true" ]; then
    IS_CUTOVER=1
    cutover "============================================="
    cutover "COLD CUTOVER MODE ENABLED (per RUNBOOK §7.2)"
    cutover "============================================="
    cutover "* Step 6 auto-alembic: SKIP (operator runs manual)"
    cutover "* Step 8 container env: 3 cutover flags = false"
    cutover "* Operator MUST follow RUNBOOK §7.2 post-deploy:"
    cutover "  - T+1:30 manual ``alembic upgrade head``"
    cutover "  - T+3:00 manual backfill verify"
    cutover "  - T+3:15 restart backend (Casbin reload)"
    cutover "  - T+3:30 manual ``sync_notification_rules``"
    cutover "============================================="
else
    IS_CUTOVER=0
fi

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

# Start infra services first (always — postgres + redis needed both modes)
docker compose -f docker-compose.yml --profile production --env-file .env.production up -d postgres redis
log "Waiting for PostgreSQL to be healthy..."
sleep 5

if [ "${IS_CUTOVER}" -eq 1 ]; then
    # Cold cutover: skip auto-alembic. Operator runs ``alembic upgrade head``
    # manually post-deploy per RUNBOOK §7.2 T+1:30 to stream log per
    # migration step + checkpoint mid-flow. Auto-rollback path also
    # disabled here because cutover scenario uses snapshot-restore (not
    # in-place SQL replay) per RUNBOOK §8.1.
    cutover "Step 6: SKIP auto-alembic (cutover mode)"
    cutover "Operator runs manually post-deploy:"
    cutover "  docker compose --profile production exec backend alembic upgrade head"
else
    # Routine deploy: auto-migrate with built-in rollback on failure.
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
fi

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

if [ "${IS_CUTOVER}" -eq 1 ]; then
    # Cold cutover: inject 3 entrypoint gate flags = false so backend
    # container starts without auto-running migration / sync / Casbin
    # policy load. Operator runs those steps manually per RUNBOOK §7.2.
    # Defensive: explicit ``false`` lowercase per docker-entrypoint.sh
    # parse contract (any other value = run as usual).
    cutover "Step 8: Backend env: 3 cutover flags = false (operator manual sequence)"
    export RUN_MIGRATIONS_ON_STARTUP="false"
    export RUN_SYNC_NOTIFICATION_RULES_ON_STARTUP="false"
    export RUN_CASBIN_LOAD_ON_STARTUP="false"
fi

# Start backend + celery (env flags propagate via process env when cutover mode;
# routine mode = unset → entrypoint defaults to ``true`` = auto-run as before)
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
