"""
Rate limiting configuration for API endpoints.

This module defines rate limit tiers and initializes the slowapi limiter.
Rate limiting helps prevent DoS attacks and ensures fair resource usage.

Usage:
    from app.core.rate_limits import limiter, RateLimits, get_user_id_key

    @router.get("/endpoint")
    @limiter.limit(RateLimits.DATA_READ)
    async def endpoint(...):
        pass
"""
import jwt
from jwt.exceptions import PyJWTError as JWTError
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import settings
from .client_ip import get_client_ip

# Mã lỗi máy-đọc cho 429 do rate limit HẠ TẦNG (slowapi). Client dùng mã này
# để phân biệt với 429 nghiệp vụ — cụ thể `REFRESH_ABUSE_LOCKED` của
# ``/auth/refresh`` (xem ``app/routers/auth.py``), nơi backend ĐÃ thu hồi
# session nên client PHẢI đăng xuất. Chỉ mã dưới đây mới có nghĩa "tạm thời,
# giữ phiên và thử lại sau".
RATE_LIMITED_ERROR_CODE = "RATE_LIMITED"


# ============================================================================
# STORAGE CONFIGURATION
# ============================================================================

# Use Redis for production, in-memory for testing
if settings.APP_ENV == "test":
    STORAGE_URI = "memory://"
    print(f"INFO [rate_limits.py]: Using in-memory storage for rate limiting (test mode)")
else:
    STORAGE_URI = settings.REDIS_URL
    print(f"INFO [rate_limits.py]: Using Redis storage for rate limiting: {STORAGE_URI}")


# ============================================================================
# LIMITER INITIALIZATION
# ============================================================================

# Default key = REAL client IP via get_client_ip. It prefers X-Real-IP, which
# nginx sets to $remote_addr and OVERWRITES any client value → non-spoofable.
# NOT get_remote_address: under the prod topology (gunicorn forwarded_allow_ips="*"
# → uvicorn ProxyHeaders always_trust) it returns the LEFTMOST X-Forwarded-For hop,
# which nginx APPENDS ($proxy_add_x_forwarded_for) so a client can prepend a forged
# value → mint a fresh per-IP bucket per request and bypass brute-force / per-IP caps.
# get_client_ip also fixes SSR (server-rendered fetches bypass nginx but carry the
# X-Real-IP forwarded by serverFetch; get_remote_address would key on the frontend
# container IP). Every @limiter.limit inherits this default unless it passes key_func.
# in_memory_fallback_enabled: Redis là storage đếm rate-limit cho MỌI endpoint
# (gồm public landing /r/, session, heartbeat). Mặc định slowapi fail-CLOSED —
# Redis chết/đầy → lệnh storage raise → request 500 hàng loạt (SPOF). Bật fallback
# → khi Redis lỗi, tự chuyển sang bộ đếm IN-MEMORY (per-process) với CÙNG limits:
# landing không 500, và vẫn GIỮ enforcement (khác swallow_errors=tắt hẳn → hở
# brute-force auth). Redis lành lại thì tự quay về Redis. circuit-breaker
# redis_breaker (database.py) chỉ bọc safe_redis_*, KHÔNG bọc client nội bộ của
# slowapi → fallback này là lớp bảo vệ riêng cho rate-limit.
limiter = Limiter(
    key_func=get_client_ip,
    storage_uri=STORAGE_URI,
    in_memory_fallback_enabled=True,
)


# ============================================================================
# 429 RESPONSE HANDLER
# ============================================================================


