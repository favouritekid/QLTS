# app/database.py
from contextlib import asynccontextmanager

import redis.asyncio as redis
import structlog
from typing import NamedTuple
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
        # Engine DÙNG CHUNG cho web workers + celery-worker + celery-beat (mỗi
        # process 1 pool riêng). Cũ 20+40=60/process × ~4 process → burst tối đa
        # ~240 » Postgres max_connections=100 → nguy cơ "too many connections".
        # Giảm về 10+10=20/process → worst-case 4 process ≈ 80 < 100 (chừa ~20
        # cho psql admin / alembic lúc deploy). ⚠️ Nếu nâng GUNICORN_WORKERS (>2)
        # hoặc celery concurrency, phải tính lại hoặc nâng PG max_connections.
        pool_size=10,
        max_overflow=10,
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


async def get_redis():
    """Return the shared Redis client for direct operations.

    Use safe_redis_* for simple get/set with circuit breaker protection.
    Use get_redis() when you need SET NX, pipelines, or other advanced
    operations not covered by safe_redis_* wrappers.
    """
    return redis_client


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


async def safe_redis_set(key: str, value: str, ex: int = None, nx: bool = False):
    """Set key trong Redis (an toàn qua circuit breaker).

    Args:
        nx: If True, use SET NX (only set if key doesn't exist).
            Returns True if key was set, False if already exists.
    """
    try:
        kwargs = {}
        if ex is not None:
            kwargs["ex"] = ex
        if nx:
            kwargs["nx"] = True
        return await redis_breaker.call_async(redis_client.set, key, value, **kwargs)
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


async def safe_redis_getdel(key: str):
    """Atomic GET + DELETE (Redis 6.2+ ``GETDEL``).

    Returns the previous value or ``None`` if the key did not exist or the
    breaker tripped. Used by Zalo Bot link flow to consume one-shot link
    codes without a TOCTOU window between read and delete.
    """
    try:
        return await redis_breaker.call_async(redis_client.getdel, key)
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis GETDEL failed", key=key, exc_info=True)
        return None


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


class DatChoMFA(NamedTuple):
    """Kết quả đặt chỗ một lần thử MFA.

    ``allowed`` là quyết định, KHÔNG phải thứ chỗ gọi tự suy ra từ ``count``:
    quy tắc chặn nằm trong script, nên chỉ có một nơi biết ngưỡng. Bắt router
    so ``count`` với trần lần nữa là mở đường cho hai bản luật lệch nhau.
    """

    allowed: bool
    count: int
    ttl: int


# Máy trạng thái đặt chỗ, chạy NGUYÊN TỬ trong Redis.
#
# Vì sao phải là Lua chứ không phải MULTI/EXEC: quyết định phụ thuộc GIÁ TRỊ
# hiện tại (đã chạm trần hay chưa), mà MULTI/EXEC không rẽ nhánh được — nó chỉ
# gửi một chùm lệnh cố định. Đọc trước rồi mới quyết ở phía client là TOCTOU:
# hai request cùng đọc n, cùng kết luận "chưa chạm trần", cùng lọt.
#
# Bốn nhánh, và nhánh thứ ba là chỗ đã có lỗi thật:
#   * chưa có khoá        → tạo count=1, đặt hạn, CHO QUA
#   * count < max         → tăng 1, trượt cửa sổ (giữ semantics cũ), CHO QUA
#   * count >= max        → KHÔNG tăng, KHÔNG gia hạn, CHẶN
#       Bản trước luôn INCR+EXPIRE kể cả khi đã chặn, nên mỗi request của kẻ
#       tấn công vừa đẩy bộ đếm lên vừa kéo hạn về TRỌN cửa sổ. Chỉ cần gõ một
#       lần trước mỗi lần hết hạn là giữ nạn nhân bị khoá MFA vô thời hạn.
#       Một hình phạt đã tuyên không được chính kẻ bị phạt gia hạn.
#   * count >= max, TTL<0 → CHẶN, nhưng đặt lại hạn: khoá không hạn là khoá
#       vĩnh viễn, hỏng theo chiều ngược lại nhưng vẫn là hỏng.
#
# Mã trả về ở ô đầu: 1 cho qua · 0 chặn · -1 bộ đếm không parse được ·
# -2 tham số không hợp lệ. Ô thứ tư báo đã phải sửa hạn (để ghi log).
_LUA_DAT_CHO_MFA = """
local window = tonumber(ARGV[1])
local max_attempts = tonumber(ARGV[2])
if window == nil or window <= 0 or max_attempts == nil or max_attempts < 1 then
  return {-2, 0, 0, 0}
end

local cur = redis.call('GET', KEYS[1])
if cur then
  local n = tonumber(cur)
  if n == nil then
    return {-1, 0, 0, 0}
  end
  if n >= max_attempts then
    local t = redis.call('TTL', KEYS[1])
    local da_sua = 0
    if t < 0 then
      redis.call('EXPIRE', KEYS[1], window)
      t = redis.call('TTL', KEYS[1])
      da_sua = 1
    end
    return {0, n, t, da_sua}
  end
end

local n = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], window)
return {1, n, redis.call('TTL', KEYS[1]), 0}
"""


