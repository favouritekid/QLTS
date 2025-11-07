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


async def get_db() -> AsyncSession:
    """Dependency function that yields a new SQLAlchemy AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session
