# app/database.py
from contextlib import asynccontextmanager
from enum import Enum

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
  -- Bộ đếm CHỈ hợp lệ khi là số nguyên >= 1. Máy trạng thái này không bao giờ
  -- tự sinh ra 0, số âm hay số thập phân, nên gặp chúng nghĩa là dữ liệu đã bị
  -- ai đó/cái gì đó ghi đè. Trước đây chỉ chặn `nil`, nên "-1" lọt qua vế
  -- `n >= max`, rơi xuống INCR thành 0 và được CẤP THÊM LƯỢT — một trạng thái
  -- hỏng tự chuyển thành quyền xác minh. Fail closed: không INCR, không đụng
  -- TTL, không cho qua.
  if n == nil or n < 1 or n ~= math.floor(n) then
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
    if dem < 1:
        # Kiểm ĐỘC LẬP với Lua, không phải kiểm thừa: nếu script bị đổi, bị
        # thay bản khác, hay Redis trả payload lạ, tầng này vẫn phải từ chối.
        # Mọi lượt hợp lệ đều có count >= 1 (cho qua: >=1; bị chặn: >= max >= 1).
        log.error("Redis RESERVE: bộ đếm ngoài miền", key=key, dem=dem)
        return None

    if da_sua_han:
        log.warning(
            "mfa_attempt_key_missing_ttl_repaired",
            key=key, dem=dem, ttl=ttl, action="mfa.reservation_ttl_repaired",
        )

    return DatChoMFA(allowed=(ma == 1), count=dem, ttl=ttl)


# =============================================================================
# TIÊU THỤ MỘT LẦN — bằng chứng MFA chỉ được dùng ĐÚNG MỘT LẦN
# =============================================================================
# Hai helper dưới đây đóng hai cửa sổ TOCTOU cùng họ với cái mà
# ``safe_redis_reserve_attempt`` đã đóng, và cùng một triết lý: quyết định nằm
# TRỌN phía Redis, còn phía Python thì KHÔNG TIN kết quả trả về cho tới khi đã
# kiểm kiểu và miền giá trị.
#
# Cả hai fail CLOSED. Đó là điểm khác biệt đáng nói nhất so với bản trước:
# ``safe_redis_get`` trả ``None`` khi lỗi và ``safe_redis_exists`` trả ``False``
# khi lỗi, nên chỗ gọi cũ đọc được "chưa ai dùng" từ một lượt Redis chết. Một
# hàng rào chống dùng-lại mà biến mất im lặng lúc hạ tầng trục trặc thì không
# phải hàng rào. Quyết định fail-open/fail-closed phải là lựa chọn TƯỜNG MINH,
# không phải hệ quả tình cờ của giá trị mặc định trong một helper dùng chung.


class TieuThuTOTP(NamedTuple):
    """Kết quả tiêu thụ một time step TOTP.

    ``accepted`` là quyết định của script, KHÔNG phải thứ chỗ gọi tự suy ra
    bằng cách so ``stored_counter`` lần nữa — cùng lý do như ``DatChoMFA``:
    một quy tắc, một nơi diễn giải.
    """

    accepted: bool
    stored_counter: int
    ttl: int


# So sánh-rồi-ghi NGUYÊN TỬ cho bộ chống phát lại TOTP (RFC 6238 §5.2).
#
# Vì sao phải là Lua: quyết định phụ thuộc GIÁ TRỊ hiện tại (counter đã tiêu),
# mà ``SET NX`` chỉ biết "có hay không có khoá" chứ không so được lớn hơn/nhỏ
# hơn. Bản trước GET rồi mới SET ở phía client: hai request cùng đọc counter
# cũ, cùng kết luận hợp lệ, cùng được chấp nhận — đo được ``[True, True]`` cho
# MỘT mã TOTP.
#
# Tính ĐƠN ĐIỆU là bất biến thật sự ở đây, không chỉ là "chưa dùng thì cho":
# chấp nhận khi và chỉ khi ``counter > stored_counter``. Nhờ vậy một mã CŨ HƠN
# gửi tới sau một mã mới hơn cũng bị chặn — nếu chỉ chặn trùng khít thì kẻ tấn
# công còn nguyên hai bước ±1 của ``valid_window`` để dùng lại.
#
# Mã trả về ở ô đầu: 1 chấp nhận · 0 từ chối · -1 counter đã lưu không parse
# được · -2 tham số không hợp lệ. Ô thứ tư báo đã phải sửa hạn (để ghi log).
_LUA_TIEU_THU_TOTP = """
local counter = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
if counter == nil or counter ~= math.floor(counter) or counter < 0 then
  return {-2, 0, 0, 0}
end
if ttl == nil or ttl < 1 then
  return {-2, 0, 0, 0}
end

local cur = redis.call('GET', KEYS[1])
if cur then
  local n = tonumber(cur)
  -- Counter đã lưu chỉ hợp lệ khi là số nguyên >= 0. Gặp giá trị khác nghĩa là
  -- khoá đã bị ghi đè bởi ai đó/cái gì đó. Fail closed: KHÔNG ghi đè, KHÔNG
  -- đụng TTL, KHÔNG cho qua. Ghi đè ở đây là tự tay xoá dấu vết của những mã
  -- đã tiêu, tức mở lại đúng cửa sổ phát lại mà hàm này sinh ra để đóng.
  if n == nil or n ~= math.floor(n) or n < 0 then
    return {-1, 0, 0, 0}
  end
  if counter <= n then
    -- Đã dùng (hoặc là bước CŨ HƠN). Từ chối — nhưng khoá không hạn là khoá
    -- VĨNH VIỄN: nó sẽ chặn mọi TOTP tương lai của chính người dùng này, tức
    -- hỏng theo chiều ngược lại. Chặn request hiện tại VÀ sửa hạn về hữu hạn.
    local t = redis.call('TTL', KEYS[1])
    local da_sua = 0
    if t < 0 then
      redis.call('EXPIRE', KEYS[1], ttl)
      t = redis.call('TTL', KEYS[1])
      da_sua = 1
    end
    return {0, n, t, da_sua}
  end
end

redis.call('SET', KEYS[1], string.format('%d', counter), 'EX', ttl)
return {1, counter, redis.call('TTL', KEYS[1]), 0}
"""


