# tests/fixtures/database.py
"""
Track T: Extracted database management fixtures from conftest.py.

Contains: safety check, schema init, table truncation.
Uses NullPool to avoid asyncpg prepared-statement cache pollution.
"""
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine as _create_engine
from sqlalchemy.pool import NullPool

log = logging.getLogger(__name__)


def verify_test_database_safety(settings, pytest_fail):
    """
    Verify we're using a safe test database before allowing DROP operations.

    Safety criteria:
    1. APP_ENV must be "test"
    2. DATABASE_URL must contain "test" or ":memory:"
    """
    current_env = settings.APP_ENV
    if current_env != "test":
        pytest_fail(
            f"SAFETY CHECK FAILED! APP_ENV is '{current_env}', not 'test'."
        )

    db_url = settings.DATABASE_URL.lower()
    is_safe = ":memory:" in db_url or "test" in db_url

    dangerous_patterns = ["/qlts_dev", "/qlts_prod", "/qlts_production", "/production", "/prod/"]
    is_dangerous = any(p in db_url for p in dangerous_patterns)

    if is_dangerous and not is_safe:
        pytest_fail(
            f"SAFETY CHECK FAILED! DATABASE_URL appears to be production: {settings.DATABASE_URL}"
        )
    if not is_safe:
        pytest_fail(
            f"SAFETY CHECK FAILED! DATABASE_URL does not contain 'test': {settings.DATABASE_URL}"
        )

    log.info(f"Safety check passed: APP_ENV={current_env}, DB_URL={settings.DATABASE_URL[:60]}...")


async def init_schema_once(settings, AppBase, CasbinBase=None):
    """
    Create the full schema from scratch. Called once per pytest session.

    Uses a SEPARATE short-lived engine (NullPool) for DDL to avoid
    asyncpg prepared-statement cache pollution.
    """
    setup_engine = _create_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        connect_args={"command_timeout": 60},
    )

    try:
        # Step 1: DROP SCHEMA CASCADE (clean slate)
        async with setup_engine.begin() as conn:
            await conn.execute(text(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND pid <> pg_backend_pid()"
            ))
            await conn.execute(text("DROP SCHEMA public CASCADE"))
            await conn.execute(text("CREATE SCHEMA public"))
        log.info("[Schema Init] Step 1: DROP SCHEMA CASCADE complete")

        await setup_engine.dispose()

        # Step 2: Recreate with fresh engine
        setup_engine = _create_engine(
            settings.DATABASE_URL,
            poolclass=NullPool,
            connect_args={"command_timeout": 60},
        )
        async with setup_engine.begin() as conn:
            # Drop stale enum types
            for enum_type in ("discount_type_enum", "outcometype", "statustype",
                              "selectablemode", "triggertype", "administrativenodelevel"):
                await conn.execute(text(f"DROP TYPE IF EXISTS {enum_type} CASCADE"))

            # Re-create migration-managed enums
            await conn.execute(text(
                "CREATE TYPE discount_type_enum AS ENUM ('amount', 'percentage')"
            ))

            await conn.run_sync(AppBase.metadata.create_all)

            # Sequences not tracked by SQLAlchemy
            await conn.execute(text(
                "CREATE SEQUENCE IF NOT EXISTS collaborator_code_seq "
                "START WITH 1 INCREMENT BY 1"
            ))

            # Partial unique indexes (match Alembic migrations)
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_email_unit_active "
                "ON lead (lower(email), unit_id) "
                "WHERE email IS NOT NULL AND deleted_at IS NULL"
            ))
            await conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_phone_active "
                "ON lead_phone_identity (phone_normalized) "
                "WHERE deleted_at IS NULL"
            ))

            if CasbinBase:
                await conn.run_sync(CasbinBase.metadata.create_all)
                await conn.execute(text("""
                    DO $$ BEGIN
                        ALTER TABLE casbin_rule
                        ADD COLUMN IF NOT EXISTS template_id VARCHAR(50),
                        ADD COLUMN IF NOT EXISTS applied_at TIMESTAMP,
                        ADD COLUMN IF NOT EXISTS applied_by INTEGER;
                        CREATE INDEX IF NOT EXISTS ix_casbin_rule_template_id
                        ON casbin_rule(template_id);
                    EXCEPTION WHEN undefined_table THEN
                        NULL;
                    END $$;
                """))

            tc = await conn.execute(text(
                "SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'"
            ))
            table_count = tc.scalar()
            log.info(f"[Schema Init] Step 2: Created {table_count} tables")
            if table_count == 0:
                raise RuntimeError("Schema init produced 0 tables!")
    finally:
        await setup_engine.dispose()

    log.info("[Schema Init] Schema initialization complete")


async def truncate_all_tables(settings, engine):
    """
    Truncate all data from all tables in a single statement.

    Uses a DEDICATED short-lived engine (NullPool) to avoid deadlocks
    with the app's connection pool.
    """
    truncate_engine = _create_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
        connect_args={"command_timeout": 60},
    )
    try:
        await engine.dispose()

        async with truncate_engine.begin() as conn:
            await conn.execute(text("SET LOCAL statement_timeout = 0"))
            result = await conn.execute(text(
                "SELECT string_agg(quote_ident(tablename), ', ') "
                "FROM pg_tables WHERE schemaname = 'public'"
            ))
            tables = result.scalar()
            if tables:
                await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
                await conn.execute(text("SELECT setval('collaborator_code_seq', 1, false)"))
    finally:
        await truncate_engine.dispose()
