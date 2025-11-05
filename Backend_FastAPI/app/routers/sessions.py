# app/routers/sessions.py
"""
API endpoints for managing user sessions.
Allows users to view active sessions, revoke specific sessions, and revoke all other sessions.
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database  # ✅ FIX: Import security from app, not app.core
from .. import models, schemas, security
from ..core import deps
from ..services import session_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=schemas.UserSessionListResponse)
async def get_active_sessions(
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
    refresh_token: Optional[str] = Cookie(
        None, alias="refresh_token"
    ),  # ✅ SECURITY FIX: Read from HttpOnly cookie
):
    """
    Get all active sessions for the current user.

    Returns:
        List of active sessions with device info, IP address, and last activity.

    Security:
        - Requires authentication
        - Users can only see their own sessions
        - Current session is identified by refresh token cookie
    """
    log.info("Fetching active sessions", user_id=current_user.id)

    # ✅ SECURITY FIX: Identify current session from refresh token cookie
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
            # Continue without marking current session

    try:
        sessions = await session_service.get_active_sessions(
            db,
            current_user.id,
            current_refresh_jti=current_refresh_jti,  # Pass current JTI to mark current session
        )

        log.info(
            "Active sessions retrieved",
            user_id=current_user.id,
            session_count=len(sessions),
        )

        # Mark current session in response
        current_session_id = None
        for session in sessions:
            if current_refresh_jti and session.refresh_jti == current_refresh_jti:
                session.is_current = True
                current_session_id = session.id

        return schemas.UserSessionListResponse(
            sessions=sessions,
            total=len(sessions),
            current_session_id=current_session_id,
        )

    except Exception as e:
        log.error(
            "Failed to fetch active sessions",
            user_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve sessions",
        )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: int,
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Revoke a specific session.

    Args:
        session_id: ID of the session to revoke

    Security:
        - Requires authentication
        - Users can only revoke their own sessions

    Raises:
        404: Session not found or doesn't belong to user
    """
    log.info("Revoking session", user_id=current_user.id, session_id=session_id)

    try:
        success = await session_service.revoke_session(
            db=db, session_id=session_id, user_id=current_user.id
        )

        if not success:
            log.warning(
                "Session not found or already revoked",
                user_id=current_user.id,
                session_id=session_id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or already revoked",
            )

        log.info(
            "Session revoked successfully",
            user_id=current_user.id,
            session_id=session_id,
        )

        return None  # 204 No Content

    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "Failed to revoke session",
            user_id=current_user.id,
            session_id=session_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke session",
        )


@router.post("/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_other_sessions(
    current_session_id: int = None,  # Optional: ID of current session to preserve
    current_user: models.User = Depends(deps.get_current_user),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Revoke all sessions except optionally the current one.

    Args:
        current_session_id: Optional ID of session to preserve (usually current session)

    Useful when:
        - User suspects account compromise
        - User wants to logout from all other devices
        - Security best practice after password change

    Security:
        - Requires authentication
        - Only revokes user's own sessions
        - Can optionally preserve current session

    Returns:
        204 No Content on success
    """
    log.info(
        "Revoking all other sessions",
        user_id=current_user.id,
        preserve_session_id=current_session_id,
    )

    try:
        revoked_count = await session_service.revoke_all_other_sessions(
            db=db, user_id=current_user.id, except_session_id=current_session_id
        )

        log.info(
            "All other sessions revoked",
            user_id=current_user.id,
            revoked_count=revoked_count,
        )

        return None  # 204 No Content

    except Exception as e:
        log.error(
            "Failed to revoke all other sessions",
            user_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke sessions",
        )
