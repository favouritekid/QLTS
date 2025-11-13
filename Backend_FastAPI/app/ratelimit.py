# app/ratelimit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings  # <-- BỔ SUNG IMPORT NÀY

# Sử dụng Redis URL từ settings, hoặc memory storage cho testing
# In test mode, use in-memory storage to avoid Redis dependency
if settings.APP_ENV == "test":
    STORAGE_URI = "memory://"
    # Very high limits for testing to avoid rate limit errors
    RATE_LIMITS = {
        "auth": "1000/minute",
        "register": "1000/minute",  # Same as auth in test mode
        "default": "10000/hour"
    }
    print(f"INFO [ratelimit.py]: Using in-memory storage for rate limiting (test mode)")
    print(f"INFO [ratelimit.py]: Test mode rate limits: {RATE_LIMITS}")
else:
    STORAGE_URI = settings.REDIS_URL
    # Production rate limits
    # ✅ SECURITY FIX (Phase 2): Stricter rate limit for registration to prevent enumeration
    RATE_LIMITS = {
        "auth": "5/minute",        # Login, forgot password, etc.
        "register": "3/minute",    # ✅ Stricter for registration (User Enumeration prevention)
        "default": "100/hour"
    }
    print(f"INFO [ratelimit.py]: Using Redis storage for rate limiting: {STORAGE_URI}")

limiter = Limiter(key_func=get_remote_address, storage_uri=STORAGE_URI)
