#!/usr/bin/env python3
"""
Phase 2 Migration Verification Script (Simple - No Dependencies)
================================================================

This script verifies the 3-tier architecture migration using psycopg2.
No need for app settings or async libraries.

Usage:
    python verify_phase2_simple.py

You'll be prompted for database connection details.
"""
import sys

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("❌ psycopg2 not installed. Installing...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg2-binary"])
    import psycopg2
    from psycopg2.extras import RealDictCursor

print("=" * 80)
print("PHASE 2 MIGRATION VERIFICATION (Simple)")
print("=" * 80)
print()

# Get connection details
print("Enter database connection details:")
db_host = input("Host [localhost]: ").strip() or "localhost"
db_port = input("Port [5432]: ").strip() or "5432"
db_name = input("Database name [qlts_dev]: ").strip() or "qlts_dev"
db_user = input("Username [postgres]: ").strip() or "postgres"
db_pass = input("Password: ").strip()

print()
print(f"Connecting to: postgresql://{db_user}@{db_host}:{db_port}/{db_name}")
print()

try:
    # Connect to database
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        database=db_name,
        user=db_user,
        password=db_pass
    )
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    print("✓ Connected to database successfully!")
    print()

    # ================================================================
    # TEST 1: Table Existence
    # ================================================================
    print("✓ Test 1: Checking new tables exist...")

    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ('major_program', 'program_offering', 'offering_academic_info')
        ORDER BY table_name
    """)
    tables = [row['table_name'] for row in cursor.fetchall()]

    for expected in ['major_program', 'offering_academic_info', 'program_offering']:
        if expected in tables:
            print(f"   ✓ {expected} table exists")
        else:
            print(f"   ✗ {expected} table MISSING")
            sys.exit(1)

    print()

    # ================================================================
    # TEST 2: Old Tables Removed
    # ================================================================
    print("✓ Test 2: Checking old tables removed...")

    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name IN ('major', 'major_academic_info')
    """)
    old_tables = [row['table_name'] for row in cursor.fetchall()]

    if 'major' not in old_tables:
        print("   ✓ major table dropped")
    else:
        print("   ✗ major table STILL EXISTS")
        sys.exit(1)

    if 'major_academic_info' not in old_tables:
        print("   ✓ major_academic_info table dropped")
    else:
        print("   ✗ major_academic_info table STILL EXISTS")
        sys.exit(1)

    print()

    # ================================================================
    # TEST 3: Record Counts
    # ================================================================
    print("✓ Test 3: Checking record counts...")

    counts = {}
    for table in ['major_program', 'program_offering', 'offering_academic_info']:
        cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}")
        counts[table] = cursor.fetchone()['cnt']
        print(f"   {table}: {counts[table]} records")

    cursor.execute("SELECT COUNT(*) as cnt FROM lead WHERE offering_id IS NOT NULL")
    counts['lead_with_offering'] = cursor.fetchone()['cnt']
    print(f"   lead (with offering_id): {counts['lead_with_offering']} records")

    print()

    # ================================================================
    # TEST 4: Lead Column Migration
    # ================================================================
    print("✓ Test 4: Verifying lead.offering_id...")

    # Check major_id column removed
    cursor.execute("""
        SELECT COUNT(*) as cnt
        FROM information_schema.columns
        WHERE table_name = 'lead' AND column_name = 'major_id'
    """)
    if cursor.fetchone()['cnt'] == 0:
        print("   ✓ lead.major_id column dropped")
    else:
        print("   ✗ lead.major_id column STILL EXISTS")
        sys.exit(1)

    # Check offering_id column exists
    cursor.execute("""
        SELECT COUNT(*) as cnt
        FROM information_schema.columns
        WHERE table_name = 'lead' AND column_name = 'offering_id'
    """)
    if cursor.fetchone()['cnt'] > 0:
        print("   ✓ lead.offering_id column exists")
    else:
        print("   ✗ lead.offering_id column MISSING")
        sys.exit(1)

    # Check NULL count
    cursor.execute("SELECT COUNT(*) as cnt FROM lead WHERE offering_id IS NULL")
    null_count = cursor.fetchone()['cnt']
    print(f"   ℹ {null_count} leads have NULL offering_id (OK for unassigned leads)")

    print()

    # ================================================================
    # TEST 5: Data Integrity - Orphaned Records
    # ================================================================
    print("✓ Test 5: Checking for orphaned records (should all be 0)...")

    # Orphaned program_offering
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM program_offering po
        WHERE NOT EXISTS (SELECT 1 FROM major_program mp WHERE mp.id = po.program_id)
    """)
    orphaned_offerings = cursor.fetchone()['cnt']
    if orphaned_offerings == 0:
        print("   ✓ No orphaned program_offerings")
    else:
        print(f"   ✗ Found {orphaned_offerings} orphaned program_offerings")
        sys.exit(1)

    # Orphaned offering_academic_info
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM offering_academic_info oai
        WHERE NOT EXISTS (SELECT 1 FROM program_offering po WHERE po.id = oai.offering_id)
    """)
    orphaned_academic = cursor.fetchone()['cnt']
    if orphaned_academic == 0:
        print("   ✓ No orphaned offering_academic_info")
    else:
        print(f"   ✗ Found {orphaned_academic} orphaned offering_academic_info")
        sys.exit(1)

    # Orphaned leads
    cursor.execute("""
        SELECT COUNT(*) as cnt FROM lead l
        WHERE l.offering_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM program_offering po WHERE po.id = l.offering_id)
    """)
    orphaned_leads = cursor.fetchone()['cnt']
    if orphaned_leads == 0:
        print("   ✓ No orphaned lead assignments")
    else:
        print(f"   ✗ Found {orphaned_leads} orphaned lead assignments")
        sys.exit(1)

    print()

    # ================================================================
    # TEST 6: Sample Data Inspection
    # ================================================================
    print("✓ Test 6: Sample data from each table...")
    print()

    print("--- major_program (first 3 records) ---")
    cursor.execute("""
        SELECT id, name, code, degree_level, is_active
        FROM major_program
        ORDER BY id
        LIMIT 3
    """)
    for row in cursor.fetchall():
        print(f"   ID={row['id']}, Name={row['name']}, Code={row['code']}, Level={row['degree_level']}, Active={row['is_active']}")

    print()
    print("--- program_offering (first 3 records) ---")
    cursor.execute("""
        SELECT id, offering_type, program_id, is_active
        FROM program_offering
        ORDER BY id
        LIMIT 3
    """)
    for row in cursor.fetchall():
        print(f"   ID={row['id']}, Type={row['offering_type']}, ProgramID={row['program_id']}, Active={row['is_active']}")

    print()
    print("--- offering_academic_info (first 3 records) ---")
    cursor.execute("""
        SELECT id, offering_id, academic_year, tuition_fee_per_year, annual_admission_quota
        FROM offering_academic_info
        ORDER BY id
        LIMIT 3
    """)
    for row in cursor.fetchall():
        print(f"   ID={row['id']}, OfferingID={row['offering_id']}, Year={row['academic_year']}, Tuition={row['tuition_fee_per_year']}, Quota={row['annual_admission_quota']}")

    print()

    # ================================================================
    # TEST 7: Hierarchical Relationship Check
    # ================================================================
    print("✓ Test 7: Verifying 3-tier hierarchy (sample)...")
    print()

    cursor.execute("""
        SELECT
            mp.id as program_id,
            mp.name as program_name,
            mp.code as program_code,
            po.id as offering_id,
            po.offering_type,
            COUNT(DISTINCT oai.id) as academic_info_count,
            COUNT(DISTINCT l.id) as lead_count
        FROM major_program mp
        LEFT JOIN program_offering po ON po.program_id = mp.id
        LEFT JOIN offering_academic_info oai ON oai.offering_id = po.id
        LEFT JOIN lead l ON l.offering_id = po.id
        GROUP BY mp.id, mp.name, mp.code, po.id, po.offering_type
        ORDER BY mp.id, po.id
        LIMIT 5
    """)

    print(f"{'PID':<5} {'Program':<30} {'Code':<10} {'OID':<5} {'Offering':<15} {'Info':<6} {'Leads':<6}")
    print("-" * 80)
    for row in cursor.fetchall():
        print(f"{row['program_id']:<5} {row['program_name'][:28]:<30} {row['program_code']:<10} {row['offering_id'] or 'N/A':<5} {row['offering_type'] or 'N/A':<15} {row['academic_info_count']:<6} {row['lead_count']:<6}")

    print()

    # ================================================================
    # SUMMARY
    # ================================================================
    print("=" * 80)
    print("MIGRATION SUMMARY")
    print("=" * 80)
    print()

    print(f"Total Programs (Cấp 1):              {counts['major_program']}")
    print(f"Total Offerings (Cấp 2):             {counts['program_offering']}")
    print(f"Total Academic Info (Cấp 3):         {counts['offering_academic_info']}")
    print(f"Leads with Offering Assignment:      {counts['lead_with_offering']}")

    cursor.execute("""
        SELECT ROUND(AVG(offering_count), 2) as avg_offerings
        FROM (
            SELECT mp.id, COUNT(po.id) as offering_count
            FROM major_program mp
            LEFT JOIN program_offering po ON po.program_id = mp.id
            GROUP BY mp.id
        ) sub
    """)
    avg_offerings = cursor.fetchone()['avg_offerings']
    print(f"Avg Offerings per Program:           {avg_offerings}")

    print()
    print("=" * 80)
    print("✅ ALL VERIFICATION TESTS PASSED!")
    print("=" * 80)
    print()
    print("Migration completed successfully. The 3-tier architecture is in place.")
    print()

    cursor.close()
    conn.close()

    sys.exit(0)

except psycopg2.Error as e:
    print(f"\n❌ DATABASE ERROR: {e}")
    sys.exit(1)
except KeyboardInterrupt:
    print("\n\nVerification interrupted by user.")
    sys.exit(1)
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
