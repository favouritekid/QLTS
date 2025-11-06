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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, security, services
from ..celery_utils import send_login_alert_email_task
from ..config import settings
from ..core import deps
from ..database import (
    safe_redis_delete,
    safe_redis_exists,
    safe_redis_get,
    safe_redis_pipeline,
    safe_redis_set,
)
from ..ratelimit import RATE_LIMITS, limiter
from ..services import session_service
from ..services.anomaly_detection import AnomalyDetector


def no_limit(func):
    return func


limit_auth = (
    limiter.limit(RATE_LIMITS["auth"]) if settings.APP_ENV != "test" else no_limit
)
limit_register = (
    limiter.limit(RATE_LIMITS["auth"]) if settings.APP_ENV != "test" else no_limit
)

from ..utils.exceptions import InvalidToken

router = APIRouter(tags=["Authentication"])
log = structlog.get_logger(__name__)


@router.post(
    "/register", response_model=schemas.User, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RATE_LIMITS["auth"])
async def register_user(
    request: Request,
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    db_user_by_username = await services.user_service.get_user_by_username(
        db, username=user_in.username
    )
    if db_user_by_username:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{user_in.username}' already registered",
        )
    db_user_by_email = await services.user_service.get_user_by_email(
        db, email=user_in.email
    )
    if db_user_by_email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{user_in.email}' already registered",
        )
    created_user = await services.user_service.create_user(db=db, user_in=user_in)
    return created_user


@router.post("/login")
@limiter.limit(RATE_LIMITS["auth"])
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(database.get_db),
):
    user = await services.user_service.authenticate_user(
        db, username=form_data.username, password=form_data.password
    )

    try:
        await services.user_service.remove_user_from_global_blacklist(user.id)
    except Exception as e:
        log.error(
            "Failed to remove user from global blacklist during login",
            user_id=user.id,
            error=str(e),
        )

    # ✅ BƯỚC 2: SỬA HÀM LOGIN

    # 1. Tạo Refresh Token TRƯỚC
    refresh_token = security.create_refresh_token(data={"sub": user.username})
    refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)

    if not refresh_jti or refresh_ttl is None:
        log.error("Failed to decode REFRESH token during login", user_id=user.id)
        raise HTTPException(status_code=500, detail="Could not process tokens")

    # 2. Tạo Access Token, truyền refresh_jti vào
    access_token = security.create_access_token(
        data={"sub": user.username}, refresh_jti=refresh_jti
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
                send_login_alert_email_task.delay(
                    email_to=user.email,
                    username=user.username,
                    ip_address=ip_address or "Unknown",
                    user_agent=user_agent_string or "Unknown",
                    device_type=session.device_type or "Unknown",
                    browser=session.browser or "Unknown",
                    os=session.os or "Unknown",
                    anomalies=anomalies,
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

    response = JSONResponse(
        content={
            "access_token": access_token,
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
async def logout(
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
        try:
            from sqlalchemy import select

            result = await db.execute(
                select(models.UserSession).where(
                    models.UserSession.refresh_jti == refresh_jti,
                    models.UserSession.user_id == current_user.id,
                )
            )
            session = result.scalar_one_or_none()
            if session:
                from datetime import datetime, timezone

                session.revoked_at = datetime.now(timezone.utc)
                db.add(session)
                await db.commit()
                log.info(
                    "Session revoked on logout",
                    session_id=session.id,
                    user_id=current_user.id,
                )
        except Exception as session_error:
            log.warning(
                "Failed to revoke session on logout",
                user_id=current_user.id,
                error=str(session_error),
            )

    response.delete_cookie(
        key="refresh_token",
        path="/api/auth",
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/check-status")
async def check_session_status(
    current_user: models.User = Depends(deps.get_current_user),
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic - Giờ nó sẽ ổn vì get_current_user đã kiểm tra)
    from datetime import datetime, timezone

    from sqlalchemy import and_

    result = await db.execute(
        select(models.UserSession).where(
            and_(
                models.UserSession.user_id == current_user.id,
                models.UserSession.revoked_at.is_(None),
                models.UserSession.expires_at > datetime.now(timezone.utc),
            )
        )
    )
    active_sessions = result.scalars().all()

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
@limiter.limit(RATE_LIMITS["auth"])
async def request_password_reset(
    request: Request,
    forgot_data: schemas.ForgotPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    await services.user_service.handle_forgot_password(
        db=db, email_in=forgot_data.email
    )
    return {
        "detail": "If a user with that email exists, a password reset link will be sent."  # <--- ĐÃ SỬA
    }


@router.post("/reset-password", response_model=schemas.User)
@limiter.limit(RATE_LIMITS["auth"])
async def perform_password_reset(
    request: Request,
    reset_data: schemas.ResetPasswordSchema,
    db: AsyncSession = Depends(database.get_db),
):
    # (Giữ nguyên logic)
    return await services.user_service.reset_password(
        db, token=reset_data.token, new_password=reset_data.new_password
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def perform_change_password(
    password_data: schemas.ChangePasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.CurrentUser,
):
    # (Giữ nguyên logic)
    await services.user_service.change_password(
        db,
        user=current_user,
        old_password=password_data.old_password,
        new_password=password_data.new_password,
    )
    try:
        await services.user_service.invalidate_all_sessions(db, current_user)
        log.info(
            "All user sessions invalidated after password change",
            user_id=current_user.id,
        )
    except Exception as e:
        log.critical(
            "Failed to invalidate all sessions after password change, "
            "potential security risk of dangling sessions!",
            user_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
    return None


@router.post("/refresh")
async def refresh_access_token(
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

        # (STEP 3: Pessimistic Lock - Giữ nguyên)
        async with db.begin():
            try:
                stmt = (
                    select(models.User)
                    .where(models.User.username == username)
                    .with_for_update(nowait=False)
                )
                result = await db.execute(stmt)
                user = result.scalar_one_or_none()

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
                new_access_token = security.create_access_token(
                    data={"sub": username}, refresh_jti=new_refresh_jti
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

                # (STEP 8: Response - Giữ nguyên)
                response = JSONResponse(
                    content={
                        "access_token": new_access_token,
                        "token_type": "bearer",
                    },
                    status_code=200,
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
