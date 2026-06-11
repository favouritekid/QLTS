# app/routers/sms_campaigns.py
"""
SMS Marketing — campaigns + build + preflight (admin only).
Stub PR-1; routes thêm ở **PR-3 (Claude)**: campaigns CRUD + groups + build
+ preflight. KHÔNG sửa main.py (đã wire ở PR-1).
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/sms", tags=["SMS Campaigns"])
