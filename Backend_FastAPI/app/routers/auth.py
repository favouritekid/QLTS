
# app/routers/auth.py
from typing import Annotated

import structlog
from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, schemas, security, services
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

# === SỬA LỖI RATE LIMIT KHI TEST ===
# Tạo một decorator "dummy" (giả) không làm gì cả
def no_limit(func):
    return func

# Quyết định dùng decorator nào dựa trên APP_ENV
limit_auth = limiter.limit(RATE_LIMITS["auth"]) if settings.APP_ENV != "test" else no_limit
limit_register = limiter.limit(RATE_LIMITS["auth"]) if settings.APP_ENV != "test" else no_limit
# === KẾT THÚC SỬA LỖI ===


from ..utils.exceptions import InvalidToken

router = APIRouter(tags=["Authentication"])
log = structlog.get_logger(__name__)


@router.post(
    "/register", response_model=schemas.User, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RATE_LIMITS["auth"])  # <-- ÁP DỤNG GIỚI HẠN
async def register_user(
    request: Request,  # <-- Thêm request để limiter hoạt động
    user_in: schemas.UserCreate,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Endpoint để đăng ký một người dùng mới.
    """
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


@router.post("/login", response_model=schemas.Token)
@limiter.limit(RATE_LIMITS["auth"])
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(database.get_db),
):
    user = await services.user_service.authenticate_user(
        db, username=form_data.username, password=form_data.password
    )
    
    # Sau khi xác thực thành công, xóa user khỏi global blacklist (nếu có)
    try:
        await services.user_service.remove_user_from_global_blacklist(user.id)
    except Exception as e:
        # Ghi log nếu không xóa được, nhưng vẫn tiếp tục login
        await log.error(
            "Failed to remove user from global blacklist during login",
            user_id=user.id,
            error=str(e)
        )
    
    # Tạo tokens với type
    access_token = security.create_access_token(data={"sub": user.username})
    refresh_token = security.create_refresh_token(data={"sub": user.username})

    # Lấy JTI và thời gian hết hạn từ tokens
    access_jti, access_ttl = security.decode_token_for_invalidation(access_token)
    refresh_jti, refresh_ttl = security.decode_token_for_invalidation(refresh_token)

    if not access_jti or not refresh_jti or refresh_ttl is None:
        log.error("Failed to decode tokens during login", user_id=user.id)
        raise HTTPException(status_code=500, detail="Could not process tokens")

    # Lưu JTI access vào DB
    user.active_jti = access_jti
    db.add(user)

    # Lưu JTI refresh vào Redis với TTL
    try:
        # Key: refresh_jti:<user_id>, Value: <refresh_token_jti>, TTL: thời gian hết hạn của refresh token
        await safe_redis_set(f"refresh_jti:{user.id}", refresh_jti, ex=refresh_ttl)
    except Exception as e:
        await db.rollback()  # Nếu lưu Redis lỗi, rollback cả DB
        log.error(
            "Failed to set refresh JTI in Redis during login",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not process session")

    try:
        await db.commit()  # Commit DB sau khi Redis thành công
    except Exception as e:
        await db.rollback()
        # Cố gắng xóa key Redis nếu commit DB thất bại
        try:
            await safe_redis_delete(f"refresh_jti:{user.id}")
        except Exception as redis_del_e:
            log.error(
                "Failed to delete refresh JTI from Redis after DB commit failure",
                user_id=user.id,
                error=str(redis_del_e),
            )
        log.error(
            "Failed to commit user active JTI during login",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="Could not save session")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    db: AsyncSession = Depends(database.get_db),
    # Lấy token từ header để decode lấy TTL
    authorization: Annotated[str | None, Header()] = None,
    current_user: models.User = deps.CurrentUser,
):
    """
    Đăng xuất người dùng:
    - Vô hiệu hóa access token hiện tại bằng blacklist.
    - Vô hiệu hóa refresh token bằng cách xóa JTI và thêm vào blacklist.
    - Xóa active_jti trong DB.
    """
    access_token = None
    if authorization and authorization.lower().startswith("bearer "):
        access_token = authorization.split(" ")[1]

    # 1. Vô hiệu hóa Access Token
    if access_token:
        access_jti, access_ttl = security.decode_token_for_invalidation(access_token)
        if access_jti and access_ttl is not None and access_ttl > 0:
            try:
                await safe_redis_set(
                    f"blacklist:{access_jti}", "revoked", ex=access_ttl
                )
                await log.info(
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
                # Không raise lỗi, vẫn tiếp tục logout

    # 2. Vô hiệu hóa Refresh Token
    try:
        refresh_jti = await safe_redis_get(f"refresh_jti:{current_user.id}")
        if refresh_jti:
            # Xóa key lưu JTI
            await safe_redis_delete(f"refresh_jti:{current_user.id}")
            # Thêm JTI vào blacklist với TTL mặc định của refresh token (nếu không decode lại)
            # Hoặc decode refresh token để lấy TTL chính xác (phức tạp hơn)
            refresh_token_ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
            await safe_redis_set(
                f"blacklist:{refresh_jti}", "revoked", ex=int(refresh_token_ttl)
            )
            await log.info(
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
        # Không raise lỗi

    # 3. Xóa active_jti trong DB (dùng service)
    await services.user_service.logout_user(
        db, user=current_user
    )  # Service này đã set active_jti = None và commit

    return None


@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(RATE_LIMITS["auth"])
async def request_password_reset(
    request: Request,
    forgot_data: schemas.ForgotPasswordSchema,
    # background_tasks: BackgroundTasks, # <-- Xóa BackgroundTasks
    db: AsyncSession = Depends(database.get_db),
):
    """
    Endpoint để yêu cầu đặt lại mật khẩu.
    Service sẽ gọi Celery task để xử lý.
    """
    # Chỉ cần gọi service, không cần background task ở router
    await services.user_service.handle_forgot_password(
        db=db, email_in=forgot_data.email
    )

    # Trả về response ngay lập tức
    return {
        "msg": "If a user with that email exists, a password reset link will be sent."
    }


@router.post("/reset-password", response_model=schemas.User)
@limiter.limit(RATE_LIMITS["auth"])  # ← THÊM DÒNG NÀY
async def perform_password_reset(
    request: Request,  # ← THÊM PARAMETER
    reset_data: schemas.ResetPasswordSchema, 
    db: AsyncSession = Depends(database.get_db)
):
    """Endpoint để thực hiện đặt lại mật khẩu bằng token."""
    # Bỏ kiểm tra 'if not user:' vì service đã ném 400/404
    return await services.user_service.reset_password(
        db, token=reset_data.token, new_password=reset_data.new_password
    )


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def perform_change_password(
    password_data: schemas.ChangePasswordSchema,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = deps.CurrentUser,
):
    """
    Endpoint để người dùng tự đổi mật khẩu.
    ✅ FIXED: Backend không cần confirm_new_password nữa.
    ✅ FIXED: Vô hiệu hóa TẤT CẢ các phiên hoạt động sau khi đổi mật khẩu thành công.
    """

    # 1. Đổi mật khẩu (service đã có logic verify old pass)
    await services.user_service.change_password(
        db,
        user=current_user,
        old_password=password_data.old_password,
        new_password=password_data.new_password,
    )  # Service này đã commit DB

    # === ⭐️ THAY ĐỔI Ở ĐÂY ===
    # 2. Vô hiệu hóa TẤT CẢ token cũ bằng cách gọi service mới
    try:
        await services.user_service.invalidate_all_sessions(db, current_user)
        await log.info(
            "All user sessions invalidated after password change",
            user_id=current_user.id,
        )
    except Exception as e:
        # Ghi log lỗi nghiêm trọng nhưng không báo lỗi 500 cho client
        # vì mật khẩu đã đổi thành công. User có thể login lại.
        log.critical(
            "Failed to invalidate all sessions after password change, "
            "potential security risk of dangling sessions!",
            user_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        # Cân nhắc: Có thể ném 500 ở đây nếu muốn đảm bảo tuyệt đối

    # === KẾT THÚC THAY ĐỔI ===

    # Bỏ phần code blacklist JTI riêng lẻ cũ ở đây

    return None


@router.post("/refresh", response_model=schemas.Token)
async def refresh_access_token(
    token_data: schemas.RefreshTokenRequest = Body(...),
    db: AsyncSession = Depends(database.get_db),
):
    """
    ✅ FIXED v2: Token rotation với Pessimistic Locking để ngăn race condition.

    Thứ tự:
    1. Lock user row trong DB (ngăn concurrent requests)
    2. Validate token
    3. Update DB
    4. Update Redis
    5. Nếu Redis fail -> Rollback DB
    """
    refresh_token = token_data.refresh_token
    credentials_exception = InvalidToken(detail="Invalid or expired refresh token")
    service_unavailable = HTTPException(
        status_code=503, detail="Auth service unavailable"
    )

    try:
        # === STEP 1: DECODE TOKEN (KHÔNG ĐỔI) ===
        try:
            payload = jwt.decode(
                refresh_token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
        except JWTError as e:
            await log.warning("JWT decode error or token expired", error=str(e))
            raise credentials_exception

        username: str | None = payload.get("sub")
        old_refresh_jti: str | None = payload.get("jti")
        token_type: str | None = payload.get("type")

        if not username or not old_refresh_jti or token_type != "refresh":
            log.warning("Invalid refresh token payload", payload=payload)
            raise credentials_exception

        # === STEP 2: CHECK BLACKLIST (EARLY EXIT) ===
        try:
            is_blacklisted = await safe_redis_exists(f"blacklist:{old_refresh_jti}")
            if is_blacklisted:
                await log.warning("Refresh token is blacklisted", jti=old_refresh_jti)
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            log.error("Blacklist check failed", error=str(e), exc_info=True)
            # ⚠️ Fail-open: Nếu Redis sập, vẫn cho phép refresh (policy decision)
            pass

        # === 🔐 CRITICAL: PESSIMISTIC LOCKING ===
        # Wrap toàn bộ logic trong một transaction lớn
        async with db.begin():
            try:
                # STEP 3: LOCK user row (ngăn concurrent refresh requests)
                stmt = (
                    select(models.User)
                    .where(models.User.username == username)
                    .with_for_update(nowait=False)  # ❌ KHÔNG skip_locked
                )

                result = await db.execute(stmt)
                user = result.scalar_one_or_none()

                if not user:
                    await log.warning("User not found during refresh", username=username)
                    raise credentials_exception

                # STEP 4: VALIDATE JTI (TRONG LOCK SCOPE)
                # Giờ chỉ có 1 request được vào đây tại một thời điểm
                stored_jti = await safe_redis_get(f"refresh_jti:{user.id}")

                if not stored_jti or stored_jti != old_refresh_jti:
                    await log.warning(
                        "JTI mismatch or not found in Redis",
                        user_id=user.id,
                        token_jti=old_refresh_jti,
                        stored_jti=stored_jti,
                    )

                    # Blacklist token bị reuse
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

                # STEP 5: GENERATE NEW TOKENS
                new_access_token = security.create_access_token(data={"sub": username})
                new_refresh_token = security.create_refresh_token(
                    data={"sub": username}
                )

                new_access_jti, _ = security.decode_token_for_invalidation(
                    new_access_token
                )
                new_refresh_jti, new_refresh_ttl = (
                    security.decode_token_for_invalidation(new_refresh_token)
                )

                if not new_access_jti or not new_refresh_jti or new_refresh_ttl is None:
                    log.error("Failed to decode new tokens", user_id=user.id)
                    raise HTTPException(
                        status_code=500, detail="Token generation failed"
                    )

                # STEP 6: UPDATE DB (VẪN TRONG LOCK)
                user.active_jti = new_access_jti
                db.add(user)

                # ⚠️ KHÔNG commit ở đây, để outer 'async with db.begin()' handle
                await log.info("DB changes staged", user_id=user.id)

                # STEP 7: UPDATE REDIS (TRƯỚC KHI COMMIT DB)
                try:
                    async with safe_redis_pipeline(transaction=True) as pipe:
                        pipe.set(
                            f"refresh_jti:{user.id}",
                            new_refresh_jti,
                            ex=new_refresh_ttl,
                        )
                        pipe.set(f"blacklist:{old_refresh_jti}", "rotated", ex=300)
                        await pipe.execute()

                    await log.info("✅ Redis update successful", user_id=user.id)

                except Exception as e_redis:
                    log.error(
                        "❌ Redis pipeline failed, will rollback DB",
                        user_id=user.id,
                        error=str(e_redis),
                        exc_info=True,
                    )
                    # ✅ Raise exception để trigger rollback của outer transaction
                    raise service_unavailable

                # STEP 8: Nếu đến đây, cả DB và Redis đều OK
                # Transaction sẽ tự động commit khi exit 'async with db.begin()'
                await log.info("✅ Token rotation completed successfully", user_id=user.id)

                return {
                    "access_token": new_access_token,
                    "refresh_token": new_refresh_token,
                    "token_type": "bearer",
                }

            except InvalidToken:
                # Validation failed -> Rollback transaction
                raise credentials_exception
            except HTTPException:
                # Service error -> Rollback transaction
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
