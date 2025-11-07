# app/ratelimit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings  # <-- BỔ SUNG IMPORT NÀY

# Sử dụng Redis URL từ settings, hoặc memory storage cho testing
# In test mode, use in-memory storage to avoid Redis dependency
if settings.APP_ENV == "test":
    STORAGE_URI = "memory://"
    print(f"INFO [ratelimit.py]: Using in-memory storage for rate limiting (test mode)")
else:
    STORAGE_URI = settings.REDIS_URL
    print(f"INFO [ratelimit.py]: Using Redis storage for rate limiting: {STORAGE_URI}")

limiter = Limiter(key_func=get_remote_address, storage_uri=STORAGE_URI)

RATE_LIMITS = {"auth": "5/minute", "default": "100/hour"}
