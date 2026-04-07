# app/tasks/utils.py
"""
Utility functions for Celery tasks.
Provides shared infrastructure like database session management,
result validation, and standardized error handling.
"""
import asyncio
import atexit
import logging
import os
import threading
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from celery.exceptions import Retry
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings

log = logging.getLogger(__name__)


# ============================================================================
# Celery task event loop management
# ============================================================================

_task_event_loop: Optional[asyncio.AbstractEventLoop] = None
_task_event_loop_pid: Optional[int] = None


def _close_task_event_loop() -> None:
    """Close the cached Celery task loop when the worker process exits."""
    global _task_event_loop, _task_event_loop_pid

    loop = _task_event_loop
    _task_event_loop = None
    _task_event_loop_pid = None

    if loop is None or loop.is_closed():
        return

    try:
        loop.run_until_complete(loop.shutdown_asyncgens())
    except Exception:
        log.debug("Failed to shutdown cached task async generators", exc_info=True)

    loop.close()


def _get_task_event_loop() -> asyncio.AbstractEventLoop:
    """
    Return a stable event loop for the current Celery worker process.

    Celery task code uses long-lived async resources such as Redis, Socket.IO,
    and occasionally app-global SQLAlchemy session factories. Re-creating and
    closing the event loop for every task leaves those resources bound to a
    dead loop, which later surfaces as ``RuntimeError: Event loop is closed``.

    Keeping one loop per worker process avoids that churn while still staying
    isolated across Celery's prefork children.
    """
    global _task_event_loop, _task_event_loop_pid

    current_pid = os.getpid()
    if _task_event_loop_pid != current_pid:
        _close_task_event_loop()

    if _task_event_loop is None or _task_event_loop.is_closed():
        _task_event_loop = asyncio.new_event_loop()
        _task_event_loop_pid = current_pid
        asyncio.set_event_loop(_task_event_loop)

    return _task_event_loop


def _run_async_task_in_fresh_thread(async_func: Callable) -> Dict:
    """
    Fallback for environments that already have a running event loop.

    Celery tasks are synchronous entrypoints, but some unit tests may invoke
    them from ``pytest.mark.asyncio`` contexts. In that case, we spin up a
    temporary thread with its own loop instead of nesting loops in-place.
    """
    result_holder: Dict[str, Any] = {}
    error_holder: Dict[str, BaseException] = {}

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result_holder["result"] = loop.run_until_complete(async_func())
            loop.run_until_complete(loop.shutdown_asyncgens())
        except BaseException as exc:  # pragma: no cover - re-raised below
            error_holder["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error_holder:
        raise error_holder["error"]

    return result_holder["result"]


atexit.register(_close_task_event_loop)


# ============================================================================
# Database Session Management
# ============================================================================

def _create_task_async_engine():
    """
    Create a new async engine for use within the current task event loop.

    This must be called while the per-worker task loop is running to avoid
    binding asyncpg connections to the wrong event loop.
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


# ============================================================================
# Result Validation
# ============================================================================

class TaskResultError(Exception):
    """Raised when task result validation fails."""
    def __init__(self, message: str, result: Optional[Dict] = None):
        super().__init__(message)
        self.result = result


def validate_result(
    result: Any,
    required_keys: List[str],
    task_name: str = "task"
) -> Dict:
    """
    Validate that a task result has the expected structure.
    
    Args:
        result: The result to validate
        required_keys: List of keys that must be present
        task_name: Name of the task for error messages
        
    Returns:
        The validated result dict
        
    Raises:
        TaskResultError: If validation fails
    """
    if result is None:
        raise TaskResultError(f"{task_name}: Result is None")
    
    if not isinstance(result, dict):
        raise TaskResultError(
            f"{task_name}: Result is not a dict (got {type(result).__name__})",
            result={"raw": str(result)}
        )
    
    missing_keys = [key for key in required_keys if key not in result]
    if missing_keys:
        raise TaskResultError(
            f"{task_name}: Missing required keys: {missing_keys}",
            result=result
        )
    
    return result


def validate_status(result: Dict, task_name: str = "task") -> str:
    """
    Validate and return the status from a result dict.
    
    Args:
        result: The result dict
        task_name: Name of the task for error messages
        
    Returns:
        The status string
        
    Raises:
        TaskResultError: If status is missing or invalid
    """
    status = result.get("status")
    if status is None:
        raise TaskResultError(f"{task_name}: Missing 'status' in result", result=result)
    
    if not isinstance(status, str):
        raise TaskResultError(
            f"{task_name}: 'status' is not a string (got {type(status).__name__})",
            result=result
        )
    
    return status


# ============================================================================
# Standardized Error Handling
# ============================================================================

def run_async_task(
    async_func: Callable,
    task_name: str,
    task_log: logging.Logger,
    validate_keys: Optional[List[str]] = None
) -> Dict:
    """
    Run an async function with standardized error handling and optional validation.
    
    Args:
        async_func: The async function to run (should be a coroutine or async callable)
        task_name: Name of the task for logging
        task_log: Logger instance
        validate_keys: Optional list of required keys to validate in result
        
    Returns:
        The result dict from the async function
        
    Raises:
        Retry: If Celery should retry the task
        TaskResultError: If result validation fails
        Exception: All other exceptions are logged and re-raised
    """
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = _get_task_event_loop()
            result = loop.run_until_complete(async_func())
        else:
            result = _run_async_task_in_fresh_thread(async_func)
        
        # Validate result if keys provided
        if validate_keys:
            result = validate_result(result, validate_keys, task_name)
        
        return result
        
    except Retry:
        # Let Celery handle retry - don't log as error
        raise
        
    except TaskResultError as e:
        task_log.error(f"{task_name}: Result validation failed: {e}")
        raise
        
    except Exception as e:
        task_log.error(f"{task_name}: Task failed unexpectedly", exc_info=True)
        raise

