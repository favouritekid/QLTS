import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import context

# Thêm sys.path
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

# Tải config và models
from app.config import settings
from app.models.base import Base

config = context.config
config.set_main_option("DATABASE_URL", settings.DATABASE_URL)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("DATABASE_URL")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """
    Hàm helper đồng bộ để chạy migration.
    Không dùng context.begin_transaction() vì đã set AUTOCOMMIT.
    """
    context.configure(
        connection=connection, 
        target_metadata=target_metadata,
    )
    
    context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    
    # KEY FIX: Set AUTOCOMMIT để chạy CONCURRENTLY operations
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.isolation_level"] = "AUTOCOMMIT"
    
    connectable = AsyncEngine(
        engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
            future=True,
        )
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())