# Đường LỖI của ba helper dưới đây KHÔNG được mang khoá vào log.
#
# ``mfa_used:{jti}`` chứa định danh của chính bằng chứng MFA, và nhánh log là
# nhánh chạy KHI REDIS SỰ CỐ — tức đúng lúc dễ xảy ra nhất, không phải một ca
# hiếm. ``key=key`` ở đó đẩy JTI đầy đủ vào log, nơi ai đọc được log cũng đọc
# được, và log sống lâu hơn cái token.
#
# Vì thế chỗ gọi truyền thêm ``nhan_khoa`` — một hằng mô tả LOẠI khoá
# ("mfa.token_claim", "mfa.totp_replay") — và chỉ nhãn ấy vào log.
#
# Cũng không ``exc_info=True``: message của ``ConnectionError`` từ redis-py có
# endpoint, mà ``REDIS_URL`` mang ``user:password``. Chỉ giữ TÊN LỚP exception,
# đủ để phân biệt mất kết nối với hết giờ. Cùng bài học với
# ``tests/integration/test_mfa_reservation_real_redis.py``.
#
# ⚠️ ``safe_redis_exists``/``safe_redis_set`` dùng chung KHÔNG bị đổi: chúng có
# hàng chục caller khác và việc đổi hành vi log của chúng nằm ngoài phạm vi
# bản vá này.


async def safe_redis_khoa_ton_tai(key: str, nhan_khoa: str) -> bool:
    """``EXISTS`` cho khoá NHẠY CẢM — đường lỗi chỉ log nhãn, không log khoá.

    Giống ``safe_redis_exists`` về ngữ nghĩa (lỗi ⇒ ``False``), khác đúng một
    điều: không bao giờ ghi ``key`` ra log. Dùng cho khoá mà bản thân tên khoá
    đã là thông tin cần giữ kín.

    Lỗi ⇒ ``False``, nghĩa là "không biết". Chỉ được dùng cho phép kiểm SỚM
    không có thẩm quyền; cổng quyết định phải là ``safe_redis_claim_once``.
    """
    try:
        return bool(await redis_breaker.call_async(redis_client.exists, key))
    except REDIS_BREAKER_EXCEPTIONS as exc:
        log.error(
            "Redis EXISTS failed", nhan_khoa=nhan_khoa, loai_loi=type(exc).__name__
        )
        return False
    except Exception as exc:
        # Phép kiểm SỚM không có thẩm quyền thì không được phép làm hỏng
        # request. Bản trước của nhánh này nằm ở router dưới dạng
        # ``except Exception: log`` — bỏ nó đi mà không thay thế sẽ biến một
        # lỗi Redis lạ (``ResponseError``, breaker mở, client bị patch trong
        # test) thành 500, thay vì để cổng có thẩm quyền ở dưới quyết định.
        log.error(
            "Redis EXISTS unexpected error",
            nhan_khoa=nhan_khoa, loai_loi=type(exc).__name__,
        )
        return False


