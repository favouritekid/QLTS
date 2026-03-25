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
import jwt
from jwt.exceptions import PyJWTError as JWTError
# ✅ PHASE 2: Removed direct sqlalchemy import (Router → Service → Repository pattern)
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, security
# PHASE 1: Removed send_login_alert_email_task (now in login_history_service)
from ..config import settings
from ..core import deps
from ..utils.exceptions import (  # ✅ PHASE 1: Import custom exceptions
    CacheServiceError,
    InvalidCredentials,
    UserServiceError,
)
from ..middleware.csrf import set_csrf_cookie  # ✅ CSRF Protection
from ..database import (
    safe_redis_delete,
    safe_redis_exists,
    safe_redis_get,
    safe_redis_pipeline,
    safe_redis_set,
    safe_redis_ttl,
)
from ..core.rate_limits import limiter, RateLimits  # ✅ MIGRATED: Use new rate limits module
from ..services import session_service, user_service
from ..services import login_history_service  # Security: Persistent login audit trail
from ..services.notification_dispatcher import safe_dispatch  # Security: Suspicious login alerts
# PHASE 1: Removed AnomalyDetector import (detection now in login_history_service)
from ..utils.exceptions import InvalidToken
from ..core.events import SystemEvents  # Security: Event registry

router = APIRouter(tags=["Authentication"])
log = structlog.get_logger(__name__)


# =============================================================================
# SHARED HELPER: Complete login flow (tokens, session, history, cookies)
# Used by both /login (non-MFA) and /verify-mfa to avoid code duplication.
# =============================================================================

