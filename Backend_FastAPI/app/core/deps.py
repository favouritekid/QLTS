# app/core/deps.py
from typing import List, Optional

import casbin
import structlog

from .constants import UserRole
from fastapi import Cookie, Depends, Header, Path, Request, HTTPException, status
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
# ✅ IMPORT REPOSITORY FOR DEPENDENCY
from ..repositories.admission_config_repository import AdmissionConfigRepository


log = structlog.get_logger(__name__)

# =============================================================================
# MODULE EXPORTS (AUTHORIZATION_GUIDELINES.md v1.0)
# =============================================================================
__all__ = [
    # Authentication (Layer 1)
    "get_current_user",
    "get_current_active_user",
    "require_password_not_forced",

    # Authorization (Layer 2)
    "check_permission",
    "require_admin",
    "require_admin_or_manager",
    "require_any_staff",
    "require_roles",

    # Resource Access / IDOR (Layer 3)
    "get_lead_for_user",
    "get_application_for_user",
    "get_notification_template_for_admin",
    "get_notification_rule_for_admin",
    "get_kpi_target_for_admin",  # Phase 2.3
    "get_officer_dashboard_scope",
    "get_criteria_access",
    "get_config_filter",
    "get_lead_list_filter",  # Phase 2.1
    "verify_criteria_visibility",  # Phase 6.5
    "verify_user_management_permission",

    # Admission State Machine IDOR (State Machine Implementation)
    "get_admission_for_manager",  # Manager approve/reject
    "get_admission_for_user",  # Officer resubmit
    "get_admission_for_owner",  # Applicant confirm (SELF check)
    
    # Admission Configuration Console IDOR
    "get_admission_path_for_user",  # Phase 1: Config Console

    # Data Classes
    "OfficerDashboardScope",
    "LeadListFilter",

    # Standard Aliases (Phase 2.2)
    "CasbinAuth",
    "RequireAdmin",
    "RequireManager",
    "RequireStaff",
]

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
            # (✅ PHASE 2: Use SessionRepository instead of direct SQL)
            try:
                from app.repositories import SessionRepository

                repo = SessionRepository(db)
                active_sessions = await repo.get_active_by_user(user.id)
                active_session = active_sessions[0] if active_sessions else None
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
            # (✅ PHASE 2: Use SessionRepository instead of direct SQL)
            try:
                from app.repositories import SessionRepository

                repo = SessionRepository(db)
                session = await repo.get_by_refresh_jti_and_user(refresh_jti, user.id)
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
        # ⚠️ DISABLED (Phase 7): This was causing issues because:
        #    - get_highest_priority_role_from_casbin() checks g-rules for user:X
        #    - If no g-rules exist (which is our case), it returns "user"
        #    - This overwrites officer/manager roles set in DB!
        #
        # Current design: DB role IS the source of truth.
        # Casbin p-rules are defined for role:X (not user:X).
        # check_permission() uses role:{user.role} as subject.
        #
        # If you need per-user Casbin roles (g-rules), implement:
        #   1. Create g-rule when user is created/role changed
        #   2. OR keep DB as source of truth (current approach)

        return user

    except (JWTError, InvalidToken):
        # Đã log lỗi bên trong security.decode_token hoặc ở trên
        raise credentials_exception
    except Exception as e:
        # Bắt các lỗi chung khác
        log.error("Unhandled error in get_current_user", error=str(e), exc_info=True)
        raise credentials_exception


# =============================================================================
# C2 SECURITY FIX: Password Reset Required Check
# =============================================================================


class PasswordChangeRequired(Exception):
    """Exception raised when user must change password before accessing system."""
    pass


async def get_current_active_user(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    """
    Dependency to check if user is active.
    """
    if current_user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )
    return current_user


async def require_password_not_forced(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    """
    C2 SECURITY FIX: Dependency to block users who must change their password.
    
    When user clicks "Not Me" (secure_account), their password_reset_required
    flag is set to True. This dependency blocks all protected endpoints until
    they change their password.
    
    Use this dependency on all endpoints EXCEPT:
    - /auth/change-password (user needs this to change password)
    - /auth/logout (user should be able to logout)
    - /auth/refresh (needed for token rotation)
    
    Raises:
        HTTPException 403: If password_reset_required is True
    
    Example:
        @router.get("/leads")
        async def get_leads(
            current_user: models.User = Depends(require_password_not_forced)
        ):
            # User is guaranteed to NOT have password_reset_required=True
            ...
    """
    if hasattr(current_user, 'password_reset_required') and current_user.password_reset_required:
        log.warning(
            "Access blocked: Password change required",
            user_id=current_user.id,
            username=current_user.username
        )
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PASSWORD_CHANGE_REQUIRED",
                "message": "You must change your password before accessing the system. "
                           "Your account was flagged for security reasons.",
            }
        )
    return current_user


