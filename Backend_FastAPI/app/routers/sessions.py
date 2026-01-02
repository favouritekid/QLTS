from app.core.rate_limits import limiter, RateLimits
# app/routers/sessions.py
"""
API endpoints for managing user sessions.
Allows users to view active sessions, revoke specific sessions, and revoke all other sessions.
"""
from typing import Optional

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database  # ✅ FIX: Import security from app, not app.core
from .. import models, schemas, security
from ..core import deps
from ..services import session_service

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("", response_model=schemas.UserSessionListResponse)
async def get_active_sessions(
    request: Request,
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
        # 1. Lấy danh sách thô (DB Models)
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

        # ✅ --- BẮT ĐẦU TỐI ƯU HÓA (Theo đề xuất của bạn) ---
        current_session_id = None
        response_sessions = []

        # 2. Dùng List Comprehension + model_construct
        # Nhanh hơn nhiều so với việc lặp và gọi model_validate
        response_sessions = [
            schemas.UserSessionResponse.model_construct(
                # Tự động map tất cả các cột từ CSDL
                **{c.name: getattr(session, c.name) for c in session.__table__.columns},
                
                # Tính toán và ghi đè 'is_current'
                is_current=bool(
                    current_refresh_jti and 
                    session.refresh_jti == current_refresh_jti
                )
            )
            for session in db_sessions
        ]

        # 3. Tìm current_session_id (nếu cần) từ danh sách đã tạo
        for s in response_sessions:
            if s.is_current:
                current_session_id = s.id
                break
        # ✅ --- KẾT THÚC TỐI ƯU HÓA ---

        return schemas.UserSessionListResponse(
            sessions=response_sessions,
            total=len(response_sessions),
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


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    request: Request,
    session_id: int,
    db: AsyncSession = Depends(database.get_db),  # ✅ PHASE 1: Inject db session (DI pattern)
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Revoke a specific session.

    Args:
        session_id: ID of the session to revoke
        db: Database session (injected)
        current_user: Current authenticated user (injected)

    Security:
        - Requires authentication
        - Users can only revoke their own sessions

    Raises:
        404: Session not found or doesn't belong to user
    """
    log.info("Revoking session", user_id=current_user.id, session_id=session_id)

    try:
        # ✅ PHASE 1: Pass db parameter to service (DI pattern)
        success, callback = await session_service.revoke_session(
            db=db,  # Pass injected database session
            session_id=session_id,
            user_id=current_user.id
        )

        if not success:
            log.warning(
                "Session not found or already revoked",
                user_id=current_user.id,
                session_id=session_id,
            )
            # No commit needed
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or already revoked",
            )

        # Commit transaction
        await db.commit()
        
        # Execute callback for side effects (Socket.IO)
        if callback:
            await callback()

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


@limiter.limit(RateLimits.DATA_WRITE)  # 200/hour
@router.post("/revoke-all", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_all_other_sessions(
    request: Request,
    request_data: schemas.RevokeAllSessionsRequest,
    db: AsyncSession = Depends(database.get_db),  # ✅ PHASE 1: Inject db session (DI pattern)
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Revoke all other sessions for the current user except optionally one.

    Args:
        request_data: Request body with optional current_session_id to preserve
        db: Database session (injected)
        current_user: Current authenticated user (injected)

    Returns:
        204 No Content on success

    Raises:
        500: If session revocation fails
    """
    session_id_to_preserve = request_data.current_session_id

    log.info(
        "Revoking all other sessions",
        user_id=current_user.id,
        preserve_session_id=session_id_to_preserve,
    )

    try:
        # ✅ PHASE 1: Pass db parameter to service (DI pattern)
        revoked_count, callback = await session_service.revoke_all_other_sessions(
            db=db,  # Pass injected database session
            user_id=current_user.id,
            except_session_id=session_id_to_preserve
        )

        # Commit transaction
        await db.commit()
        
        # Execute callback for side effects
        if callback:
            await callback()

        log.info(
            "All other sessions revoked",
            user_id=current_user.id,
            revoked_count=revoked_count,
        )

        return None  # 204 No Content

    # ✅ THÊM KHỐI CATCH NÀY (để bắt lỗi từ service)
    except Exception as e:
        log.error(
            "Failed to revoke all other sessions (endpoint level)",
            user_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        # Báo lỗi về frontend để họ biết thao tác thất bại
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revoke sessions",
        )