def _la_so_nguyen(x):
    return isinstance(x, int) and not isinstance(x, bool)


async def safe_redis_reserve_attempt(
    key: str, window_seconds: int, max_attempts: int
):
    """Đặt chỗ MỘT lần thử MFA — nguyên tử, và fail closed.

    Toàn bộ quyết định nằm trong một script server-side (``_LUA_DAT_CHO_MFA``),
    nên không có cửa sổ TOCTOU giữa đọc và ghi, và một request ĐÃ BỊ CHẶN không
    tự gia hạn hình phạt của nó.

    Returns:
        ``DatChoMFA(allowed, count, ttl)`` khi đặt chỗ ĐƯỢC CHỨNG MINH — gồm cả
        việc TTL dương. ``None`` ở MỌI ca còn lại: lỗi kết nối, script lỗi, kết
        quả thiếu/sai kiểu, bộ đếm hỏng, hoặc TTL không dương. ``None`` ⇒ chỗ
        gọi phải trả 503 TRƯỚC mọi chi phí CPU.
    """
    try:
        raw = await redis_breaker.call_async(
            redis_client.eval,
            _LUA_DAT_CHO_MFA,
            1,
            key,
            str(int(window_seconds)),
            str(int(max_attempts)),
        )
    except REDIS_BREAKER_EXCEPTIONS:
        log.error("Redis RESERVE failed", key=key, exc_info=True)
        return None
    except Exception:
        # Kể cả lỗi ngoài dự kiến (script lỗi, server không hỗ trợ EVAL) cũng
        # fail closed: đây là hàng rào của một đường brute-force, không phải cache.
        log.error("Redis RESERVE unexpected error", key=key, exc_info=True)
        return None

    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        log.error("Redis RESERVE trả kết quả lạ", key=key, ket_qua=repr(raw))
        return None
    if not all(_la_so_nguyen(x) for x in raw):
        log.error("Redis RESERVE trả sai kiểu", key=key, ket_qua=repr(raw))
        return None

    ma, dem, ttl, da_sua_han = raw

    if ma == -1:
        # Bộ đếm không phải số: không kết luận được còn bao nhiêu lượt.
        log.error("Redis RESERVE: bộ đếm hỏng, không parse được", key=key)
        return None
    if ma == -2:
        log.error(
            "Redis RESERVE: tham số không hợp lệ",
            key=key, window=window_seconds, max_attempts=max_attempts,
        )
        return None
    if ma not in (0, 1):
        log.error("Redis RESERVE: mã trả về lạ", key=key, ma=ma)
        return None
    if ttl <= 0:
        # Không chứng minh được hạn ⇒ coi như chưa đặt chỗ. Thà 503 còn hơn để
        # lại một bộ đếm không bao giờ tự hết.
        log.error("Redis RESERVE: TTL không dương", key=key, ttl=ttl)
        return None
    if dem < 0:
        log.error("Redis RESERVE: bộ đếm âm", key=key, dem=dem)
        return None

    if da_sua_han:
        log.warning(
            "mfa_attempt_key_missing_ttl_repaired",
            key=key, dem=dem, ttl=ttl, action="mfa.reservation_ttl_repaired",
        )

    return DatChoMFA(allowed=(ma == 1), count=dem, ttl=ttl)


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
