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


# ============================================================================
# OWNERSHIP VERIFICATION DEPENDENCIES (IDOR PREVENTION)
# ============================================================================


async def get_application_for_user(
    application_id: int = Path(..., description="ID of the Application"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
) -> models.Application:
    """
    Verify ownership and retrieve an application.

    **Security Levels:**
    - **Admin**: Can access all applications
    - **Manager**: Can access applications for leads in their managed units
    - **Officer**: Can access applications for their assigned leads only

    **IDOR Prevention:**
    This dependency prevents Insecure Direct Object Reference attacks by verifying
    that the current user has permission to access the specified application.

    Args:
        application_id: ID of the application to access
        db: Database session (injected)
        current_user: Current authenticated user (injected)

    Returns:
        Application model if access is permitted

    Raises:
        ResourceNotFoundError: If application doesn't exist
        PermissionDeniedError: If user doesn't have permission

    Example:
        ```python
        @router.get("/applications/{application_id}")
        async def get_application(
            application: models.Application = Depends(get_application_for_user)
        ):
            # application is guaranteed to be accessible by current user
            return application
        ```
    """
    from ..services import application_service

    # Get application with lead relationship
    try:
        application = await application_service.get_application_by_id(
            db,
            application_id,
            load_lead=True  # Ensure lead is loaded for ownership check
        )
    except ResourceNotFoundError:
        log.warning(
            "Application not found",
            application_id=application_id,
            user_id=current_user.id
        )
        raise ResourceNotFoundError(
            detail=f"Application with id {application_id} not found"
        )

    # Verify application has associated lead
    if not application.lead:
        log.error(
            "Application has no associated lead - data integrity issue",
            application_id=application_id
        )
        raise ResourceNotFoundError(
            detail=f"Application {application_id} has no associated lead"
        )

    lead = application.lead

    # ADMIN: Full access to all applications
    if current_user.role == "admin":
        log.debug(
            "Admin accessing application",
            application_id=application_id,
            admin_id=current_user.id
        )
        return application

    # MANAGER: Access to applications for leads in their managed units
    if current_user.role == "manager":
        managed_units = await get_user_managed_units(db, current_user.id)
        if lead.unit_id in managed_units:
            log.debug(
                "Manager accessing application in managed unit",
                application_id=application_id,
                manager_id=current_user.id,
                unit_id=lead.unit_id
            )
            return application
        else:
            log.warning(
                "IDOR attempt detected: Manager trying to access application outside managed units",
                application_id=application_id,
                lead_unit_id=lead.unit_id,
                managed_units=managed_units,
                manager_id=current_user.id,
                username=current_user.username
            )
            raise PermissionDeniedError(
                detail="You do not have permission to access this application. "
                       "This application belongs to a lead outside your managed units."
            )

    # OFFICER: Access to applications for their assigned leads only
    if current_user.role == "officer":
        if lead.assigned_officer_id == current_user.id:
            log.debug(
                "Officer accessing application for assigned lead",
                application_id=application_id,
                officer_id=current_user.id,
                lead_id=lead.id
            )
            return application
        else:
            log.warning(
                "IDOR attempt detected: Officer trying to access another officer's application",
                application_id=application_id,
                lead_id=lead.id,
                lead_officer_id=lead.assigned_officer_id,
                officer_id=current_user.id,
                username=current_user.username
            )
            raise PermissionDeniedError(
                detail="You do not have permission to access this application. "
                       "This application belongs to a lead assigned to another officer."
            )

    # ACCESS DENIED - Unknown role or no permission
    log.warning(
        "IDOR attempt detected: User with unknown role trying to access application",
        application_id=application_id,
        user_id=current_user.id,
        user_role=current_user.role,
        lead_officer_id=lead.assigned_officer_id,
        lead_unit_id=lead.unit_id
    )
    raise PermissionDeniedError(
        detail="You do not have permission to access this application."
    )


async def get_user_managed_units(
    db: AsyncSession,
    user_id: int
) -> List[int]:
    """
    Get list of unit IDs that a user manages.

    Returns all organizational units where the user has an active manager assignment.
    This is used for ownership verification in IDOR prevention.

    Args:
        db: Database session
        user_id: ID of the user to check

    Returns:
        List of unit IDs where user is an active manager

    Example:
        >>> managed_units = await get_user_managed_units(db, user_id=5)
        >>> # [10, 20, 30]  # User 5 manages units 10, 20, and 30
    """
    from sqlalchemy import select
    from ..models import UserUnitAssignment

    # Query for active manager assignments
    stmt = select(UserUnitAssignment.unit_id).where(
        UserUnitAssignment.user_id == user_id,
        UserUnitAssignment.role == "manager",
        UserUnitAssignment.is_active == True
    )

    result = await db.execute(stmt)
    managed_unit_ids = [row[0] for row in result.all()]

    log.debug(
        "Fetched managed units",
        user_id=user_id,
        managed_units=managed_unit_ids
    )

    return managed_unit_ids


async def get_distribution_rule_for_user(
    rule_id: int = Path(..., description="ID của Distribution Rule"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
) -> models.OfferingDistributionConfig:
    """
    Verify ownership and retrieve a distribution rule.

    **Security Levels:**
    - **Admin**: Full access to all distribution rules
    - **Manager**: Access only to rules in their managed units
    - **Officer**: Denied (raises 403)

    **IDOR Prevention:**
    This dependency prevents Insecure Direct Object Reference attacks by verifying
    that the current user has permission to access the specified distribution rule.

    Args:
        rule_id: ID of the distribution rule to access
        db: Database session (injected)
        current_user: Current authenticated user (injected)

    Returns:
        OfferingDistributionConfig model if access is permitted

    Raises:
        ResourceNotFoundError: If rule doesn't exist
        PermissionDeniedError: If user doesn't have permission to access this rule

    Example:
        ```python
        @router.delete("/distribution-rules/{rule_id}")
        async def delete_rule(
            rule: models.OfferingDistributionConfig = Depends(get_distribution_rule_for_user)
        ):
            # rule is guaranteed to be accessible by current user
            await config_service.delete_distribution_rule(db, rule.id)
        ```
    """
    from sqlalchemy import select
    from ..services import config_service

    # Fetch the distribution rule
    try:
        rule = await config_service.get_distribution_rule_by_id(db, rule_id)
    except ResourceNotFoundError:
        log.warning(
            "Distribution rule not found",
            rule_id=rule_id,
            user_id=current_user.id
        )
        raise

    # Admin has full access
    if current_user.role == "admin":
        log.debug(
            "Admin accessing distribution rule",
            rule_id=rule_id,
            user_id=current_user.id
        )
        return rule

    # Manager: check if rule belongs to their managed units
    if current_user.role == "manager":
        managed_units = await get_user_managed_units(db, current_user.id)

        if rule.unit_id in managed_units:
            log.debug(
                "Manager accessing distribution rule in managed unit",
                rule_id=rule_id,
                unit_id=rule.unit_id,
                user_id=current_user.id
            )
            return rule
        else:
            log.warning(
                "IDOR attempt detected: Manager trying to access distribution rule outside managed units",
                rule_id=rule_id,
                rule_unit_id=rule.unit_id,
                managed_units=managed_units,
                user_id=current_user.id,
                username=current_user.username
            )
            raise PermissionDeniedError(
                detail=f"You do not have permission to access this distribution rule. "
                       f"This rule belongs to unit {rule.unit_id}, which is not in your managed units."
            )

    # Officer or other roles: deny access
    log.warning(
        "IDOR attempt detected: Non-admin/manager user trying to access distribution rule",
        rule_id=rule_id,
        user_id=current_user.id,
        user_role=current_user.role
    )
    raise PermissionDeniedError(
        detail="You do not have permission to manage distribution rules. "
               "Only Admins and Managers can access this resource."
    )


async def get_organizational_unit_for_user(
    unit_id: int = Path(..., description="ID của Organization Unit"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
    allow_read_only: bool = False,
) -> models.OrganizationUnit:
    """
    Verify ownership and retrieve an organizational unit.

    **Security Levels:**
    - **Admin**: Full access to all units
    - **Manager**: Access to their managed units (+ descendants if implemented)
    - **Officer**: Read-only access if allow_read_only=True, otherwise denied

    **IDOR Prevention:**
    This dependency prevents cross-unit access violations by verifying
    organizational unit ownership.

    Args:
        unit_id: ID of the organizational unit to access
        db: Database session (injected)
        current_user: Current authenticated user (injected)
        allow_read_only: If True, allows Officers to view units they belong to

    Returns:
        OrganizationUnit model if access is permitted

    Raises:
        ResourceNotFoundError: If unit doesn't exist
        PermissionDeniedError: If user doesn't have permission to access this unit

    Example:
        ```python
        # Write operation (managers only)
        @router.put("/organization-units/{unit_id}")
        async def update_unit(
            unit: models.OrganizationUnit = Depends(get_organizational_unit_for_user)
        ):
            # Only admin/managers can reach here
            ...

        # Read operation (allow officers)
        @router.get("/organization-units/{unit_id}")
        async def get_unit(
            unit: models.OrganizationUnit = Depends(
                lambda **kwargs: get_organizational_unit_for_user(**kwargs, allow_read_only=True)
            )
        ):
            # Admin, managers, and officers in this unit can view
            ...
        ```
    """
    from sqlalchemy import select
    from ..services import organization_service

    # Fetch the organizational unit
    try:
        unit = await organization_service.get_organization_unit_by_id(db, unit_id)
    except ResourceNotFoundError:
        log.warning(
            "Organizational unit not found",
            unit_id=unit_id,
            user_id=current_user.id
        )
        raise

    # Admin has full access
    if current_user.role == "admin":
        log.debug(
            "Admin accessing organizational unit",
            unit_id=unit_id,
            user_id=current_user.id
        )
        return unit

    # Manager: check if unit is in their managed units
    if current_user.role == "manager":
        managed_units = await get_user_managed_units(db, current_user.id)

        if unit_id in managed_units:
            log.debug(
                "Manager accessing managed organizational unit",
                unit_id=unit_id,
                user_id=current_user.id
            )
            return unit
        else:
            log.warning(
                "IDOR attempt detected: Manager trying to access organizational unit outside managed units",
                unit_id=unit_id,
                managed_units=managed_units,
                user_id=current_user.id,
                username=current_user.username
            )
            raise PermissionDeniedError(
                detail=f"You do not have permission to access this organizational unit. "
                       f"Unit {unit_id} is not in your managed units."
            )

    # Officer: allow read-only if enabled and user belongs to this unit
    if current_user.role == "officer" and allow_read_only:
        if current_user.unit_id == unit_id:
            log.debug(
                "Officer viewing own organizational unit (read-only)",
                unit_id=unit_id,
                user_id=current_user.id
            )
            return unit
        else:
            log.warning(
                "IDOR attempt detected: Officer trying to view organizational unit they don't belong to",
                unit_id=unit_id,
                user_unit_id=current_user.unit_id,
                user_id=current_user.id
            )
            raise PermissionDeniedError(
                detail=f"You can only view your own organizational unit (Unit {current_user.unit_id})."
            )

    # Officer without read permission or other roles: deny access
    log.warning(
        "IDOR attempt detected: Insufficient permissions to access organizational unit",
        unit_id=unit_id,
        user_id=current_user.id,
        user_role=current_user.role,
        allow_read_only=allow_read_only
    )
    raise PermissionDeniedError(
        detail="You do not have permission to access organizational units. "
               "Only Admins and Managers can manage organizational units."
    )


async def verify_user_management_permission(
    target_user_id: int,
    db: AsyncSession,
    current_user: models.User,
) -> models.User:
    """
    Verify permission to manage a target user and return the user.

    **Security Levels:**
    - **Admin**: Can manage all users
    - **Manager**: Can only manage users in their managed units
    - **Officer**: Cannot manage users (denied)

    **IDOR Prevention:**
    This dependency prevents unauthorized user management by verifying
    that managers can only manage users within their organizational scope.

    Args:
        target_user_id: ID of the user to manage
        db: Database session
        current_user: Current authenticated user

    Returns:
        Target User model if management is permitted

    Raises:
        ResourceNotFoundError: If target user doesn't exist
        PermissionDeniedError: If current user cannot manage target user

    Example:
        ```python
        @router.delete("/users/{user_id}")
        async def delete_user(
            user_id: int,
            db: AsyncSession = Depends(database.get_db),
            current_admin: models.User = PermissionDep,
        ):
            # Pre-verify ownership
            target_user = await verify_user_management_permission(
                target_user_id=user_id,
                db=db,
                current_user=current_admin
            )
            # Proceed with deletion
            await user_service.delete_user(db, target_user.id)
        ```
    """
    from sqlalchemy import select
    from ..services import user_service

    # Fetch target user
    target_user = await user_service.get_user_by_id(db, target_user_id)
    if not target_user:
        log.warning(
            "Target user not found for management verification",
            target_user_id=target_user_id,
            current_user_id=current_user.id
        )
        raise ResourceNotFoundError(detail=f"User {target_user_id} not found")

    # Admin has full access
    if current_user.role == "admin":
        log.debug(
            "Admin managing user",
            target_user_id=target_user_id,
            current_user_id=current_user.id
        )
        return target_user

    # Manager: check if target user is in their managed units
    if current_user.role == "manager":
        managed_units = await get_user_managed_units(db, current_user.id)

        # Check if target user belongs to any managed unit
        if target_user.unit_id and target_user.unit_id in managed_units:
            log.debug(
                "Manager managing user in managed unit",
                target_user_id=target_user_id,
                target_unit_id=target_user.unit_id,
                current_user_id=current_user.id
            )
            return target_user
        else:
            log.warning(
                "IDOR attempt detected: Manager trying to manage user outside managed units",
                target_user_id=target_user_id,
                target_unit_id=target_user.unit_id,
                managed_units=managed_units,
                current_user_id=current_user.id,
                current_username=current_user.username
            )
            raise PermissionDeniedError(
                detail=f"You do not have permission to manage this user. "
                       f"User belongs to unit {target_user.unit_id}, which is not in your managed units."
            )

    # Officer or other roles: deny access
    log.warning(
        "IDOR attempt detected: Non-admin/manager trying to manage user",
        target_user_id=target_user_id,
        current_user_id=current_user.id,
        current_user_role=current_user.role
    )
    raise PermissionDeniedError(
        detail="You do not have permission to manage users. "
               "Only Admins and Managers can perform user management operations."
    )


# ============================================================================
# DEPENDENCY SHORTCUTS
# ============================================================================

# (Giữ nguyên các dependency shortcuts)
CurrentUser = Depends(get_current_user)
AdminRequired = Depends(require_roles(["admin"]))
AdminManagerRequired = Depends(require_roles(["admin", "manager"]))
OfficerRequired = Depends(require_roles(["officer", "admin", "manager"]))

# NEW: Ownership verification shortcuts for IDOR prevention
DistributionRuleAccessDep = Depends(get_distribution_rule_for_user)
OrgUnitAccessDep = Depends(get_organizational_unit_for_user)
