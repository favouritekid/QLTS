# app/core/deps.py
from typing import List, Optional

import casbin
import structlog

from .constants import UserRole
from fastapi import Cookie, Depends, Header, Path, Request, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import PyJWTError as JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models, security  # ✅ THÊM IMPORT security
from ..database import safe_redis_exists, safe_redis_get
from ..services import user_service
from ..utils.exceptions import (
    BusinessRuleViolation,
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
    "get_notification_template_for_admin",
    "get_notification_rule_for_admin",
    "get_kpi_target_for_admin",  # Phase 2.3
    "get_kpi_plan_for_user",  # Phase A6: KPI Planning IDOR
    "get_kpi_plan_month_for_user",  # Phase A6: KPI Planning IDOR
    "get_officer_dashboard_scope",
    "get_criteria_access",
    "get_config_filter",
    "get_lead_list_filter",  # Phase 2.1
    "verify_criteria_visibility",  # Phase 6.5
    "verify_user_management_permission",

    # Admission State Machine IDOR (State Machine Implementation)
    "get_admission_for_manager",  # Manager approve/reject
    "get_admission_for_user",  # Officer resubmit
    "get_admission_for_user_read",  # Read-only fee-status / detail (no lock)

    # Admission Configuration Console IDOR
    "get_admission_path_for_user",  # Phase 1: Config Console

    # Collaborator System (Phase 1)
    "require_collaborator_role",
    "get_own_collaborator",
    "get_collaborator_for_user",
    "get_lead_claim_for_review",

    # Drill-down IDOR (widget endpoints)
    "resolve_drill_down_officer_id",
    "resolve_kpi_plan_officer_id",

    # Data Classes
    "DashboardScopeContext",
    "OfficerDashboardScope",  # alias for migration, remove later
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
    Also enforces MFA for privileged roles (admin, manager) per OWASP ASVS 5.0.
    """
    from ..config import settings

    if current_user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user"
        )

    # OWASP ASVS 5.0: Enforce MFA for privileged accounts
    if (
        current_user.role in settings.MFA_ENFORCE_ROLES
        and not getattr(current_user, "mfa_enabled", False)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="MFA is required for privileged accounts. Please enable MFA in Settings.",
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


async def require_finance_staff(
    current_user: models.User = Depends(get_current_active_user),
) -> models.User:
    """
    Dependency that requires the user to have finance-related role (admin, manager, or accountant).

    Use this on finance endpoints like recording payments, issuing invoices, etc.

    Example:
        @router.post("/payments")
        async def record_payment(
            current_user: models.User = Depends(require_finance_staff)
        ):
            # Guaranteed to be admin, manager, or accountant
            ...

    Raises:
        PermissionDeniedError: If user is not finance staff
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER, UserRole.ACCOUNTANT]:
        raise PermissionDeniedError(
            detail="Finance staff access required for this operation."
        )
    return current_user


async def require_any_staff(
    current_user: models.User = Depends(get_current_active_user),
) -> models.User:
    """
    Dependency that requires the user to be any staff role (admin, manager, accountant, or officer).

    Use this on endpoints accessible by all authenticated staff members.

    Example:
        @router.get("/team-data")
        async def get_team_data(
            current_user: models.User = Depends(require_any_staff)
        ):
            # Guaranteed to be admin, manager, accountant, or officer
            ...

    Raises:
        PermissionDeniedError: If user is not a staff member
    """
    if current_user.role not in [UserRole.ADMIN, UserRole.MANAGER, UserRole.ACCOUNTANT, UserRole.OFFICER]:
        raise PermissionDeniedError(
            detail="Staff access required for this operation."
        )
    return current_user


class DashboardScopeContext:
    """
    Pre-resolved scope context for all dashboard-family endpoints.

    Created once by the dependency resolver; routers and services read
    from this object instead of resolving scope/descendants themselves.

    Replaces the old OfficerDashboardScope (V12 plan).
    """
    __slots__ = (
        "scope_kind",
        "requested_officer_id",
        "requested_unit_id",
        "effective_officer_ids",
        "effective_unit_root_id",
        "effective_unit_ids",
        "includes_descendants",
        "forced_by_role",
        "label",
        "requesting_user",
    )

    def __init__(
        self,
        *,
        scope_kind: str,
        requested_officer_id: int | None,
        requested_unit_id: int | None,
        effective_officer_ids: list[int],
        effective_unit_root_id: int | None,
        effective_unit_ids: list[int],
        includes_descendants: bool,
        forced_by_role: bool,
        label: str,
        requesting_user: models.User,
    ):
        self.scope_kind = scope_kind
        self.requested_officer_id = requested_officer_id
        self.requested_unit_id = requested_unit_id
        self.effective_officer_ids = effective_officer_ids
        self.effective_unit_root_id = effective_unit_root_id
        self.effective_unit_ids = effective_unit_ids
        self.includes_descendants = includes_descendants
        self.forced_by_role = forced_by_role
        self.label = label
        self.requesting_user = requesting_user


# Keep old name as alias during migration — remove after router migration done
OfficerDashboardScope = DashboardScopeContext


async def _validate_officer_target(
    db: AsyncSession,
    officer_id: int,
    current_user: models.User,
) -> models.User:
    """
    Shared helper: validate that officer_id points to an existing user with
    role=officer, and that current_user is allowed to view them.

    Used by both get_officer_dashboard_scope and resolve_drill_down_officer_id
    to enforce identical security semantics.

    Returns the validated target User on success.
    Raises ResourceNotFoundError (404) on any failure — never leaks existence.
    """
    target = await db.get(models.User, officer_id)
    if not target or target.role != UserRole.OFFICER:
        raise ResourceNotFoundError(detail="Officer not found")

    user_role = current_user.role

    if user_role == UserRole.MANAGER:
        if current_user.unit_id is None:
            raise ResourceNotFoundError(detail="Officer not found")
        from ..repositories.organization_repository import OrganizationRepository
        org_repo = OrganizationRepository(db)
        allowed_unit_ids = await org_repo.get_descendant_unit_ids(current_user.unit_id)
        if target.unit_id not in allowed_unit_ids:
            raise ResourceNotFoundError(detail="Officer not found")

    elif user_role == UserRole.ADMIN:
        pass  # Admin can view any officer

    else:
        # Should not reach here — callers gate on role first.
        raise ResourceNotFoundError(detail="Officer not found")

    return target


