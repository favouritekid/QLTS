# app/routers/auth.py
from typing import Annotated

import structlog
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
# ✅ PHASE 2: Removed direct sqlalchemy import (Router → Service → Repository pattern)
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, security
from ..celery_utils import send_login_alert_email_task
from ..config import settings
from ..core import deps
from ..utils.exceptions import (  # ✅ PHASE 1: Import custom exceptions
    CacheServiceError,
    InvalidCredentials,
    UserServiceError,
)
from ..database import (
    safe_redis_delete,
    safe_redis_exists,
    safe_redis_get,
    safe_redis_pipeline,
    safe_redis_set,
)
from ..core.rate_limits import limiter, RateLimits  # ✅ MIGRATED: Use new rate limits module
from ..services import session_service, user_service
from ..services.anomaly_detection import AnomalyDetector
from ..utils.exceptions import InvalidToken

router = APIRouter(tags=["Authentication"])
log = structlog.get_logger(__name__)


@router.post(
    "/register", response_model=schemas.User, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RateLimits.AUTH_REGISTER)  # ✅ RATE LIMIT: 3/min - Stricter for registration (prevents enumeration)
async def register_user(
    request: Request,
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(database.get_db),
):
    """
    User registration endpoint.

    ✅ SECURITY FIX (Phase 2): User Enumeration Prevention (CVSS 5.3 MEDIUM)
    - Returns generic error message to prevent username/email enumeration
    - Logs specific details internally for admin monitoring
    - Prevents attackers from discovering valid usernames/emails
    - Stricter rate limit (3/minute vs 5/minute for other auth endpoints)

    VULNERABILITY: User Enumeration
    - Old behavior: "Username 'john' already registered" → Attacker knows username exists
    - Attack: Enumerate all usernames/emails in database
    - Fix: Generic message "Username or email already registered" + stricter rate limit
    """
    db_user_by_username = await user_service.get_user_by_username(
        db, username=user_in.username
    )
    db_user_by_email = await user_service.get_user_by_email(
        db, email=user_in.email
    )

    # ✅ FIX: Check both conditions together and return generic message
    if db_user_by_username or db_user_by_email:
        # Log specific details for admin monitoring (internal only)
        log.warning(
            "🔒 SECURITY: Registration failed - duplicate credential",
            username=user_in.username if db_user_by_username else None,
            email=user_in.email if db_user_by_email else None,
            client_ip=request.client.host if request.client else "unknown"
        )

        # Return generic message to client (prevents enumeration)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already registered",  # ✅ Generic message
        )

    # ✅ FIX: create_user returns Tuple[User, Callback]
    created_user, post_commit_callback = await user_service.create_user(db=db, user_in=user_in)
    
    # ✅ FIX: Commit transaction and execute callback
    await db.commit()
    await post_commit_callback()

    # ✅ FIX: Automatically add Casbin grouping policy to map user to their role
    try:
        enforcer = request.app.state.enforcer
        if enforcer:
            role_name = f"role:{created_user.role}"
            user_subject = f"user:{created_user.id}"
            await enforcer.add_grouping_policy(user_subject, role_name)
            log.info(
                "Casbin grouping policy added for new user",
                user_id=created_user.id,
                role=created_user.role,
            )
    except Exception as e:
        log.error(
            "Failed to add Casbin grouping policy for new user",
            user_id=created_user.id,
            error=str(e),
        )
        # Don't fail registration if Casbin update fails

    return created_user


