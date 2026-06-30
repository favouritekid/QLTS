# app/routers/sms_reports.py
"""
SMS Marketing — reports click + dashboard CTR + opt-out admin (admin only).
PR-5. Router "dumb": dịch HTTP ↔ service, commit (mutation), không business
logic. Hard gate `require_admin`. KHÔNG sửa main.py (đã wire ở PR-1).
"""
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import require_admin
from app.schemas import sms as sms_schemas
from app.services.sms_report_service import SmsReportService

router = APIRouter(prefix="/api/sms", tags=["SMS Reports"])

_MAX_ID = 2147483647


@router.get("/reports/clicks", response_model=sms_schemas.SmsClickReport)
async def report_clicks(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
    granularity: str = Query("day", pattern="^(day|month|year)$"),
    campaign_id: Optional[int] = Query(None, ge=1, le=_MAX_ID),
    carrier: Optional[str] = Query(None, max_length=20),
    group_id: Optional[int] = Query(None, ge=1, le=_MAX_ID),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
):
    """Report click theo ngày/tháng/năm + CTR (distinct non-bot / handed_off)."""
    return await SmsReportService(db).click_report(
        granularity=granularity,
        campaign_id=campaign_id,
        carrier=carrier,
        group_id=group_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/campaigns/{campaign_id}/dashboard",
    response_model=sms_schemas.SmsCampaignDashboard,
)
async def campaign_dashboard(
    campaign_id: Annotated[int, Path(ge=1, le=_MAX_ID)],
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    """CTR + phân bố nhà mạng + danh sách số đã click của 1 campaign."""
    return await SmsReportService(db).dashboard(campaign_id)


@router.get("/opt-out", response_model=sms_schemas.SmsOptOutList)
async def list_opt_outs(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
    skip: int = Query(0, ge=0, le=_MAX_ID),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None, max_length=32),
    source: Optional[str] = Query(None, max_length=30),
):
    """Danh sách số từ chối nhận tin (suppression toàn cục)."""
    return await SmsReportService(db).list_opt_outs(
        skip=skip, limit=limit, search=search, source=source
    )


@router.post(
    "/opt-out/manual",
    response_model=sms_schemas.SmsOptOutOut,
    status_code=status.HTTP_201_CREATED,
)
async def manual_opt_out(
    payload: sms_schemas.SmsOptOutManualCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    """Admin ghi opt-out thủ công (đối tác/điện thoại/SMS reply)."""
    result = await SmsReportService(db).manual_opt_out(payload, current_user)
    await db.commit()
    return result
