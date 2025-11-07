# 🛠️ Database Management Scripts

Collection of scripts for database backup, restore, and recovery.

---

## 📋 Quick Reference

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `backup_database.sh` | Backup PostgreSQL database | Daily/before major changes |
| `restore_database.sh` | Restore from backup | After data loss |
| `rebuild_database.py` | Recreate structure from migrations | After accidental table deletion |
| `export_data.py` | Export data to CSV | Before risky operations |
| `import_data.py` | Import data from CSV | After recovery/migration |

---

## 🔧 Scripts Overview

### 1. backup_database.sh

**Automatic PostgreSQL backup with compression**

```bash
# Basic usage (backup qlts_dev)
./scripts/backup_database.sh

# Backup specific database
./scripts/backup_database.sh qlts_prod

# With custom credentials
DB_HOST=localhost DB_USER=postgres DB_PASSWORD=secret ./scripts/backup_database.sh
```

**Features:**
- Creates compressed `.dump` file (pg_restore compatible)
- Creates human-readable `.sql` file
- Creates schema-only backup
- Auto-cleanup (keeps last 7 days)
- Safe, non-destructive

**Output:**
```
backups/
├── qlts_dev_20250107_143000.dump    ← Main backup
├── qlts_dev_20250107_143000.sql     ← SQL version
└── schema_20250107_143000.sql       ← Structure only
```

**Automation:**
```bash
# Run daily at 2 AM
crontab -e
# Add:
0 2 * * * /mnt/d/QLTS/Backend_FastAPI/scripts/backup_database.sh >> /tmp/backup.log 2>&1
```

---

### 2. restore_database.sh

**Restore database from backup file**

```bash
# Restore from .dump file
./scripts/restore_database.sh backups/qlts_dev_20250107_143000.dump

# Restore from .sql file
./scripts/restore_database.sh backups/qlts_dev_20250107_143000.sql

# Restore to specific database
./scripts/restore_database.sh backups/backup.dump qlts_dev
```

**Features:**
- Auto-detect file format (.dump or .sql)
- Creates safety backup before restore
- Resets auto-increment sequences
- Verifies restore success
- Interactive confirmation

⚠️ **WARNING**: This OVERWRITES the target database!

---

### 3. rebuild_database.py

**Recreate database structure from Alembic migrations**

```bash
# Interactive mode (with confirmations)
python scripts/rebuild_database.py

# Auto-confirm (skip prompts)
python scripts/rebuild_database.py --auto-confirm

# Specific database
DATABASE_URL="postgresql://..." python scripts/rebuild_database.py
```

**Features:**
- Drops all existing tables
- Runs all Alembic migrations
- Verifies final structure
- Shows statistics

**Use cases:**
- Tests accidentally dropped production tables
- Database schema corruption
- Fresh setup from migrations

---

### 4. export_data.py

**Export database tables to CSV files**

```bash
# Export all tables
python scripts/export_data.py

# Export specific tables
python scripts/export_data.py --tables user lead consultation

# Custom output directory
python scripts/export_data.py --output backups/csv_$(date +%Y%m%d)
```

**Features:**
- Exports to CSV (human-readable, git-friendly)
- Handles datetime conversions
- Creates manifest file
- Safe, read-only operation

**Output:**
```
exports/
├── user.csv
├── lead.csv
├── consultation.csv
├── ...
└── export_manifest.txt    ← Metadata
```

**Use cases:**
- Pre-deployment backup
- Data migration
- Analysis/reporting
- Version control for seed data

---

### 5. import_data.py

**Import data from CSV files back to database**

```bash
# Import all tables (from exports/)
python scripts/import_data.py

# Import from custom directory
python scripts/import_data.py --input backups/csv_20250107

# Import specific tables only
python scripts/import_data.py --tables user lead

# Skip tables that already have data
python scripts/import_data.py --skip-existing
```

**Features:**
- Respects foreign key dependencies (correct order)
- Handles NULL values
- Resets auto-increment sequences
- Shows detailed progress
- Interactive confirmation

**Import Order:**
```
1. organization_unit    (no dependencies)
2. pipeline_stage
3. consultation_status
4. user
5. user_session         (depends on user)
6. lead                 (depends on user, organization_unit)
7. consultation         (depends on lead, user)
... (maintains referential integrity)
```

---

## 📖 Common Workflows

### Daily Backup Routine

```bash
# 1. Automated daily backup (via cron)
0 2 * * * /mnt/d/QLTS/Backend_FastAPI/scripts/backup_database.sh

# 2. Weekly CSV export (for version control)
0 3 * * 0 cd /mnt/d/QLTS/Backend_FastAPI && python scripts/export_data.py --output exports/weekly_$(date +%Y%m%d)
```

### Recovery After Tests Deleted Production DB

**Scenario**: Tests ran on production and deleted all tables!

**Solution 1: Restore from backup** (if you have one)
```bash
# Find latest backup
ls -lt backups/*.dump | head -1

# Restore
./scripts/restore_database.sh backups/qlts_dev_20250107_143000.dump
```

**Solution 2: Rebuild structure + Import data** (if you have CSV exports)
```bash
# 1. Recreate tables from migrations
python scripts/rebuild_database.py --auto-confirm

# 2. Import data from CSV
python scripts/import_data.py --input exports/
```

