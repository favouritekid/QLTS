# app/ratelimit.py
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from .config import settings  # <-- BỔ SUNG IMPORT NÀY

# Sử dụng Redis URL từ settings, hoặc memory storage cho testing
# In test mode, use in-memory storage to avoid Redis dependency
if settings.APP_ENV == "test":
    STORAGE_URI = "memory://"
    # Very high limits for testing to avoid rate limit errors
    RATE_LIMITS = {
        "auth": "1000/minute",
        "register": "1000/minute",  # Same as auth in test mode
        "notifications": "10000/minute",  # Very high for tests
        "default": "10000/hour"
    }
    print(f"INFO [ratelimit.py]: Using in-memory storage for rate limiting (test mode)")
    print(f"INFO [ratelimit.py]: Test mode rate limits: {RATE_LIMITS}")
else:
    STORAGE_URI = settings.REDIS_URL
    # Production rate limits
    # ✅ SECURITY FIX (Phase 2): Stricter rate limit for registration to prevent enumeration
    # ✅ PHASE 1.1.1: Add rate limiting for notifications endpoint (Thundering Herd protection)
    RATE_LIMITS = {
        "auth": "5/minute",        # Login, forgot password, etc.
        "register": "3/minute",    # ✅ Stricter for registration (User Enumeration prevention)
        "notifications": "60/minute",  # ✅ PHASE 1.1.1: 60 requests/minute per user
        "default": "100/hour"
    }
    print(f"INFO [ratelimit.py]: Using Redis storage for rate limiting: {STORAGE_URI}")

limiter = Limiter(key_func=get_remote_address, storage_uri=STORAGE_URI)


# ✅ PHASE 1.1.1: Custom key function for per-user rate limiting
# This is used for authenticated endpoints where we want to rate limit per user, not per IP
def get_user_id_key(request: Request) -> str:
    """
    Get rate limit key based on user_id from JWT token.

    This allows rate limiting per authenticated user instead of per IP address,
    which is more accurate and prevents users from bypassing limits with VPN/proxy.

    Falls back to IP address if user is not authenticated (shouldn't happen for protected routes).
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
