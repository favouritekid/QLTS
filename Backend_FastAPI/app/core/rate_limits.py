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
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from ..config import settings


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

# Initialize limiter with remote address as key (default)
# This rate limits based on client IP address
limiter = Limiter(key_func=get_remote_address, storage_uri=STORAGE_URI)


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

        # Fallback to IP if no user (shouldn't happen for authenticated endpoints)
        return get_remote_address(request)
    except Exception:
        # If anything fails, fallback to IP-based rate limiting
        return get_remote_address(request)


def get_intake_key(request: Request) -> str:
    """Rate-limit key cho website lead intake = HASH của header ``X-API-Key``.

    ``wp_remote_post`` gọi server-side nên mọi lead đến từ MỘT IP (server
    WordPress) → limit theo IP sẽ chặn nhầm toàn bộ traffic hợp lệ. Limit theo
    key thay vào đó (per-key bucket). KHÔNG nhúng API key thô vào key Redis (lộ
    secret trong keyspace) → hash SHA-256 trước (theo tiền lệ magic-link token).
    Verify tính hợp lệ của key là dependency riêng (401/503) chạy TRƯỚC limiter.
    """
    import hashlib

    api_key = request.headers.get("X-API-Key")
    if api_key:
        digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
        return f"intake_{digest}"
    return get_remote_address(request)


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
    AUTH_REFRESH_TOKEN = "20/hour" if settings.APP_ENV != "test" else "10000/hour"

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
    # Website lead intake (server-to-server từ WordPress). Vì wp_remote_post
    # chạy server-side → mọi lead chung 1 IP → KHÔNG dùng limit theo IP mà theo
    # API key (get_intake_key) với cap cao. Verify key là dependency riêng (401/503)
    # chạy TRƯỚC limiter nên chỉ request đã qua key mới bị đếm.
    PUBLIC_INTAKE = "500/hour" if settings.APP_ENV != "test" else "10000/hour"

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