# Alias for use in router Depends
PasswordSafeDep = Depends(require_password_not_forced)


async def check_permission(
    request: Request, 
    current_user: models.User = Depends(get_current_active_user)  # ✅ PHASE 1 FIX: was get_current_user
) -> models.User:
    """
    Casbin RBAC permission check.
    
    ✅ SECURITY FIX (Phase 1): Now uses get_current_active_user to block inactive users.
    Previously allowed inactive users which was a security vulnerability affecting 18+ files.
    
    ✅ FIX (Phase 7): Changed subject from user:X to role:X to match policy definitions.
    Policies are defined for role:officer, role:manager, etc. not user:1, user:2.
    
    Checks: (role:X, url_path, http_method) against Casbin policy.
    """
    enforcer: casbin.AsyncEnforcer = request.app.state.enforcer
    if not enforcer:
        log.critical("Casbin enforcer not found in app state!")
        raise PermissionDeniedError("Permission system is misconfigured.")

    # ✅ FIX: Use role:X instead of user:X to match policy templates
    subject = f"role:{current_user.role}"
    object_path = request.url.path
    action = request.method

    if not enforcer.enforce(subject, object_path, action):
        log.warning(
            "Permission Denied (Casbin)",
            subject=subject,
            object=object_path,
            action=action,
            user_id=current_user.id,
            username=current_user.username,
        )
        raise PermissionDeniedError(
            detail="You do not have permission for this action."
        )

    return current_user


def require_roles(required_roles: List[str]):
    # (Giữ nguyên logic)
    async def role_checker(
        current_user: models.User = Depends(get_current_active_user),
    ) -> models.User:
        if current_user.role not in required_roles:
            from ..utils.exceptions import PermissionDeniedError

            raise PermissionDeniedError(
                detail=f"User does not have the required roles: {required_roles}"
            )
        return current_user

    return role_checker


# =============================================================================
# PHASE 6: ADMIN/MANAGER ROLE DEPENDENCIES (Security Gateway Compliance)
# =============================================================================


async def require_admin(
    current_user: models.User = Depends(get_current_active_user),
) -> models.User:
    """
    Dependency that requires the user to have 'admin' role.
    
    Use this on endpoints that should ONLY be accessible by admins.
    
    Example:
        @router.post("/config")
        async def create_config(
            current_admin: models.User = Depends(require_admin)
        ):
            # Guaranteed to be admin
            ...
    
    Raises:
        PermissionDeniedError: If user is not an admin
    """
    if current_user.role != UserRole.ADMIN:
        raise PermissionDeniedError(
            detail="Admin access required for this operation."
        )
    return current_user


async def require_admin_or_manager(
    current_user: models.User = Depends(get_current_active_user),
) -> models.User:
    """
    Dependency that requires the user to have 'admin' or 'manager' role.
    
    Use this on endpoints that should be accessible by admins and managers.
    
    Example:
        @router.get("/reports")
        async def get_reports(
            current_user: models.User = Depends(require_admin_or_manager)
        ):
            # Guaranteed to be admin or manager
            ...
    
    Raises:
        PermissionDeniedError: If user is not an admin or manager
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise PermissionDeniedError(
            detail="Admin or Manager access required for this operation."
        )
    return current_user


async def require_any_staff(
    current_user: models.User = Depends(get_current_active_user),
) -> models.User:
    """
    Dependency that requires the user to be any staff role (admin, manager, or officer).
    
    Use this on endpoints accessible by all authenticated staff members.
    
    Example:
        @router.get("/team-data")
        async def get_team_data(
            current_user: models.User = Depends(require_any_staff)
        ):
            # Guaranteed to be admin, manager, or officer
            ...
    
    Raises:
        PermissionDeniedError: If user is not a staff member
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER, UserRole.OFFICER]:
        raise PermissionDeniedError(
            detail="Staff access required for this operation."
        )
    return current_user


