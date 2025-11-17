# app/core/deps.py
from typing import List, Optional

import casbin
import structlog
from fastapi import Cookie, Depends, Header, Path, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, security  # ✅ THÊM IMPORT security
from ..database import safe_redis_exists, safe_redis_get
from ..services import user_service
from ..utils.exceptions import (
    InvalidToken,
    PermissionDeniedError,
    ResourceNotFoundError,
)

log = structlog.get_logger(__name__)

# ✅ SECURITY FIX: Keep OAuth2 scheme for backwards compatibility, but make it optional
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(
    request: Request,  # ← PHASE 2: Add request to access enforcer
    access_token_cookie: Optional[str] = Cookie(None, alias="access_token"),
    authorization: Optional[str] = Header(None),
    token_from_oauth: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(database.get_db)
) -> models.User:
    """
    ✅ SECURITY FIX: Dependency to get current user from JWT token.

    Priority for token source (most secure first):
    1. httpOnly cookie (access_token) - RECOMMENDED for browser requests
    2. Authorization header (fallback for API clients & backwards compatibility)

    Checks: session validity (r_jti), blacklist, and user status.
    """
    credentials_exception = InvalidToken(detail="Could not validate credentials")

    # === ✅ SECURITY FIX: Read token from httpOnly cookie first ===
    token = None
    token_source = None

    if access_token_cookie:
        token = access_token_cookie
        token_source = "cookie"
    elif authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ")[1]
        token_source = "header"
    elif token_from_oauth:
        token = token_from_oauth
        token_source = "oauth_scheme"

    if not token:
        log.warning("No authentication token provided (no cookie, header, or oauth)")
        raise credentials_exception

    log.debug(f"Token source: {token_source}")

    try:
        # ✅ BƯỚC 3: SỬA HÀM get_current_user

        # === STEP 1: DECODE TOKEN ===
        try:
            # Dùng hàm decode mới đã tạo trong security.py
            payload = security.decode_token(token)
        except InvalidToken as e:
            log.warning("JWT decoding error or token expired", error=str(e))
            raise credentials_exception

        username: str | None = payload.get("sub")
        access_jti: str | None = payload.get("jti")
        refresh_jti: str | None = payload.get("r_jti")  # <-- Lấy JTI của Refresh Token
        token_type: str = payload.get("type", "access")

        if (
            username is None
            or access_jti is None
            or refresh_jti is None  # <-- Kiểm tra cả refresh_jti
            or token_type != "access"
        ):
            log.warning(
                "Token missing critical claims (sub, jti, r_jti, or wrong type)",
                payload=payload,
            )
            raise credentials_exception

        # === STEP 2: CHECK ACCESS JTI BLACKLIST ===
        # (Kiểm tra xem chính Access Token này đã bị logout/xoay vòng chưa)
        try:
            is_jti_blacklisted = await safe_redis_exists(f"blacklist:{access_jti}")
            if is_jti_blacklisted:
                log.info(
                    "Token validation failed: Access JTI found in blacklist",
                    jti=access_jti,
                )
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            log.error(
                "Redis Access JTI blacklist check failed", jti=access_jti, error=str(e)
            )
            # (Không cần fallback CSDL cho access JTI)

        # === STEP 3: GET USER & CHECK USER BLACKLIST ===
        user = await user_service.get_user_by_username(db, username=username)
        if user is None:
            log.warning("Token validation failed: User not found", username=username)
            raise credentials_exception

        try:
            is_user_blacklisted = await safe_redis_exists(f"user_blacklist:{user.id}")
            if is_user_blacklisted:
                log.info(
                    "Token rejected: User found in global blacklist (password changed?)",
                    user_id=user.id,
                )
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            log.error(
                "Redis user blacklist check failed", user_id=user.id, error=str(e)
            )
            # (Giữ nguyên logic fallback CSDL cho user blacklist)
            try:
                from datetime import datetime, timezone

                from sqlalchemy import and_, select

                result = await db.execute(
                    select(models.UserSession)
                    .where(
                        and_(
                            models.UserSession.user_id == user.id,
                            models.UserSession.revoked_at.is_(None),
                            models.UserSession.expires_at > datetime.now(timezone.utc),
                        )
                    )
                    .limit(1)
                )
                active_session = result.scalar_one_or_none()
                if active_session is None:
                    log.warning(
                        "Database fallback: No active sessions found for user",
                        user_id=user.id,
                    )
                    raise credentials_exception
                log.info(
                    "Database fallback successful: User has active sessions",
                    user_id=user.id,
                )
            except InvalidToken:
                raise
            except Exception as db_error:
                log.error(
                    "Database fallback failed during user blacklist check",
                    user_id=user.id,
                    error=str(db_error),
                )
                raise credentials_exception

        # === ✅ NEW STEP 4: CHECK SESSION VALIDITY ===
        # (Kiểm tra xem session (liên kết qua r_jti) có bị revoke không)
        try:
            stored_user_id = await safe_redis_get(f"session:{refresh_jti}")
            if not stored_user_id or int(stored_user_id) != user.id:
                log.warning(
                    "Token validation failed: Session not found in Redis (revoked?)",
                    user_id=user.id,
                    refresh_jti=refresh_jti,
                )
                raise credentials_exception
        except InvalidToken:
            raise
        except Exception as e:
            log.error(
                "Redis Session check failed", refresh_jti=refresh_jti, error=str(e)
            )
            # (Fallback CSDL cho session check)
            try:
                from datetime import datetime, timezone

                from sqlalchemy import and_, select

                result = await db.execute(
                    select(models.UserSession).where(
                        and_(
                            models.UserSession.user_id == user.id,
                            models.UserSession.refresh_jti == refresh_jti,
                            models.UserSession.revoked_at.is_(None),
                            models.UserSession.expires_at > datetime.now(timezone.utc),
                        )
                    )
                )
                session = result.scalar_one_or_none()
                if session is None:
                    log.warning(
                        "Database fallback: Session not found or revoked",
                        jti=refresh_jti,
                    )
                    raise credentials_exception
                log.info(
                    "Database fallback successful: Session validated via database",
                    jti=refresh_jti,
                )
            except InvalidToken:
                raise
            except Exception as db_error:
                log.error(
                    "Database fallback failed during Session check",
                    jti=refresh_jti,
                    error=str(db_error),
                )
                raise credentials_exception

        # ← PHASE 2: Auto-sync DB role to match Casbin (source of truth)
        try:
            enforcer = request.app.state.enforcer
            casbin_role = await user_service.get_highest_priority_role_from_casbin(
                enforcer, user.id
            )

            if user.role != casbin_role:
                log.warning(
                    "DB/Casbin role mismatch detected! Auto-syncing DB to Casbin.",
                    user_id=user.id,
                    db_role=user.role,
                    casbin_role=casbin_role
                )
                # Update DB to match Casbin (source of truth)
                user.role = casbin_role
                db.add(user)
                await db.commit()
                await db.refresh(user)
                log.info(
                    "DB role auto-synced successfully",
                    user_id=user.id,
                    new_role=casbin_role
                )
        except Exception as e_sync:
            # Don't fail auth if sync fails, just log it
            log.error(
                "Auto-sync failed, but continuing with authentication",
                user_id=user.id,
                error=str(e_sync),
                exc_info=True
            )

        return user

    except (JWTError, InvalidToken):
        # Đã log lỗi bên trong security.decode_token hoặc ở trên
        raise credentials_exception
    except Exception as e:
        # Bắt các lỗi chung khác
        log.error("Unhandled error in get_current_user", error=str(e), exc_info=True)
        raise credentials_exception


