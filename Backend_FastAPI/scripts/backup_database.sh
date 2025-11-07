#!/bin/bash
# ============================================
# Database Backup Script
# ============================================
# Automatically backup PostgreSQL database
# Usage: ./backup_database.sh [database_name]
# ============================================

set -e  # Exit on error

# Configuration
DEFAULT_DB_NAME="qlts_dev"
DB_NAME="${1:-$DEFAULT_DB_NAME}"
DB_HOST="${DB_HOST:-192.168.88.125}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-admin}"

# Backup directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_ROOT/backups"
mkdir -p "$BACKUP_DIR"

# Timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.dump"
BACKUP_SQL="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql"

echo "============================================"
echo "🔄 Database Backup Script"
echo "============================================"
echo "Database: $DB_NAME"
echo "Host: $DB_HOST"
echo "User: $DB_USER"
echo "Backup dir: $BACKUP_DIR"
echo ""

# Export password
export PGPASSWORD="$DB_PASSWORD"

# Backup with custom format (compressed, allows selective restore)
echo "📦 Creating backup (custom format)..."
if pg_dump -h "$DB_HOST" -U "$DB_USER" -Fc "$DB_NAME" > "$BACKUP_FILE"; then
    echo "✅ Backup created: $BACKUP_FILE"
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "   Size: $BACKUP_SIZE"
else
    echo "❌ Backup failed!"
    exit 1
fi

# Also create SQL backup (human-readable, easy to review)
echo ""
echo "📝 Creating SQL backup (plain text)..."
if pg_dump -h "$DB_HOST" -U "$DB_USER" "$DB_NAME" > "$BACKUP_SQL"; then
    echo "✅ SQL backup created: $BACKUP_SQL"
    SQL_SIZE=$(du -h "$BACKUP_SQL" | cut -f1)
    echo "   Size: $SQL_SIZE"
else
    echo "⚠️  SQL backup failed (continuing...)"
fi

# Create schema-only backup
echo ""
echo "🗂️  Creating schema-only backup..."
SCHEMA_FILE="$BACKUP_DIR/schema_${TIMESTAMP}.sql"
if pg_dump -h "$DB_HOST" -U "$DB_USER" -s "$DB_NAME" > "$SCHEMA_FILE"; then
    echo "✅ Schema backup created: $SCHEMA_FILE"
else
    echo "⚠️  Schema backup failed (continuing...)"
fi

# Cleanup old backups (keep last 7 days)
echo ""
echo "🧹 Cleaning up old backups (keeping last 7 days)..."
find "$BACKUP_DIR" -name "${DB_NAME}_*.dump" -mtime +7 -delete 2>/dev/null || true
find "$BACKUP_DIR" -name "${DB_NAME}_*.sql" -mtime +7 -delete 2>/dev/null || true
REMAINING=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.dump" | wc -l)
echo "   Remaining backups: $REMAINING"

# Summary
echo ""
echo "============================================"
echo "✅ Backup completed successfully!"
echo "============================================"
echo "Files created:"
echo "  - $BACKUP_FILE"
echo "  - $BACKUP_SQL"
echo "  - $SCHEMA_FILE"
echo ""
echo "To restore:"
echo "  pg_restore -h $DB_HOST -U $DB_USER -d $DB_NAME $BACKUP_FILE"
echo "  or"
echo "  psql -h $DB_HOST -U $DB_USER -d $DB_NAME < $BACKUP_SQL"
echo "============================================"