@router.post("/login")
@limiter.limit(RateLimits.AUTH_LOGIN)  # ✅ RATE LIMIT: 5/min - Prevents brute force attacks
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(database.get_db),
):
    # ✅ SECURITY FIX: Check account lockout before authentication
    from ..security.account_lockout import AccountLockoutService

    is_locked, lockout_ttl = await AccountLockoutService.check_lockout(
        form_data.username
    )

    if is_locked:
        # Add delay to slow down attacker
        import asyncio
        await asyncio.sleep(2)

        log.warning(
            "Login attempt blocked: Account is locked",
            username=form_data.username,
            remaining_seconds=lockout_ttl,
            ip_address=request.client.host if request.client else None,
        )

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account temporarily locked due to too many failed login attempts. "
                   f"Please try again in {lockout_ttl // 60} minutes.",
        )

    # Attempt authentication
    try:
        user = await user_service.authenticate_user(
            db, username=form_data.username, password=form_data.password
        )
    except (InvalidCredentials, HTTPException) as auth_error:
        # ✅ SECURITY FIX: Record failed attempt
        await AccountLockoutService.record_failed_attempt(
            db=db,
            username=form_data.username,
            ip_address=request.client.host if request.client else None,
        )

        # Re-raise original error (don't reveal lockout info to attacker)
        raise auth_error

    # ✅ SECURITY FIX: Reset attempts counter on successful login
    await AccountLockoutService.reset_attempts(form_data.username)

    try:
        await user_service.remove_user_from_global_blacklist(user.id)
    except Exception as e:
        log.error(
            "Failed to remove user from global blacklist during login",
            user_id=user.id,
            error=str(e),
        )

    # ✅ SECURITY FIX: Revoke all old sessions to prevent session fixation
    # This ensures only the new session (from this login) will be valid
    try:
        from ..services import session_service
        revoked_count = await session_service.revoke_all_other_sessions(
            db=db,
            user_id=user.id,
            except_session_id=None  # Revoke ALL old sessions
        )
        if revoked_count > 0:
            log.info(
                "Old sessions revoked on login (session fixation prevention)",
                user_id=user.id,
                revoked_count=revoked_count
            )
    except Exception as e:
        log.error(
            "Failed to revoke old sessions during login",
            user_id=user.id,
            error=str(e),
            exc_info=True
        )
        # Continue login even if revocation fails (fail-open for availability)

    # ✅ BƯỚC 2: SỬA HÀM LOGIN

    # 1. Tạo Refresh Token TRƯỚC
    refresh_token = security.create_refresh_token(data={"sub": user.username})
    refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)

    if not refresh_jti or refresh_ttl is None:
        log.error("Failed to decode REFRESH token during login", user_id=user.id)
        raise HTTPException(status_code=500, detail="Could not process tokens")

    # 2. Tạo Access Token, truyền refresh_jti vào
    # ✅ SECURITY FIX: Embed user_id and role in JWT for middleware authorization
    access_token = security.create_access_token(
        data={"sub": user.username, "user_id": user.id, "role": user.role},
        refresh_jti=refresh_jti,
    )
    access_jti, access_ttl = security.decode_token_for_invalidation(access_token)

    if not access_jti:
        log.error("Failed to decode ACCESS token during login", user_id=user.id)
        raise HTTPException(status_code=500, detail="Could not process tokens")

    # (Đã xóa logic active_jti)

    try:
        await safe_redis_set(f"session:{refresh_jti}", str(user.id), ex=refresh_ttl)
        log.info(
            "Refresh JTI stored in Redis for session",
            user_id=user.id,
            refresh_jti=refresh_jti[:8] + "...",
        )
    except Exception as e:
        await db.rollback()
        log.error(
            "Failed to set refresh JTI in Redis during login",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not process session")

    # (Giữ nguyên logic tạo session)
    try:
        from datetime import datetime, timedelta, timezone

        ip_address = request.client.host if request.client else None
        user_agent_string = request.headers.get("User-Agent")
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )
        session = await session_service.create_session(
            db=db,
            user_id=user.id,
            refresh_jti=refresh_jti,
            ip_address=ip_address,
            user_agent_string=user_agent_string,
            expires_at=expires_at,
        )
        detector = AnomalyDetector(db)
        anomalies = await detector.analyze_login(
            user_id=user.id,
            ip_address=ip_address,
            device_type=session.device_type,
            browser=session.browser,
            os=session.os,
            country=session.country,
            city=session.city,
            login_time=session.created_at,
        )
        if anomalies["is_suspicious"]:
            session.is_suspicious = True
            db.add(session)
            try:
                # Format location from session data
                location_parts = []
                if session.city:
                    location_parts.append(session.city)
                if session.country:
                    location_parts.append(session.country)
                location = ", ".join(location_parts) if location_parts else None

                send_login_alert_email_task.delay(
                    email_to=user.email,
                    username=user.username,
                    ip_address=ip_address or "Unknown",
                    user_agent=user_agent_string or "Unknown",
                    device_type=session.device_type or "Unknown",
                    browser=session.browser or "Unknown",
                    os=session.os or "Unknown",
                    anomalies=anomalies,
                    location=location,
                )
                log.info(
                    "Login alert email queued for suspicious activity",
                    user_id=user.id,
                    ip_address=ip_address,
                    anomalies=anomalies,
                )
            except Exception as email_error:
                log.warning(
                    "Failed to queue login alert email",
                    user_id=user.id,
                    error=str(email_error),
                )
    except Exception as session_error:
        log.error(
            "Failed to create session tracking record",
            user_id=user.id,
            error=str(session_error),
            exc_info=True,
        )

    # (Giữ nguyên logic commit và response)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        try:
            await safe_redis_delete(f"session:{refresh_jti}")
        except Exception as redis_del_e:
            log.error(
                "Failed to delete session JTI from Redis after DB commit failure",
                user_id=user.id,
                error=str(redis_del_e),
            )
        log.error(
            "Failed to commit DB changes during login",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not save session")

    # ✅ SECURITY FIX: Tokens are ONLY in httpOnly cookies (not in response body)
    # This prevents XSS attacks from stealing tokens via JavaScript
    response = JSONResponse(
        content={
            # "access_token": access_token,  # REMOVED - httpOnly cookies only
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
            },
        },
        status_code=200,
    )

    # ✅ SECURITY FIX: Set access_token in httpOnly cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="lax",  # Allow cookie to be sent on navigation from external sites
        max_age=int(access_ttl) if access_ttl else settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",  # Available to all routes (middleware needs to read it)
    )

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.APP_ENV == "production",
        samesite="strict",
        max_age=int(refresh_ttl),
        path="/api",  # ✅ FIX: Changed from "/api/auth" to "/api" so cookie is sent to all /api/* endpoints
    )
    return response


