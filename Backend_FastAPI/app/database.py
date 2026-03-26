# app/database.py
from contextlib import asynccontextmanager

import redis.asyncio as redis
import structlog
from aiobreaker import CircuitBreaker
from redis.exceptions import ConnectionError, TimeoutError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

log = structlog.get_logger(__name__)

# === CẤU HÌNH ENGINE CSDL ===
# Different configuration for SQLite (testing) vs PostgreSQL (production)
if "sqlite" in settings.DATABASE_URL:
    # SQLite configuration (for testing)
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )
else:
    # PostgreSQL configuration (for production)
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=20,
        max_overflow=40,
        echo=False,
        connect_args={
            # ✅ Sét timeout ở mức độ command (phía client driver - asyncpg)
            "command_timeout": 30,  # 30 giây
            "server_settings": {
                "application_name": "qlts_backend_api",
                # ✅ Sét timeout ở mức độ CSDL (PostgreSQL)
                "statement_timeout": "30000",  # 30000ms = 30 giây
            },
        },
    )

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# === KHỞI TẠO REDIS CLIENT GỐC ===
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

# ===============================================================
# === 🔧 CIRCUIT BREAKER PATTERN VỚI AIOBREAKER (SỬA LẠI) 🔧 ===
# ===============================================================

# Khởi tạo breaker
# ===============================================================
# === 🔧 CIRCUIT BREAKER PATTERN (ĐÃ SỬA safe_redis_pipeline) ===
# ===============================================================

redis_breaker = CircuitBreaker(fail_max=5, timeout_duration=60)

REDIS_BREAKER_EXCEPTIONS = (ConnectionError, TimeoutError)


async def safe_redis_ping():
    """Ping Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.ping)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis ping failed", exc_info=True)
        return False


async def safe_redis_get(key: str):
    """Lấy key từ Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.get, key)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis GET failed", key=key, exc_info=True)
        return None


async def safe_redis_exists(key: str) -> bool:
    """Kiểm tra key tồn tại (an toàn qua circuit breaker)."""
    try:
        result = await redis_breaker.call_async(redis_client.exists, key)
        return bool(result)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis EXISTS failed", key=key, exc_info=True)
        return False


