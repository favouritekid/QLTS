# app/routers/sms_shortlink.py
"""
SMS Marketing — short-link resolver. Route GET /r/{code} (về backend, qua
nginx location /r/). Stub PR-1; route thêm ở **PR-5 (Codex)**: resolve +
rate-limit + click event + 302 redirect. KHÔNG sửa main.py (đã wire ở PR-1).
"""
from fastapi import APIRouter

router = APIRouter(tags=["SMS Shortlink"])
