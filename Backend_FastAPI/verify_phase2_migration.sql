-- ============================================================================
-- Phase 2 Migration Verification Script
-- ============================================================================
-- This script verifies the 3-tier architecture migration completed successfully.
-- Run this after migration: alembic upgrade head
--
-- Expected Results:
-- - All counts should match or be consistent
-- - All integrity checks should return 0 (zero orphaned records)
-- - No NULL values where they shouldn't be
-- ============================================================================

\echo ''
\echo '============================================================================'
\echo 'PHASE 2 MIGRATION VERIFICATION'
\echo '============================================================================'
\echo ''

-- ============================================================================
-- TEST 1: Table Existence
-- ============================================================================
\echo '✓ Test 1: Checking new tables exist...'
SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'major_program')
        THEN '   ✓ major_program table exists'
        ELSE '   ✗ major_program table MISSING'
    END as result
UNION ALL
SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'program_offering')
        THEN '   ✓ program_offering table exists'
        ELSE '   ✗ program_offering table MISSING'
    END
UNION ALL
SELECT
    CASE
        WHEN EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'offering_academic_info')
        THEN '   ✓ offering_academic_info table exists'
        ELSE '   ✗ offering_academic_info table MISSING'
    END;

\echo ''

-- ============================================================================
-- TEST 2: Old Tables Removed
-- ============================================================================
\echo '✓ Test 2: Checking old tables removed...'
SELECT
    CASE
        WHEN NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'major')
        THEN '   ✓ major table dropped'
        ELSE '   ✗ major table STILL EXISTS (migration incomplete)'
    END as result
UNION ALL
SELECT
    CASE
        WHEN NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'major_academic_info')
        THEN '   ✓ major_academic_info table dropped'
        ELSE '   ✗ major_academic_info table STILL EXISTS (migration incomplete)'
    END;

\echo ''

-- ============================================================================
-- TEST 3: Record Counts
-- ============================================================================
\echo '✓ Test 3: Checking record counts...'
SELECT
    'major_program' as table_name,
    COUNT(*) as record_count
FROM major_program
UNION ALL
SELECT
    'program_offering',
    COUNT(*)
FROM program_offering
UNION ALL
SELECT
    'offering_academic_info',
    COUNT(*)
FROM offering_academic_info
UNION ALL
SELECT
    'lead (with offering_id)',
    COUNT(*)
FROM lead
WHERE offering_id IS NOT NULL;

\echo ''

-- ============================================================================
-- TEST 4: Lead Column Migration
-- ============================================================================
\echo '✓ Test 4: Verifying lead.offering_id...'

-- Check that major_id column no longer exists
SELECT
    CASE
        WHEN NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'lead' AND column_name = 'major_id'
        )
        THEN '   ✓ lead.major_id column dropped'
        ELSE '   ✗ lead.major_id column STILL EXISTS'
    END as result;

-- Check that offering_id column exists
SELECT
    CASE
        WHEN EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'lead' AND column_name = 'offering_id'
        )
        THEN '   ✓ lead.offering_id column exists'
        ELSE '   ✗ lead.offering_id column MISSING'
    END;

-- Count leads with NULL offering_id (should be acceptable for some cases)
WITH null_offerings AS (
    SELECT COUNT(*) as cnt FROM lead WHERE offering_id IS NULL
)
SELECT
    '   ℹ ' || cnt || ' leads have NULL offering_id (this is OK for unassigned leads)'
FROM null_offerings;

\echo ''

-- ============================================================================
-- TEST 5: Data Integrity - Orphaned Records
-- ============================================================================
\echo '✓ Test 5: Checking for orphaned records (should all be 0)...'

-- Orphaned program_offering (program_id not in major_program)
WITH orphaned_offerings AS (
    SELECT COUNT(*) as cnt
    FROM program_offering po
    WHERE NOT EXISTS (
        SELECT 1 FROM major_program mp WHERE mp.id = po.program_id
    )
)
SELECT
    CASE
        WHEN cnt = 0 THEN '   ✓ No orphaned program_offerings'
        ELSE '   ✗ Found ' || cnt || ' orphaned program_offerings'
    END as result
FROM orphaned_offerings;

-- Orphaned offering_academic_info (offering_id not in program_offering)
WITH orphaned_academic AS (
    SELECT COUNT(*) as cnt
    FROM offering_academic_info oai
    WHERE NOT EXISTS (
        SELECT 1 FROM program_offering po WHERE po.id = oai.offering_id
    )
)
SELECT
    CASE
        WHEN cnt = 0 THEN '   ✓ No orphaned offering_academic_info'
        ELSE '   ✗ Found ' || cnt || ' orphaned offering_academic_info'
    END
FROM orphaned_academic;

