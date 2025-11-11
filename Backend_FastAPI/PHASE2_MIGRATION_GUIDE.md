# Phase 2 Migration Guide: 3-Tier Architecture

## ⚠️  **CRITICAL: READ BEFORE MIGRATING**

This migration refactors the major/program structure from 2-tier to 3-tier architecture. It is a **BREAKING CHANGE** that:

- Creates 3 new tables
- Migrates all existing data
- Drops 2 old tables
- Updates Lead references

**Estimated downtime:** 1-5 minutes (depends on data size)

---

## 📋 **Pre-Migration Checklist**

### ✅ **Step 1: Backup Database (MANDATORY)**

**PostgreSQL Backup:**
```bash
# Full database backup
pg_dump -h localhost -U your_user -d qlts_db -F c -b -v -f "backup_before_phase2_$(date +%Y%m%d_%H%M%S).backup"

# Or SQL format (easier to restore specific tables)
pg_dump -h localhost -U your_user -d qlts_db > "backup_before_phase2_$(date +%Y%m%d_%H%M%S).sql"
```

**Docker PostgreSQL Backup:**
```bash
docker exec -t postgres_container pg_dump -U your_user qlts_db > "backup_before_phase2_$(date +%Y%m%d_%H%M%S).sql"
```

**Verify backup:**
```bash
# Check file size (should not be 0)
ls -lh backup_before_phase2_*.sql

# Count lines (should match your data)
wc -l backup_before_phase2_*.sql
```

---

### ✅ **Step 2: Check Current State**

Run these SQL queries to understand your current data:

```sql
-- Count existing majors
SELECT COUNT(*) as total_majors FROM major;

-- Count academic info records
SELECT COUNT(*) as total_academic_info FROM major_academic_info;

-- Count leads with major assignments
SELECT COUNT(*) as leads_with_major FROM lead WHERE major_id IS NOT NULL;

-- Check for orphaned data
SELECT COUNT(*) as orphaned_academic_info
FROM major_academic_info mai
WHERE NOT EXISTS (SELECT 1 FROM major m WHERE m.id = mai.major_id);
```

**Record these numbers** - you'll compare them after migration.

---

### ✅ **Step 3: Stop Application** (Recommended)

```bash
# Stop FastAPI backend
pkill -f "uvicorn"

# Or if using systemd
sudo systemctl stop qlts-api

# Or if using docker-compose
docker-compose stop backend
```

---

## 🚀 **Running the Migration**

### **Option A: Production (Recommended)**

```bash
cd /home/user/QLTS/Backend_FastAPI

# Run migration
alembic upgrade head

# Monitor output - should show:
# [STEP 1/9] Creating major_program table...
# [STEP 2/9] Creating program_offering table...
# ...
# ✅ MIGRATION COMPLETED SUCCESSFULLY!
```

### **Option B: Dry Run (Test First)**

```bash
# Generate SQL without executing
alembic upgrade head --sql > migration_preview.sql

# Review the SQL
less migration_preview.sql

# If satisfied, run actual migration
alembic upgrade head
```

---

## ✅ **Post-Migration Verification**

### **Step 1: Run Verification SQL Script**

```bash
# Connect to PostgreSQL and run verification
psql -h localhost -U your_user -d qlts_db -f verify_phase2_migration.sql

# Or with Docker
docker exec -i postgres_container psql -U your_user -d qlts_db < verify_phase2_migration.sql
```

**Expected output:**
```
✓ Test 1: Checking new tables exist...
   ✓ major_program table exists
   ✓ program_offering table exists
   ✓ offering_academic_info table exists

✓ Test 2: Checking old tables removed...
   ✓ major table dropped
   ✓ major_academic_info table dropped

✓ Test 5: Checking for orphaned records...
   ✓ No orphaned program_offerings
   ✓ No orphaned offering_academic_info
   ✓ No orphaned lead assignments

...

✅ VERIFICATION COMPLETE!
```

### **Step 2: Compare Counts**

```sql
-- New structure counts (should match old counts)
SELECT
    (SELECT COUNT(*) FROM major_program) as programs,
    (SELECT COUNT(*) FROM program_offering) as offerings,
    (SELECT COUNT(*) FROM offering_academic_info) as academic_info,
    (SELECT COUNT(*) FROM lead WHERE offering_id IS NOT NULL) as lead_assignments;
```

**Expected:**
- `programs` = your old `total_majors`
- `offerings` = your old `total_majors` (1 default offering per major)
- `academic_info` = your old `total_academic_info`
- `lead_assignments` = your old `leads_with_major`

### **Step 3: Test API Endpoints**

```bash
# Start application
# (Restart your backend service)

# Test organization units endpoint (should include major_programs)
curl http://localhost:8000/api/organization-units

# Check response structure - should have:
# - major_programs (NEW)
# - major_programs[].offerings (NEW)
# - major_programs[].offerings[].academic_info_history (NEW)
```

---

## 🔄 **Rollback Procedure (If Needed)**

### ⚠️  **WARNING: Data Loss Risk**

Rolling back will:
- Restore old 2-tier structure
- Merge multiple offerings back into single major
- **Lose custom offering types** (only "Chính quy" preserved)
- **Lose offering-specific data**

**Only rollback immediately after migration if critical issues found!**

### **Step 1: Rollback Migration**

