"""Public lead intake endpoint cho website tuyển sinh (WordPress/Formidable).

KHÔNG yêu cầu đăng nhập. Bảo vệ bằng header ``X-API-Key`` (dependency
``verify_intake_api_key`` ở ``core/deps.py`` chạy TRƯỚC limiter → 401/503 xảy ra
trước khi đếm rate-limit). Rate-limit theo API key đã hash (``get_intake_key``)
với cap cao vì ``wp_remote_post`` gọi server-side (mọi lead chung 1 IP). Xem
``Documents/WEBSITE_LEAD_INTAKE_PLAN.md``.
"""

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, schemas
from app.core.deps import verify_intake_api_key
from app.core.rate_limits import RateLimits, get_intake_key, limiter
from app.services import public_lead_intake_service

log = structlog.get_logger("public_leads")

router = APIRouter(prefix="/api/public/leads", tags=["Public Lead Intake"])


@router.post(
    "/intake",
    response_model=schemas.PublicLeadIntakeAck,
    dependencies=[Depends(verify_intake_api_key)],
)
@limiter.limit(RateLimits.PUBLIC_INTAKE, key_func=get_intake_key)
async def intake_public_lead(
    request: Request,
    payload: schemas.PublicLeadIntake,
    db: AsyncSession = Depends(database.get_db),
):
    """Nhận 1 lead từ website. Upsert-by-phone, auto-assign khi tạo mới.

    Honeypot + toàn bộ quyết định nằm ở service (router chỉ I/O + commit). Trả
    response GENERIC (``received``) — KHÔNG lộ created/updated/noted/lead_id thật
    ra caller công khai (chống enumeration ứng viên theo SĐT).
    """
    result, post_commit = await public_lead_intake_service.intake_public_lead(
        db, payload
    )
    await db.commit()
    if post_commit:
        # Best-effort: lỗi fanout SAU commit KHÔNG được làm 500 (business đã lưu;
        # WP retry sẽ idempotent qua upsert/dedup → tránh note/notif trùng).
        try:
            await post_commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("intake post-commit fanout failed", error=str(exc))
    log.info("intake processed", status=result.status, lead_id=result.lead_id)
    return schemas.PublicLeadIntakeAck()