async def _complete_login_flow(
    user: "models.User",
    request: Request,
    db: "AsyncSession",
) -> JSONResponse:
    """
    Complete the login flow after authentication is fully verified.

    Creates tokens, session, login history, handles suspicious login detection,
    and returns a JSONResponse with httpOnly cookies.

    Used by:
    - /login (after password auth, when MFA is NOT enabled)
    - /verify-mfa (after both password + MFA code verified)
    """
    from datetime import datetime, timedelta, timezone

    try:
        await user_service.remove_user_from_global_blacklist(user.id)
    except Exception as e:
        log.error("Failed to remove user from global blacklist", user_id=user.id, error=str(e))

    # 1. Create tokens
    refresh_token = security.create_refresh_token(data={"sub": user.username})
    refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)
    if not refresh_jti or refresh_ttl is None:
        raise HTTPException(status_code=500, detail="Could not process tokens")

    access_token = security.create_access_token(
        data={"sub": user.username, "user_id": user.id, "role": user.role},
        refresh_jti=refresh_jti,
    )
    access_jti, access_ttl = security.decode_token_for_invalidation(access_token)
    if not access_jti:
        raise HTTPException(status_code=500, detail="Could not process tokens")

    # 2. Store session in Redis
    try:
        await safe_redis_set(f"session:{refresh_jti}", str(user.id), ex=refresh_ttl)
    except Exception as e:
        await db.rollback()
        log.error("Failed to set session in Redis", user_id=user.id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Could not process session")

    # 3. Create DB session + login history
    post_commit_callbacks = []
    ip_address = request.client.host if request.client else None
    user_agent_string = request.headers.get("User-Agent")
    session = None

    try:
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        session, session_callback = await session_service.create_session(
            db=db,
            user_id=user.id,
            refresh_jti=refresh_jti,
            ip_address=ip_address,
            user_agent_string=user_agent_string,
            expires_at=expires_at,
        )
        if session_callback:
            post_commit_callbacks.append(session_callback)
    except Exception as session_error:
        log.error("Failed to create session", user_id=user.id, error=str(session_error), exc_info=True)

    # 4. Record login history + suspicious login detection
    login_notification_data = None
    try:
        login_record, login_history_callback = await login_history_service.record_login(
            db=db,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent_string,
            country=session.country if session else None,
            city=session.city if session else None,
            email_to=user.email,
            username=user.username,
            refresh_jti=refresh_jti,
        )
        if login_history_callback:
            post_commit_callbacks.append(login_history_callback)

        if login_record.is_suspicious:
            log.warning(
                "Login recorded with security flags",
                user_id=user.id,
                is_new_ip=login_record.is_new_ip,
                is_new_device=login_record.is_new_device,
                is_new_location=login_record.is_new_location,
                risk_score=login_record.risk_score,
            )
            anomalies = []
            if login_record.is_new_ip:
                anomalies.append("new_ip")
            if login_record.is_new_device:
                anomalies.append("new_device")
            if login_record.is_new_location:
                anomalies.append("new_location")

            login_notification_data = {
                "type": "SUSPICIOUS_LOGIN",
                "login_id": login_record.id,
                "ip_address": ip_address or "unknown",
                "location": f"{login_record.city or ''}, {login_record.country or ''}".strip(", ") or None,
                "device": f"{login_record.browser or ''} on {login_record.os or ''}".strip() or None,
                "browser": login_record.browser,
                "os": login_record.os,
                "risk_score": login_record.risk_score,
                "anomalies": anomalies,
            }
            # Sync is_suspicious to UserSession
            if session:
                session.is_suspicious = True
                db.add(session)
            # Dispatch notification (fire-and-forget after commit)
            async def _dispatch_suspicious_login():
                try:
                    await safe_dispatch(
                        db=db,
                        event=SystemEvents.SUSPICIOUS_LOGIN,
                        payload={
                            "user_id": user.id,
                            "user_ids": [user.id],
                            "login_history_id": login_record.id,
                            "ip_address": ip_address or "unknown",
                            "location": f"{login_record.city or ''}, {login_record.country or ''}".strip(", "),
                            "device": f"{login_record.browser or ''} on {login_record.os or ''}".strip(),
                            "risk_score": login_record.risk_score,
                            "anomalies": anomalies,
                            "actor_id": user.id,
                        },
                    )
                except Exception as notif_error:
                    log.error("Failed to dispatch suspicious login notification", user_id=user.id, error=str(notif_error))
            post_commit_callbacks.append(_dispatch_suspicious_login)
    except Exception as history_error:
        log.error("Failed to record login history", user_id=user.id, error=str(history_error), exc_info=True)

    # 5. Commit and execute callbacks
    try:
        await db.commit()
        for callback in post_commit_callbacks:
            try:
                await callback()
            except Exception as cb_e:
                log.error("Post-commit callback failed", error=str(cb_e))
                # Rollback to clear session error state so subsequent
                # callbacks or responses can still use the session.
                try:
                    await db.rollback()
                except Exception:
                    pass
    except Exception as e:
        await db.rollback()
        try:
            await safe_redis_delete(f"session:{refresh_jti}")
        except Exception:
            pass
        log.error("Failed to commit DB changes during login", user_id=user.id, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail="Could not save session")

    # 6. Build response with httpOnly cookies
    response = JSONResponse(
        content={
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
                "status": user.status,
                "password_reset_required": user.password_reset_required,
                "mfa_enabled": user.mfa_enabled,
            },
            "login_notification": login_notification_data,
        },
        status_code=200,
    )
    response.set_cookie(
        key="access_token", value=access_token,
        httponly=True, secure=settings.APP_ENV == "production",
        samesite="lax", max_age=int(access_ttl) if access_ttl else settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token", value=refresh_token,
        httponly=True, secure=settings.APP_ENV == "production",
        samesite="strict", max_age=int(refresh_ttl), path="/api",
    )
    set_csrf_cookie(response)
    return response


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

        remaining_minutes = max(1, (lockout_ttl + 59) // 60)  # Round up

        log.warning(
            "Login attempt blocked: Account is locked",
            username=form_data.username,
            remaining_seconds=lockout_ttl,
            ip_address=request.client.host if request.client else None,
        )

        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": f"Tài khoản tạm thời bị khóa do nhập sai quá nhiều lần. "
                          f"Vui lòng thử lại sau {remaining_minutes} phút.",
            },
            headers={"Retry-After": str(lockout_ttl)},
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

    # ===== MFA CHECK =====
    # If user has MFA enabled, return mfa_token instead of full login.
    # CRITICAL: Do NOT reset_attempts here. Password correct ≠ auth complete.
    # Counter only resets after BOTH factors verified (in /verify-mfa).
    if getattr(user, "mfa_enabled", False):
        from ..services import mfa_service

        mfa_token = mfa_service.create_mfa_token(
            username=user.username, user_id=user.id
        )
        log.info("MFA required for login", user_id=user.id, action="mfa.challenge_issued")
        return JSONResponse(
            content={
                "mfa_required": True,
                "mfa_token": mfa_token,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "mfa_enabled": True,
                },
            },
            status_code=200,
        )
    # ===== END MFA CHECK =====

    # Reset attempts counter only when auth is fully complete (no MFA)
    await AccountLockoutService.reset_attempts(form_data.username)

    # Complete login flow (shared helper: tokens, session, history, cookies)
    return await _complete_login_flow(user, request, db)


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
            revoked, callback = await session_service.revoke_session_by_jti(
                db=db,
                refresh_jti=refresh_jti,
                user_id=current_user.id
            )
            if revoked:
                await db.commit()
                if callback:
                    await callback()
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
    # ✅ FIX: get_current_user already validates session in Redis
    # No need to check again - if we reach here, session is valid
    
    # Get active sessions count for user info
    active_sessions = await session_service.get_active_sessions(
        db=db,
        user_id=current_user.id
    )

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

    # Cache identifiers before any rollback — ORM object may expire after rollback
    user_id = user.id
    user_email = user.email

    # SECURITY: Invalidate all sessions BEFORE committing password change.
    # If revocation fails, rollback so old password stays active — fail-closed:
    # no dangling sessions with a changed password.
    try:
        await user_service.invalidate_all_sessions(db, user)
        log.warning(
            "All user sessions invalidated after password reset",
            user_id=user_id,
            email=user_email,
            security_event="PASSWORD_RESET_SESSIONS_INVALIDATED",
        )
    except (CacheServiceError, UserServiceError) as e:
        await db.rollback()
        log.critical(
            "Failed to invalidate sessions — password reset rolled back",
            user_id=user_id,
            error=e.detail,
            context=e.context,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset failed. Please try again later."
        )
    except Exception as e:
        await db.rollback()
        log.critical(
            "Failed to invalidate sessions — password reset rolled back",
            user_id=user_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password reset failed. Please try again later."
        )

    # Session invalidation succeeded — now commit password change
    await db.commit()
    await post_commit_callback()

    # Refresh user object — may fail if session management detached it
    try:
        await db.refresh(user)
    except Exception:
        pass  # User data is already committed; stale ORM object is acceptable

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

    # Cache identifier before any rollback — ORM object may expire after rollback
    current_user_id = current_user.id

    # C2 SECURITY FIX: Clear password_reset_required flag after password change
    if hasattr(current_user, 'password_reset_required') and current_user.password_reset_required:
        current_user.password_reset_required = False
        db.add(current_user)
        log.info("Cleared password_reset_required flag", user_id=current_user_id)

    # SECURITY: Invalidate all sessions BEFORE committing password change.
    # If revocation fails, rollback so the old password stays active —
    # fail-closed: no dangling sessions with a changed password.
    try:
        await user_service.invalidate_all_sessions(db, current_user)
        log.info(
            "All user sessions invalidated after password change",
            user_id=current_user_id,
        )
    except (CacheServiceError, UserServiceError) as e:
        await db.rollback()
        log.critical(
            "Failed to invalidate sessions — password change rolled back",
            user_id=current_user_id,
            error=e.detail,
            context=e.context,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed. Please try again later."
        )
    except Exception as e:
        await db.rollback()
        log.critical(
            "Failed to invalidate sessions — password change rolled back",
            user_id=current_user_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed. Please try again later."
        )

    # Session invalidation succeeded — now commit the password change
    await db.commit()
    await post_commit_callback()

    # Clear auth cookies — forces browser to stop sending blacklisted tokens
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(key="access_token", path="/", samesite="lax")
    response.delete_cookie(key="refresh_token", path="/api", samesite="strict")
    response.delete_cookie(key="csrf_token", path="/")
    return response


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

    # ✅ M4: Per-user rate limiting for failed refresh attempts
    # We extract username from token even on failure to track abuse
    _refresh_username = None

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
        _refresh_username = username  # Track for rate limiting on failure

        if not username or not old_refresh_jti or token_type != "refresh":
            log.warning("Invalid refresh token payload", sub=username, type=token_type)
            raise credentials_exception

        # ✅ M4: Check if user exceeded failed refresh attempts
        try:
            fail_key = f"refresh_fail:{username}"
            fail_count_str = await safe_redis_get(fail_key)
            fail_count = int(fail_count_str) if fail_count_str else 0
            if fail_count >= settings.REFRESH_MAX_FAILURES:
                log.warning(
                    "Refresh token rate limited - too many failures",
                    username=username,
                    fail_count=fail_count,
                    security_event="REFRESH_RATE_LIMITED",
                )
                raise HTTPException(
                    status_code=429,
                    detail="Too many failed refresh attempts. Please login again.",
                )
        except HTTPException:
            raise
        except Exception as e:
            log.error("Redis refresh rate limit check failed", error=str(e))

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

        # ✅ FIX: Use begin_nested() (savepoint) to avoid conflict with implicit transaction
        async with db.begin_nested():
            try:
                user = await user_service.get_user_for_refresh(db, username)

                if not user:
                    log.warning("User not found during refresh", username=username)
                    raise credentials_exception

                # SECURITY: Check user-level blacklist (set by invalidate_all_sessions
                # on password change/reset). Without this, old refresh tokens could
                # still rotate even after all sessions were invalidated.
                try:
                    is_user_blacklisted = await safe_redis_exists(f"user_blacklist:{user.id}")
                    if is_user_blacklisted:
                        log.warning(
                            "Refresh blocked: user in global blacklist (password changed?)",
                            user_id=user.id,
                        )
                        raise credentials_exception
                except InvalidToken:
                    raise
                except Exception as e:
                    log.error("Redis user blacklist check failed during refresh", error=str(e))
                    # Fail-closed: if we can't verify, reject the refresh
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

                # ✅ CSRF Protection: Refresh CSRF token on token refresh
                set_csrf_cookie(response)

                # ✅ M4: Clear failed refresh counter on success
                try:
                    await safe_redis_delete(f"refresh_fail:{username}")
                except Exception:
                    pass

                return response

            except InvalidToken:
                raise credentials_exception
            except HTTPException:
                raise

    except (JWTError, InvalidToken):
        # ✅ M4: Increment failed refresh counter
        if _refresh_username:
            try:
                fail_key = f"refresh_fail:{_refresh_username}"
                window = settings.REFRESH_FAILURE_WINDOW_MINUTES * 60
                current = await safe_redis_get(fail_key)
                new_count = (int(current) if current else 0) + 1
                await safe_redis_set(fail_key, str(new_count), ex=window)

                if new_count >= settings.REFRESH_MAX_FAILURES:
                    log.warning(
                        "Refresh failure threshold reached - revoking all sessions",
                        username=_refresh_username,
                        fail_count=new_count,
                        security_event="REFRESH_ABUSE_DETECTED",
                    )
                    try:
                        user = await user_service.get_user_by_username(db, _refresh_username)
                        if user:
                            await user_service.invalidate_all_sessions(db, user)
                    except Exception as revoke_err:
                        log.error("Failed to revoke sessions after refresh abuse", error=str(revoke_err))
            except Exception as redis_err:
                log.error("Failed to track refresh failure", error=str(redis_err))

        raise credentials_exception
    except HTTPException:
        raise
    except Exception as e:
        log.error(
            "Unhandled exception in refresh token endpoint", error=str(e), exc_info=True
        )
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


