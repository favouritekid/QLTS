# app/ratelimit.py
from slowapi import Limiter
from slowapi.util import get_remote_address

from .config import settings  # <-- BỔ SUNG IMPORT NÀY

# Sử dụng Redis URL từ settings
REDIS_URL = settings.REDIS_URL  # <-- THAY ĐỔI Ở ĐÂY

limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL)

RATE_LIMITS = {"auth": "5/minute", "default": "100/hour"}