async def safe_redis_set(key: str, value: str, ex: int):
    """Set key trong Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.set, key, value, ex=ex)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis SET failed", key=key, exc_info=True)
        raise


async def safe_redis_delete(key: str):
    """Xóa key khỏi Redis (an toàn qua circuit breaker)."""
    try:
        return await redis_breaker.call_async(redis_client.delete, key)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis DELETE failed", key=key, exc_info=True)
        return 0


# ✅ PHASE 1.2.1: Redis List operations for notification inbox caching
async def safe_redis_lpush(key: str, *values):
    """
    LPUSH values to Redis list (safe with circuit breaker).

    Used for notification inbox cache: adds new notifications to the front of the list.
    """
    try:
        return await redis_breaker.call_async(redis_client.lpush, key, *values)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis LPUSH failed", key=key, exc_info=True)
        return 0


async def safe_redis_ltrim(key: str, start: int, end: int):
    """
    LTRIM Redis list to keep only specified range (safe with circuit breaker).

    Used to maintain max 100 notifications in inbox cache.
    Example: LTRIM user_inbox:123 0 99 → keeps first 100 items
    """
    try:
        return await redis_breaker.call_async(redis_client.ltrim, key, start, end)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis LTRIM failed", key=key, start=start, end=end, exc_info=True)
        return False


async def safe_redis_lrange(key: str, start: int, end: int):
    """
    LRANGE to get items from Redis list (safe with circuit breaker).

    Used to fetch notification IDs from inbox cache.
    Example: LRANGE user_inbox:123 0 49 → gets first 50 items

    Returns:
        List of items, or empty list if key doesn't exist or error occurs
    """
    try:
        result = await redis_breaker.call_async(redis_client.lrange, key, start, end)
        return result if result else []
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis LRANGE failed", key=key, start=start, end=end, exc_info=True)
        return []


async def safe_redis_ttl(key: str) -> int:
    """
    Get remaining TTL (time-to-live) of a key in seconds.

    Returns:
        Positive int: seconds remaining
        -1: key exists but has no expiry
        -2: key does not exist
    """
    try:
        return await redis_breaker.call_async(redis_client.ttl, key)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis TTL failed", key=key, exc_info=True)
        return -2


async def safe_redis_expire(key: str, seconds: int):
    """
    Set expiration time for a key (safe with circuit breaker).

    Used to set TTL for inbox cache (7 days = 604800 seconds).
    """
    try:
        return await redis_breaker.call_async(redis_client.expire, key, seconds)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis EXPIRE failed", key=key, seconds=seconds, exc_info=True)
        return False


async def safe_redis_incr(key: str, amount: int = 1):
    """
    Increment a Redis key by amount (safe with circuit breaker).

    Phase C2: Used for per-user rate limiting (INCR + EXPIRE pattern).
    Returns the new value as int, or None on failure.
    """
    try:
        return await redis_breaker.call_async(redis_client.incr, key, amount)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis INCR failed", key=key, amount=amount, exc_info=True)
        return None


# ✅ FIX: Tạo async context manager cho pipeline


@asynccontextmanager
async def safe_redis_pipeline(transaction: bool = True):
    """
    Async context manager cho Redis pipeline với circuit breaker protection.

    Usage:
        async with safe_redis_pipeline() as pipe:
            pipe.set("key1", "value1")
            pipe.set("key2", "value2")
            await pipe.execute()
    """
    pipe = None
    try:
        # Pipeline không cần qua breaker khi tạo (chỉ là object local)
        pipe = redis_client.pipeline(transaction=transaction)
        yield pipe

    except REDIS_BREAKER_EXCEPTIONS as e:
        log.error("Redis PIPELINE operation failed", error=str(e), exc_info=True)
        if pipe:
            await pipe.reset()  # Cleanup pipeline
        raise
    except Exception as e:
        log.error("Unexpected error in Redis pipeline", error=str(e), exc_info=True)
        if pipe:
            await pipe.reset()
        raise
    finally:
        # Cleanup (nếu cần)
        pass


# ===============================================================
# === ✅ REDIS DISTRIBUTED LOCK (PRIORITY 2 - Deep Dive Audit) ===
# ===============================================================


@asynccontextmanager
async def redis_distributed_lock(lock_name: str, timeout: int = 10, retry_delay: float = 0.1):
    """
    ✅ PRIORITY 2 FIX (Deep Dive Audit): Redis Distributed Lock

    Replaces asyncio.Lock() to support multi-worker/multi-process deployments.

    This lock works across multiple:
    - uvicorn workers (--workers 4)
    - Kubernetes pods (replicas > 1)
    - Docker containers (scale > 1)
    - Servers behind load balancer

    Args:
        lock_name: Unique lock identifier (e.g., "org_cache_rebuild")
        timeout: Lock auto-expiry in seconds (prevents deadlock if holder crashes)
        retry_delay: Sleep duration between lock acquisition attempts

    Usage:
        async with redis_distributed_lock("org_cache_rebuild"):
            # Critical section - only ONE worker across entire cluster enters here
            cache_data = await rebuild_expensive_cache()
            await redis_client.set("cache_key", cache_data)

    Pattern:
        - Uses Redis SET NX EX (atomic set-if-not-exists with expiry)
        - Auto-releases lock on context exit
        - Auto-expires after timeout (prevents deadlock)
        - Retries acquisition if lock held by another worker

    Refs:
        - Redis SETNX: https://redis.io/commands/setnx/
        - Distributed Locks: https://redis.io/docs/manual/patterns/distributed-locks/
    """
    import asyncio
    import uuid

    lock_key = f"lock:{lock_name}"
    # Unique lock value to prevent accidental release by wrong holder
    lock_value = str(uuid.uuid4())
    acquired = False

    try:
        # Try to acquire lock with retries
        while True:
            # SET NX EX: Set if Not eXists with EXpiry (atomic operation)
            acquired = await redis_breaker.call_async(
                redis_client.set,
                lock_key,
                lock_value,
                nx=True,  # Only set if key doesn't exist
                ex=timeout  # Auto-expire after timeout seconds
            )

            if acquired:
                log.debug(
                    "Distributed lock acquired",
                    lock_name=lock_name,
                    lock_value=lock_value,
                    timeout=timeout
                )
                break

            # Lock held by another worker - wait and retry
            log.debug(
                "Distributed lock held by another worker, retrying...",
                lock_name=lock_name,
                retry_delay=retry_delay
            )
            await asyncio.sleep(retry_delay)

        # Critical section - caller's code runs here
        yield

    finally:
        # Release lock only if we acquired it (check value to prevent wrong release)
        if acquired:
            try:
                # LUA script ensures atomic check-and-delete
                release_script = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("del", KEYS[1])
                else
                    return 0
                end
                """
                released = await redis_breaker.call_async(
                    redis_client.eval,
                    release_script,
                    1,
                    lock_key,
                    lock_value
                )

                if released:
                    log.debug("Distributed lock released", lock_name=lock_name)
                else:
                    log.warning(
                        "Lock already expired or released by timeout",
                        lock_name=lock_name
                    )
            except REDIS_BREAKER_EXCEPTIONS:
                log.error(
                    "Failed to release distributed lock (will auto-expire)",
                    lock_name=lock_name,
                    timeout=timeout,
                    exc_info=True
                )


# ===============================================================


async def get_db() -> AsyncSession:
    """Dependency function that yields a new SQLAlchemy AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session