class OfficerDashboardScope:
    """
    Data class containing validated scope parameters for officer dashboard.
    
    This is returned by get_officer_dashboard_scope dependency to provide
    pre-validated, role-enforced filtering parameters.
    """
    def __init__(
        self,
        scope: str,
        officer_id: int | None,
        unit_id: int | None,
        requesting_user: models.User
    ):
        self.scope = scope
        self.officer_id = officer_id
        self.unit_id = unit_id
        self.requesting_user = requesting_user


async def get_officer_dashboard_scope(
    scope: str = "personal",
    officer_id: int | None = None,
    unit_id: int | None = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> OfficerDashboardScope:
    """
    Security Gateway for Officer Dashboard scoping.
    
    Enforces role-based access to dashboard data:
    - Officers: Can only view personal data
    - Managers: Can view team data (their unit only)
    - Admins: Full access to all scopes and filters
    
    This dependency REPLACES inline role checks in router with centralized
    security logic per MASTER_ARCHITECTURE.md Section 0.2.
    
    Args:
        scope: "personal", "team", or "organization"
        officer_id: Optional officer filter (requires manager/admin)
        unit_id: Optional unit filter (requires admin)
        
    Returns:
        OfficerDashboardScope with validated/sanitized parameters
        
    Raises:
        HTTPException 400: Invalid scope value
        PermissionDeniedError: Scope/filter not allowed for user's role
    """
    # Validate scope value
    if scope not in ("personal", "team", "organization"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid scope: {scope}. Must be 'personal', 'team', or 'organization'"
        )
    
    user_role = current_user.role
    
    # === OFFICER: Personal data only ===
    if user_role == UserRole.OFFICER:
        if scope != "personal":
            raise PermissionDeniedError(
                detail="Officers can only view personal dashboard"
            )
        if officer_id is not None and officer_id != current_user.id:
            raise PermissionDeniedError(
                detail="Officers cannot view other officers' data"
            )
        if unit_id is not None:
            raise PermissionDeniedError(
                detail="Officers cannot filter by unit"
            )
        # Force personal scope
        return OfficerDashboardScope(
            scope="personal",
            officer_id=current_user.id,
            unit_id=None,
            requesting_user=current_user
        )
    
    # === MANAGER: Team or personal, own unit only ===
    if user_role == UserRole.MANAGER:
        if scope == "organization":
            raise PermissionDeniedError(
                detail="Managers cannot view organization-wide data"
            )
        if unit_id is not None and unit_id != current_user.unit_id:
            raise PermissionDeniedError(
                detail="Managers cannot view data from other units"
            )
        
        # If filtering by officer, validate officer belongs to manager's unit
        if officer_id is not None:
            target_officer = await db.get(models.User, officer_id)
            if not target_officer or target_officer.unit_id != current_user.unit_id:
                raise PermissionDeniedError(
                    detail="Officer not found in your unit"
                )
        
        return OfficerDashboardScope(
            scope=scope,
            officer_id=officer_id,
            unit_id=current_user.unit_id,  # Always force manager's unit
            requesting_user=current_user
        )
    
    # === ADMIN: Full access ===
    return OfficerDashboardScope(
        scope=scope,
        officer_id=officer_id,
        unit_id=unit_id,
        requesting_user=current_user
    )


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
    if current_user.role in [UserRole.ADMIN, UserRole.MANAGER]:
        return lead
    if current_user.role == UserRole.OFFICER and lead.assigned_officer_id == current_user.id:
        return lead
    # ✅ SECURITY FIX: Return 404 instead of 403 to prevent resource enumeration
    # Per IDOR best practices, unauthorized access should not reveal resource existence
    raise ResourceNotFoundError(
        detail="Lead not found"
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
    if current_user.role == UserRole.ADMIN:
        log.debug(
            "Admin accessing application",
            application_id=application_id,
            admin_id=current_user.id
        )
        return application

    # MANAGER: Access to applications for leads in their managed units
    if current_user.role == UserRole.MANAGER:
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
    if current_user.role == UserRole.OFFICER:
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


async def get_notification_for_user(
    notification_id: int = Path(..., description="ID of the Notification"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> models.Notification:
    """
    Verify ownership and retrieve a notification.

    **Security Levels:**
    - **Admin**: Can access all notifications (for debugging/support)
    - **Manager/Officer/User**: Can only access their own notifications

    **IDOR Prevention:**
    This dependency prevents Insecure Direct Object Reference attacks by verifying
    that the current user owns the notification before access.

    **Important Security Note:**
    Returns 404 (not 403) when user doesn't own the notification.
    This prevents inference attacks where attacker can enumerate existing IDs.

    Args:
        notification_id: ID of the notification to access
        db: Database session (injected)
        current_user: Current authenticated user (injected)

    Returns:
        Notification model if access is permitted

    Raises:
        ResourceNotFoundError: If notification doesn't exist OR user doesn't own it

    Example:
        ```python
        @router.delete("/notifications/{notification_id}")
        async def delete_notification(
            notification: models.Notification = Depends(get_notification_for_user)
        ):
            # notification is guaranteed to be owned by current user
            await db.delete(notification)
        ```

    Reference: AUTHORIZATION_DECISIONS.md Decision 2 & 5
    """
    from ..repositories.notification_repository import NotificationRepository

    repo = NotificationRepository(db)
    notification = await repo.get(notification_id)

    # Notification not found
    if not notification:
        log.debug(
            "Notification not found",
            notification_id=notification_id,
            user_id=current_user.id
        )
        raise ResourceNotFoundError(
            detail="Notification not found"
        )

    # ADMIN: Full access (for debugging/support purposes)
    if current_user.role == UserRole.ADMIN:
        log.debug(
            "Admin accessing notification",
            notification_id=notification_id,
            admin_id=current_user.id,
            notification_owner=notification.user_id
        )
        return notification

    # ALL OTHER ROLES: Must own the notification
    if notification.user_id == current_user.id:
        return notification

    # IDOR ATTEMPT: User trying to access someone else's notification
    # Return 404 (not 403) to prevent inference attack
    log.warning(
        "IDOR attempt detected: User trying to access another user's notification",
        notification_id=notification_id,
        notification_owner_id=notification.user_id,
        attacker_id=current_user.id,
        attacker_username=current_user.username,
        attacker_role=current_user.role
    )

    # Return 404 to hide existence of notification (security best practice)
    raise ResourceNotFoundError(
        detail="Notification not found"
    )


async def get_user_managed_units(
    db: AsyncSession,
    user_id: int
) -> List[int]:
    """
    Get list of unit IDs that a user manages.
    
    Returns all organizational units where the user has an active manager assignment.
    This is used for ownership verification in IDOR prevention.
    
    ✅ REFACTORED: Uses UserRepository instead of direct SQL.
    
    Args:
        db: Database session
        user_id: ID of the user to check
        
    Returns:
        List of unit IDs where user is an active manager
    """
    from ..repositories import UserRepository
    
    repo = UserRepository(db)
    managed_unit_ids = await repo.get_managed_unit_ids(user_id)
    
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
    if current_user.role == UserRole.ADMIN:
        log.debug(
            "Admin accessing distribution rule",
            rule_id=rule_id,
            user_id=current_user.id
        )
        return rule

    # Manager: check if rule belongs to their managed units
    if current_user.role == UserRole.MANAGER:
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
    if current_user.role == UserRole.ADMIN:
        log.debug(
            "Admin accessing organizational unit",
            unit_id=unit_id,
            user_id=current_user.id
        )
        return unit

    # Manager: check if unit is in their managed units
    if current_user.role == UserRole.MANAGER:
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
    if current_user.role == UserRole.OFFICER and allow_read_only:
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
    if current_user.role == UserRole.ADMIN:
        log.debug(
            "Admin managing user",
            target_user_id=target_user_id,
            current_user_id=current_user.id
        )
        return target_user

    # Manager: check if target user is in their managed units
    if current_user.role == UserRole.MANAGER:
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


async def get_notification_template_for_admin(
    template_id: int = Path(..., description="ID of the Notification Template"),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(check_permission),
) -> models.NotificationTemplate:
    """
    Verify access and retrieve a notification template.

    **Security Levels:**
    - **Admin/Manager/Officer**: All authenticated users can access (Casbin enforces endpoint-level permission)

    **IDOR Prevention:**
    This dependency prevents Insecure Direct Object Reference attacks by verifying
    that the notification template exists before allowing access.

    Args:
        template_id: ID of the notification template to access
        db: Database session (injected)
        current_admin: Current authenticated user with admin permission (injected via Casbin)

    Returns:
        NotificationTemplate model if it exists

    Raises:
        ResourceNotFoundError: If template doesn't exist

    Example:
        ```python
        @router.get("/notification-templates/{template_id}")
        async def get_template(
            template: models.NotificationTemplate = Depends(get_notification_template_for_admin)
        ):
            # template is guaranteed to exist
            return template
        ```
    """
    from sqlalchemy import select

    result = await db.execute(
        select(models.NotificationTemplate).where(
            models.NotificationTemplate.id == template_id
        )
    )
    template = result.scalar_one_or_none()

    if not template:
        log.warning(
            "Notification template not found",
            template_id=template_id,
            user_id=current_admin.id
        )
        raise ResourceNotFoundError(
            detail=f"Notification template {template_id} not found"
        )

    log.debug(
        "User accessing notification template",
        template_id=template_id,
        user_id=current_admin.id
    )
    return template


async def get_notification_rule_for_admin(
    rule_id: int = Path(..., description="ID of the Notification Rule"),
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(check_permission),
) -> models.NotificationRule:
    """
    Verify access and retrieve a notification rule with eager-loaded actions.

    **Security Levels:**
    - **Admin/Manager/Officer**: All authenticated users can access (Casbin enforces endpoint-level permission)

    **IDOR Prevention:**
    This dependency prevents Insecure Direct Object Reference attacks by verifying
    that the notification rule exists before allowing access.

    Args:
        rule_id: ID of the notification rule to access
        db: Database session (injected)
        current_admin: Current authenticated user with admin permission (injected via Casbin)

    Returns:
        NotificationRule model with actions eager-loaded if it exists

    Raises:
        ResourceNotFoundError: If rule doesn't exist

    Example:
        ```python
        @router.get("/notification-rules/{rule_id}")
        async def get_rule(
            rule: models.NotificationRule = Depends(get_notification_rule_for_admin)
        ):
            # rule is guaranteed to exist with actions loaded
            return rule
        ```
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(models.NotificationRule)
        .options(selectinload(models.NotificationRule.actions))
        .where(models.NotificationRule.id == rule_id)
    )
    rule = result.scalar_one_or_none()

    if not rule:
        log.warning(
            "Notification rule not found",
            rule_id=rule_id,
            user_id=current_admin.id
        )
        raise ResourceNotFoundError(
            detail=f"Notification rule {rule_id} not found"
        )

    log.debug(
        "User accessing notification rule",
        rule_id=rule_id,
        user_id=current_admin.id
    )
    return rule



async def get_admission_config_repo(
    db: AsyncSession = Depends(database.get_db)
) -> AdmissionConfigRepository:
    """Dependency for AdmissionConfigRepository."""
    return AdmissionConfigRepository(db)


def verify_criteria_visibility(
    criteria: models.AdmissionCriteria,
    current_user: models.User,
    criteria_code: str,
) -> None:
    """
    Check if user can view criteria based on is_active status.
    
    Per AUTHORIZATION_GUIDELINES.md Section 4:
    - Active criteria: Accessible by all active users
    - Inactive (Draft): Accessible ONLY by Admin/Manager
    - Returns 404 for unauthorized (not 403) - IDOR protection
    
    Use this helper for inline checks when criteria_code comes from Body
    instead of Path parameter.
    
    Args:
        criteria: The criteria to check
        current_user: Current authenticated user
        criteria_code: For error message
        
    Raises:
        ResourceNotFoundError: If user cannot view inactive criteria
    """
    if not criteria.is_active:
        if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
            log.warning(
                "Unauthorized access attempt to inactive criteria",
                user_id=current_user.id,
                criteria_code=criteria_code
            )
            raise ResourceNotFoundError(detail=f"Criteria '{criteria_code}' not found")


async def get_criteria_access(
    criteria_code: str = Path(..., description="Criteria Code"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> models.AdmissionCriteria:
    """
    Get Admission Criteria with IDOR & RBAC protection.
    
    Rules:
    - Active criteria: Accessible by all active users.
    - Inactive (Draft): Accessible ONLY by Admin/Manager.
    
    Raises 404 if not found OR if user lacks permission to view inactive data.
    """
    repo = AdmissionConfigRepository(db)
    criteria = await repo.get_criteria_by_code(criteria_code, load_level="with_groups")
    
    if not criteria:
        raise ResourceNotFoundError(detail=f"Criteria '{criteria_code}' not found")

    # Use shared helper for visibility check
    verify_criteria_visibility(criteria, current_user, criteria_code)
            
    return criteria



# ============================================================================
# DEPENDENCY SHORTCUTS (LEGACY - DEPRECATED)
# ============================================================================
# ⚠️ DEPRECATED: These aliases will be removed in next major version.
# Use the direct async functions instead per AUTHORIZATION_GUIDELINES.md

# DEPRECATED: Use Depends(get_current_user) directly
CurrentUser = Depends(get_current_user)

# DEPRECATED: Use Depends(require_admin) instead
AdminRequired = Depends(require_roles(["admin"]))

# DEPRECATED: Use Depends(require_admin_or_manager) instead
AdminManagerRequired = Depends(require_roles(["admin", "manager"]))

# DEPRECATED: Use Depends(require_any_staff) instead
OfficerRequired = Depends(require_roles(["officer", "admin", "manager"]))


# ============================================================================
# STANDARD ALIASES (AUTHORIZATION_GUIDELINES.md v1.0)
# ============================================================================
# These are the recommended pre-wrapped Depends for router use.
# Usage: current_user: models.User = CasbinAuth

# Casbin RBAC - checks (user, path, method) against policy
CasbinAuth = Depends(check_permission)

# Role-based shortcuts (for when Casbin is overkill)
RequireAdmin = Depends(require_admin)
RequireManager = Depends(require_admin_or_manager)
RequireStaff = Depends(require_any_staff)


async def get_config_filter(
    active_only: bool = True,
    current_user: models.User = Depends(get_current_active_user),
) -> bool:
    """
    Enforce active_only=True for non-admin users.

    Security:
    - Admin/Manager: Can set active_only=False to see draft/inactive items.
    - Others: Forced to view active_only=True.
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER]:
        return True  # Force active only
    return active_only


# NEW: Ownership verification shortcuts for IDOR prevention
DistributionRuleAccessDep = Depends(get_distribution_rule_for_user)
OrgUnitAccessDep = Depends(get_organizational_unit_for_user)


# =============================================================================
# PHASE 2: CONTEXT FILTERING DEPENDENCIES
# =============================================================================


class LeadListFilter:
    """
    Data class containing role-enforced filter parameters for lead listing.
    
    Returned by get_lead_list_filter dependency to provide pre-validated,
    role-enforced filtering parameters per AUTHORIZATION_GUIDELINES.md Section 5.
    """
    def __init__(
        self,
        assigned_officer_id: str | None,
        unit_id: int | None,
        requesting_user: models.User,
        is_forced_officer_filter: bool = False
    ):
        self.assigned_officer_id = assigned_officer_id
        self.unit_id = unit_id
        self.requesting_user = requesting_user
        self.is_forced_officer_filter = is_forced_officer_filter


async def get_lead_list_filter(
    assigned_officer_id: str | None = None,
    unit_id: int | None = None,
    current_user: models.User = Depends(get_current_active_user),
) -> LeadListFilter:
    """
    Security Gateway for Lead listing with role-based filtering.
    
    Enforces role-based visibility rules:
    - Officers: Can ONLY see their assigned leads (forced filter)
    - Managers: Can filter by officers in their unit
    - Admins: Full access to all filters
    
    This dependency REPLACES inline role checks in router per
    AUTHORIZATION_GUIDELINES.md Section 5 (Context Filtering).
    
    Args:
        assigned_officer_id: Optional officer filter (ignored for non-admins)
        unit_id: Optional unit filter
        
    Returns:
        LeadListFilter with validated/sanitized parameters
    """
    user_role = current_user.role
    
    # === OFFICER: Force their own ID, ignore any passed filter ===
    if user_role == UserRole.OFFICER:
        return LeadListFilter(
            assigned_officer_id=str(current_user.id),  # Force own ID
            unit_id=None,  # Officers cannot filter by unit
            requesting_user=current_user,
            is_forced_officer_filter=True
        )
    
    # === MANAGER: Can filter by officers, force own unit ===
    if user_role == UserRole.MANAGER:
        return LeadListFilter(
            assigned_officer_id=assigned_officer_id,
            unit_id=current_user.unit_id,  # Force manager's unit
            requesting_user=current_user,
            is_forced_officer_filter=False
        )
    
    # === ADMIN: Full access ===
    return LeadListFilter(
        assigned_officer_id=assigned_officer_id,
        unit_id=unit_id,
        requesting_user=current_user,
        is_forced_officer_filter=False
    )


async def get_kpi_target_for_admin(
    target_id: int = Path(..., description="ID of the KPI Target"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
) -> models.KpiTarget:
    """
    Fetch KPI Target with admin/manager authorization.

    This dependency replaces direct db.get() in router per
    AUTHORIZATION_GUIDELINES.md Section 4 (IDOR Protection).

    Args:
        target_id: ID of the KPI Target to fetch

    Returns:
        KpiTarget if found and active

    Raises:
        ResourceNotFoundError: If target not found or inactive
    """
    from ..models.config import KpiTarget

    target = await db.get(KpiTarget, target_id)
    if not target or not target.is_active:
        raise ResourceNotFoundError(detail="KPI Target not found")
    return target


# =============================================================================
# ADMISSION STATE MACHINE IDOR DEPENDENCIES
# Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Sections 2.2 and 3
# =============================================================================

async def get_admission_for_manager(
    profile_id: int = Path(..., description="Admission Profile ID"),
    current_user: models.User = Depends(get_current_active_user),
    db: AsyncSession = Depends(database.get_db),
) -> models.AdmissionProfile:
    """
    IDOR Protection for Manager actions (approve/reject).

    ✅ CRITICAL FIX #2: Added SELECT FOR UPDATE lock to prevent race conditions
    Scenario: 2 managers approve/reject same profile simultaneously
    Without lock: Both pass state check, last write wins (inconsistent state)
    With lock: Second request waits, then fails state validation

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.1.3:
    - Admin: Can access all profiles
    - Manager: Can access profiles where lead.unit_id == user.unit_id
    - Return 404 (not 403) for unauthorized access

    Used by:
    - POST /admissions/{id}/approve
    - POST /admissions/{id}/reject

    Args:
        profile_id: Admission profile ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        AdmissionProfile with lead relationship loaded (LOCKED)

    Raises:
        ResourceNotFoundError: Profile not found OR unauthorized (fake 404)
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload  # Use selectinload to avoid LEFT JOIN

    # ✅ CRITICAL FIX #2: Acquire row lock for state-changing operations
    # Use selectinload (separate query) instead of joinedload (LEFT JOIN)
    # to avoid PostgreSQL "FOR UPDATE cannot be applied to nullable side of outer join"
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(selectinload(models.AdmissionProfile.lead))
        .with_for_update()  # ✅ CRITICAL: Prevent concurrent approve/reject
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")

    # IDOR CHECK (after lock acquired)
    if current_user.role != UserRole.ADMIN:
        if not profile.lead or profile.lead.unit_id != current_user.unit_id:
            # Fake 404 to prevent information leakage
            log.warning(
                "IDOR attempt: Manager tried to access profile from different unit",
                user_id=current_user.id,
                user_unit_id=current_user.unit_id,
                profile_id=profile_id,
                profile_unit_id=profile.lead.unit_id if profile.lead else None,
            )
            raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")

    return profile


async def get_admission_for_user(
    profile_id: int = Path(..., description="Admission Profile ID"),
    current_user: models.User = Depends(get_current_active_user),
    db: AsyncSession = Depends(database.get_db),
) -> models.AdmissionProfile:
    """
    IDOR Protection for Officer/Manager actions (resubmit, update).

    ✅ CRITICAL FIX #2: Added SELECT FOR UPDATE lock
    Prevents race conditions in resubmit operations

    Per ADMISSION_STATE_MACHINE_IMPLEMENTATION_PLAN.md Section 3.2:
    - Admin: Can access all profiles
    - Officer: Can access profiles where lead.unit_id == user.unit_id
    - Manager: Can access profiles where lead.unit_id == user.unit_id
    - Return 404 (not 403) for unauthorized access

    Used by:
    - POST /admissions/{id}/resubmit

    Args:
        profile_id: Admission profile ID
        current_user: Current authenticated user
        db: Database session

    Returns:
        AdmissionProfile with lead relationship loaded (LOCKED)

    Raises:
        ResourceNotFoundError: Profile not found OR unauthorized (fake 404)
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload  # Use selectinload to avoid LEFT JOIN

    # ✅ CRITICAL FIX #2: Acquire row lock for resubmit
    # Use selectinload (separate query) instead of joinedload (LEFT JOIN)
    # to avoid PostgreSQL "FOR UPDATE cannot be applied to nullable side of outer join"
    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(selectinload(models.AdmissionProfile.lead))
        .with_for_update()
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")

    # IDOR CHECK
    if current_user.role != UserRole.ADMIN:
        if not profile.lead or profile.lead.unit_id != current_user.unit_id:
            # Fake 404 to prevent information leakage
            log.warning(
                "IDOR attempt: User tried to access profile from different unit",
                user_id=current_user.id,
                user_unit_id=current_user.unit_id,
                profile_id=profile_id,
                profile_unit_id=profile.lead.unit_id if profile.lead else None,
            )
            raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")

    return profile


# ==============================================================================
# DEPRECATED: get_admission_for_owner
# ==============================================================================
# 
# This dependency was designed for user-based confirmation with Lead.user_id.
# However, the Lead model doesn't have a user_id field, so this check is broken.
# 
# REPLACED BY: Token-based confirmation flow (Magic Link)
# - POST /api/admissions/confirm/{token} (public endpoint)
# - Uses AdmissionConfirmationToken + CCCD verification
# 
# See: implementation_plan.md (Magic Link + CCCD Verification)
# 
# async def get_admission_for_owner(
#     profile_id: int = Path(..., description="Admission Profile ID"),
#     current_user: models.User = Depends(get_current_active_user),
#     db: AsyncSession = Depends(database.get_db),
# ) -> models.AdmissionProfile:
#     """DEPRECATED: Use token-based confirmation instead."""
#     raise NotImplementedError(
#         "get_admission_for_owner is deprecated. "
#         "Use token-based confirmation: POST /api/admissions/confirm/{token}"
#     )


# ==============================================================================
# FSM VALIDATION DEPENDENCIES (Smart Dependencies Pattern)
# ==============================================================================

async def validate_status_transition(
    to_status_id: str,
    lead_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user)
) -> models.ConsultationStatus:
    """
    Smart Dependency: Validate FSM transition BEFORE updating lead status.
    
    This dependency enforces RULE #12: Backend must validate transitions.
    
    Args:
        to_status_id: Target status ID
        lead_id: Lead ID to update
        db: Database session
        current_user: Authenticated user
        
    Returns:
        Validated ConsultationStatus object
        
    Raises:
        ResourceNotFoundError: If lead or status not found (404)
        BusinessRuleViolation: If transition violates FSM rules (400)
        
    Architecture Compliance:
        - Smart Dependency: ALL validation logic here
        - Dumb Router: Just coordinates service + commit
        - Service: Pure Python, no HTTPException
    """
    from ..repositories.lead_repository import LeadRepository
    from ..services.phase_manager import derive_phase_from_admission
    from ..services.fsm_engine import is_transition_allowed
    from ..utils.exceptions import BusinessRuleViolation
    
    # 1. Get lead with admission_profile for phase derivation (IDOR check)
    repo = LeadRepository(db)
    lead = await repo.get_lead_by_id_and_unit(lead_id, current_user.unit_id)
    
    if not lead:
        raise ResourceNotFoundError(f"Lead {lead_id} not found")
    
    # 2. Get target status
    to_status = await db.get(models.ConsultationStatus, to_status_id)
    if not to_status:
        raise ResourceNotFoundError(f"Status {to_status_id} not found")
    
    # 3. Derive lead phase from admission_profile
    lead_phase = derive_phase_from_admission(lead.admission_profile).value
    
    # 4. ✅ RULE #12: Validate transition using FSM engine
    is_allowed = await is_transition_allowed(
        db=db,
        from_status_id=lead.consultation_status_id,
        to_status_id=to_status_id,
        lead_phase=lead_phase,
        user_role=current_user.role
    )
    
    if not is_allowed:
        log.warning(
            "FSM validation failed - invalid transition",
            user_id=current_user.id,
            lead_id=lead_id,
            from_status=lead.consultation_status_id,
            to_status=to_status_id,
            lead_phase=lead_phase,
            user_role=current_user.role
        )
        raise BusinessRuleViolation(
            f"Invalid status transition from {lead.consultation_status_id or 'NULL'} "
            f"to {to_status_id}. Not allowed in current phase '{lead_phase}' "
            f"for role '{current_user.role}'."
        )
    
    log.info(
        "FSM validation passed",
        user_id=current_user.id,
        lead_id=lead_id,
        from_status=lead.consultation_status_id,
        to_status=to_status_id,
        lead_phase=lead_phase
    )
    
    return to_status