async def get_officer_dashboard_scope(
    scope: str = "personal",
    officer_id: int | None = None,
    unit_id: int | None = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> DashboardScopeContext:
    """
    Security Gateway + Scope Resolver for all dashboard-family endpoints.

    Creates a fully-resolved DashboardScopeContext so that routers and
    services never need to resolve descendants or derive unit from officer.

    Role-scope matrix (V12):
    - officer  → personal only
    - manager  → unit only
    - admin    → organization, or personal when officer_id is provided
    - manager personal  → 400
    - admin unit        → 400
    - admin personal without officer_id → 400

    Compatibility: inbound scope=team is normalized to unit.
    IDOR: unauthorized officer_id → 404 (never 403).
    """
    from ..repositories.organization_repository import OrganizationRepository
    from ..repositories.officer_repository import OfficerRepository

    # --- Compatibility alias: team → unit ---
    if scope == "team":
        scope = "unit"

    # --- Validate scope value ---
    if scope not in ("personal", "unit", "organization"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Scope không hợp lệ: {scope}. Phải là 'personal', 'unit', hoặc 'organization'"
        )

    user_role = current_user.role

    # =====================================================================
    # OFFICER: personal only, short-circuit (no CTE)
    # =====================================================================
    if user_role == UserRole.OFFICER:
        if scope != "personal":
            raise PermissionDeniedError(
                detail="Officers can only view personal dashboard"
            )
        if officer_id is not None and officer_id != current_user.id:
            raise ResourceNotFoundError(detail="Officer not found")
        if unit_id is not None:
            raise PermissionDeniedError(
                detail="Officers cannot filter by unit"
            )
        return DashboardScopeContext(
            scope_kind="personal",
            requested_officer_id=current_user.id,
            requested_unit_id=None,
            effective_officer_ids=[current_user.id],
            effective_unit_root_id=current_user.unit_id,
            effective_unit_ids=[current_user.unit_id] if current_user.unit_id else [],
            includes_descendants=False,
            forced_by_role=True,
            label="Cá nhân",
            requesting_user=current_user,
        )

    # =====================================================================
    # MANAGER: unit only
    # =====================================================================
    if user_role == UserRole.MANAGER:
        if scope != "unit":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Manager chỉ được dùng scope 'unit'"
            )
        if unit_id is not None and unit_id != current_user.unit_id:
            raise PermissionDeniedError(
                detail="Managers cannot view data from other units"
            )

        # Validate officer drill-down if requested
        target_officer = None
        if officer_id is not None:
            target_officer = await _validate_officer_target(db, officer_id, current_user)

        # Resolve descendant units
        root_unit_id = current_user.unit_id
        if root_unit_id is None:
            raise BusinessRuleViolation(
                detail="Manager chưa được gán đơn vị"
            )

        org_repo = OrganizationRepository(db)
        descendant_unit_ids = await org_repo.get_descendant_unit_ids(root_unit_id)

        # If drill-down to specific officer, short-circuit to single officer
        if target_officer is not None:
            return DashboardScopeContext(
                scope_kind="unit",
                requested_officer_id=officer_id,
                requested_unit_id=root_unit_id,
                effective_officer_ids=[officer_id],
                effective_unit_root_id=root_unit_id,
                effective_unit_ids=descendant_unit_ids,
                includes_descendants=True,
                forced_by_role=True,
                label=f"Cá nhân: {target_officer.full_name}",
                requesting_user=current_user,
            )

        # Aggregated: all officers in descendant units
        officer_repo = OfficerRepository(db)
        effective_ids: list[int] = []
        for uid in descendant_unit_ids:
            ids = await officer_repo.get_active_officer_ids(scope="unit", unit_id=uid)
            effective_ids.extend(ids)
        effective_ids = list(set(effective_ids))

        return DashboardScopeContext(
            scope_kind="unit",
            requested_officer_id=None,
            requested_unit_id=root_unit_id,
            effective_officer_ids=effective_ids,
            effective_unit_root_id=root_unit_id,
            effective_unit_ids=descendant_unit_ids,
            includes_descendants=True,
            forced_by_role=True,
            label="Đơn vị",
            requesting_user=current_user,
        )

    # =====================================================================
    # ADMIN: organization or personal (with officer_id)
    # =====================================================================
    if user_role == UserRole.ADMIN:
        if scope == "unit":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin không dùng scope 'unit'. Dùng 'organization' với scope_unit_id để xem một đơn vị."
            )

        # --- personal: must have officer_id ---
        if scope == "personal":
            if officer_id is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Admin cần chỉ định officer_id khi dùng scope 'personal'"
                )
            target_officer = await _validate_officer_target(db, officer_id, current_user)
            return DashboardScopeContext(
                scope_kind="personal",
                requested_officer_id=officer_id,
                requested_unit_id=None,
                effective_officer_ids=[officer_id],
                effective_unit_root_id=target_officer.unit_id,
                effective_unit_ids=[target_officer.unit_id] if target_officer.unit_id else [],
                includes_descendants=False,
                forced_by_role=False,
                label=f"Cá nhân: {target_officer.full_name}",
                requesting_user=current_user,
            )

        # --- organization ---
        org_repo = OrganizationRepository(db)
        officer_repo = OfficerRepository(db)

        # If drill-down to specific officer
        if officer_id is not None:
            target_officer = await _validate_officer_target(db, officer_id, current_user)

            # Still compute org-level units for context
            if unit_id is not None:
                eff_unit_ids = await org_repo.get_descendant_unit_ids(unit_id)
                root = unit_id
                includes_desc = True
            elif target_officer.unit_id:
                eff_unit_ids = [target_officer.unit_id]
                root = target_officer.unit_id
                includes_desc = False
            else:
                eff_unit_ids = []
                root = None
                includes_desc = False

            return DashboardScopeContext(
                scope_kind="organization",
                requested_officer_id=officer_id,
                requested_unit_id=unit_id,
                effective_officer_ids=[officer_id],
                effective_unit_root_id=root,
                effective_unit_ids=eff_unit_ids,
                includes_descendants=includes_desc,
                forced_by_role=False,
                label=f"Cá nhân: {target_officer.full_name}",
                requesting_user=current_user,
            )

        # Aggregated organization view
        if unit_id is not None:
            # Scoped to a unit subtree
            eff_unit_ids = await org_repo.get_descendant_unit_ids(unit_id)
            effective_ids: list[int] = []
            for uid in eff_unit_ids:
                ids = await officer_repo.get_active_officer_ids(scope="organization", unit_id=uid)
                effective_ids.extend(ids)
            effective_ids = list(set(effective_ids))
            return DashboardScopeContext(
                scope_kind="organization",
                requested_officer_id=None,
                requested_unit_id=unit_id,
                effective_officer_ids=effective_ids,
                effective_unit_root_id=unit_id,
                effective_unit_ids=eff_unit_ids,
                includes_descendants=True,
                forced_by_role=False,
                label="Tổ chức (đơn vị)",
                requesting_user=current_user,
            )

        # Full organization — all officers
        all_ids = await officer_repo.get_active_officer_ids(scope="organization", unit_id=None)
        return DashboardScopeContext(
            scope_kind="organization",
            requested_officer_id=None,
            requested_unit_id=None,
            effective_officer_ids=all_ids,
            effective_unit_root_id=None,
            effective_unit_ids=[],
            includes_descendants=False,
            forced_by_role=False,
            label="Tổ chức",
            requesting_user=current_user,
        )

    # =====================================================================
    # ALL OTHER ROLES: Deny by default (fail-closed)
    # =====================================================================
    raise PermissionDeniedError(
        detail="Your role is not allowed to access officer dashboard"
    )


