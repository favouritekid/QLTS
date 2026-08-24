#!/usr/bin/env python3
"""
Database Rebuild Script
Recreate database structure from Alembic migrations

Usage:
    python rebuild_database.py                    # Interactive mode
    python rebuild_database.py --auto-confirm     # Skip confirmations
    python rebuild_database.py --database qlts_dev  # Specific database
"""

import asyncio
import os
import sys
import argparse
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Set environment
os.environ["APP_ENV"] = os.getenv("APP_ENV", "development")

from app.database import engine
from app.config import settings
from sqlalchemy import text
import subprocess


def print_header(text: str):
    """Print formatted header."""
    print("\n" + "=" * 60)
    print(f"🔧 {text}")
    print("=" * 60)


def print_success(text: str):
    """Print success message."""
    print(f"✅ {text}")


def print_warning(text: str):
    """Print warning message."""
    print(f"⚠️  {text}")


def print_error(text: str):
    """Print error message."""
    print(f"❌ {text}")


async def check_database_connection():
    """Check if database is accessible."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()
        return True
    except Exception as e:
        print_error(f"Cannot connect to database: {e}")
        return False


async def get_current_tables():
    """Get list of current tables."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
                )
            )
            return [row[0] for row in result.fetchall()]
    except Exception:
        return []


async def drop_all_tables():
    """Drop all tables (CASCADE)."""
    print("\n🗑️  Dropping all existing tables...")

    try:
        async with engine.begin() as conn:
            # Drop all tables
            await conn.execute(
                text(
                    """
                DO $$ DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public') LOOP
                        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
                    END LOOP;
                END $$;
            """
                )
            )

            # Drop all sequences
            await conn.execute(
                text(
                    """
                DO $$ DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public') LOOP
                        EXECUTE 'DROP SEQUENCE IF EXISTS ' || quote_ident(r.sequence_name) || ' CASCADE';
                    END LOOP;
                END $$;
            """
                )
            )

        print_success("All tables and sequences dropped")
        return True
    except Exception as e:
        print_error(f"Failed to drop tables: {e}")
        return False


def run_alembic_upgrade():
    """Run Alembic migrations."""
    print("\n🔄 Running Alembic migrations...")

    try:
        # Change to project root
        os.chdir(project_root)

        # Run alembic upgrade head
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=True,
        )

        # Print output
        if result.stdout:
            for line in result.stdout.split("\n"):
                if line.strip():
                    print(f"   {line}")

        print_success("Alembic migrations completed")
        return True
    except subprocess.CalledProcessError as e:
        print_error("Alembic migration failed!")
        if e.stdout:
            print("\nStdout:")
            print(e.stdout)
        if e.stderr:
            print("\nStderr:")
            print(e.stderr)
        return False
    except Exception as e:
        print_error(f"Failed to run Alembic: {e}")
        return False


async def verify_database():
    """Verify database structure after rebuild."""
    print("\n🔍 Verifying database structure...")

    try:
        async with engine.connect() as conn:
            # Count tables
            result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
                )
            )
            table_count = result.scalar()

            # Count indexes
            result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM pg_indexes WHERE schemaname='public'"
                )
            )
            index_count = result.scalar()

            # Get Alembic version
            try:
                result = await conn.execute(text("SELECT version_num FROM alembic_version"))
                version = result.scalar()
            except Exception:
                version = "NOT SET"

            print(f"\n📊 Database Statistics:")
            print(f"   Tables: {table_count}")
            print(f"   Indexes: {index_count}")
            print(f"   Alembic version: {version}")

            # List tables
            print(f"\n📋 Tables:")
            result = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
                )
            )
            for row in result.fetchall():
                print(f"   - {row[0]}")

            # Expected tables
            expected_tables = [
                "alembic_version",
                "application",
                "assignment_log",
                "consultation",
                "consultation_status",
                "crm_interaction",
                "lead",
                "lead_scoring_config",
                "lead_status_history",
                "major",
                "officer_assignment_config",
                "organization_unit",
                "pipeline_stage",
                "skill_requirement_rule",
                "user",
                "user_session",
            ]

            missing = set(expected_tables) - set([row[0] for row in result.fetchall()])
            if missing:
                print_warning(f"Missing expected tables: {', '.join(missing)}")
            else:
                print_success("All expected tables present")

            return table_count > 0
    except Exception as e:
        print_error(f"Verification failed: {e}")
        return False


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Rebuild database from Alembic migrations"
    )
    parser.add_argument(
        "--auto-confirm",
        action="store_true",
        help="Skip confirmation prompts",
    )
    parser.add_argument(
        "--database",
        type=str,
        help="Database name (overrides config)",
    )
    args = parser.parse_args()

    print_header("Database Rebuild Script")

    # Show current config
    print(f"\n📋 Configuration:")
    print(f"   APP_ENV: {settings.APP_ENV}")
    # KHÔNG in DATABASE_URL. 60 ký tự đầu đủ để lộ TRỌN mật khẩu, host và
    # một phần tên CSDL. Tệp này nằm trong ảnh production và có khả năng
    # PHÁ HUỶ dữ liệu, nên nó là chỗ cuối cùng nên in credential ra màn hình.
    print("   DATABASE_URL: (không hiển thị)")

    # Check database connection
    print("\n🔌 Checking database connection...")
    if not await check_database_connection():
        print_error("Cannot connect to database. Check your configuration.")
        return 1

    print_success("Database connection OK")

    # Show current tables
    current_tables = await get_current_tables()
    if current_tables:
        print(f"\n📋 Current tables ({len(current_tables)}):")
        for table in current_tables[:10]:  # Show first 10
            print(f"   - {table}")
        if len(current_tables) > 10:
            print(f"   ... and {len(current_tables) - 10} more")
    else:
        print("\n📋 Database is empty (no tables)")

    # Confirmation
    if not args.auto_confirm:
        print("\n⚠️  WARNING: This will DROP ALL TABLES and recreate from migrations!")
        print("⚠️  ALL DATA WILL BE LOST!")
        print("\nType 'yes' to continue, anything else to cancel: ", end="")
        confirm = input().strip()

        if confirm.lower() != "yes":
            print("\n❌ Operation cancelled")
            return 0

    # Drop all tables
    if not await drop_all_tables():
        return 1

    # Run Alembic migrations
    if not run_alembic_upgrade():
        return 1

    # Verify
    if not await verify_database():
        print_warning("Verification had issues, but migrations may have succeeded")

    # Success
    print_header("Database Rebuild Complete")
    print("\n✅ Database structure rebuilt successfully!")
    print("\n📝 Next steps:")
    print("   1. Import data if you have backups:")
    print("      python scripts/import_data.py")
    print("   2. Or start fresh and create seed data")
    print("   3. Verify application can connect and work properly")

    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n❌ Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
