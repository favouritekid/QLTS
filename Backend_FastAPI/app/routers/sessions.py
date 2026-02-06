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
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database
from .. import models, schemas, security
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
    db: AsyncSession = Depends(database.get_db),
    refresh_token: Optional[str] = Cookie(None, alias="refresh_token"),
):
    """
    Get all active sessions for the current user.

    Security:
        - Requires authentication
        - Users can only see their own sessions
        - Current session is identified by refresh token cookie
    """
    log.info("Fetching active sessions", user_id=current_user.id)

    # Identify current session from refresh token cookie
    # This is intentional exception handling for token parsing
    current_refresh_jti = None
    if refresh_token:
        try:
            payload = security.decode_token(refresh_token)
            current_refresh_jti = payload.get("jti")
            log.info("Current session identified", refresh_jti=current_refresh_jti)
        except Exception as e:
            log.warning(
                "Failed to decode refresh token for session identification",
                error=str(e),
            )
            # Continue without marking current session - this is intentional

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
    request_data: schemas.RevokeAllSessionsRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Revoke all other sessions for the current user except optionally one.

    Args:
        request_data: Request body with optional current_session_id to preserve

    Returns:
        204 No Content on success
    """
    session_id_to_preserve = request_data.current_session_id

    log.info(
        "Revoking all other sessions",
        user_id=current_user.id,
        preserve_session_id=session_id_to_preserve,
    )

    revoked_count, callback = await session_service.revoke_all_other_sessions(
        db=db,
        user_id=current_user.id,
        except_session_id=session_id_to_preserve
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