async def check_permission(
    request: Request, current_user: models.User = Depends(get_current_user)
):
    # (Giữ nguyên logic, thêm await cho log)
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    if not enforcer:
        log.critical("Casbin enforcer not found in app state!")
        raise PermissionDeniedError("Permission system is misconfigured.")

    subject = f"user:{current_user.id}"
    object_path = request.url.path
    action = request.method

    if not enforcer.enforce(subject, object_path, action):
        log.warning(
            "Permission Denied (Casbin)",
            subject=subject,
            object=object_path,
            action=action,
        )
        raise PermissionDeniedError(
            detail="You do not have permission for this action."
        )

    return current_user


def require_roles(required_roles: List[str]):
    # (Giữ nguyên logic)
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
    # (Giữ nguyên logic)
    from ..services import lead_service

    try:
        lead = await lead_service.get_lead_by_id_shallow(db, lead_id)
    except ResourceNotFoundError:
        raise
    if current_user.role in ["admin", "manager"]:
        return lead
    if current_user.role == "officer" and lead.assigned_officer_id == current_user.id:
        return lead
    raise PermissionDeniedError(
        detail="You do not have permission to access this lead."
    )


# (Giữ nguyên các dependency shortcuts)
CurrentUser = Depends(get_current_user)
AdminRequired = Depends(require_roles(["admin"]))
AdminManagerRequired = Depends(require_roles(["admin", "manager"]))
OfficerRequired = Depends(require_roles(["officer", "admin", "manager"]))
