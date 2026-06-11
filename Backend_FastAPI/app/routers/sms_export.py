# app/routers/sms_export.py
"""
SMS Marketing — export Excel per nhà mạng + download + mark-handed-off (admin).
Stub PR-1; routes thêm ở **PR-4 (Codex)**. KHÔNG sửa main.py (đã wire ở PR-1).
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/sms", tags=["SMS Export"])