def configure_rate_limiting(app) -> bool:
    """Gắn limiter + handler 429 vào app. PHẢI gọi ở MODULE LEVEL.

    🔴 KHÔNG được gọi trong ``lifespan``. Starlette dựng middleware stack ở
    lần ``__call__`` đầu tiên — chính là scope ``lifespan`` — và
    ``build_middleware_stack()`` COPY ``self.exception_handlers`` sang một dict
    mới đưa cho ``ExceptionMiddleware``. Mọi ``add_exception_handler`` chạy sau
    thời điểm đó chỉ sửa dict gốc và KHÔNG bao giờ có hiệu lực.

    Bằng chứng thực nghiệm (dev, 2026-07-30) khi handler còn đăng ký trong
    lifespan: request thứ 21 trả ``{"detail":"20 per 1 hour",
    "error_code":"HTTP_429"}`` — tức ``RateLimitExceeded`` (kế thừa Starlette
    ``HTTPException``) rơi vào ``http_exception_handler`` mặc định; câu tiếng
    Việt và header ``Retry-After`` chưa bao giờ xuất hiện.

    Trả về True nếu đã gắn (bỏ qua ở APP_ENV=test như trước).
    """
    if settings.APP_ENV == "test":
        return False
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    return True


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Body cho 429 do slowapi — LUÔN kèm ``error_code`` top-level.

    Đây là hàm module-level (không phải closure trong ``main.py``) để test
    khẳng định được contract mã lỗi mà không phải làm cạn một bucket thật.

    ``error_code`` bắt buộc vì client phân loại 429 theo mã, không theo chuỗi
    thông báo: chỉ ``RATE_LIMITED`` mới là "tạm thời, giữ phiên". Không có mã
    (hoặc mã khác) thì client coi là phiên đã chết và đăng xuất — fail-safe
    theo hướng an toàn.
    """
    # ⚠️ KHÔNG gọi `limiter._inject_headers(response, request.state.view_rate_limit)`:
    # đo thực tế (dev, 2026-07-30) cho thấy nó là NO-OP vì `Limiter(...)` không
    # bật `headers_enabled` — response chưa bao giờ có `Retry-After` /
    # `X-RateLimit-*`. Đổi lại, nó chạm hai mẩu state riêng tư của slowapi
    # (`app.state.limiter`, `request.state.view_rate_limit`) và cả hai được
    # evaluate TRƯỚC khi hàm kịp short-circuit; `State.__getattr__` ném
    # AttributeError khi thiếu key, mà exception ném từ trong một exception
    # handler thì không được ExceptionMiddleware bắt → 500 thay cho 429, đúng
    # trên endpoint mà cả thay đổi này sinh ra để bảo đảm contract 429.
    # Muốn có `Retry-After` thì bật `headers_enabled=True` ở Limiter trước.
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Quá nhiều yêu cầu. Vui lòng thử lại sau.",
            "error_code": RATE_LIMITED_ERROR_CODE,
        },
    )


# ============================================================================
# CUSTOM KEY FUNCTIONS
# ============================================================================

def get_user_id_key(request: Request) -> str:
    """
    Get rate limit key based on user_id from JWT token.

    This allows rate limiting per authenticated user instead of per IP address,
    which is more accurate and prevents users from bypassing limits with VPN/proxy.

    Falls back to IP address if user is not authenticated (shouldn't happen for protected routes).

    Usage:
        from app.core.rate_limits import limiter, RateLimits, get_user_id_key

        # Create user-specific limiter
        user_limiter = Limiter(key_func=get_user_id_key, storage_uri=STORAGE_URI)

        @router.get("/endpoint")
        @user_limiter.limit(RateLimits.DATA_READ)
        async def endpoint(...):
            pass
    """
    try:
        # Get user from request state (set by JWT authentication middleware)
        if hasattr(request.state, "user") and request.state.user:
            user_id = request.state.user.id
            return f"user_{user_id}"

        # Fallback to the REAL client IP (non-spoofable X-Real-IP) — NOT
        # get_remote_address, whose leftmost-XFF value is client-spoofable. Should
        # not happen on authenticated routes (get_current_user sets request.state.user).
        return get_client_ip(request)
    except Exception:
        # If anything fails, fall back to the non-spoofable client IP.
        return get_client_ip(request)


def get_refresh_identity_key(request: Request) -> str:
    """Khoá rate-limit cho ``POST /auth/refresh``: theo NGƯỜI DÙNG nếu chứng
    minh được, không thì theo IP.

    ``/auth/refresh`` không đi qua ``get_current_user`` (nó chạy TRƯỚC khi có
    access token hợp lệ) nên ``request.state.user`` luôn trống — ``get_user_id_key``
    ở trên vô dụng ở đây và mọi request rơi về IP. Audit prod 2026-07-30: cả
    trường ra Internet qua MỘT IP NAT, nên hạn mức 20/giờ theo IP là quota
    CHUNG cho toàn bộ nhân sự — 32% request refresh (86/270 trong 24h) bị chặn,
    và mỗi lần chặn là một officer bị đá ra giữa lúc nhập liệu.

    Danh tính chỉ được công nhận khi ĐỦ SÁU điều kiện, vì khoá này quyết định
    hạn mức nào được áp:

    1. có cookie ``refresh_token``;
    2. ``jwt.decode`` với ``algorithms`` TƯỜNG MINH — thiếu tham số này là mở
       đường cho token ``alg: none``, và khi đó bất kỳ ai cũng tự đúc được một
       ``sub`` để mượn xô 120/giờ của người khác (hoặc để mỗi request một xô mới);
    3. còn hạn — ``jwt.decode`` tự kiểm ``exp`` và ném ``ExpiredSignatureError``;
    4. ``type == "refresh"`` — không nhận access token;
    5. ``sub`` không rỗng;
    6. ``jti`` không rỗng.

    Sai bất kỳ điều nào → về khoá IP. Fail-safe theo hướng SIẾT: token không
    chứng minh được danh tính thì phải chịu hạn mức chặt hơn, không được
    hưởng hạn mức rộng.
    """
    ip_key = f"refresh:ip:{get_client_ip(request)}"
    try:
        token = request.cookies.get("refresh_token")
        if not token:
            return ip_key

        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        if payload.get("type") != "refresh":
            return ip_key

        sub = payload.get("sub")
        jti = payload.get("jti")
        if not sub or not jti:
            return ip_key

        return f"refresh:user:{sub}"
    except JWTError:
        # Hết hạn / chữ ký sai / payload hỏng — không chứng minh được danh tính.
        return ip_key
    except Exception:
        # Bất kỳ sự cố nào khác (cookie dị dạng, settings thiếu…) cũng phải trả
        # về một khoá hợp lệ: ném ra từ key_func sẽ làm hỏng cả request.
        return ip_key


def refresh_limit(key: str) -> str:
    """Hạn mức động cho ``/auth/refresh`` theo loại khoá.

    ⚠️ Tham số PHẢI tên là ``key``: ``slowapi/wrappers.py:86`` kiểm
    ``"key" in inspect.signature(limit_provider).parameters`` để quyết định gọi
    ``limit_provider(key_func(request))`` hay ``limit_provider()``. Đổi tên
    tham số là lặng lẽ rơi về nhánh không-đối-số và ``TypeError`` lúc chạy.

    Hai hạn mức lấy thẳng từ ``RateLimits`` (đọc lúc GỌI, nên không vướng thứ
    tự định nghĩa trong tệp) — không chép lại con số ở đây, kẻo sửa một nơi mà
    nơi kia ở lại.
    """
    if key.startswith("refresh:user:"):
        return RateLimits.AUTH_REFRESH_TOKEN_IDENTIFIED
    return RateLimits.AUTH_REFRESH_TOKEN


# ============================================================================
# RATE LIMIT TIERS
# ============================================================================

class RateLimits:
    """
    Standard rate limit tiers for different endpoint types.

    Tiers are designed based on endpoint sensitivity and expected usage patterns:
    - Authentication: Strict limits to prevent brute force attacks
    - Admin: Moderate limits for privileged operations
    - User Data: Higher limits for normal operations
    - Public: Lower limits for unauthenticated access
    - Realtime: High limits for notification/websocket endpoints

    Usage in test mode:
    - All limits are significantly higher to avoid failures in automated tests
    - Test mode is detected via settings.APP_ENV == "test"
    """

    # ============================================================================
    # AUTHENTICATION ENDPOINTS (STRICT)
    # ============================================================================
    # Very strict limits to prevent brute force attacks

    AUTH_LOGIN = "5/minute" if settings.APP_ENV != "test" else "1000/minute"
    AUTH_REGISTER = "3/minute" if settings.APP_ENV != "test" else "1000/minute"
    AUTH_PASSWORD_RESET = "3/hour" if settings.APP_ENV != "test" else "10000/hour"
    AUTH_PASSWORD_CHANGE = "10/hour" if settings.APP_ENV != "test" else "10000/hour"
    # ``POST /auth/refresh`` KHÔNG dùng trực tiếp hằng nào dưới đây — nó đi qua
    # ``refresh_limit(key)``, hàm này chọn một trong hai tuỳ khoá chứng minh
    # được danh tính hay không. Đây vẫn là nơi duy nhất giữ hai con số.
    #
    # Nhánh IP: request KHÔNG chứng minh được là ai. Siết như cũ.
    AUTH_REFRESH_TOKEN = "20/hour" if settings.APP_ENV != "test" else "10000/hour"
    # Nhánh chủ thể: ANOMALY_MAX_SESSIONS_PER_USER = 10 phiên × refresh chủ động
    # ~4.6 lần/giờ/phiên ≈ 46 lần nền, cộng bootstrap + reactive 401 +
    # CSRF-recovery, chừa biên ~2×.
    AUTH_REFRESH_TOKEN_IDENTIFIED = (
        "120/hour" if settings.APP_ENV != "test" else "10000/hour"
    )

    # ============================================================================
    # ADMIN ENDPOINTS (MODERATE)
    # ============================================================================
    # Moderate limits for privileged operations

    ADMIN_READ = "300/hour" if settings.APP_ENV != "test" else "10000/hour"
    ADMIN_WRITE = "100/hour" if settings.APP_ENV != "test" else "10000/hour"
    ADMIN_BULK = "10/hour" if settings.APP_ENV != "test" else "1000/hour"
    ADMIN_DELETE = "50/hour" if settings.APP_ENV != "test" else "10000/hour"

    # ============================================================================
    # USER DATA ENDPOINTS (NORMAL)
    # ============================================================================
    # Higher limits for normal CRUD operations

    DATA_READ = "1000/hour" if settings.APP_ENV != "test" else "10000/hour"
    DATA_WRITE = "200/hour" if settings.APP_ENV != "test" else "10000/hour"
    DATA_EXPORT = "20/hour" if settings.APP_ENV != "test" else "1000/hour"
    DATA_SEARCH = "500/hour" if settings.APP_ENV != "test" else "10000/hour"

    # ============================================================================
    # PUBLIC ENDPOINTS (RESTRICTED)
    # ============================================================================
    # Lower limits for unauthenticated access

    PUBLIC_READ = "100/hour" if settings.APP_ENV != "test" else "10000/hour"
    PUBLIC_CONTACT = "5/hour" if settings.APP_ENV != "test" else "1000/hour"

    # ============================================================================
    # REAL-TIME ENDPOINTS (HIGH)
    # ============================================================================
    # High limits for notification and WebSocket endpoints

    REALTIME = "500/hour" if settings.APP_ENV != "test" else "10000/hour"
    NOTIFICATION_READ = "1000/hour" if settings.APP_ENV != "test" else "10000/hour"
    NOTIFICATION_WRITE = "100/hour" if settings.APP_ENV != "test" else "10000/hour"

    # ============================================================================
    # FILE UPLOAD ENDPOINTS (VERY STRICT)
    # ============================================================================
    # Very strict limits for file uploads to prevent abuse

    FILE_UPLOAD = "20/hour" if settings.APP_ENV != "test" else "1000/hour"
    FILE_UPLOAD_BULK = "5/hour" if settings.APP_ENV != "test" else "1000/hour"

    # ============================================================================
    # REPORTING ENDPOINTS (MODERATE)
    # ============================================================================
    # Moderate limits for analytics and reporting

    REPORT_GENERATE = "30/hour" if settings.APP_ENV != "test" else "10000/hour"
    ANALYTICS_READ = "200/hour" if settings.APP_ENV != "test" else "10000/hour"

    # ============================================================================
    # LEGACY COMPATIBILITY
    # ============================================================================
    # For backward compatibility with existing code

    NOTIFICATIONS = "60/minute" if settings.APP_ENV != "test" else "10000/minute"  # Legacy
    DEFAULT = "100/hour" if settings.APP_ENV != "test" else "10000/hour"  # Legacy