async def resolve_drill_down_officer_id(
    officer_id: int | None = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> int:
    """
    IDOR gate for widget drill-down endpoints (leaderboard, upcoming-activities,
    recommendations, team-stats).

    Returns a validated officer_id that the current user is allowed to view.

    When officer_id is None (no drill-down), returns current_user.id as default
    context for highlight matching — no role validation needed.

    When officer_id IS provided (explicit drill-down):
    - Officer: self only. Any other → 404.
    - Manager/Admin: target must exist, have role=officer, and be in scope.
      Self-ID by a non-officer → 404 (manager/admin are not officers).
      Manager scope = own unit + descendant units.
    - Other roles: denied (fail-closed).

    Returns 404 (not 403) per AUTHORIZATION_GUIDELINES — never leak resource existence.
    """
    # No drill-down requested → return self as default (used for highlight matching)
    if officer_id is None:
        return current_user.id

    user_role = current_user.role

    # === OFFICER: Self only ===
    if user_role == UserRole.OFFICER:
        if officer_id == current_user.id:
            return current_user.id
        raise ResourceNotFoundError(detail="Officer not found")

    # === MANAGER / ADMIN: full validation (including self-ID) ===
    if user_role in (UserRole.MANAGER, UserRole.ADMIN):
        await _validate_officer_target(db, officer_id, current_user)
        return officer_id

    # === Fail-closed for unknown roles ===
    raise PermissionDeniedError(
        detail="Your role is not allowed to access officer data"
    )


async def resolve_kpi_plan_officer_id(
    officer_id: int | None = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> int:
    """
    IDOR gate for /my-kpi-plan endpoint.

    Differs from resolve_drill_down_officer_id because KPI plan retrieval
    requires an actual officer target — not a "highlight matching" context.

    - Officer: returns self (officer_id optional). Other officer → 404.
    - Manager/Admin: officer_id is REQUIRED. Must point to a valid officer
      in scope. Missing officer_id → 400 (BusinessRuleViolation).
    - Other roles: fail-closed.
    """
    user_role = current_user.role

    # === OFFICER: self only ===
    if user_role == UserRole.OFFICER:
        if officer_id is None or officer_id == current_user.id:
            return current_user.id
        raise ResourceNotFoundError(detail="Officer not found")

    # === MANAGER / ADMIN: officer_id required ===
    if user_role in (UserRole.MANAGER, UserRole.ADMIN):
        if officer_id is None:
            raise BusinessRuleViolation(
                detail="officer_id is required when viewing another officer's KPI plan"
            )
        await _validate_officer_target(db, officer_id, current_user)
        return officer_id

    # === Fail-closed ===
    raise PermissionDeniedError(
        detail="Your role is not allowed to access officer KPI plans"
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

    if current_user.role == UserRole.ADMIN:
        return lead

    if current_user.role == UserRole.MANAGER:
        if current_user.unit_id is not None:
            from ..repositories.organization_repository import OrganizationRepository
            org_repo = OrganizationRepository(db)
            allowed_unit_ids = await org_repo.get_descendant_unit_ids(current_user.unit_id)
            if lead.unit_id in allowed_unit_ids:
                return lead
        raise ResourceNotFoundError(detail="Lead not found")

    if current_user.role == UserRole.OFFICER and lead.assigned_officer_id == current_user.id:
        return lead

    raise ResourceNotFoundError(detail="Lead not found")


# ============================================================================
# OWNERSHIP VERIFICATION DEPENDENCIES (IDOR PREVENTION)
# ============================================================================


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


async def get_session_for_user(
    session_id: int = Path(..., description="ID of the Session"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_user),
) -> models.UserSession:
    """
    Verify ownership and retrieve a user session.

    **IDOR Prevention:**
    Returns 404 (not 403) when session doesn't belong to user,
    preventing attackers from enumerating valid session IDs.

    Args:
        session_id: ID of the session to access
        db: Database session (injected)
        current_user: Current authenticated user (injected)

    Returns:
        UserSession model if access is permitted

    Raises:
        ResourceNotFoundError: If session doesn't exist OR user doesn't own it
    """
    from ..repositories.session_repository import SessionRepository

    repo = SessionRepository(db)
    session = await repo.get_for_update(session_id, current_user.id)

    if not session:
        log.warning(
            "IDOR attempt or session not found",
            session_id=session_id,
            user_id=current_user.id,
        )
        raise ResourceNotFoundError(detail="Session not found")

    return session


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
                managed_units_count=len(managed_units),
                user_id=current_user.id,
                username=current_user.username
            )
            raise ResourceNotFoundError(
                detail="Distribution rule not found"
            )

    # Officer or other roles: deny access
    log.warning(
        "IDOR attempt detected: Non-admin/manager user trying to access distribution rule",
        rule_id=rule_id,
        user_id=current_user.id,
        user_role=current_user.role
    )
    raise ResourceNotFoundError(
        detail="Distribution rule not found"
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
                managed_units_count=len(managed_units),
                user_id=current_user.id,
                username=current_user.username
            )
            raise ResourceNotFoundError(
                detail="Organizational unit not found"
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
            raise ResourceNotFoundError(
                detail="Organizational unit not found"
            )

    # Officer without read permission or other roles: deny access
    log.warning(
        "IDOR attempt detected: Insufficient permissions to access organizational unit",
        unit_id=unit_id,
        user_id=current_user.id,
        user_role=current_user.role,
        allow_read_only=allow_read_only
    )
    raise ResourceNotFoundError(
        detail="Organizational unit not found"
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
                managed_units_count=len(managed_units),
                current_user_id=current_user.id,
                current_username=current_user.username
            )
            raise ResourceNotFoundError(
                detail="User not found"
            )

    # Officer or other roles: deny access
    log.warning(
        "IDOR attempt detected: Non-admin/manager trying to manage user",
        target_user_id=target_user_id,
        current_user_id=current_user.id,
        current_user_role=current_user.role
    )
    raise ResourceNotFoundError(
        detail="User not found"
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


# ============================================================================
# D4: DELIVERY OPS IDOR SCOPING
# ============================================================================


class DeliveryScopeFilter:
    """Pre-resolved scope for notification delivery queries."""
    __slots__ = ("scope_kind", "allowed_user_ids", "allowed_unit_ids", "officer_id")

    def __init__(
        self,
        scope_kind: str,
        allowed_user_ids: Optional[List[int]] = None,
        allowed_unit_ids: Optional[List[int]] = None,
        officer_id: Optional[int] = None,
    ):
        self.scope_kind = scope_kind
        self.allowed_user_ids = allowed_user_ids
        self.allowed_unit_ids = allowed_unit_ids
        self.officer_id = officer_id


async def get_delivery_scope_filter(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> DeliveryScopeFilter:
    """
    Resolve delivery scope: Admin=all, Manager=unit hierarchy, Officer=self.

    Performance note (H4): For managers, executes 2 queries per request
    (hierarchy CTE + user IDs). Acceptable for current scale (<100 units).
    If this becomes a bottleneck, consider caching allowed_user_ids in Redis
    with TTL keyed by (user_id, unit_id) and invalidating on unit changes.
    """
    if current_user.role == UserRole.ADMIN:
        return DeliveryScopeFilter(scope_kind="all")

    if current_user.role == UserRole.MANAGER and current_user.unit_id:
        from ..repositories.organization_repository import OrganizationRepository
        org_repo = OrganizationRepository(db)
        descendant_unit_ids = await org_repo.get_descendant_unit_ids(current_user.unit_id)
        from sqlalchemy import select
        user_q = select(models.User.id).where(models.User.unit_id.in_(descendant_unit_ids))
        result = await db.execute(user_q)
        allowed_ids = [row[0] for row in result.all()]
        return DeliveryScopeFilter(
            scope_kind="unit",
            allowed_user_ids=allowed_ids,
            allowed_unit_ids=descendant_unit_ids,
        )

    return DeliveryScopeFilter(
        scope_kind="self",
        allowed_user_ids=[current_user.id],
        officer_id=current_user.id,
    )


async def _check_external_source_in_units(
    db: AsyncSession, record, unit_ids: List[int]
) -> bool:
    """Check if an external delivery's source resource belongs to given units.

    Supports source_type='lead', 'admission_profile', and 'collaborator'.
    Unknown source types return False (deny by default).
    """
    if not unit_ids:
        return False
    from sqlalchemy import select
    if record.source_type == "lead":
        from app.models.lead import Lead
        q = select(Lead.unit_id).where(Lead.id == record.source_id)
        result = await db.execute(q)
        row = result.first()
        return row is not None and row[0] in unit_ids
    if record.source_type == "admission_profile":
        from app.models.admission import AdmissionProfile
        from app.models.lead import Lead
        q = (
            select(Lead.unit_id)
            .join(AdmissionProfile, AdmissionProfile.lead_id == Lead.id)
            .where(AdmissionProfile.id == record.source_id)
        )
        result = await db.execute(q)
        row = result.first()
        return row is not None and row[0] in unit_ids
    if record.source_type == "collaborator":
        from app.models.collaborator import Collaborator
        q = select(Collaborator.unit_id).where(Collaborator.id == record.source_id)
        result = await db.execute(q)
        row = result.first()
        return row is not None and row[0] in unit_ids
    return False


async def _check_external_source_assigned_to(
    db: AsyncSession, record, officer_id: int
) -> bool:
    """Check if an external delivery's source is assigned to the given officer.

    Supports:
    - source_type='lead': Lead.assigned_officer_id
    - source_type='admission_profile': AdmissionProfile → Lead.assigned_officer_id
    - source_type='collaborator': Collaborator.managed_by_officer_id
    """
    from sqlalchemy import select
    from app.models.lead import Lead
    if record.source_type == "lead":
        q = select(Lead.assigned_officer_id).where(Lead.id == record.source_id)
    elif record.source_type == "admission_profile":
        from app.models.admission import AdmissionProfile
        q = (
            select(Lead.assigned_officer_id)
            .join(AdmissionProfile, AdmissionProfile.lead_id == Lead.id)
            .where(AdmissionProfile.id == record.source_id)
        )
    elif record.source_type == "collaborator":
        from app.models.collaborator import Collaborator
        q = select(Collaborator.managed_by_officer_id).where(Collaborator.id == record.source_id)
    else:
        return False
    result = await db.execute(q)
    row = result.first()
    return row is not None and row[0] == officer_id


async def get_delivery_for_user(
    delivery_id: int = Path(..., description="Delivery record ID"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
):
    """Get single delivery with IDOR check. Returns 404 on scope violation."""
    from app.repositories.notification_delivery_repository import NotificationDeliveryRepository
    repo = NotificationDeliveryRepository(db)
    record = await repo.get_by_id(delivery_id)
    if not record:
        raise ResourceNotFoundError(detail="Delivery record not found")

    if current_user.role == UserRole.ADMIN:
        return record

    if current_user.role == UserRole.MANAGER and current_user.unit_id:
        from ..repositories.organization_repository import OrganizationRepository
        org_repo = OrganizationRepository(db)
        descendant_unit_ids = await org_repo.get_descendant_unit_ids(current_user.unit_id)
        from sqlalchemy import select
        if record.user_id:
            user_q = select(models.User.unit_id).where(models.User.id == record.user_id)
            result = await db.execute(user_q)
            row = result.first()
            if row and row[0] in descendant_unit_ids:
                return record
        elif record.recipient_kind == "external" and record.source_type and record.source_id:
            # External deliveries: check source ownership via unit hierarchy
            if await _check_external_source_in_units(db, record, descendant_unit_ids):
                return record
        raise ResourceNotFoundError(detail="Delivery record not found")

    # Officer scope
    if record.user_id == current_user.id:
        return record
    if record.user_id is None and record.recipient_kind == "external":
        if record.source_type in ("lead", "admission_profile", "collaborator") and record.source_id:
            if await _check_external_source_assigned_to(db, record, current_user.id):
                return record
    raise ResourceNotFoundError(detail="Delivery record not found")


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
        unit_ids: list[int] | None,
        nav_source: str | None,
        scope: str | None,
        scope_officer_id: int | None,
        scope_unit_id: int | None,
        include_descendants: bool,
        loss_reason: str | None,
        effective_scope: dict | None,
        requesting_user: models.User,
        is_forced_officer_filter: bool = False
    ):
        self.assigned_officer_id = assigned_officer_id
        self.unit_id = unit_id
        self.unit_ids = unit_ids
        self.nav_source = nav_source
        self.scope = scope
        self.scope_officer_id = scope_officer_id
        self.scope_unit_id = scope_unit_id
        self.include_descendants = include_descendants
        self.loss_reason = loss_reason
        self.effective_scope = effective_scope
        self.requesting_user = requesting_user
        self.is_forced_officer_filter = is_forced_officer_filter


async def get_lead_list_filter(
    assigned_officer_id: str | None = None,
    unit_id: int | None = None,
    nav_source: str | None = None,
    scope: str | None = None,
    scope_officer_id: int | None = None,
    scope_unit_id: int | None = None,
    include_descendants: bool | None = None,
    loss_reason: str | None = None,
    db: AsyncSession = Depends(database.get_db),
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
    normalized_scope = "unit" if scope == "team" else scope
    dashboard_ctx = None
    effective_scope = None
    unit_ids: list[int] | None = None
    includes_descendants = bool(include_descendants)

    should_resolve_dashboard_ctx = any(
        value is not None
        for value in (
            nav_source,
            normalized_scope,
            scope_officer_id,
            scope_unit_id,
            include_descendants,
        )
    )

    if should_resolve_dashboard_ctx:
        resolved_scope = normalized_scope
        if resolved_scope is None:
            if user_role == UserRole.OFFICER:
                resolved_scope = "personal"
            elif user_role == UserRole.MANAGER:
                resolved_scope = "unit"
            else:
                resolved_scope = "organization"

        dashboard_ctx = await get_officer_dashboard_scope(
            scope=resolved_scope,
            officer_id=scope_officer_id,
            unit_id=scope_unit_id,
            db=db,
            current_user=current_user,
        )
        includes_descendants = dashboard_ctx.includes_descendants
        if dashboard_ctx.effective_unit_ids:
            unit_ids = dashboard_ctx.effective_unit_ids
        # Personal scope: filter by assigned_officer_id only, not unit.
        # Matches dashboard active_leads counting (officer_repository L900).
        if dashboard_ctx.scope_kind == "personal":
            unit_ids = None
        effective_scope = {
            "scope_kind": dashboard_ctx.scope_kind,
            "label": dashboard_ctx.label,
            "forced_by_role": dashboard_ctx.forced_by_role,
            "includes_descendants": dashboard_ctx.includes_descendants,
        }
    
    # === OFFICER: Force their own ID, ignore any passed filter ===
    if user_role == UserRole.OFFICER:
        effective_officer_id = (
            str(dashboard_ctx.effective_officer_ids[0])
            if dashboard_ctx and dashboard_ctx.effective_officer_ids
            else str(current_user.id)
        )
        if effective_scope is None:
            effective_scope = {
                "scope_kind": "personal",
                "label": "Cá nhân (bắt buộc theo quyền)",
                "forced_by_role": True,
                "includes_descendants": False,
            }
        return LeadListFilter(
            assigned_officer_id=effective_officer_id,  # Force own ID
            unit_id=None,  # Officers cannot filter by unit
            unit_ids=unit_ids,
            nav_source=nav_source,
            scope=dashboard_ctx.scope_kind if dashboard_ctx else normalized_scope,
            scope_officer_id=dashboard_ctx.requested_officer_id if dashboard_ctx else scope_officer_id,
            scope_unit_id=dashboard_ctx.requested_unit_id if dashboard_ctx else scope_unit_id,
            include_descendants=includes_descendants,
            loss_reason=loss_reason,
            effective_scope=effective_scope,
            requesting_user=current_user,
            is_forced_officer_filter=True
        )
    
    # === MANAGER: Can filter by officers, force own unit ===
    if user_role == UserRole.MANAGER:
        effective_officer_id = assigned_officer_id
        effective_unit_id = current_user.unit_id

        if dashboard_ctx is not None:
            if len(dashboard_ctx.effective_officer_ids) == 1:
                effective_officer_id = str(dashboard_ctx.effective_officer_ids[0])
            if dashboard_ctx.effective_unit_ids:
                effective_unit_id = None
            elif dashboard_ctx.effective_unit_root_id is not None:
                effective_unit_id = dashboard_ctx.effective_unit_root_id
        elif effective_scope is None:
            effective_scope = {
                "scope_kind": "unit",
                "label": "Đơn vị",
                "forced_by_role": True,
                "includes_descendants": False,
            }

        return LeadListFilter(
            assigned_officer_id=effective_officer_id,
            unit_id=effective_unit_id,
            unit_ids=unit_ids,
            nav_source=nav_source,
            scope=dashboard_ctx.scope_kind if dashboard_ctx else normalized_scope,
            scope_officer_id=dashboard_ctx.requested_officer_id if dashboard_ctx else scope_officer_id,
            scope_unit_id=dashboard_ctx.requested_unit_id if dashboard_ctx else scope_unit_id,
            include_descendants=includes_descendants,
            loss_reason=loss_reason,
            effective_scope=effective_scope,
            requesting_user=current_user,
            is_forced_officer_filter=False
        )
    
    # === ADMIN: Full access ===
    effective_officer_id = assigned_officer_id
    effective_unit_id = unit_id

    if dashboard_ctx is not None:
        if len(dashboard_ctx.effective_officer_ids) == 1:
            effective_officer_id = str(dashboard_ctx.effective_officer_ids[0])
        if dashboard_ctx.effective_unit_ids:
            effective_unit_id = None
        elif dashboard_ctx.effective_unit_root_id is not None:
            effective_unit_id = dashboard_ctx.effective_unit_root_id

    return LeadListFilter(
        assigned_officer_id=effective_officer_id,
        unit_id=effective_unit_id,
        unit_ids=unit_ids,
        nav_source=nav_source,
        scope=dashboard_ctx.scope_kind if dashboard_ctx else normalized_scope,
        scope_officer_id=dashboard_ctx.requested_officer_id if dashboard_ctx else scope_officer_id,
        scope_unit_id=dashboard_ctx.requested_unit_id if dashboard_ctx else scope_unit_id,
        include_descendants=includes_descendants,
        loss_reason=loss_reason,
        effective_scope=effective_scope,
        requesting_user=current_user,
        is_forced_officer_filter=False
    )


async def get_kpi_target_for_admin(
    target_id: int = Path(..., description="ID of the KPI Target"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
) -> models.KpiTarget:
    """
    Fetch KPI Target with admin/manager authorization + IDOR scope check.

    A0: Manager can only access targets belonging to their own unit (or global).
    Always returns 404 (never 403) to prevent inference IDOR.

    Args:
        target_id: ID of the KPI Target to fetch

    Returns:
        KpiTarget if found, active, and within user's scope

    Raises:
        ResourceNotFoundError: If target not found, inactive, or outside scope
    """
    from ..models.config import KpiTarget

    target = await db.get(KpiTarget, target_id)
    if not target or not target.is_active:
        raise ResourceNotFoundError(detail="KPI Target not found")

    # IDOR: Manager scope check
    if current_user.role == "manager":
        # "True global" = unit_id IS NULL AND officer_id IS NULL → manager can see
        is_true_global = target.unit_id is None and target.officer_id is None
        # Unit-scoped → must match manager's unit
        is_own_unit = target.unit_id is not None and target.unit_id == current_user.unit_id
        # Officer-scoped with unit_id=NULL → check officer belongs to manager's unit
        if not is_true_global and not is_own_unit:
            if target.officer_id is not None and target.unit_id is None:
                # Resolve officer's unit via DB
                officer = await db.get(models.User, target.officer_id)
                if not officer or officer.unit_id != current_user.unit_id:
                    raise ResourceNotFoundError(detail="KPI Target not found")
            elif not is_own_unit:
                raise ResourceNotFoundError(detail="KPI Target not found")  # 404, not 403

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
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update()  # ✅ CRITICAL: Prevent concurrent approve/reject
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")

    # IDOR CHECK (after lock acquired) — 3-tier: Admin→all, Manager→unit, Officer→assigned+unit
    if current_user.role != UserRole.ADMIN:
        if not profile.lead or profile.lead.unit_id != current_user.unit_id:
            log.warning(
                "IDOR attempt: Manager tried to access profile from different unit",
                user_id=current_user.id,
                user_unit_id=current_user.unit_id,
                profile_id=profile_id,
                profile_unit_id=profile.lead.unit_id if profile.lead else None,
            )
            raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")
        # Officer: must also be the assigned officer
        if current_user.role == UserRole.OFFICER:
            if profile.lead.assigned_officer_id != current_user.id:
                log.warning(
                    "IDOR attempt: Officer tried to access profile not assigned to them",
                    user_id=current_user.id,
                    profile_id=profile_id,
                    assigned_officer_id=profile.lead.assigned_officer_id,
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
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")

    # IDOR CHECK — 3-tier: Admin→all, Manager→unit, Officer→assigned+unit
    if current_user.role != UserRole.ADMIN:
        if not profile.lead or profile.lead.unit_id != current_user.unit_id:
            log.warning(
                "IDOR attempt: User tried to access profile from different unit",
                user_id=current_user.id,
                user_unit_id=current_user.unit_id,
                profile_id=profile_id,
                profile_unit_id=profile.lead.unit_id if profile.lead else None,
            )
            raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")
        # Officer: must also be the assigned officer
        if current_user.role == UserRole.OFFICER:
            if profile.lead.assigned_officer_id != current_user.id:
                log.warning(
                    "IDOR attempt: Officer tried to access profile not assigned to them",
                    user_id=current_user.id,
                    profile_id=profile_id,
                    assigned_officer_id=profile.lead.assigned_officer_id,
                )
                raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")

    return profile


# Roles allowed to hit admission read endpoints. Anything outside this
# allow-list (accountant, regular user, collaborator, etc.) is rejected
# at the dependency layer regardless of unit_id, so callers can't sneak
# in via routes that aren't behind CasbinAuth. ADM-001 review fix.
_ADMISSION_READ_ALLOWED_ROLES = frozenset({
    UserRole.ADMIN,
    UserRole.MANAGER,
    UserRole.OFFICER,
})


async def get_admission_for_user_read(
    profile_id: int = Path(..., description="Admission Profile ID"),
    current_user: models.User = Depends(get_current_active_user),
    db: AsyncSession = Depends(database.get_db),
) -> models.AdmissionProfile:
    """
    IDOR Protection for read-only admission endpoints (fee-status, detail).

    Same 3-tier scope as ``get_admission_for_user`` but WITHOUT
    ``SELECT FOR UPDATE``. State-changing endpoints (approve/reject/resubmit)
    must keep using the locking variants.

    Role allow-list (ADM-001 review fix): only ADMIN, MANAGER, OFFICER may
    reach this dependency. Accountant / regular user / collaborator are
    rejected up front so a route that forgets to add CasbinAuth doesn't
    silently leak fee fields to staff outside the admission scope.

    - Admin: Can access all profiles
    - Officer: Can access profiles where lead.unit_id == user.unit_id
              AND lead.assigned_officer_id == user.id
    - Manager: Can access profiles where lead.unit_id == user.unit_id
    - Anyone else: rejected (404 fake)
    - Return 404 (not 403) for unauthorized access

    Used by:
    - GET /admissions/{id}/fee-status

    Raises:
        ResourceNotFoundError: Profile not found OR unauthorized (fake 404)
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    # Defense-in-depth role gate (in addition to any RBAC at the route).
    # Outside the admission allow-list → fake 404, never 403, to avoid
    # leaking that the profile ID is real.
    if current_user.role not in _ADMISSION_READ_ALLOWED_ROLES:
        log.warning(
            "IDOR attempt: non-admission role tried to read profile",
            user_id=current_user.id,
            user_role=str(current_user.role),
            profile_id=profile_id,
        )
        raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")

    stmt = (
        select(models.AdmissionProfile)
        .where(models.AdmissionProfile.id == profile_id)
        .options(
            selectinload(models.AdmissionProfile.lead)
            .selectinload(models.Lead.assigned_officer),
            selectinload(models.AdmissionProfile.assigned_reviewer),
        )
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if not profile:
        raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")

    if current_user.role != UserRole.ADMIN:
        if not profile.lead or profile.lead.unit_id != current_user.unit_id:
            log.warning(
                "IDOR attempt: User tried to read profile from different unit",
                user_id=current_user.id,
                user_unit_id=current_user.unit_id,
                profile_id=profile_id,
                profile_unit_id=profile.lead.unit_id if profile.lead else None,
            )
            raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")
        if current_user.role == UserRole.OFFICER:
            if profile.lead.assigned_officer_id != current_user.id:
                log.warning(
                    "IDOR attempt: Officer tried to read profile not assigned to them",
                    user_id=current_user.id,
                    profile_id=profile_id,
                    assigned_officer_id=profile.lead.assigned_officer_id,
                )
                raise ResourceNotFoundError(detail=f"Admission profile {profile_id} not found")

    return profile


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
    
    # 1. Get lead with relationships for phase derivation
    repo = LeadRepository(db)
    lead = await repo.get_by_id_full(lead_id)

    if not lead:
        raise ResourceNotFoundError(f"Lead {lead_id} not found")
    
    # 2. Get target status
    to_status = await db.get(models.ConsultationStatus, to_status_id)
    if not to_status:
        raise ResourceNotFoundError(f"Status {to_status_id} not found")
    
    # 3. Derive lead phase from current-year admission_profile.
    # Wave 4 #15b: replaces ``lead.admission_profile`` (singular relationship,
    # removed) with the per-year helper. ``current_intake_year`` from
    # ``system_config`` defaults to 2026 if the row is missing — matches
    # the storefront default seeded by phase1_13.
    from ..services.system_config_service import SystemConfigService
    current_year = await SystemConfigService(db).get_value(
        "current_intake_year", 2026
    )
    if isinstance(current_year, str):
        current_year = int(current_year)
    current_profile = lead.current_admission_profile(current_year)
    lead_phase = derive_phase_from_admission(current_profile).value
    
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


# =============================================================================
# KPI PLANNING IDOR DEPENDENCIES (Phase A6 — spec §2.6)
# =============================================================================

async def get_kpi_plan_for_user(
    plan_id: int = Path(..., description="KPI Plan ID"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
) -> "models.KpiPlan":
    """
    IDOR-safe: Admin sees all, Manager sees only own unit's plans.
    Returns 404 if not found OR not authorized (never 403).
    """
    from ..repositories.kpi_planning_repository import KpiPlanningRepository

    repo = KpiPlanningRepository(db)
    plan = await repo.get_plan_by_id(plan_id, with_months=True)

    if not plan or not plan.is_active:
        raise ResourceNotFoundError(detail="KPI Plan not found")

    if current_user.role == "admin":
        return plan

    if current_user.role == "manager" and plan.unit_id == current_user.unit_id:
        return plan

    raise ResourceNotFoundError(detail="KPI Plan not found")  # 404, not 403


async def get_kpi_plan_month_for_user(
    month_id: int = Path(..., description="KPI Plan Month ID"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin_or_manager),
) -> "models.KpiPlanMonth":
    """
    IDOR-safe for plan month. Joins plan to check unit scope.
    Returns 404 if not found OR not authorized (never 403).
    """
    from ..repositories.kpi_planning_repository import KpiPlanningRepository

    repo = KpiPlanningRepository(db)
    month = await repo.get_month_with_plan(month_id)

    if not month or not month.plan.is_active:
        raise ResourceNotFoundError(detail="KPI Plan Month not found")

    if current_user.role == "admin":
        return month

    if current_user.role == "manager" and month.plan.unit_id == current_user.unit_id:
        return month

    raise ResourceNotFoundError(detail="KPI Plan Month not found")  # 404, not 403


# =============================================================================
# COLLABORATOR SYSTEM DEPENDENCIES (Phase 1)
# =============================================================================


async def require_collaborator_role(
    current_user: models.User = Depends(get_current_active_user),
) -> models.User:
    """Requires user to have collaborator role."""
    if current_user.role != UserRole.COLLABORATOR:
        raise PermissionDeniedError("Collaborator access required")
    return current_user


async def get_own_collaborator(
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_collaborator_role),
) -> models.Collaborator:
    """Load Collaborator record linked to current user. Checks active status."""
    from ..repositories.collaborator_repository import CollaboratorRepository

    repo = CollaboratorRepository(db)
    collab = await repo.get_by_user_id(current_user.id)
    if not collab:
        raise ResourceNotFoundError("Collaborator profile not found")
    if collab.status not in ("active", "suspended"):
        raise BusinessRuleViolation("Collaborator account is not active")
    return collab


async def get_collaborator_for_user(
    collaborator_id: int = Path(...),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> models.Collaborator:
    """
    IDOR protection for collaborator access:
    - Admin: all collaborators
    - Manager: collaborators in their unit
    - Returns 404 for unauthorized (not 403)
    """
    from ..repositories.collaborator_repository import CollaboratorRepository

    repo = CollaboratorRepository(db)
    collab = await repo.get_by_id(collaborator_id)
    if not collab:
        raise ResourceNotFoundError("Collaborator not found")
    if current_user.role == UserRole.ADMIN:
        return collab
    if current_user.role == UserRole.MANAGER:
        if collab.unit_id == current_user.unit_id:
            return collab
    if current_user.role == UserRole.OFFICER:
        if collab.managed_by_officer_id == current_user.id:
            return collab
    raise ResourceNotFoundError("Collaborator not found")


async def get_lead_claim_for_review(
    claim_id: int = Path(...),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> models.LeadClaim:
    """Admin/Manager can review claims. IDOR via unit scope."""
    from ..repositories.lead_claim_repository import LeadClaimRepository

    repo = LeadClaimRepository(db)
    claim = await repo.get_by_id(claim_id)
    if not claim:
        raise ResourceNotFoundError("Claim not found")
    if current_user.role == UserRole.ADMIN:
        return claim
    if current_user.role == UserRole.MANAGER:
        if claim.collaborator and claim.collaborator.unit_id == current_user.unit_id:
            return claim
    raise ResourceNotFoundError("Claim not found")


# =============================================================================
# COMMISSION SYSTEM DEPENDENCIES (Phase 2)
# =============================================================================


async def get_commission_policy_for_admin(
    policy_id: int = Path(...),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> "models.CommissionPolicy":
    """Admin-only access to commission policies."""
    if current_user.role != UserRole.ADMIN:
        raise ResourceNotFoundError("Policy not found")

    from ..repositories.commission_repository import CommissionPolicyRepository
    repo = CommissionPolicyRepository(db)
    policy = await repo.get_by_id(policy_id)
    if not policy:
        raise ResourceNotFoundError("Policy not found")
    return policy


async def get_commission_record_for_user(
    record_id: int = Path(...),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(get_current_active_user),
) -> "models.CommissionRecord":
    """
    IDOR protection for commission records:
    - Admin: all records
    - Manager: records in their unit
    """
    from ..repositories.commission_repository import CommissionRecordRepository
    repo = CommissionRecordRepository(db)
    record = await repo.get_by_id(record_id)
    if not record:
        raise ResourceNotFoundError("Commission record not found")
    if current_user.role == UserRole.ADMIN:
        return record
    if current_user.role == UserRole.MANAGER:
        if record.collaborator and record.collaborator.unit_id == current_user.unit_id:
            return record
    raise ResourceNotFoundError("Commission record not found")