async def safe_redis_consume_totp_counter(
    key: str, counter: int, ttl_seconds: int, nhan_khoa: str = "mfa.totp_replay"
):
    """Tiêu thụ MỘT time step TOTP — nguyên tử, đơn điệu, và fail closed.

    Chấp nhận khi và chỉ khi ``counter`` LỚN HƠN counter đã tiêu gần nhất.

    Returns:
        ``TieuThuTOTP(accepted, stored_counter, ttl)`` khi kết quả được CHỨNG
        MINH — gồm cả TTL dương. ``None`` ở MỌI ca còn lại: lỗi kết nối, script
        lỗi, kết quả thiếu/sai kiểu, counter đã lưu hỏng, hoặc TTL không dương.
        ``None`` ⇒ chỗ gọi phải TỪ CHỐI mã TOTP, không được coi là "chưa dùng".
    """
    # Kiểm đầu vào TRƯỚC khi chạm Redis: một ``key`` rỗng sẽ gom mọi người dùng
    # vào chung một khoá, còn counter âm/không nguyên thì script từ chối — nhưng
    # bắt lỗi ở đây cho thông báo đúng chỗ sai.
    if not isinstance(key, str) or not key:
        log.error("Redis TOTP consume: key rỗng hoặc sai kiểu")
        return None
    if not _la_so_nguyen(counter) or counter < 0:
        log.error("Redis TOTP consume: counter ngoài miền", nhan_khoa=nhan_khoa)
        return None
    if not _la_so_nguyen(ttl_seconds) or ttl_seconds < 1:
        log.error(
            "Redis TOTP consume: ttl ngoài miền",
            nhan_khoa=nhan_khoa, ttl=ttl_seconds,
        )
        return None

    try:
        raw = await redis_breaker.call_async(
            redis_client.eval,
            _LUA_TIEU_THU_TOTP,
            1,
            key,
            str(int(counter)),
            str(int(ttl_seconds)),
        )
    except REDIS_BREAKER_EXCEPTIONS as exc:
        log.error(
            "Redis TOTP consume failed",
            nhan_khoa=nhan_khoa, loai_loi=type(exc).__name__,
        )
        return None
    except Exception as exc:
        # Kể cả lỗi ngoài dự kiến (script lỗi, server không hỗ trợ EVAL) cũng
        # fail closed: đây là hàng rào chống phát lại, không phải cache.
        log.error(
            "Redis TOTP consume unexpected error",
            nhan_khoa=nhan_khoa, loai_loi=type(exc).__name__,
        )
        return None

    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        log.error(
            "Redis TOTP consume trả kết quả lạ",
            nhan_khoa=nhan_khoa, ket_qua=repr(raw),
        )
        return None
    if not all(_la_so_nguyen(x) for x in raw):
        log.error(
            "Redis TOTP consume trả sai kiểu",
            nhan_khoa=nhan_khoa, ket_qua=repr(raw),
        )
        return None

    ma, da_luu, ttl, da_sua_han = raw

    if ma == -1:
        log.error(
            "Redis TOTP consume: counter đã lưu hỏng, không parse được",
            nhan_khoa=nhan_khoa,
        )
        return None
    if ma == -2:
        log.error(
            "Redis TOTP consume: tham số không hợp lệ",
            nhan_khoa=nhan_khoa, counter=counter, ttl=ttl_seconds,
        )
        return None
    if ma not in (0, 1):
        log.error("Redis TOTP consume: mã trả về lạ", nhan_khoa=nhan_khoa, ma=ma)
        return None
    if ttl <= 0:
        # Không chứng minh được hạn ⇒ coi như chưa tiêu thụ được. Thà từ chối
        # còn hơn để lại một khoá không bao giờ tự hết.
        log.error("Redis TOTP consume: TTL không dương", nhan_khoa=nhan_khoa, ttl=ttl)
        return None
    if da_luu < 0:
        # Kiểm ĐỘC LẬP với Lua: nếu script bị thay hay Redis trả payload lạ,
        # tầng này vẫn phải từ chối.
        log.error("Redis TOTP consume: counter trả về ngoài miền", nhan_khoa=nhan_khoa)
        return None
    if da_sua_han not in (0, 1):
        # Cờ, không phải số đếm. Giá trị ngoài {0,1} nghĩa là payload không do
        # script này sinh ra — và khi đã không tin được một ô thì không có lý do
        # gì tin ba ô còn lại.
        log.error(
            "Redis TOTP consume: cờ sửa hạn ngoài miền",
            nhan_khoa=nhan_khoa, da_sua_han=da_sua_han,
        )
        return None

    # Quan hệ giữa ba ô phải TỰ NHẤT QUÁN. Kiểm bốn ô là int thôi thì chưa đủ:
    # một payload ``[1, counter-1, ttl, 0]`` vẫn lọt và trả ``accepted=True``
    # trong khi counter được ghi KHÔNG PHẢI counter ta vừa xin tiêu — tức lớp
    # chống phát lại tưởng đã tiêu bước N mà thực tế Redis giữ bước khác.
    if ma == 1 and da_luu != counter:
        log.error(
            "Redis TOTP consume: chấp nhận nhưng counter ghi được khác counter đã xin",
            nhan_khoa=nhan_khoa, counter=counter, da_luu=da_luu,
        )
        return None
    if ma == 0 and da_luu < counter:
        # Từ chối chỉ hợp lệ khi counter đã tiêu LỚN HƠN HOẶC BẰNG counter xin.
        log.error(
            "Redis TOTP consume: từ chối nhưng counter đã lưu nhỏ hơn counter đã xin",
            nhan_khoa=nhan_khoa, counter=counter, da_luu=da_luu,
        )
        return None

    if da_sua_han:
        log.warning(
            "totp_replay_key_missing_ttl_repaired",
            nhan_khoa=nhan_khoa, ttl=ttl, action="mfa.replay_ttl_repaired",
        )

    return TieuThuTOTP(accepted=(ma == 1), stored_counter=da_luu, ttl=ttl)