@router.post("/logout")
@limiter.limit(RateLimits.DATA_WRITE)  # ✅ RATE LIMIT: 200/hour - Normal write operation
async def logout(
    request: Request,
    response: Response,
    refresh_token: str = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(database.get_db),
    authorization: Annotated[str | None, Header()] = None,
    current_user: models.User = deps.CurrentUser,
):
    # (Giữ nguyên logic)
    access_token = None
    if authorization and authorization.lower().startswith("bearer "):
        access_token = authorization.split(" ")[1]

    if access_token:
        access_jti, access_ttl = security.decode_token_for_invalidation(access_token)
        if access_jti and access_ttl is not None and access_ttl > 0:
            try:
                await safe_redis_set(
                    f"blacklist:{access_jti}", "revoked", ex=access_ttl
                )
                log.info(
                    "Access token blacklisted on logout",
                    jti=access_jti,
                    user_id=current_user.id,
                )
            except Exception as e:
                log.error(
                    "Failed to blacklist access token on logout",
                    jti=access_jti,
                    error=str(e),
                )

    refresh_jti = None
    try:
        refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)
        if refresh_jti:
            await safe_redis_delete(f"session:{refresh_jti}")
            if refresh_ttl and refresh_ttl > 0:
                await safe_redis_set(
                    f"blacklist:{refresh_jti}", "revoked", ex=refresh_ttl
                )
            else:
                refresh_token_ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
                await safe_redis_set(
                    f"blacklist:{refresh_jti}", "revoked", ex=int(refresh_token_ttl)
                )
            log.info(
                "Refresh token blacklisted on logout",
                jti=refresh_jti,
                user_id=current_user.id,
            )
    except Exception as e:
        log.error(
            "Failed to blacklist refresh token on logout",
            user_id=current_user.id,
            error=str(e),
        )

    if refresh_jti:
        # ✅ PHASE 2: Use session_service instead of direct SQL
        try:
            revoked = await session_service.revoke_session_by_jti(
                db=db,
                refresh_jti=refresh_jti,
                user_id=current_user.id
            )
            if revoked:
                await db.commit()
                log.info(
                    "Session revoked on logout",
                    user_id=current_user.id,
                )
            else:
                log.warning(
                    "Session not found for revocation on logout",
                    user_id=current_user.id,
                )
        except Exception as session_error:
            log.warning(
                "Failed to revoke session on logout",
                user_id=current_user.id,
                error=str(session_error),
            )

    # ✅ SECURITY FIX: Delete both cookies
    response.delete_cookie(
        key="access_token",
        path="/",
        samesite="lax",
    )
    response.delete_cookie(
        key="refresh_token",
        path="/api",  # ✅ FIX: Changed from "/api/auth" to "/api" to match set_cookie path
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/check-status")
@limiter.limit(RateLimits.DATA_READ)  # ✅ RATE LIMIT: 1000/hour - Normal read operation
async def check_session_status(
    request: Request,
    current_user: models.User = Depends(deps.get_current_user),
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(database.get_db),
):
    # ✅ PHASE 2: Use session_service instead of direct SQL
    active_sessions = await session_service.get_active_sessions(
        db=db,
        user_id=current_user.id
    )

    # (Đoạn check `has_valid_session` này giờ có thể hơi thừa
    # vì `get_current_user` đã làm, nhưng giữ lại cũng không sao)
    has_valid_session = False
    for session in active_sessions:
        stored_user_id = await safe_redis_get(f"session:{session.refresh_jti}")
        if stored_user_id and int(stored_user_id) == current_user.id:
            has_valid_session = True
            break

    if not has_valid_session:
        log.warning(
            "No valid session found in Redis for user (in check-status)",
            user_id=current_user.id,
        )
        raise HTTPException(status_code=401, detail="Session has been revoked")

    return {
        "status": "active",
        "user_id": current_user.id,
        "username": current_user.username,
        "session_valid": True,
        "active_sessions_count": len(active_sessions),
    }


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(RateLimits.AUTH_PASSWORD_RESET)  # ✅ RATE LIMIT: 3/hour - Prevents password reset abuse
async def request_password_reset(
    request: Request,
    forgot_data: schemas.ForgotPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    await user_service.handle_forgot_password(
        db=db, email_in=forgot_data.email
    )
    return {
        "detail": "If a user with that email exists, a password reset link will be sent."  # <--- ĐÃ SỬA
    }


@router.post("/reset-password", response_model=schemas.User)
@limiter.limit(RateLimits.AUTH_PASSWORD_RESET)  # ✅ RATE LIMIT: 3/hour - Same as forgot-password
async def perform_password_reset(
    request: Request,
    reset_data: schemas.ResetPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Reset password using token from email.

    Security: Invalidates ALL sessions after password reset to prevent
    session hijacking attacks. If an attacker had access to the account,
    all their sessions will be revoked.
    """
    user, post_commit_callback = await user_service.reset_password(
        db, token=reset_data.token, new_password=reset_data.new_password
    )

    # ✅ FIX: Commit the password change to DB
    await db.commit()
    await post_commit_callback()

    # 🔐 SECURITY FIX: Invalidate all sessions after password reset
    # This prevents session hijacking if attacker had compromised account
    try:
        await user_service.invalidate_all_sessions(db, user)
        log.warning(
            "All user sessions invalidated after password reset",
            user_id=user.id,
            email=user.email,
            security_event="PASSWORD_RESET_SESSIONS_INVALIDATED",
        )
    except (CacheServiceError, UserServiceError) as e:
        # ✅ PHASE 1: Catch custom exceptions from service layer
        log.critical(
            "Failed to invalidate sessions after password reset - SECURITY RISK",
            user_id=user.id,
            error=e.detail,
            context=e.context,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to invalidate sessions after password reset"
        )
    except Exception as e:
        log.critical(
            "Failed to invalidate all sessions after password reset, "
            "CRITICAL SECURITY RISK: attacker sessions may still be active!",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        # ✅ NEW: Throw 500 to indicate failure (security-critical)
        raise HTTPException(
            status_code=500,
            detail="Password reset successful but failed to invalidate sessions. Please logout manually from all devices and contact support immediately."
        )

    # 📧 Send confirmation email to notify user about password reset
    # This allows user to take action if they didn't initiate the reset
    try:
        from datetime import datetime, timezone
        from ..celery_utils import send_password_reset_confirmation_email_task

        reset_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        # Try to get IP address from request
        ip_address = request.client.host if request.client else None

        send_password_reset_confirmation_email_task.delay(
            email_to=user.email,
            username=user.full_name or user.email,
            reset_time=reset_time,
            ip_address=ip_address,
        )
        log.info(
            "Password reset confirmation email queued",
            user_id=user.id,
            email=user.email,
        )
    except Exception as e:
        log.error(
            "Failed to queue password reset confirmation email",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        # Don't fail the request if email fails

    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(RateLimits.AUTH_PASSWORD_CHANGE)  # ✅ RATE LIMIT: 10/hour - Moderate for authenticated users
async def perform_change_password(
    request: Request,
    password_data: schemas.ChangePasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.CurrentUser,
):
    """
    Change user password and invalidate all sessions.

    Security: This endpoint invalidates ALL sessions after password change.
    If session invalidation fails, the request will fail with 500 to prevent
    security issues with dangling sessions.
    """
    _, post_commit_callback = await user_service.change_password(
        db,
        user=current_user,
        old_password=password_data.old_password,
        new_password=password_data.new_password,
    )

    # ✅ FIX: Commit the password change to DB
    await db.commit()
    await post_commit_callback()

    # Invalidate all sessions after password change
    try:
        await user_service.invalidate_all_sessions(db, current_user)
        log.info(
            "All user sessions invalidated after password change",
            user_id=current_user.id,
        )
    except (CacheServiceError, UserServiceError) as e:
        log.critical(
            "Failed to invalidate sessions after password change - SECURITY RISK",
            user_id=current_user.id,
            error=e.detail,
            context=e.context,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to invalidate sessions after password change"
        )
    except Exception as e:
        log.critical(
            "Failed to invalidate all sessions after password change",
            user_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Password changed but failed to invalidate sessions. Please logout manually from all devices and contact support."
        )

    return None


@router.post("/refresh")
@limiter.limit(RateLimits.AUTH_REFRESH_TOKEN)  # ✅ RATE LIMIT: 20/hour - Higher for token refresh
async def refresh_access_token(
    request: Request,
    refresh_token: str = Cookie(None, alias="refresh_token"),
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    if not refresh_token:
        raise HTTPException(
            status_code=401, detail="Refresh token missing. Please login again."
        )

    credentials_exception = InvalidToken(detail="Invalid or expired refresh token")
    service_unavailable = HTTPException(
        status_code=503, detail="Auth service unavailable"
    )

    try:
        # (STEP 1: Decode - Giữ nguyên)
        try:
            payload = jwt.decode(
                refresh_token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError as e:
            log.warning("JWT decode error or token expired", error=str(e))
            raise credentials_exception

        username: str | None = payload.get("sub")
        old_refresh_jti: str | None = payload.get("jti")
        token_type: str | None = payload.get("type")

        if not username or not old_refresh_jti or token_type != "refresh":
            log.warning("Invalid refresh token payload", payload=payload)
            raise credentials_exception

        # (STEP 2: Check Blacklist - Giữ nguyên)
        try:
            is_blacklisted = await safe_redis_exists(f"blacklist:{old_refresh_jti}")
            if is_blacklisted:
                log.warning("Refresh token is blacklisted", jti=old_refresh_jti)
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            log.error("Blacklist check failed", error=str(e), exc_info=True)

        # (✅ PHASE 2: Use user_service with pessimistic lock instead of direct SQL)
        async with db.begin():
            try:
                user = await user_service.get_user_for_refresh(db, username)

                if not user:
                    log.warning("User not found during refresh", username=username)
                    raise credentials_exception

                # (STEP 4: Validate JTI - Giữ nguyên)
                stored_user_id = await safe_redis_get(f"session:{old_refresh_jti}")

                if not stored_user_id or int(stored_user_id) != user.id:
                    log.warning(
                        "Session not found or user mismatch in Redis",
                        user_id=user.id,
                        token_jti=old_refresh_jti,
                        stored_user_id=stored_user_id,
                    )
                    if old_refresh_jti:
                        ttl = int(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)
                        try:
                            await safe_redis_set(
                                f"blacklist:{old_refresh_jti}", "reuse_attempt", ex=ttl
                            )
                        except Exception as e_blacklist:
                            log.error(
                                "Failed to blacklist reuse attempt",
                                jti=old_refresh_jti,
                                error=str(e_blacklist),
                            )
                    raise credentials_exception

                # ✅ BƯỚC 2 (tt): SỬA HÀM REFRESH

                # 1. Tạo Refresh Token MỚI TRƯỚC
                new_refresh_token = security.create_refresh_token(
                    data={"sub": username}
                )
                new_refresh_jti, new_refresh_ttl = (
                    security.decode_token_for_invalidation(new_refresh_token)
                )

                if not new_refresh_jti or new_refresh_ttl is None:
                    log.error("Failed to decode new REFRESH token", user_id=user.id)
                    raise HTTPException(
                        status_code=500, detail="Token generation failed"
                    )

                # 2. Tạo Access Token MỚI, truyền new_refresh_jti vào
                # ✅ SECURITY FIX: Embed user_id and role in JWT for middleware authorization
                new_access_token = security.create_access_token(
                    data={"sub": username, "user_id": user.id, "role": user.role},
                    refresh_jti=new_refresh_jti,
                )
                new_access_jti, _ = security.decode_token_for_invalidation(
                    new_access_token
                )

                if not new_access_jti:
                    log.error("Failed to decode new ACCESS token", user_id=user.id)
                    raise HTTPException(
                        status_code=500, detail="Token generation failed"
                    )

                # (Đã xóa logic active_jti)

                # (STEP 6: Update Session - Giữ nguyên)
                try:
                    await session_service.update_session_activity(
                        db=db,
                        old_refresh_jti=old_refresh_jti,
                        new_refresh_jti=new_refresh_jti,
                        user_id=user.id,
                    )
                except Exception as session_error:
                    log.warning(
                        "Failed to update session activity",
                        user_id=user.id,
                        error=str(session_error),
                    )

                log.info("DB changes staged", user_id=user.id)

                # (STEP 7: Update Redis - Giữ nguyên)
                try:
                    async with safe_redis_pipeline(transaction=True) as pipe:
                        pipe.delete(f"session:{old_refresh_jti}")
                        pipe.set(
                            f"session:{new_refresh_jti}",
                            str(user.id),
                            ex=new_refresh_ttl,
                        )

                        # ✅ SỬA LỖI: Blacklist token cũ bằng đúng TTL của nó
                        full_refresh_ttl = int(
                            settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
                        )
                        safe_ttl = max(60, full_refresh_ttl)  # Đảm bảo TTL dương
                        pipe.set(f"blacklist:{old_refresh_jti}", "rotated", ex=safe_ttl)

                        await pipe.execute()

                    log.info(
                        "✅ Redis update successful (session rotated)", user_id=user.id
                    )
                except Exception as e_redis:
                    log.error(
                        "❌ Redis pipeline failed, will rollback DB",
                        user_id=user.id,
                        error=str(e_redis),
                        exc_info=True,
                    )
                    raise service_unavailable

                log.info("✅ Token rotation completed successfully", user_id=user.id)

                # ✅ FIX-4: Add user info to refresh response for auto-refresh mechanism
                # ✅ FIX-5: Tokens are ONLY in httpOnly cookies (not in response body)
                response = JSONResponse(
                    content={
                        # "access_token": new_access_token,  # REMOVED - httpOnly cookies only
                        "token_type": "bearer",
                        "user": {
                            "id": user.id,
                            "username": user.username,
                            "email": user.email,
                            "full_name": user.full_name,
                            "role": user.role,
                        },
                    },
                    status_code=200,
                )

                # ✅ SECURITY FIX: Set new access_token in httpOnly cookie
                new_access_ttl = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
                response.set_cookie(
                    key="access_token",
                    value=new_access_token,
                    httponly=True,
                    secure=settings.APP_ENV == "production",
                    samesite="lax",
                    max_age=int(new_access_ttl),
                    path="/",
                )

                response.set_cookie(
                    key="refresh_token",
                    value=new_refresh_token,
                    httponly=True,
                    secure=settings.APP_ENV == "production",
                    samesite="strict",
                    max_age=int(new_refresh_ttl),
                    path="/api",  # ✅ FIX: Changed from "/api/auth" to "/api" so cookie is sent to all /api/* endpoints
                )
                return response

            except InvalidToken:
                raise credentials_exception
            except HTTPException:
                raise

    except (JWTError, InvalidToken):
        raise credentials_exception
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "Unhandled exception in refresh token endpoint", error=str(e), exc_info=True
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred")
