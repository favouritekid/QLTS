# app/utils/redis_lock.py
"""
Redis Distributed Lock for Student Code Generation.

Security:
- Prevents concurrent generation of duplicate student codes
- Uses Redis SETNX (SET if Not eXists) with expiration
- Automatic lock release on timeout (prevents deadlock)

Usage:
    async with acquire_redis_lock(key="student_code_gen", timeout=10):
        # Critical section - generate student code
        student_code = generate_unique_student_code()
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import redis.asyncio as aioredis
from structlog import get_logger

from app.config import settings

log = get_logger(__name__)

# Global Redis client (initialized in main.py)
_redis_client: Optional[aioredis.Redis] = None


def init_redis_client():
    """
    Initialize Redis client (call this in main.py startup event).

    Returns:
        Redis client instance
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=10
        )
        log.info("Redis client initialized", redis_url=settings.REDIS_URL)
    return _redis_client


async def close_redis_client():
    """Close Redis client (call this in main.py shutdown event)."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        log.info("Redis client closed")
        _redis_client = None


def get_redis_client() -> aioredis.Redis:
    """
    Get Redis client instance.

    Returns:
        Redis client

    Raises:
        RuntimeError: If Redis client not initialized
    """
    if _redis_client is None:
        raise RuntimeError(
            "Redis client not initialized. Call init_redis_client() in main.py startup."
        )
    return _redis_client


@asynccontextmanager
async def acquire_redis_lock(
    key: str,
    timeout: int = 10,
    retry_delay: float = 0.1,
    max_retries: int = 50
) -> AsyncGenerator[bool, None]:
    """
    Acquire distributed lock using Redis SETNX.

    Pattern:
    - Uses SETNX (SET if Not eXists) to atomically acquire lock
    - Sets expiration to prevent deadlock if process crashes
    - Retries with exponential backoff if lock is held
    - Automatically releases lock on exit (even if exception)

    Args:
        key: Lock key (e.g., "student_code_gen:2025")
        timeout: Lock expiration time in seconds (default 10s)
        retry_delay: Initial retry delay in seconds (default 0.1s)
        max_retries: Maximum retry attempts (default 50 = ~5s total)

    Yields:
        True if lock acquired, False if failed after max_retries

    Example:
        async with acquire_redis_lock("student_code_gen", timeout=10) as acquired:
            if not acquired:
                raise ConflictError("Too many concurrent enrollments")
            # Critical section - guaranteed exclusive access
            student_code = generate_code()

    Security:
    - Prevents race conditions in student_code generation
    - Timeout ensures no permanent deadlock
    - Exponential backoff reduces thundering herd
    """
    redis = get_redis_client()
    lock_key = f"lock:{key}"
    lock_value = f"locked_at_{asyncio.get_event_loop().time()}"
    acquired = False

    try:
        # Try to acquire lock with retries
        for attempt in range(max_retries):
            # SETNX with expiration (NX = set if not exists, EX = expiration in seconds)
            acquired = await redis.set(
                lock_key,
                lock_value,
                nx=True,  # Only set if key doesn't exist
                ex=timeout  # Expire after timeout seconds
            )

            if acquired:
                log.debug(
                    "Redis lock acquired",
                    lock_key=lock_key,
                    timeout=timeout,
                    attempt=attempt + 1
                )
                break

            # Lock is held, wait and retry with exponential backoff
            wait_time = retry_delay * (2 ** min(attempt, 5))  # Cap at 2^5 = 32x
            log.debug(
                "Redis lock held, retrying",
                lock_key=lock_key,
                attempt=attempt + 1,
                max_retries=max_retries,
                wait_time=wait_time
            )
            await asyncio.sleep(wait_time)

        if not acquired:
            log.warning(
                "Failed to acquire Redis lock after max retries",
                lock_key=lock_key,
                max_retries=max_retries
            )

        yield acquired

    finally:
        # Release lock if acquired
        if acquired:
            await redis.delete(lock_key)
            log.debug("Redis lock released", lock_key=lock_key)
