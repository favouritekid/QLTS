"""Staff-facing Zalo Bot link API.

Three authenticated endpoints under ``/api/zalo-bot``:

- ``POST /link-code`` — generate a one-shot link code (TTL 600s).
  Rate-limited per user at 5 requests / 10 minutes via atomic INCR.
- ``GET /link-status`` — return whether the caller has an active bot
  binding plus display metadata. Never reveals other users' bindings.
- ``POST /unlink`` — deactivate the caller's binding and flip
  ``zalo_bot_enabled`` to ``False``.

All endpoints require ``get_current_active_user`` — anonymous access
is impossible. The link code is the only secret we hand back; the
chat_id is bound by the staff member typing it into Zalo, not by API.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.deps import get_current_active_user
from app.database import (
    get_db,
    safe_redis_expire,
    safe_redis_incr,
)
from app.utils.exceptions import BusinessRuleViolation

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/zalo-bot", tags=["Zalo Bot Link"])


# Per-user link-code throttle
_LINK_CODE_RL_PREFIX = "zalo_bot:ratelimit:link_code:"
_LINK_CODE_RL_LIMIT = 5  # requests
_LINK_CODE_RL_WINDOW = 600  # seconds (10 min)


async def _check_link_code_rate_limit(user_id: int) -> None:
    """Atomic INCR + EXPIRE — never use GET-then-SET (race window).

    Raises ``BusinessRuleViolation`` (400) on overflow. Redis breaker
    open returns ``None`` from INCR — we let the request through in
    that case rather than failing closed; quota cap on the link service
    side bounds total Redis writes either way.
    """
    key = f"{_LINK_CODE_RL_PREFIX}{user_id}"
    new_val = await safe_redis_incr(key)
    if new_val == 1:
        await safe_redis_expire(key, _LINK_CODE_RL_WINDOW)
    if new_val is not None and new_val > _LINK_CODE_RL_LIMIT:
        raise BusinessRuleViolation(
            "Quá nhiều yêu cầu. Vui lòng thử lại sau 10 phút."
        )


@router.post("/link-code")
async def generate_link_code(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Generate a fresh 6-char link code for the calling staff member.

    Returns the code, its TTL (10 minutes), and an instruction string
    suitable for copy-paste into Zalo.
    """
    from app.services import zalo_bot_link_service

    await _check_link_code_rate_limit(current_user.id)

    code, post_commit = await zalo_bot_link_service.generate_link_code(
        db, current_user.id
    )
    await db.commit()
    if post_commit:
        await post_commit()

    return {
        "code": code,
        "expires_in_seconds": 600,  # v5/E8: 10-min window for staff onboarding
        "instructions": (
            f"Mở Zalo, tìm bot QLTS, gửi: /lienkiet {code}"
        ),
    }


@router.get("/link-status")
async def get_link_status(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Return the calling user's bot binding state.

    Always returns a 200 with a stable shape — UI can render
    ``is_linked: false`` directly without checking 404.
    """
    from app.services import zalo_bot_link_service

    status = await zalo_bot_link_service.get_link_status(db, current_user.id)
    return status or {
        "is_linked": False,
        "display_name": None,
        "linked_at": None,
    }


@router.post("/unlink")
async def unlink_zalo_bot(
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Deactivate the caller's link and flip ``zalo_bot_enabled=False``.

    Idempotent — calling unlink on an already-unlinked user returns
    ``{"unlinked": false}`` without raising.
    """
    from app.services import zalo_bot_link_service

    ok, message = await zalo_bot_link_service.unlink(db, current_user.id)
    if ok:
        await db.commit()
    else:
        await db.rollback()
    return {"unlinked": ok, "message": message}