```bash
cd /home/user/QLTS/Backend_FastAPI

# Rollback one version
alembic downgrade -1

# Monitor output - should show:
# [STEP 1/7] Recreating major table...
# [STEP 2/7] Recreating major_academic_info table...
# ...
# ✅ ROLLBACK COMPLETED!
```

### **Step 2: Verify Rollback**

```sql
-- Check old tables exist
SELECT
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'major') as major_exists,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'major_academic_info') as academic_info_exists,
    EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'major_program') as program_exists;

-- Expected: major_exists=true, academic_info_exists=true, program_exists=false
```

### **Step 3: Restore from Backup (Nuclear Option)**

If rollback fails or data is corrupted:

```bash
# Stop application
sudo systemctl stop qlts-api

# Drop database
psql -h localhost -U postgres -c "DROP DATABASE qlts_db;"
psql -h localhost -U postgres -c "CREATE DATABASE qlts_db OWNER your_user;"

# Restore from backup
psql -h localhost -U your_user -d qlts_db < backup_before_phase2_YYYYMMDD_HHMMSS.sql

# Or custom format
pg_restore -h localhost -U your_user -d qlts_db backup_before_phase2_YYYYMMDD_HHMMSS.backup

# Verify restoration
psql -h localhost -U your_user -d qlts_db -c "SELECT COUNT(*) FROM major;"
```

---

## 🐛 **Troubleshooting**

### **Issue 1: Migration hangs or times out**

**Cause:** Large dataset or slow database connection

**Solution:**
```sql
-- Check for long-running queries
SELECT pid, now() - query_start AS duration, query
FROM pg_stat_activity
WHERE state != 'idle' AND query NOT LIKE '%pg_stat_activity%'
ORDER BY duration DESC;

-- If needed, increase timeout
-- In alembic/env.py, add: context.configure(connect_args={'options': '-c statement_timeout=600000'})
```

### **Issue 2: Foreign key constraint violations**

**Cause:** Data inconsistency or orphaned records

**Solution:**
```sql
-- Find orphaned major_academic_info before migration
SELECT * FROM major_academic_info mai
WHERE NOT EXISTS (SELECT 1 FROM major m WHERE m.id = mai.major_id);

-- Clean up orphans
DELETE FROM major_academic_info
WHERE major_id NOT IN (SELECT id FROM major);
```

### **Issue 3: Duplicate code violations**

**Cause:** Multiple majors with same code

**Solution:**
```sql
-- Find duplicates
SELECT code, COUNT(*)
FROM major
GROUP BY code
HAVING COUNT(*) > 1;

-- Fix duplicates (add suffix)
UPDATE major SET code = code || '_DUP' || id
WHERE id IN (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY code ORDER BY id) as rn
        FROM major
    ) sub WHERE rn > 1
);
```

### **Issue 4: Verification shows orphaned records**

**Cause:** Migration logic error or interrupted migration

**Solution:**
```bash
# Rollback immediately
alembic downgrade -1

# Review migration logs
# Fix data issues
# Re-run migration
alembic upgrade head
```

---

## 📊 **Migration Statistics (For Reference)**

Based on average QLTS deployment:

| Metric | Estimated Time |
|--------|---------------|
| 10 majors | < 1 second |
| 100 majors | 1-2 seconds |
| 1,000 majors | 5-10 seconds |
| 10,000 academic info records | 10-30 seconds |
| 100,000 leads | 1-2 minutes |

**Total downtime:** Usually **< 5 minutes** for typical deployment.

---

## ✅ **Post-Migration Tasks**

After successful migration and verification:

1. **Update Models in Code** (if not already done):
   - Use `MajorProgram`, `ProgramOffering`, `OfferingAcademicInfo` models
   - Update imports in services and routers

2. **Update API Documentation**:
   - API endpoints now return 3-tier structure
   - Update Swagger/OpenAPI docs

3. **Notify Team**:
   - Migration completed
   - New schema in place
   - Old `major` and `major_academic_info` tables removed

4. **Monitor Performance**:
   ```sql
   -- Check query performance
   SELECT schemaname, tablename, n_tup_ins, n_tup_upd, n_tup_del
   FROM pg_stat_user_tables
   WHERE tablename IN ('major_program', 'program_offering', 'offering_academic_info');
   ```

5. **Archive Backup**:
   ```bash
   # Keep backup for at least 30 days
   mv backup_before_phase2_*.sql /backups/archive/
   ```

---

## 📞 **Support**

If you encounter issues:

1. **Check migration logs** for error messages
2. **Run verification script** to identify issues
3. **Rollback if critical** (within 1 hour of migration)
4. **Restore from backup** if rollback fails

**DO NOT:**
- ❌ Run migration on production without backup
- ❌ Skip verification steps
- ❌ Modify migration script manually (unless you know what you're doing)
- ❌ Run migration during peak hours

---

## 🎯 **Success Criteria**

Migration is successful when:

- ✅ All verification tests pass
- ✅ No orphaned records found
- ✅ API endpoints return correct 3-tier structure
- ✅ Lead assignments preserved
- ✅ Academic info data intact
- ✅ Application running without errors

---

**Last Updated:** 2025-11-11
**Migration Version:** k6l7m8n9o0p1
**Estimated Reading Time:** 10 minutes
