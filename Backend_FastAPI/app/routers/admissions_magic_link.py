"""PR-CO-2-BE / PR-3E (Phase 3 close-out plan v2 LOCKED 2026-05-14):
multi-action magic-link consume router.

Sibling of the legacy single-action ``/api/admissions/confirm/{token}``
endpoint (kept in ``admissions.py`` for backward compatibility). This
v2 surface accepts a typed action enum in the path, routes to
``magic_link_service.consume_token``, and returns a uniform response
shape for the FE landing pages in PR-CO-2-FE.

PUBLIC ENDPOINT — no authentication required. Security comes from:
- 256-bit URL-safe token (impossible to guess)
- CCCD verification (constant-time ``hmac.compare_digest``)
- Per-token rate limit (5/60s, Redis ``mlt:{token}``, fail-closed)
- ADM-023 CCCD brute-force cooldown ladder (preserved from legacy flow)
- Global + per-IP slowapi limits (DATA_WRITE + 100/day per IP)
- CSRF-exempt prefix (registered in ``middleware/csrf.py``)
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database
from ..core.events import SystemEvents
from ..core.rate_limits import limiter, RateLimits
# Hotfix R8: XFF-aware client IP so the ``100/day`` per-IP cap really
# keys off the candidate's IP rather than the nginx container.
from ..core.client_ip import get_client_ip
from ..schemas.magic_link import (
    MagicLinkAction,
    MagicLinkConsumeRequest,
    MagicLinkConsumeResponse,
)
from ..services import magic_link_service
from ..services.notification_dispatcher import (
    rooms_for_admission,
    safe_dispatch,
)
from ..utils.exceptions import BadRequest, ResourceNotFoundError

log = structlog.get_logger(__name__)


router = APIRouter(
    prefix="/api/v2/admissions/magic-link",
    tags=["admissions-v2-magic-link"],
)


@router.post(
    "/{action}/{token}",
    response_model=MagicLinkConsumeResponse,
    summary="Consume a magic-link token (4-action: submit | resubmit | confirm | withdraw)",
    description="""
    Multi-action public magic-link consume endpoint. The ``{action}`` path
    parameter MUST match the token row's ``action_type`` — mismatch
    returns 404 (does not leak token existence).

    **Workflow** (per action, infrastructure shared):
      1. Per-token rate limit (5/60s, Redis ``mlt:{token}``, fail-closed)
      2. ADM-013 profile-first 3-step row lock
      3. Action enum match + freshness gates (expired/used/locked)
      4. CCCD constant-time compare (last 4 digits)
      5. Dispatch action handler (confirm wired; submit/resubmit/withdraw
         currently 501 — FU PR-CO-2-BE-2)

    **CSRF**: this endpoint is CSRF-exempt by allowlist
    (``middleware/csrf.py``) since candidates do not hold a CSRF cookie.

    **Wave A acceptance gate**: "Magic-link confirm consume atomic" — the
    ADM-013 lock + ``confirmed_at IS NULL`` predicate at consume time
    serialise concurrent consumes to a single winner.
    """,
)
@limiter.limit(RateLimits.DATA_WRITE)
@limiter.limit("100/day", key_func=get_client_ip)
async def consume_magic_link_token(
    request: Request,
    action: MagicLinkAction,
    token: str,
    body: MagicLinkConsumeRequest,
    db: AsyncSession = Depends(database.get_db),
) -> MagicLinkConsumeResponse:
    """Public endpoint — see route docstring for full behaviour."""
    try:
        profile, callback = await magic_link_service.consume_token(
            db=db,
            token_value=token,
            cccd_last4=body.cccd,
            action=action.value,
        )

        # Persist the consume + any state-machine mutations the action
        # handler made (e.g. ``confirmed_at``, ``status`` transition).
        await db.commit()
        await db.refresh(profile)

        # Post-commit notification fanout. The callback is the proven
        # `verify_and_confirm` hand-off from the legacy confirm flow.
        if callback is not None:
            await callback()

        # Hotfix R1: parity with legacy POST /api/admissions/confirm/{token}
        # (admissions.py:2160-2174) — broadcast APPLICATION_STATUS_CHANGED so
        # officer / admin / socket clients see the status flip realtime. The
        # legacy callback only handles the candidate-facing notification; the
        # status fanout is a separate concern.
        # Officer-facing rooms are computed from the freshly committed
        # ``profile`` (we've already refreshed above), so realtime listeners
        # observe ``status='confirmed'`` consistent with the persisted state.
        if action == MagicLinkAction.CONFIRM and profile.lead_id:
            await safe_dispatch(
                db=db,
                event=SystemEvents.APPLICATION_STATUS_CHANGED,
                payload={
                    "application_id": profile.id,
                    "lead_id": profile.lead_id,
                    "old_status": "approved",
                    "new_status": "confirmed",
                    "actor_id": 0,
                    "actor_name": "Ứng viên xác nhận",
                },
                dedupe_key=f"admission_profile_confirmed:{profile.id}",
                rooms=rooms_for_admission(profile),
            )

        return MagicLinkConsumeResponse(
            message="Yêu cầu đã được xử lý thành công.",
            profile_id=profile.id,
            action=action,
            status=profile.status,
            consumed_at=(
                profile.confirmed_at
                if profile.confirmed_at is not None
                else profile.updated_at
            ),
            next_url=None,  # FE picks destination per action
        )

    except ResourceNotFoundError as e:
        # 404 covers both "token does not exist" and "action enum
        # mismatch" — same response by design (no enumeration).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )
    except BadRequest as e:
        # Commit any mutations the service applied before raising
        # (cooldown ladder updates, lock_until, hard-lock audit row).
        # Mirrors the legacy confirm router's pattern.
        await db.commit()
        post_commit = getattr(e, "post_commit_callback", None)
        if post_commit is not None:
            try:
                await post_commit()
            except Exception as cb_err:  # noqa: BLE001 — best-effort
                log.error(
                    "Magic-link post-commit callback failed (best-effort)",
                    error=str(cb_err),
                    token_prefix=token[:8],
                    action=action.value,
                )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
