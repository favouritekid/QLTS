#!/usr/bin/env bash
# =============================================================================
# QLTS Daily Database Backup
# =============================================================================
# Cron setup: 0 3 * * * /path/to/qlts/scripts/backup-cron.sh >> /var/log/qlts-backup.log 2>&1
# Retention: 14 days
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS=14
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

cd "$PROJECT_DIR"

# Load environment
set -a
source .env.production
set +a

mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting database backup..."

# Dump database
BACKUP_FILE="$BACKUP_DIR/qlts_${TIMESTAMP}.sql.gz"
docker compose exec -T postgres pg_dump \
    -U "${POSTGRES_USER:-qlts}" \
    "${POSTGRES_DB:-qlts_production}" \
    | gzip > "$BACKUP_FILE"

BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "[$(date)] Backup saved: $BACKUP_FILE ($BACKUP_SIZE)"

# Cleanup old backups
DELETED=$(find "$BACKUP_DIR" -name "qlts_*.sql.gz" -mtime +$RETENTION_DAYS -delete -print | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "[$(date)] Cleaned up $DELETED backup(s) older than $RETENTION_DAYS days"
fi

echo "[$(date)] Backup completed successfully"