**Solution 3: Rebuild structure only** (fresh start)
```bash
# Recreate empty database
python scripts/rebuild_database.py --auto-confirm

# Manually recreate seed data via application
```

---

### Pre-deployment Safety

```bash
# Before deploying major changes:

# 1. Full database backup
./scripts/backup_database.sh

# 2. Export to CSV (for version control)
python scripts/export_data.py --output backups/pre_deploy_$(date +%Y%m%d)

# 3. Commit CSV exports to git (if sensitive data removed)
git add exports/
git commit -m "chore: Database snapshot before deployment"

# 4. Deploy with confidence!
```

---

### Database Migration

```bash
# Migrate from old server to new server:

# 1. On OLD server: Export data
python scripts/export_data.py --output migration_data
tar -czf migration_data.tar.gz migration_data/

# 2. Transfer to NEW server
scp migration_data.tar.gz user@newserver:/tmp/

# 3. On NEW server: Setup database
alembic upgrade head

# 4. Import data
tar -xzf /tmp/migration_data.tar.gz
python scripts/import_data.py --input migration_data
```

---

## ⚙️ Configuration

### Environment Variables

All scripts respect these environment variables:

```bash
# Database connection
export DB_HOST="192.168.88.125"
export DB_USER="postgres"
export DB_PASSWORD="admin"
export DATABASE_URL="postgresql+asyncpg://postgres:admin@192.168.88.125:5432/qlts_dev"

# Application environment
export APP_ENV="development"  # or "production", "test"
```

### Script Permissions

```bash
# Make shell scripts executable
chmod +x scripts/*.sh

# Python scripts can run directly
python scripts/rebuild_database.py
```

---

## 🛡️ Safety Features

### Built-in Protections

1. **backup_database.sh**
   - ✅ Non-destructive (read-only)
   - ✅ Creates timestamped backups
   - ✅ Auto-cleanup old backups

2. **restore_database.sh**
   - ⚠️ Requires explicit confirmation
   - ✅ Creates safety backup before restore
   - ✅ Verifies restore success

3. **rebuild_database.py**
   - ⚠️ Requires explicit "yes" confirmation
   - ⚠️ Drops ALL tables (cannot undo!)
   - ✅ Shows current tables before dropping
   - ✅ Verifies final structure

4. **export_data.py**
   - ✅ Non-destructive (read-only)
   - ✅ Creates manifest for tracking

5. **import_data.py**
   - ⚠️ Requires explicit confirmation
   - ✅ Respects foreign key order
   - ✅ Resets sequences
   - ✅ Can skip existing data

---

## 🚨 Troubleshooting

### "Connection refused" errors

```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Check network connectivity
telnet 192.168.88.125 5432

# Verify credentials
psql -h 192.168.88.125 -U postgres -d qlts_dev
```

### "Permission denied" errors

```bash
# Check pg_hba.conf allows remote connections
sudo cat /etc/postgresql/*/main/pg_hba.conf

# Should have line like:
host    all             all             192.168.0.0/16          md5
```

### Alembic migration errors

```bash
# Check current version
alembic current

# Force to specific version
alembic stamp head

# Retry upgrade
alembic upgrade head
```

### Import fails with foreign key errors

```bash
# Import respects order, but if custom tables exist:

# 1. Disable constraints temporarily
psql -h $DB_HOST -U $DB_USER -d $DB_NAME << EOF
SET session_replication_role = 'replica';
-- Run your imports
SET session_replication_role = 'origin';
EOF

# 2. Or drop/recreate foreign keys
```

---

## 📚 Related Documentation

- `../DATABASE_RECOVERY_GUIDE.md` - Complete recovery procedures
- `../PYTEST_DOTENV_CONFLICT.md` - Why tests deleted production DB
- `../SETUP_TEST_DATABASE.md` - Prevent future accidents
- `../alembic/README` - Alembic migration guide

---

## ✅ Best Practices

1. **Backup BEFORE risky operations**
   ```bash
   ./scripts/backup_database.sh
   # Now safe to proceed
   ```

2. **Test restores periodically**
   ```bash
   # Verify backups actually work!
   ./scripts/restore_database.sh backups/latest.dump
   ```

3. **Keep CSV exports in git** (after removing sensitive data)
   ```bash
   python scripts/export_data.py
   # Remove sensitive data from CSV files
   git add exports/
   git commit -m "chore: Update database snapshot"
   ```

4. **Automate daily backups**
   ```bash
   # Add to crontab
   0 2 * * * /path/to/backup_database.sh
   ```

5. **Document backup locations**
   - Keep backups on different disk/server
   - Test recovery process regularly
   - Know how to restore quickly

---

## 🎯 Summary

| Goal | Command |
|------|---------|
| Daily backup | `./scripts/backup_database.sh` |
| Restore data | `./scripts/restore_database.sh backups/file.dump` |
| Rebuild structure | `python scripts/rebuild_database.py` |
| Export for safekeeping | `python scripts/export_data.py` |
| Import after recovery | `python scripts/import_data.py` |

**Remember**: Backups are useless if you can't restore from them. Test your recovery process! 🔥
