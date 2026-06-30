# app/routers/sms_shortlink.py
"""
SMS Marketing — short-link resolver. Route GET /r/{code} (về backend, qua
nginx location /r/). PR-5: resolve token → ghi click + 302 redirect, public
(không auth), rate-limit theo IP. Router "dumb": commit rồi trả 302.
KHÔNG sửa main.py (đã wire ở PR-1).
"""
from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.client_ip import get_client_ip
from app.core.rate_limits import limiter
from app.services.sms_tracking_service import SmsTrackingService

router = APIRouter(tags=["SMS Shortlink"])

# /r/ là endpoint CLICK của người thật từ SMS → nhà mạng VN CGNAT chia IP
# egress cho hàng nghìn thuê bao; trần phải rộng + KEY THEO get_client_ip
# (XFF-aware) chứ KHÔNG get_remote_address (= IP nginx → khoá global). nginx
# limit_req zone=general là lớp chặn DoS thật.
_SHORTLINK_LIMIT = "2000/hour"

# Bearer URL công khai → mọi response no-referrer/no-store/noindex (§6.1).
_SEC_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex",
}


@router.get("/r/{code}")
@limiter.limit(_SHORTLINK_LIMIT, key_func=get_client_ip)
async def resolve_shortlink(
    request: Request,  # required by slowapi rate limiter + IP/UA
    code: str = Path(..., max_length=64),
    db: AsyncSession = Depends(database.get_db),
) -> RedirectResponse:
    """Resolve /r/{code} → ghi click (bot eval) → 302. Code sai/không thấy/hết
    hạn → 404 generic (service raise ResourceNotFoundError)."""
    target = await SmsTrackingService(db).resolve(
        code,
        ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        headers=request.headers,
    )
    await db.commit()
    resp = RedirectResponse(url=target, status_code=302)
    for k, v in _SEC_HEADERS.items():
        resp.headers[k] = v
    return resp
