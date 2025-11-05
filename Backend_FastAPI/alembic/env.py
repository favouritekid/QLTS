# Sửa lỗi 1: Import AsyncEngine và asyncio
import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import context

# Thêm sys.path
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import settings

# Import Base và settings
from app.models.base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Đặt DATABASE_URL từ settings
config.set_main_option("DATABASE_URL", settings.DATABASE_URL)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Đặt target_metadata
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.
    ...
    """
    # Sửa lỗi 2: Đọc đúng key "DATABASE_URL"
    url = config.get_main_option("DATABASE_URL")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


# Tách logic migration ra hàm sync helper
def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


# Sửa lỗi 3: Chuyển hàm này thành "async def"
async def run_migrations_online() -> None:
    """Run migrations in 'online' mode.
    ...
    """

    connectable = AsyncEngine(
        engine_from_config(
            # SỬA LỖI 4: Dùng 'config.config_ini_section'
            # thay vì 'config.main_section' (không tồn tại)
            config.get_section(config.config_ini_section),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
            future=True,
        )
    )

    # Dùng 'async with' và 'run_sync'
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)  # <-- Gọi hàm sync helper

    await connectable.dispose()  # <-- Đóng engine


if context.is_offline_mode():
    run_migrations_offline()
else:
    # Chạy hàm async 'run_migrations_online'
    asyncio.run(run_migrations_online())
