#!/usr/bin/env python3
"""
Import Database Data from CSV
Import CSV files back into database

Usage:
    python import_data.py                    # Import from exports/
    python import_data.py --input backups/   # Import from custom directory
    python import_data.py --tables user lead # Import specific tables only
"""

import asyncio
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

os.environ["APP_ENV"] = os.getenv("APP_ENV", "development")

from app.database import engine
from sqlalchemy import text
import pandas as pd


# Import order (respecting foreign key constraints)
IMPORT_ORDER = [
    "organization_unit",
    "pipeline_stage",
    "consultation_status",
    "skill_requirement_rule",
    "user",
    "user_session",
    "major",
    "lead_scoring_config",
    "officer_assignment_config",
    "lead",
    "consultation",
    "crm_interaction",
    "lead_status_history",
    "assignment_log",
    "application",
]


async def table_exists(table_name: str) -> bool:
    """Check if table exists in database."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = :table_name)"
                ),
                {"table_name": table_name},
            )
            return result.scalar()
    except Exception:
        return False


async def get_row_count(table_name: str) -> int:
    """Get current row count in table."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            return result.scalar()
    except Exception:
        return 0


async def import_table(table_name: str, csv_file: Path, skip_existing: bool = False):
    """Import single table from CSV."""
    try:
        # Check if table exists
        if not await table_exists(table_name):
            print(f"   ⚠️  {table_name}: Table doesn't exist (skipping)")
            return 0

        # Check existing data
        existing_count = await get_row_count(table_name)
        if existing_count > 0 and skip_existing:
            print(
                f"   ⏭️  {table_name}: Already has {existing_count} rows (skipping)"
            )
            return 0

        # Read CSV
        df = pd.read_csv(csv_file)

        if len(df) == 0:
            print(f"   ⚠️  {table_name}: CSV is empty (skipping)")
            return 0

        # Convert to list of dicts
        records = df.to_dict("records")

        # Prepare INSERT statement
        columns = list(records[0].keys())
        placeholders = ", ".join([f":{col}" for col in columns])
        insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"

        # Insert all records
        inserted = 0
        failed = 0
        async with engine.begin() as conn:
            for record in records:
                try:
                    # Convert NaN to None
                    for key, value in record.items():
                        if pd.isna(value):
                            record[key] = None

                    await conn.execute(text(insert_sql), record)
                    inserted += 1
                except Exception as e:
                    failed += 1
                    if failed <= 5:  # Show first 5 errors
                        print(f"      Error inserting row: {e}")

        if failed > 0:
            print(
                f"   ⚠️  {table_name}: {inserted} rows inserted, {failed} failed"
            )
        else:
            print(f"   ✅ {table_name}: {inserted} rows inserted")

        return inserted

    except Exception as e:
        print(f"   ❌ {table_name}: Error - {e}")
        return -1


async def reset_sequences():
    """Reset auto-increment sequences after import."""
    print("\n🔄 Resetting sequences...")
    try:
        async with engine.begin() as conn:
            # Get all tables
            result = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename != 'alembic_version'"
                )
            )
            tables = [row[0] for row in result.fetchall()]

            reset_count = 0
            for table in tables:
                try:
                    # Try to reset sequence for 'id' column
                    await conn.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1)) FROM {table}"
                        )
                    )
                    reset_count += 1
                except Exception:
                    # Skip tables without id column
                    pass

            print(f"   ✅ Reset {reset_count} sequences")

    except Exception as e:
        print(f"   ⚠️  Sequence reset failed: {e}")


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Import database tables from CSV")
    parser.add_argument(
        "--input",
        type=str,
        default="exports",
        help="Input directory (default: exports)",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        help="Specific tables to import (default: all in correct order)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip tables that already have data",
    )
    args = parser.parse_args()

    # Input directory
    input_dir = project_root / args.input
    if not input_dir.exists():
        print(f"❌ Input directory not found: {input_dir}")
        return 1

    print("=" * 60)
    print("📥 Database Import Script")
    print("=" * 60)
    print(f"Input directory: {input_dir}")
    print()

    # Get tables to import
    if args.tables:
        tables_to_import = args.tables
        print(f"Importing {len(tables_to_import)} specified tables...")
    else:
        # Use predefined order
        tables_to_import = [
            t for t in IMPORT_ORDER if (input_dir / f"{t}.csv").exists()
        ]
        print(
            f"Importing {len(tables_to_import)} tables in dependency order..."
        )

    if not tables_to_import:
        print("❌ No CSV files found to import")
        return 1

    print()

    # Warning
    print("⚠️  WARNING: This will INSERT data into existing tables!")
    if not args.skip_existing:
        print("⚠️  Existing data may cause conflicts!")
    print("\nType 'yes' to continue: ", end="")
    confirm = input().strip()

    if confirm.lower() != "yes":
        print("\n❌ Import cancelled")
        return 0

    print()

    # Import each table
    total_rows = 0
    success_count = 0
    error_count = 0

    for table in tables_to_import:
        csv_file = input_dir / f"{table}.csv"

        if not csv_file.exists():
            print(f"   ⚠️  {table}: CSV file not found (skipping)")
            continue

        row_count = await import_table(table, csv_file, args.skip_existing)

        if row_count >= 0:
            total_rows += row_count
            success_count += 1
        else:
            error_count += 1

    # Reset sequences
    await reset_sequences()

    # Summary
    print()
    print("=" * 60)
    print("✅ Import Complete")
    print("=" * 60)
    print(f"Tables imported: {success_count}/{len(tables_to_import)}")
    print(f"Total rows: {total_rows:,}")
    if error_count > 0:
        print(f"Errors: {error_count}")
    print()
    print("⚠️  Remember to:")
    print("  1. Verify data integrity")
    print("  2. Check foreign key relationships")
    print("  3. Test application functionality")
    print("=" * 60)


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code or 0)
    except KeyboardInterrupt:
        print("\n\n❌ Import cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Import failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
