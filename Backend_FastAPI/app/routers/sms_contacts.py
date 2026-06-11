# app/routers/sms_contacts.py
"""
SMS Marketing — contact groups & contacts (admin only).
Stub PR-1; routes thêm ở **PR-2 (Codex)**: contact-groups CRUD + contacts
CRUD + membership + import. KHÔNG sửa main.py (đã wire ở PR-1).
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/sms", tags=["SMS Contacts"])
