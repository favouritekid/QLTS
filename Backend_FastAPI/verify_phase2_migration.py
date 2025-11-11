#!/usr/bin/env python3
"""
Phase 2 Migration Verification Script (Python Version)
======================================================

This script verifies the 3-tier architecture migration completed successfully.
Run this after migration: alembic upgrade head

Usage:
    python verify_phase2_migration.py
"""
import asyncio
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Import settings to get DB URL
try:
    from app.core.config import settings
    DB_URL = settings.DATABASE_URL
except:
    print("⚠️  Could not import settings. Using default DB URL.")
    DB_URL = "postgresql+asyncpg://postgres:postgres@localhost/qlts_dev"

print("=" * 80)
print("PHASE 2 MIGRATION VERIFICATION (Python)")
print("=" * 80)
print(f"\nConnecting to: {DB_URL.split('@')[1] if '@' in DB_URL else 'database'}")
print()


async def run_verification():
    """Run all verification tests"""

    # Create async engine
    engine = create_async_engine(DB_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as session:
            # ================================================================
            # TEST 1: Table Existence
            # ================================================================
            print("✓ Test 1: Checking new tables exist...")

            result = await session.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('major_program', 'program_offering', 'offering_academic_info')
                ORDER BY table_name
            """))
            tables = [row[0] for row in result.fetchall()]

            for expected in ['major_program', 'offering_academic_info', 'program_offering']:
                if expected in tables:
                    print(f"   ✓ {expected} table exists")
                else:
                    print(f"   ✗ {expected} table MISSING")
                    return False

            print()

            # ================================================================
            # TEST 2: Old Tables Removed
            # ================================================================
            print("✓ Test 2: Checking old tables removed...")

            result = await session.execute(text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('major', 'major_academic_info')
            """))
            old_tables = [row[0] for row in result.fetchall()]

            if 'major' not in old_tables:
                print("   ✓ major table dropped")
            else:
                print("   ✗ major table STILL EXISTS")
                return False

            if 'major_academic_info' not in old_tables:
                print("   ✓ major_academic_info table dropped")
            else:
                print("   ✗ major_academic_info table STILL EXISTS")
                return False

            print()

            # ================================================================
            # TEST 3: Record Counts
            # ================================================================
            print("✓ Test 3: Checking record counts...")

            counts = {}
            for table in ['major_program', 'program_offering', 'offering_academic_info']:
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = result.scalar()
                print(f"   {table}: {counts[table]} records")

            result = await session.execute(text("SELECT COUNT(*) FROM lead WHERE offering_id IS NOT NULL"))
            counts['lead_with_offering'] = result.scalar()
            print(f"   lead (with offering_id): {counts['lead_with_offering']} records")

            print()

            # ================================================================
            # TEST 4: Lead Column Migration
            # ================================================================
            print("✓ Test 4: Verifying lead.offering_id...")

            # Check major_id column removed
            result = await session.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_name = 'lead' AND column_name = 'major_id'
            """))
            if result.scalar() == 0:
                print("   ✓ lead.major_id column dropped")
            else:
                print("   ✗ lead.major_id column STILL EXISTS")
                return False

            # Check offering_id column exists
            result = await session.execute(text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_name = 'lead' AND column_name = 'offering_id'
            """))
            if result.scalar() > 0:
                print("   ✓ lead.offering_id column exists")
            else:
                print("   ✗ lead.offering_id column MISSING")
                return False

            # Check NULL count
            result = await session.execute(text("SELECT COUNT(*) FROM lead WHERE offering_id IS NULL"))
            null_count = result.scalar()
            print(f"   ℹ {null_count} leads have NULL offering_id (OK for unassigned leads)")

            print()

            # ================================================================
            # TEST 5: Data Integrity - Orphaned Records
            # ================================================================
            print("✓ Test 5: Checking for orphaned records (should all be 0)...")

            # Orphaned program_offering
            result = await session.execute(text("""
                SELECT COUNT(*) FROM program_offering po
                WHERE NOT EXISTS (SELECT 1 FROM major_program mp WHERE mp.id = po.program_id)
            """))
            orphaned_offerings = result.scalar()
            if orphaned_offerings == 0:
                print("   ✓ No orphaned program_offerings")
            else:
                print(f"   ✗ Found {orphaned_offerings} orphaned program_offerings")
                return False

            # Orphaned offering_academic_info
            result = await session.execute(text("""
                SELECT COUNT(*) FROM offering_academic_info oai
                WHERE NOT EXISTS (SELECT 1 FROM program_offering po WHERE po.id = oai.offering_id)
            """))
            orphaned_academic = result.scalar()
            if orphaned_academic == 0:
                print("   ✓ No orphaned offering_academic_info")
            else:
                print(f"   ✗ Found {orphaned_academic} orphaned offering_academic_info")
                return False

            # Orphaned leads
            result = await session.execute(text("""
                SELECT COUNT(*) FROM lead l
                WHERE l.offering_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM program_offering po WHERE po.id = l.offering_id)
            """))
            orphaned_leads = result.scalar()
            if orphaned_leads == 0:
                print("   ✓ No orphaned lead assignments")
            else:
                print(f"   ✗ Found {orphaned_leads} orphaned lead assignments")
                return False

            print()

            # ================================================================
            # TEST 6: Sample Data Inspection
            # ================================================================
            print("✓ Test 6: Sample data from each table...")
            print()

            print("--- major_program (first 3 records) ---")
            result = await session.execute(text("""
                SELECT id, name, code, degree_level, is_active
                FROM major_program
                ORDER BY id
                LIMIT 3
            """))
            for row in result.fetchall():
                print(f"   ID={row[0]}, Name={row[1]}, Code={row[2]}, Level={row[3]}, Active={row[4]}")

            print()
            print("--- program_offering (first 3 records) ---")
            result = await session.execute(text("""
                SELECT id, offering_type, program_id, is_active
                FROM program_offering
                ORDER BY id
                LIMIT 3
            """))
            for row in result.fetchall():
                print(f"   ID={row[0]}, Type={row[1]}, ProgramID={row[2]}, Active={row[3]}")

            print()
            print("--- offering_academic_info (first 3 records) ---")
            result = await session.execute(text("""
                SELECT id, offering_id, academic_year, tuition_fee_per_year, annual_admission_quota
                FROM offering_academic_info
                ORDER BY id
                LIMIT 3
            """))
            for row in result.fetchall():
                print(f"   ID={row[0]}, OfferingID={row[1]}, Year={row[2]}, Tuition={row[3]}, Quota={row[4]}")

            print()

            # ================================================================
            # TEST 7: Hierarchical Relationship Check
            # ================================================================
            print("✓ Test 7: Verifying 3-tier hierarchy (sample)...")
            print()

            result = await session.execute(text("""
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
            """))

            print(f"{'PID':<5} {'Program':<30} {'Code':<10} {'OID':<5} {'Offering':<15} {'Info':<6} {'Leads':<6}")
            print("-" * 80)
            for row in result.fetchall():
                print(f"{row[0]:<5} {row[1][:28]:<30} {row[2]:<10} {row[3] or 'N/A':<5} {row[4] or 'N/A':<15} {row[5]:<6} {row[6]:<6}")

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

            result = await session.execute(text("""
                SELECT ROUND(AVG(offering_count), 2)
                FROM (
                    SELECT mp.id, COUNT(po.id) as offering_count
                    FROM major_program mp
                    LEFT JOIN program_offering po ON po.program_id = mp.id
                    GROUP BY mp.id
                ) sub
            """))
            avg_offerings = result.scalar()
            print(f"Avg Offerings per Program:           {avg_offerings}")

            print()
            print("=" * 80)
            print("✅ ALL VERIFICATION TESTS PASSED!")
            print("=" * 80)
            print()
            print("Migration completed successfully. The 3-tier architecture is in place.")
            print()

            return True

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        result = asyncio.run(run_verification())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\nVerification interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        sys.exit(1)