class KetQuaChiem(Enum):
    """Ba kết cục của một lần chiếm khoá dùng-một-lần.

    Ba, không phải hai. Bản trước chỉ có "đã dùng / chưa dùng" nên lượt Redis
    hỏng bị gộp vào "chưa dùng" và người gọi đi tiếp — fail open. Tách
    ``KHONG_CHUNG_MINH_DUOC`` ra buộc chỗ gọi phải xử lý ca ấy tường minh.
    """

    DA_CHIEM = "claimed"
    DA_BI_CHIEM = "already_claimed"
    KHONG_CHUNG_MINH_DUOC = "unavailable"


async def safe_redis_claim_once(
    key: str, value: str, ttl_seconds: int, nhan_khoa: str = "khoa_mot_lan"
) -> KetQuaChiem:
    """Chiếm MỘT lần duy nhất một khoá — ``SET NX EX``, fail closed.

    ``SET key value NX EX ttl`` là một lệnh, nên nó đã nguyên tử: đúng một
    trong nhiều request đồng thời nhận được ``True``. Không cần Lua ở đây —
    quyết định không phụ thuộc GIÁ TRỊ hiện tại, chỉ phụ thuộc SỰ TỒN TẠI.

    Returns:
        ``DA_CHIEM`` — request này là request duy nhất chiếm được khoá.
        ``DA_BI_CHIEM`` — ai đó đã chiếm trước.
        ``KHONG_CHUNG_MINH_DUOC`` — lỗi kết nối, breaker mở, tham số sai, hoặc
        Redis trả kiểu không nhận ra. Chỗ gọi phải TỪ CHỐI, không được đi tiếp.
    """
    if not isinstance(key, str) or not key:
        log.error("Redis CLAIM: key rỗng hoặc sai kiểu")
        return KetQuaChiem.KHONG_CHUNG_MINH_DUOC
    if not _la_so_nguyen(ttl_seconds) or ttl_seconds < 1:
        log.error("Redis CLAIM: ttl ngoài miền", nhan_khoa=nhan_khoa, ttl=ttl_seconds)
        return KetQuaChiem.KHONG_CHUNG_MINH_DUOC

    try:
        raw = await redis_breaker.call_async(
            redis_client.set, key, value, nx=True, ex=int(ttl_seconds)
        )
    except REDIS_BREAKER_EXCEPTIONS as exc:
        log.error(
            "Redis CLAIM failed",
            nhan_khoa=nhan_khoa, loai_loi=type(exc).__name__,
        )
        return KetQuaChiem.KHONG_CHUNG_MINH_DUOC
    except Exception as exc:
        log.error(
            "Redis CLAIM unexpected error",
            nhan_khoa=nhan_khoa, loai_loi=type(exc).__name__,
        )
        return KetQuaChiem.KHONG_CHUNG_MINH_DUOC

    # Đo trên redis-py 6.4.0 (25-08-2026), cả Redis 7 thật lẫn fakeredis:
    # đặt được → ``True`` · NX trượt → ``None``. ``False`` KHÔNG xuất hiện ở
    # phiên bản này, nhưng vẫn nhận nó như "đã có khoá": một client/phiên bản
    # khác trả ``False`` thì ngữ nghĩa vẫn là NX trượt, và đoán sai theo chiều
    # đó chỉ dẫn tới từ chối — an toàn. Mọi kiểu còn lại là thứ ta không diễn
    # giải được, và "không diễn giải được" phải rơi về fail closed chứ không
    # rơi về nhánh cho đi tiếp.
    if raw is True:
        return KetQuaChiem.DA_CHIEM
    if raw is None or raw is False:
        return KetQuaChiem.DA_BI_CHIEM

    log.error("Redis CLAIM trả kiểu lạ", nhan_khoa=nhan_khoa, ket_qua=repr(raw))
    return KetQuaChiem.KHONG_CHUNG_MINH_DUOC


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
