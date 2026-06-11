# app/routers/sms_reports.py
"""
SMS Marketing — reports click ngày/tháng/năm + dashboard CTR (admin).
Stub PR-1; routes thêm ở **PR-5 (Codex)**. KHÔNG sửa main.py (đã wire ở PR-1).
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/sms", tags=["SMS Reports"])
