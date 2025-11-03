# app/core/deps.py
import casbin

from typing import List
from fastapi import Path
import structlog
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, services
from ..config import settings
from ..database import safe_redis_exists  # <-- Import redis_client TRỰC TIẾP
from ..utils.exceptions import InvalidToken, PermissionDeniedError, ResourceNotFoundError

log = structlog.get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(database.get_db)
) -> models.User:
    """
    ✅ FIXED: Dependency để lấy user hiện tại từ JWT token.
    Thêm kiểm tra user-level blacklist.
    """
    credentials_exception = InvalidToken(detail="Could not validate credentials")

    try:
        # === STEP 1: DECODE TOKEN ===
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        username: str | None = payload.get("sub")
        jti: str | None = payload.get("jti")
        token_type: str = payload.get("type", "access")

        if username is None or jti is None:
            log.warning("Token missing username or jti", payload=payload)
            raise credentials_exception

        # === STEP 2: CHECK JTI BLACKLIST ===
        try:
            # Kiểm tra blacklist JTI riêng lẻ (cho logout/rotation)
            is_jti_blacklisted = await safe_redis_exists(f"blacklist:{jti}")
            if is_jti_blacklisted:
                await log.info("Token validation failed: JTI found in blacklist", jti=jti)
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            await log.error("Redis JTI blacklist check failed", jti=jti, error=str(e))
            # Fail-open: Bỏ qua lỗi Redis ở đây
            pass

        # === STEP 3: GET USER & CHECK USER BLACKLIST ===
        user = await services.user_service.get_user_by_username(db, username=username)
        if user is None:
            log.warning("Token validation failed: User not found", username=username)
            raise credentials_exception

        # === ⭐️ THÊM KIỂM TRA USER BLACKLIST Ở ĐÂY ===
        try:
            # Kiểm tra blacklist toàn cục cho user (cho đổi mật khẩu)
            is_user_blacklisted = await safe_redis_exists(f"user_blacklist:{user.id}")
            if is_user_blacklisted:
                await log.info(
                    "Token rejected: User found in global blacklist (password changed?)",
                    user_id=user.id,
                )
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            await log.error(
                "Redis user blacklist check failed", user_id=user.id, error=str(e)
            )
            # Fail-open: Bỏ qua lỗi Redis ở đây
            pass
        # === KẾT THÚC THÊM KIỂM TRA ===

        # === STEP 4: VERIFY ACTIVE JTI (Cho access token) ===
        # Chỉ verify active_jti cho ACCESS tokens
        if token_type == "access" and user.active_jti != jti:
            await log.info(
                "Token validation failed: Access token JTI mismatch or invalidated",
                user_jti=user.active_jti,
                token_jti=jti,
            )
            raise credentials_exception

        return user

    except JWTError as e:
        log.warning("JWT decoding error or token expired", error=str(e))
        raise credentials_exception

    except InvalidToken:
        raise

async def check_permission(
    request: Request,
    current_user: models.User = Depends(get_current_user)
):
    """
    Dependency kiểm tra quyền động bằng Casbin.
    """
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    if not enforcer:
        log.critical("Casbin enforcer not found in app state!")
        raise PermissionDeniedError("Permission system is misconfigured.")

    subject = f"user:{current_user.id}"
    object_path = request.url.path
    action = request.method

    # --- SỬA LỖI Ở ĐÂY: Bỏ `await` ---
    # `enforce` itself is synchronous, even on AsyncEnforcer
    if not enforcer.enforce(subject, object_path, action):
    # ---
        await log.warning(
            "Permission Denied (Casbin)",
            subject=subject,
            object=object_path,
            action=action,
        )
        raise PermissionDeniedError(detail="You do not have permission for this action.")

    return current_user

def require_roles(required_roles: List[str]):
    """
    Dependency factory để kiểm tra vai trò người dùng.
    """

    async def role_checker(
        current_user: models.User = Depends(get_current_user),
    ) -> models.User:
        if current_user.role not in required_roles:
            from ..utils.exceptions import PermissionDeniedError

            raise PermissionDeniedError(
                detail=f"User does not have the required roles: {required_roles}"
            )
        return current_user

    return role_checker

async def get_lead_for_user(
    lead_id: int = Path(..., description="ID của Lead"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
) -> models.Lead:
    """
    Dependency để lấy một Lead và xác thực quyền truy cập của user.
    - Admin/Manager: Có thể truy cập mọi Lead.
    - Officer: Chỉ có thể truy cập Lead được gán cho mình.
    """
    
    # Dùng service để lấy lead (đã bao gồm eager loading)
    # Chúng ta cần import lead_service vào deps.py
    # HOẶC import service vào đây (cẩn thận vòng lặp import)
    # Tạm thời, chúng ta sẽ import service ở đây:
    from ..services import lead_service
    
    try:
        # Lấy lead bằng service (đã bao gồm xử lý 404)
        lead = await lead_service.get_lead_by_id(db, lead_id)
    except ResourceNotFoundError:
        # Ném lại lỗi 404
        raise
        
    # Kiểm tra quyền
    if current_user.role in ["admin", "manager"]:
        return lead  # Admin/Manager được xem tất cả

    if current_user.role == "officer" and lead.assigned_officer_id == current_user.id:
        return lead  # Officer được xem lead của mình

    # Nếu không rơi vào các trường hợp trên -> 403 Forbidden
    raise PermissionDeniedError(detail="You do not have permission to access this lead.")

# Các dependency shortcuts
CurrentUser = Depends(get_current_user)
AdminRequired = Depends(require_roles(["admin"]))
AdminManagerRequired = Depends(require_roles(["admin", "manager"]))
OfficerRequired = Depends(require_roles(["officer", "admin", "manager"]))
