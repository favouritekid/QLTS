# app/routers/sms_public.py
"""
SMS Marketing — public surface (no auth, CSRF-exempt dưới /api/public/). PR-5:
GET landing/{code} (read-only, no-store, noindex, no-referrer) + POST opt-out
(idempotent). Router "dumb": commit (opt-out) rồi trả. KHÔNG sửa main.py.
"""
from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.client_ip import get_client_ip
from app.core.rate_limits import RateLimits, limiter
from app.schemas import sms as sms_schemas
from app.services.sms_landing_service import SmsLandingService

router = APIRouter(prefix="/api/public/sms", tags=["SMS Public"])


def _set_public_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex"
    response.headers["Referrer-Policy"] = "no-referrer"


@router.get("/landing/{code}", response_model=sms_schemas.SmsLandingResponse)
@limiter.limit(RateLimits.PUBLIC_READ, key_func=get_client_ip)
async def get_landing(
    request: Request,  # required by slowapi rate limiter
    response: Response,
    code: str = Path(..., max_length=64),
    db: AsyncSession = Depends(database.get_db),
):
    """Nội dung landing — read-only, KHÔNG ghi click (đã ghi ở /r/), KHÔNG lộ
    PII recipient. 404 generic nếu code sai/hết hạn."""
    result = await SmsLandingService(db).get_landing(code)
    _set_public_headers(response)
    return result


@router.post("/opt-out", response_model=sms_schemas.SmsPublicOptOutResponse)
@limiter.limit(RateLimits.PUBLIC_READ, key_func=get_client_ip)
async def public_opt_out(
    request: Request,  # required by slowapi rate limiter
    response: Response,
    payload: sms_schemas.SmsPublicOptOutRequest,
    db: AsyncSession = Depends(database.get_db),
):
    """Opt-out công khai từ landing — idempotent (UNIQUE phone)."""
    result = await SmsLandingService(db).public_opt_out(payload.code)
    await db.commit()
    _set_public_headers(response)
    return result