# =============================================================================
# MFA (Multi-Factor Authentication) ENDPOINTS
# =============================================================================


@router.post("/verify-mfa")
@limiter.limit(RateLimits.AUTH_LOGIN)  # 5/min - IP-based rate limit (Layer 1)
async def verify_mfa(
    request: Request,
    mfa_data: schemas.MfaVerifySchema,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Verify MFA code after successful password authentication.

    Security (defense in depth):
    - Layer 1: IP-based rate limit (5/min via slowapi)
    - Layer 2: Per-user Redis counter (5 attempts / 5 min)
    - Layer 3: AccountLockoutService (cumulative lockout)
    """
    from ..services import mfa_service
    from ..security.account_lockout import AccountLockoutService

    # 1. Decode mfa_token (verify type="mfa")
    payload = mfa_service.decode_mfa_token(mfa_data.mfa_token)
    username = payload.get("sub")
    user_id = payload.get("user_id")

    if not username or not user_id:
        raise HTTPException(status_code=401, detail="Invalid MFA token")

    # 1b. Check if this mfa_token was already used (prevent reuse within 5min window)
    mfa_jti = payload.get("jti")
    if mfa_jti:
        try:
            already_used = await safe_redis_exists(f"mfa_used:{mfa_jti}")
            if already_used:
                raise HTTPException(status_code=401, detail="MFA token already used. Please login again.")
        except HTTPException:
            raise
        except Exception as e:
            log.error("Redis MFA token blacklist check failed", error=str(e))

    # 2. Check per-user MFA attempt limit (Layer 2)
    attempt_key = f"mfa_attempts:{username}"
    try:
        attempts_str = await safe_redis_get(attempt_key)
        attempts = int(attempts_str) if attempts_str else 0
        if attempts >= settings.MFA_MAX_ATTEMPTS:
            # Get remaining TTL from Redis for Retry-After header
            attempt_ttl = await safe_redis_ttl(attempt_key)
            retry_after = max(attempt_ttl, 60) if attempt_ttl > 0 else settings.MFA_ATTEMPT_WINDOW_MINUTES * 60
            log.warning(
                "mfa_rate_limited", user_id=user_id, username=username,
                attempts=attempts, retry_after=retry_after, action="mfa.rate_limited",
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "Quá nhiều lần thử xác thực. Vui lòng thử lại sau.",
                },
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception as e:
        log.error("Redis MFA attempt check failed", error=str(e))

    # 3. Load user
    user = await user_service.get_user_by_username(db, username=username)
    if not user or user.id != user_id:
        raise HTTPException(status_code=401, detail="Invalid MFA token")

    # 4. Verify MFA code
    is_valid = await mfa_service.verify_mfa_code(db, user, mfa_data.code)

    if not is_valid:
        # Increment per-user MFA counter (Layer 2)
        l2_blocked = False
        try:
            window = settings.MFA_ATTEMPT_WINDOW_MINUTES * 60
            current = await safe_redis_get(attempt_key)
            new_count = (int(current) if current else 0) + 1
            await safe_redis_set(attempt_key, str(new_count), ex=window)
            l2_blocked = new_count >= settings.MFA_MAX_ATTEMPTS
        except Exception as e:
            log.error("Redis MFA attempt increment failed", error=str(e))

        # Feed into AccountLockoutService (Layer 3) only if L2 hasn't already blocked.
        # Avoids double-punish: L2 blocks fast OTP brute-force, L3 tracks cumulative auth failures.
        if not l2_blocked:
            await AccountLockoutService.record_failed_attempt(
                db=db,
                username=username,
                ip_address=request.client.host if request.client else None,
            )

        log.warning(
            "mfa_failed", user_id=user.id, action="mfa.verify_failed",
        )
        raise HTTPException(status_code=401, detail="Invalid verification code")

    # 5. MFA verified - blacklist this mfa_token to prevent reuse
    if mfa_jti:
        try:
            mfa_ttl = settings.MFA_TOKEN_EXPIRE_MINUTES * 60
            await safe_redis_set(f"mfa_used:{mfa_jti}", "1", ex=mfa_ttl)
        except Exception as e:
            log.error("Failed to blacklist used mfa_token", error=str(e))

    # 6. Reset attempt counters
    try:
        await safe_redis_delete(attempt_key)
    except Exception:
        pass
    await AccountLockoutService.reset_attempts(username)

    log.info("mfa_login_complete", user_id=user.id, action="mfa.verify_success")

    # 7. Complete login flow (shared helper: tokens, session, history, cookies)
    return await _complete_login_flow(user, request, db)


@router.post("/mfa/setup", response_model=schemas.MfaSetupResponse)
@limiter.limit(RateLimits.DATA_WRITE)
async def mfa_setup(
    request: Request,
    current_user: models.User = Depends(deps.get_current_user),
):
    """
    Initiate MFA setup. Returns QR code and secret.
    Secret is stored temporarily in Redis (10min TTL), NOT in DB.
    """
    from ..services import mfa_service

    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is already enabled. Disable it first to re-setup.",
        )

    setup_data, _ = await mfa_service.setup_mfa(
        user_id=current_user.id, username=current_user.username
    )

    return setup_data


@router.post("/mfa/enable", response_model=schemas.MfaBackupCodesResponse)
@limiter.limit(RateLimits.DATA_WRITE)
async def mfa_enable(
    request: Request,
    enable_data: schemas.MfaEnableRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
    refresh_token_cookie: str = Cookie(None, alias="refresh_token"),
):
    """
    Enable MFA after verifying TOTP code from authenticator app.
    Returns one-time backup codes. Revokes all other sessions.
    """
    from ..services import mfa_service

    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is already enabled.",
        )

    # Get current session ID to preserve it during session revocation
    current_session_id = None
    if refresh_token_cookie:
        try:
            payload = security.decode_token(refresh_token_cookie)
            current_refresh_jti = payload.get("jti")
            if current_refresh_jti:
                from ..repositories.session_repository import SessionRepository
                session_repo = SessionRepository(db)
                session_record = await session_repo.get_by_refresh_jti_and_user(
                    current_refresh_jti, current_user.id
                )
                if session_record:
                    current_session_id = session_record.id
        except Exception:
            pass  # Continue without preserving current session

    backup_codes, callback = await mfa_service.enable_mfa(
        db=db,
        user=current_user,
        code=enable_data.code,
        current_session_id=current_session_id,
    )

    await db.commit()

    if callback:
        await callback()

    return schemas.MfaBackupCodesResponse(backup_codes=backup_codes)


@router.post("/mfa/disable", status_code=status.HTTP_200_OK)
@limiter.limit(RateLimits.DATA_WRITE)
async def mfa_disable(
    request: Request,
    disable_data: schemas.MfaDisableRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """Disable MFA. Requires password verification."""
    from ..services import mfa_service

    if not current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is not enabled.",
        )

    result, callback = await mfa_service.disable_mfa(
        db=db, user=current_user, password=disable_data.password
    )

    await db.commit()

    if callback:
        await callback()

    return {"message": "MFA disabled successfully."}


@router.get("/mfa/status", response_model=schemas.MfaStatusResponse)
@limiter.limit(RateLimits.DATA_READ)
async def mfa_status(
    request: Request,
    current_user: models.User = Depends(deps.get_current_user),
):
    """Get MFA status for current user."""
    return schemas.MfaStatusResponse(
        mfa_enabled=current_user.mfa_enabled,
        has_backup_codes=bool(current_user.backup_codes_hashed),
    )


@router.post("/mfa/backup-codes", response_model=schemas.MfaBackupCodesResponse)
@limiter.limit(RateLimits.DATA_WRITE)
async def mfa_regenerate_backup_codes(
    request: Request,
    regen_data: schemas.MfaBackupCodesRequest,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(deps.get_current_user),
):
    """Regenerate backup codes. Invalidates all old codes. Requires password."""
    from ..services import mfa_service

    new_codes, callback = await mfa_service.regenerate_backup_codes(
        db=db, user=current_user, password=regen_data.password
    )

    await db.commit()

    if callback:
        await callback()

    return schemas.MfaBackupCodesResponse(backup_codes=new_codes)
