import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import context

# Thêm sys.path
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

# V6 vòng 6 (F41): cửa ra dòng lệnh của Alembic qua CHỦ SỞ HỮU bộ che
# (app/core/log_redaction.py — chỉ phụ thuộc stdlib). Alembic chạy NGOÀI web/celery:
# one-off `--entrypoint alembic backend upgrade head` của deploy.sh (log Actions) và
# `alembic upgrade head` trong docker-entrypoint.sh (docker logs).
from app.core.log_redaction import gan_bo_che_moi_handler, thoat_cli_an_toan  # noqa: E402

# Tải config và models
from app.config import settings
from app.models.base import Base

config = context.config
config.set_main_option("DATABASE_URL", settings.DATABASE_URL)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
# Handler console do fileConfig dựng (logger gốc, `alembic`, `sqlalchemy.engine`)
# KHÔNG có bộ che — phủ SAU khi fileConfig đã dựng xong.
gan_bo_che_moi_handler()
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


# Ngoại lệ không bắt ⇒ Python in THÔ ra stderr (DETAIL / [SQL] / [parameters] / hàng
# lỗi). Bắt ở đây: in mô tả an toàn rồi thoát mã KHÁC 0 (deploy và entrypoint vẫn dừng).
try:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        asyncio.run(run_migrations_online())
except BaseException as _loi:  # noqa: BLE001 — cửa ra CLI: mọi ngoại lệ
    thoat_cli_an_toan(_loi, ten="alembic")