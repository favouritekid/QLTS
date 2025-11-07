#!/usr/bin/env python3
"""
Export Database Data to CSV
Export all tables to CSV files for backup/migration

Usage:
    python export_data.py                    # Export all tables
    python export_data.py --tables user lead # Export specific tables
    python export_data.py --output exports/  # Custom output directory
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


async def get_all_tables():
    """Get list of all tables."""
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename != 'alembic_version' ORDER BY tablename"
            )
        )
        return [row[0] for row in result.fetchall()]


async def export_table(table_name: str, output_dir: Path):
    """Export single table to CSV."""
    try:
        async with engine.connect() as conn:
            # Get data
            result = await conn.execute(text(f"SELECT * FROM {table_name}"))
            rows = result.fetchall()
            columns = result.keys()

            if not rows:
                print(f"   ⚠️  {table_name}: No data (skipping)")
                return 0

            # Convert to DataFrame
            df = pd.DataFrame(rows, columns=columns)

            # Convert datetime to string
            for col in df.columns:
                if df[col].dtype == "datetime64[ns, UTC]" or df[col].dtype == "datetime64[ns]":
                    df[col] = df[col].astype(str)

            # Save to CSV
            csv_file = output_dir / f"{table_name}.csv"
            df.to_csv(csv_file, index=False, encoding="utf-8")

            print(f"   ✅ {table_name}: {len(rows)} rows → {csv_file.name}")
            return len(rows)

    except Exception as e:
        print(f"   ❌ {table_name}: Error - {e}")
        return -1


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Export database tables to CSV")
    parser.add_argument(
        "--tables",
        nargs="+",
        help="Specific tables to export (default: all)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="exports",
        help="Output directory (default: exports)",
    )
    args = parser.parse_args()

    # Create output directory
    output_dir = project_root / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("📦 Database Export Script")
    print("=" * 60)
    print(f"Output directory: {output_dir}")
    print()

    # Get tables to export
    if args.tables:
        tables = args.tables
        print(f"Exporting {len(tables)} specified tables...")
    else:
        tables = await get_all_tables()
        print(f"Exporting all {len(tables)} tables...")

    print()

    # Export each table
    total_rows = 0
    success_count = 0
    error_count = 0

    for table in tables:
        row_count = await export_table(table, output_dir)
        if row_count >= 0:
            total_rows += row_count
            success_count += 1
        else:
            error_count += 1

    # Create manifest file
    manifest_file = output_dir / "export_manifest.txt"
    with open(manifest_file, "w") as f:
        f.write(f"Export Date: {datetime.now().isoformat()}\n")
        f.write(f"Total Tables: {len(tables)}\n")
        f.write(f"Successful: {success_count}\n")
        f.write(f"Errors: {error_count}\n")
        f.write(f"Total Rows: {total_rows}\n")
        f.write("\nExported Tables:\n")
        for table in tables:
            csv_file = output_dir / f"{table}.csv"
            if csv_file.exists():
                size = csv_file.stat().st_size
                f.write(f"  - {table}.csv ({size} bytes)\n")

    # Summary
    print()
    print("=" * 60)
    print("✅ Export Complete")
    print("=" * 60)
    print(f"Tables exported: {success_count}/{len(tables)}")
    print(f"Total rows: {total_rows:,}")
    if error_count > 0:
        print(f"Errors: {error_count}")
    print(f"\nFiles saved to: {output_dir}")
    print(f"Manifest: {manifest_file}")
    print()
    print("To import data:")
    print(f"  python scripts/import_data.py --input {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n❌ Export cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Export failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
