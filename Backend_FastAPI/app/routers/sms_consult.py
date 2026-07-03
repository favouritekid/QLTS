# app/routers/sms_consult.py
"""
SMS Marketing — consult officer (P2-3 §16.7). Officer tạo link tư vấn 1-1 cho
lead trong phạm vi mình + xem hồ sơ 'quan tâm ngành' của lead. Router "dumb":
commit (mutation) rồi trả. KHÔNG sửa main.py logic (chỉ đăng ký router).

Gate 2 tầng: `CasbinAuth` (RBAC path-level — officer có policy) + `get_lead_for_user`
(IDOR resource-level — officer chỉ lead được giao; ngoài phạm vi → 404).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import CasbinAuth, get_lead_for_user
from app.schemas import sms as sms_schemas
from app.services.sms_consult_service import SmsConsultService

router = APIRouter(prefix="/api/sms", tags=["SMS Consult"])


@router.post(
    "/leads/{lead_id}/consult-link",
    response_model=sms_schemas.SmsConsultLinkResponse,
)
async def create_consult_link(
    lead: models.Lead = Depends(get_lead_for_user),
    current_user: models.User = CasbinAuth,
    db: AsyncSession = Depends(database.get_db),
):
    """Sinh consult link cho lead → trả raw `code`/`url` 1 LẦN (copy gửi Zalo)."""
    result = await SmsConsultService(db).create_consult_link(lead, current_user)
    await db.commit()
    return result


@router.get(
    "/leads/{lead_id}/interests",
    response_model=sms_schemas.SmsLeadInterestResponse,
)
async def get_lead_interests(
    lead: models.Lead = Depends(get_lead_for_user),
    current_user: models.User = CasbinAuth,
    db: AsyncSession = Depends(database.get_db),
):
    """Hồ sơ 'quan tâm ngành' của lead (qua contact match phone) — read-only."""
    return await SmsConsultService(db).lead_interests(lead)
