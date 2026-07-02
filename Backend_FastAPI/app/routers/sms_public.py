# app/routers/sms_public.py
"""
SMS Marketing — public surface (no auth, CSRF-exempt dưới /api/public/). PR-5:
GET landing/{code} (read-only, no-store, noindex, no-referrer) + POST opt-out
(idempotent). PR-7 P2-2: session/program-view/heartbeat đo deep engagement
(§16). Router "dumb": commit (mutation) rồi trả. KHÔNG sửa main.py.
"""
from fastapi import APIRouter, Depends, Path, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.client_ip import get_client_ip
from app.core.rate_limits import RateLimits, limiter
from app.schemas import sms as sms_schemas
from app.services.sms_engagement_service import SmsEngagementService
from app.services.sms_landing_service import SmsLandingService

router = APIRouter(prefix="/api/public/sms", tags=["SMS Public"])

# Deep-engagement là traffic người thật từ landing → nhà mạng VN CGNAT chia IP
# egress cho nhiều thuê bao → trần rộng + key theo get_client_ip (XFF-aware,
# X-Real-IP nginx overwrite non-spoofable) chứ KHÔNG get_remote_address (=IP
# nginx → khoá global). nginx limit_req là lớp chặn DoS thật.
_SESSION_LIMIT = "600/hour"   # ~1 phiên/lượt xem landing
_VIEW_LIMIT = "2000/hour"     # khách mở nhiều trang ngành
_HEARTBEAT_LIMIT = "6000/hour"  # heartbeat ~15s × nhiều phiên/IP


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


# ---------------------------------------------------------------------
# Phase 2 (§16) — deep engagement tracking (session / view / heartbeat)
# ---------------------------------------------------------------------
@router.post(
    "/landing/{code}/session",
    response_model=sms_schemas.SmsSessionStartResponse,
)
@limiter.limit(_SESSION_LIMIT, key_func=get_client_ip)
async def start_session(
    request: Request,  # required by slowapi rate limiter + IP/UA
    response: Response,
    code: str = Path(..., max_length=64),
    db: AsyncSession = Depends(database.get_db),
):
    """Tạo phiên xem landing → sinh session_token raw TRẢ 1 LẦN (server lưu
    hash). Không tạo ở GET landing (tránh crawler/prefetch tạo phiên rác)."""
    result = await SmsEngagementService(db).start_session(
        code,
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        headers=request.headers,
    )
    await db.commit()
    _set_public_headers(response)
    return result


@router.post(
    "/landing/{code}/program-view",
    response_model=sms_schemas.SmsProgramViewResponse,
)
@limiter.limit(_VIEW_LIMIT, key_func=get_client_ip)
async def record_program_view(
    request: Request,  # required by slowapi rate limiter
    response: Response,
    payload: sms_schemas.SmsProgramViewRequest,
    code: str = Path(..., max_length=64),
    db: AsyncSession = Depends(database.get_db),
):
    """Mở 1 lượt xem trang ngành (snapshot tên ngành) — trả program_view_id để
    client đính vào heartbeat của trang đó."""
    result = await SmsEngagementService(db).record_program_view(code, payload)
    await db.commit()
    _set_public_headers(response)
    return result


@router.post(
    "/landing/{code}/heartbeat",
    response_model=sms_schemas.SmsHeartbeatResponse,
)
@limiter.limit(_HEARTBEAT_LIMIT, key_func=get_client_ip)
async def heartbeat(
    request: Request,  # required by slowapi rate limiter
    response: Response,
    payload: sms_schemas.SmsHeartbeatRequest,
    code: str = Path(..., max_length=64),
    db: AsyncSession = Depends(database.get_db),
):
    """Cộng dwell trang ngành (clamp wall-clock) → cập nhật interest_score."""
    result = await SmsEngagementService(db).heartbeat(code, payload)
    await db.commit()
    _set_public_headers(response)
    return result
