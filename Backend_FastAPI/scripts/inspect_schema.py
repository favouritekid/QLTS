#!/usr/bin/env python3
"""
Schema Inspection Script

Inspects database schema for temporal architecture tables:
- user
- user_unit_assignment
- organization_unit
- major
- major_academic_info

Shows:
- Columns with types and constraints
- Foreign keys
- Indexes
- Constraints
"""
import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from app.database import AsyncSessionLocal


async def inspect_table_columns(db, table_name: str):
    """Get all columns for a table."""
    query = text("""
        SELECT
            column_name,
            data_type,
            character_maximum_length,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_name = :table_name
        ORDER BY ordinal_position
    """)

    result = await db.execute(query, {"table_name": table_name})
    return result.fetchall()


async def inspect_table_indexes(db, table_name: str):
    """Get all indexes for a table."""
    query = text("""
        SELECT
            i.relname as index_name,
            a.attname as column_name,
            ix.indisunique as is_unique,
            ix.indisprimary as is_primary
        FROM pg_class t
        JOIN pg_index ix ON t.oid = ix.indrelid
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
        WHERE t.relname = :table_name
        ORDER BY i.relname, a.attnum
    """)

    result = await db.execute(query, {"table_name": table_name})
    return result.fetchall()


async def inspect_table_foreign_keys(db, table_name: str):
    """Get all foreign keys for a table."""
    query = text("""
        SELECT
            tc.constraint_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name,
            rc.update_rule,
            rc.delete_rule
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        JOIN information_schema.referential_constraints AS rc
            ON tc.constraint_name = rc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_name = :table_name
        ORDER BY tc.constraint_name
    """)

    result = await db.execute(query, {"table_name": table_name})
    return result.fetchall()


async def inspect_table_constraints(db, table_name: str):
    """Get all constraints (unique, check) for a table."""
    query = text("""
        SELECT
            tc.constraint_name,
            tc.constraint_type,
            kcu.column_name
        FROM information_schema.table_constraints AS tc
        LEFT JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE tc.table_name = :table_name
            AND tc.constraint_type IN ('UNIQUE', 'CHECK')
        ORDER BY tc.constraint_name
    """)

    result = await db.execute(query, {"table_name": table_name})
    return result.fetchall()


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_table_info(table_name: str, columns, indexes, foreign_keys, constraints):
    """Print all information for a table."""
    print_section(f"TABLE: {table_name}")

    # Columns
    print("\n📋 COLUMNS:")
    print("-" * 80)
    print(f"{'Column Name':<30} {'Type':<20} {'Nullable':<10} {'Default'}")
    print("-" * 80)

    for col in columns:
        col_name = col[0]
        data_type = col[1]
        max_len = col[2]
        nullable = col[3]
        default = col[4] or ""

        # Format type with length
        if max_len:
            type_str = f"{data_type}({max_len})"
        else:
            type_str = data_type

        print(f"{col_name:<30} {type_str:<20} {nullable:<10} {default}")

    # Indexes
    print("\n🔍 INDEXES:")
    print("-" * 80)
    print(f"{'Index Name':<40} {'Column':<25} {'Unique':<8} {'Primary'}")
    print("-" * 80)

    if indexes:
        for idx in indexes:
            idx_name = idx[0]
            col_name = idx[1]
            is_unique = "Yes" if idx[2] else "No"
            is_primary = "Yes" if idx[3] else "No"
            print(f"{idx_name:<40} {col_name:<25} {is_unique:<8} {is_primary}")
    else:
        print("(No indexes)")

    # Foreign Keys
    print("\n🔗 FOREIGN KEYS:")
    print("-" * 80)
    print(f"{'Constraint Name':<35} {'Column':<20} {'References':<30} {'On Delete'}")
    print("-" * 80)

    if foreign_keys:
        for fk in foreign_keys:
            fk_name = fk[0]
            col_name = fk[1]
            ref_table = fk[2]
            ref_col = fk[3]
            delete_rule = fk[5]
            ref_str = f"{ref_table}.{ref_col}"
            print(f"{fk_name:<35} {col_name:<20} {ref_str:<30} {delete_rule}")
    else:
        print("(No foreign keys)")

    # Constraints
    print("\n⚡ CONSTRAINTS (UNIQUE, CHECK):")
    print("-" * 80)
    print(f"{'Constraint Name':<40} {'Type':<15} {'Column'}")
    print("-" * 80)

    if constraints:
        for con in constraints:
            con_name = con[0]
            con_type = con[1]
            col_name = con[2] or "N/A"
            print(f"{con_name:<40} {con_type:<15} {col_name}")
    else:
        print("(No unique/check constraints)")


async def main():
    """Main inspection workflow."""
    print("=" * 80)
    print("  DATABASE SCHEMA INSPECTION - Temporal Architecture")
    print("=" * 80)

    # Tables to inspect (in order of importance)
    tables = [
        "user",
        "user_unit_assignment",
        "organization_unit",
        "major",
        "major_academic_info"
    ]

    try:
        async with AsyncSessionLocal() as db:
            for table_name in tables:
                # Check if table exists
                check_query = text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_name = :table_name
                    )
                """)
                result = await db.execute(check_query, {"table_name": table_name})
                exists = result.scalar()

                if not exists:
                    print_section(f"TABLE: {table_name}")
                    print(f"\n⚠️  Table '{table_name}' does NOT exist in database")
                    continue

                # Get all information
                columns = await inspect_table_columns(db, table_name)
                indexes = await inspect_table_indexes(db, table_name)
                foreign_keys = await inspect_table_foreign_keys(db, table_name)
                constraints = await inspect_table_constraints(db, table_name)

                # Print
                print_table_info(table_name, columns, indexes, foreign_keys, constraints)

            # Summary
            print_section("SUMMARY")
            print("\n✅ Schema inspection completed!")
            print("\n📊 Expected schema for Phase 1:")
            print("  1. user table should have:")
            print("     - current_assignment_id column (INTEGER, nullable)")
            print("     - FK: current_assignment_id → user_unit_assignment.id")
            print("  2. user_unit_assignment table should exist with:")
            print("     - user_id, unit_id, role, start_date, end_date, is_active")
            print("     - Multiple indexes for performance")
            print("  3. organization_unit table should have:")
            print("     - is_active column (BOOLEAN)")
            print("  4. major table should have:")
            print("     - is_active column (BOOLEAN)")
            print("  5. major_academic_info table should exist with:")
            print("     - major_id, academic_year, tuition_fee_per_year, etc.")
            print("     - UNIQUE constraint on (major_id, academic_year)")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
