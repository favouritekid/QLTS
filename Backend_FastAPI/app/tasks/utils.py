# app/tasks/utils.py
"""
Utility functions for Celery tasks.
Provides shared infrastructure like database session management.
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings

log = logging.getLogger(__name__)


def _create_task_async_engine():
    """
    Create a new async engine for use within a task's event loop.

    This must be called INSIDE asyncio.run() context to avoid the
    "Future attached to a different loop" error with asyncpg.
    """
    return create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=3,  # Small pool for single task
        max_overflow=5,
        pool_timeout=30,
    )


def _create_task_session_maker(engine):
    """Create a sessionmaker bound to the given engine."""
    return sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


@asynccontextmanager
async def task_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions in Celery tasks.
    
    Creates engine INSIDE async context to avoid event loop issues.
    Automatically disposes engine after task completes.
    
    Usage:
        async with task_db_session() as session:
            result = await some_service(session)
            await session.commit()
    """
    engine = _create_task_async_engine()
    session_maker = _create_task_session_maker(engine)
    
    try:
        async with session_maker() as session:
            yield session
    finally:
        await engine.dispose()
        log.debug("Task DB engine disposed")
