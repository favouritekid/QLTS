from app.core.rate_limits import limiter, RateLimits
# app/routers/sessions.py
"""
API endpoints for managing user sessions.
Allows users to view active sessions, revoke specific sessions, and revoke all other sessions.

✅ PHASE 7: Removed generic except Exception blocks per MASTER_ARCHITECTURE.
Global exception handlers in middleware/exception_handlers.py handle all errors.
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database
from .. import models, schemas
from ..core import deps
from ..services import session_service
from ..utils.exceptions import SessionNotFoundError

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("", response_model=schemas.UserSessionListResponse)
async def get_active_sessions(
    request: Request,
    current_user: models.User = Depends(deps.get_current_user),
    current_session: Optional[models.UserSession] = Depends(deps.get_current_session),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Get all active sessions for the current user.

    Security:
        - Requires authentication
        - Users can only see their own sessions
        - Current session = ``deps.get_current_session`` (the ``r_jti`` of the
          authenticated access token) — the same source ``POST /revoke-all``
          uses to pick the session it keeps.
    """
    log.info("Fetching active sessions", user_id=current_user.id)

    # Cookie fallback removed: ``get_current_user`` refuses any access token
    # without ``r_jti`` and always sets ``request.state.refresh_jti``, so the
    # old "decode the refresh cookie" branch was unreachable — and it trusted
    # the cookie without checking its type or ``sub``.
    current_refresh_jti = (
        current_session.refresh_jti if current_session is not None else None
    )

    # Fetch sessions from service
    db_sessions = await session_service.get_active_sessions(
        db,
        current_user.id,
        current_refresh_jti=current_refresh_jti,
    )
    log.info(
        "Active sessions retrieved",
        user_id=current_user.id,
        session_count=len(db_sessions),
    )

    # Transform to response schema
    current_session_id = None
    response_sessions = [
        schemas.UserSessionResponse.model_construct(
            **{c.name: getattr(session, c.name) for c in session.__table__.columns},
            is_current=bool(
                current_refresh_jti and 
                session.refresh_jti == current_refresh_jti
            )
        )
        for session in db_sessions
    ]

    for s in response_sessions:
        if s.is_current:
            current_session_id = s.id
            break

    return schemas.UserSessionListResponse(
        sessions=response_sessions,
        total=len(response_sessions),
        current_session_id=current_session_id,
    )


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    request: Request,
    session: models.UserSession = Depends(deps.get_session_for_user),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Revoke a specific session.

    Security:
        - Requires authentication
        - IDOR protection via get_session_for_user dependency (returns 404 if not owned)

    Raises:
        404: Session not found or doesn't belong to user
    """
    log.info("Revoking session", user_id=current_user.id, session_id=session.id)

    success, callback = await session_service.revoke_session(
        db=db,
        session_id=session.id,
        user_id=current_user.id
    )

    if not success:
        log.warning(
            "Session already revoked",
            user_id=current_user.id,
            session_id=session.id,
        )
        raise SessionNotFoundError(detail="Session not found or already revoked")

    await db.commit()

    if callback:
        await callback()

    log.info(
        "Session revoked successfully",
        user_id=current_user.id,
        session_id=session.id,
    )

    return None  # 204 No Content


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post("/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_other_sessions(
    request: Request,
    request_data: Optional[schemas.RevokeAllSessionsRequest] = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    current_session: Optional[models.UserSession] = Depends(deps.get_current_session),
):
    """
    Revoke every other session of the current user, KEEPING the one this
    request authenticated with.

    The kept session is ``deps.get_current_session`` — the live session named
    by the ``r_jti`` of the validated access token — never the body. The body
    (``current_session_id``) is still accepted so the current frontend does not
    break, but it decides nothing: a different value is only logged.

    Current session not resolvable (revoked / expired between
    ``get_current_user`` and this lookup) ⇒ every live session of the user is
    revoked; the body is NOT used as a fallback.

    Returns:
        204 No Content on success
    """
    keep_session_id = current_session.id if current_session is not None else None
    claimed_session_id = (
        request_data.current_session_id if request_data is not None else None
    )

    if claimed_session_id is not None and claimed_session_id != keep_session_id:
        log.warning(
            "revoke-all: body current_session_id ignored; kept session comes from the token",
            user_id=current_user.id,
            kept_session_id=keep_session_id,
            claimed_session_id=claimed_session_id,
            action="session.revoke_all_body_ignored",
        )
    if keep_session_id is None:
        log.warning(
            "revoke-all: current session not resolved; revoking every live session",
            user_id=current_user.id,
            action="session.revoke_all_current_unresolved",
        )

    log.info(
        "Revoking all other sessions",
        user_id=current_user.id,
        kept_session_id=keep_session_id,
    )

    revoked_count, callback = await session_service.revoke_all_other_sessions(
        db=db,
        user_id=current_user.id,
        except_session_id=keep_session_id,
    )

    await db.commit()
    
    if callback:
        await callback()

    log.info(
        "All other sessions revoked",
        user_id=current_user.id,
        revoked_count=revoked_count,
    )

    return None  # 204 No Content