-- Orphaned leads (offering_id not in program_offering, excluding NULL)
WITH orphaned_leads AS (
    SELECT COUNT(*) as cnt
    FROM lead l
    WHERE l.offering_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM program_offering po WHERE po.id = l.offering_id
    )
)
SELECT
    CASE
        WHEN cnt = 0 THEN '   ✓ No orphaned lead assignments'
        ELSE '   ✗ Found ' || cnt || ' orphaned lead assignments'
    END
FROM orphaned_leads;

\echo ''

-- ============================================================================
-- TEST 6: Foreign Key Constraints
-- ============================================================================
\echo '✓ Test 6: Checking foreign key constraints exist...'

SELECT
    tc.constraint_name,
    '   ✓ ' || tc.table_name || '.' || kcu.column_name ||
    ' → ' || ccu.table_name || '.' || ccu.column_name as fk_info
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
    ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_name IN ('major_program', 'program_offering', 'offering_academic_info')
ORDER BY tc.table_name, tc.constraint_name;

\echo ''

-- ============================================================================
-- TEST 7: Unique Constraints
-- ============================================================================
\echo '✓ Test 7: Checking unique constraints...'

SELECT
    '   ✓ ' || tc.table_name || ': ' || tc.constraint_name as constraint_info
FROM information_schema.table_constraints tc
WHERE tc.constraint_type = 'UNIQUE'
  AND tc.table_name IN ('major_program', 'program_offering', 'offering_academic_info')
ORDER BY tc.table_name;

\echo ''

-- ============================================================================
-- TEST 8: Sample Data Inspection
-- ============================================================================
\echo '✓ Test 8: Sample data from each table...'
\echo ''
\echo '--- major_program (first 3 records) ---'
SELECT id, name, code, degree_level, is_active, unit_id
FROM major_program
ORDER BY id
LIMIT 3;

\echo ''
\echo '--- program_offering (first 3 records) ---'
SELECT id, offering_type, program_id, duration_semesters, is_active
FROM program_offering
ORDER BY id
LIMIT 3;

\echo ''
\echo '--- offering_academic_info (first 3 records) ---'
SELECT id, offering_id, academic_year, tuition_fee_per_year, annual_admission_quota, is_published
FROM offering_academic_info
ORDER BY id
LIMIT 3;

\echo ''

-- ============================================================================
-- TEST 9: Hierarchical Relationship Check
-- ============================================================================
\echo '✓ Test 9: Verifying 3-tier hierarchy (sample)...'
\echo ''
SELECT
    mp.id as program_id,
    mp.name as program_name,
    mp.code as program_code,
    po.id as offering_id,
    po.offering_type,
    COUNT(oai.id) as academic_info_count,
    COUNT(l.id) as lead_count
FROM major_program mp
LEFT JOIN program_offering po ON po.program_id = mp.id
LEFT JOIN offering_academic_info oai ON oai.offering_id = po.id
LEFT JOIN lead l ON l.offering_id = po.id
GROUP BY mp.id, mp.name, mp.code, po.id, po.offering_type
ORDER BY mp.id, po.id
LIMIT 5;

\echo ''

-- ============================================================================
-- TEST 10: Migration Completeness Summary
-- ============================================================================
\echo '============================================================================'
\echo 'MIGRATION SUMMARY'
\echo '============================================================================'
\echo ''

SELECT
    'Total Programs (Cấp 1):' as metric,
    COUNT(*)::text as value
FROM major_program
UNION ALL
SELECT
    'Total Offerings (Cấp 2):',
    COUNT(*)::text
FROM program_offering
UNION ALL
SELECT
    'Total Academic Info (Cấp 3):',
    COUNT(*)::text
FROM offering_academic_info
UNION ALL
SELECT
    'Avg Offerings per Program:',
    ROUND(AVG(offering_count), 2)::text
FROM (
    SELECT mp.id, COUNT(po.id) as offering_count
    FROM major_program mp
    LEFT JOIN program_offering po ON po.program_id = mp.id
    GROUP BY mp.id
) sub
UNION ALL
SELECT
    'Leads with Offering Assignment:',
    COUNT(*)::text
FROM lead
WHERE offering_id IS NOT NULL
UNION ALL
SELECT
    'Programs with Academic Info:',
    COUNT(DISTINCT po.program_id)::text
FROM program_offering po
JOIN offering_academic_info oai ON oai.offering_id = po.id;

\echo ''
\echo '============================================================================'
\echo '✅ VERIFICATION COMPLETE!'
\echo '============================================================================'
\echo ''
\echo 'Review the results above. All integrity checks should show 0 orphaned records.'
\echo 'If any issues are found, consider running: alembic downgrade -1'
\echo ''
