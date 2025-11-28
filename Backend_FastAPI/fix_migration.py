#!/usr/bin/env python3
"""
Fix notification_rule migration issue.

This script:
1. Manually drops the notification_rule table if it exists
2. Resets migration state to the previous version
3. Runs the migration again
"""
import asyncio
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings

async def fix_migration():
    """Fix the notification_rule migration."""
    print("🔧 Starting migration fix...")

    # Create async engine
    engine = create_async_engine(
        settings.ASYNC_DATABASE_URL,
        echo=True
    )

    try:
        async with engine.begin() as conn:
            print("\n1️⃣ Dropping notification_rule table if exists...")

            # Drop indexes first
            await conn.execute(text("""
                DROP INDEX IF EXISTS ix_notification_rule_event_enabled;
            """))
            await conn.execute(text("""
                DROP INDEX IF EXISTS ix_notification_rule_enabled;
            """))
            await conn.execute(text("""
                DROP INDEX IF EXISTS ix_notification_rule_event;
            """))
            await conn.execute(text("""
                DROP INDEX IF EXISTS ix_notification_rule_id;
            """))

            # Drop table
            await conn.execute(text("""
                DROP TABLE IF EXISTS notification_rule CASCADE;
            """))

            print("✅ Table and indexes dropped successfully")

            print("\n2️⃣ Resetting alembic version to previous migration...")

            # Update alembic_version to previous migration
            await conn.execute(text("""
                UPDATE alembic_version
                SET version_num = 'a2b3c4d5e6f7'
                WHERE version_num = '7caf68807fa8';
            """))

            print("✅ Alembic version reset to a2b3c4d5e6f7")

        print("\n✅ Migration fix completed!")
        print("\nNow run: alembic upgrade head")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(fix_migration())
