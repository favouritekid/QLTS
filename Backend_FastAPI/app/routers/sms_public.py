# app/routers/sms_public.py
"""
SMS Marketing — public surface (no auth, CSRF-exempt dưới /api/public/).
Stub PR-1; routes thêm ở **PR-5 (Codex)**: GET landing/{code} (read-only,
no-store) + POST opt-out. KHÔNG sửa main.py (đã wire ở PR-1).
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/public/sms", tags=["SMS Public"])
