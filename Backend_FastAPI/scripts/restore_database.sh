#!/bin/bash
# ============================================
# Database Restore Script
# ============================================
# Restore PostgreSQL database from backup
# Usage: ./restore_database.sh <backup_file> [database_name]
# ============================================

set -e  # Exit on error

# Check arguments
if [ $# -lt 1 ]; then
    echo "❌ Usage: $0 <backup_file> [database_name]"
    echo ""
    echo "Examples:"
    echo "  $0 backups/qlts_dev_20250107_143000.dump"
    echo "  $0 backups/qlts_dev_20250107_143000.sql"
    echo "  $0 backups/qlts_dev_20250107_143000.dump qlts_dev"
    exit 1
fi

BACKUP_FILE="$1"
DEFAULT_DB_NAME="qlts_dev"
DB_NAME="${2:-$DEFAULT_DB_NAME}"
DB_HOST="${DB_HOST:-192.168.88.125}"
DB_USER="${DB_USER:-postgres}"
DB_PASSWORD="${DB_PASSWORD:-admin}"

# Verify backup file exists
if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "============================================"
echo "🔄 Database Restore Script"
echo "============================================"
echo "Backup file: $BACKUP_FILE"
echo "Database: $DB_NAME"
echo "Host: $DB_HOST"
echo "User: $DB_USER"
echo ""

# Warning
echo "⚠️  WARNING: This will OVERWRITE the database '$DB_NAME'!"
echo "⚠️  All existing data will be REPLACED with backup data!"
echo ""
read -p "Are you sure you want to continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "❌ Restore cancelled."
    exit 0
fi

# Export password
export PGPASSWORD="$DB_PASSWORD"

# Detect file type
FILE_EXT="${BACKUP_FILE##*.}"

echo ""
echo "🔍 Detecting file format..."

if [ "$FILE_EXT" = "dump" ]; then
    echo "   Format: PostgreSQL custom dump"
    RESTORE_CMD="pg_restore -h $DB_HOST -U $DB_USER -d $DB_NAME --clean --if-exists"
elif [ "$FILE_EXT" = "sql" ]; then
    echo "   Format: SQL script"
    RESTORE_CMD="psql -h $DB_HOST -U $DB_USER -d $DB_NAME"
else
    echo "❌ Unknown file format: $FILE_EXT"
    echo "   Supported: .dump, .sql"
    exit 1
fi

# Create backup of current database before restore
echo ""
echo "📦 Creating backup of current database..."
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SAFETY_BACKUP="$PROJECT_ROOT/backups/pre_restore_${DB_NAME}_${TIMESTAMP}.dump"
mkdir -p "$PROJECT_ROOT/backups"

if pg_dump -h "$DB_HOST" -U "$DB_USER" -Fc "$DB_NAME" > "$SAFETY_BACKUP" 2>/dev/null; then
    echo "✅ Safety backup created: $SAFETY_BACKUP"
else
    echo "⚠️  Safety backup failed (database might be empty)"
fi

# Restore database
echo ""
echo "🔄 Restoring database..."
echo "   This may take several minutes..."

if [ "$FILE_EXT" = "dump" ]; then
    if $RESTORE_CMD "$BACKUP_FILE"; then
        echo "✅ Restore completed successfully!"
    else
        echo "❌ Restore failed!"
        echo ""
        echo "Try restoring without --clean option:"
        echo "  pg_restore -h $DB_HOST -U $DB_USER -d $DB_NAME $BACKUP_FILE"
        exit 1
    fi
elif [ "$FILE_EXT" = "sql" ]; then
    if $RESTORE_CMD < "$BACKUP_FILE"; then
        echo "✅ Restore completed successfully!"
    else
        echo "❌ Restore failed!"
        exit 1
    fi
fi

# Verify restore
echo ""
echo "🔍 Verifying restore..."

TABLE_COUNT=$(psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';" 2>/dev/null | tr -d ' ')

if [ -n "$TABLE_COUNT" ] && [ "$TABLE_COUNT" -gt 0 ]; then
    echo "✅ Verification passed: $TABLE_COUNT tables found"
else
    echo "⚠️  Verification warning: No tables found"
fi

# Show table list
echo ""
echo "📋 Tables in database:"
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "\dt" | grep "public |" || echo "   (none)"

# Reset sequences (important for auto-increment IDs)
echo ""
echo "🔄 Resetting sequences..."
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" << 'EOF'
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        BEGIN
            EXECUTE 'SELECT setval(pg_get_serial_sequence(''' || r.tablename || ''', ''id''), COALESCE(MAX(id), 1)) FROM ' || r.tablename;
        EXCEPTION WHEN OTHERS THEN
            -- Skip tables without id column
        END;
    END LOOP;
END $$;
EOF
echo "✅ Sequences reset"

# Summary
echo ""
echo "============================================"
echo "✅ Restore completed!"
echo "============================================"
echo "Database: $DB_NAME"
echo "From: $BACKUP_FILE"
echo "Tables: $TABLE_COUNT"
echo ""
echo "Safety backup: $SAFETY_BACKUP"
echo "(If something went wrong, you can restore from this)"
echo "============================================"
