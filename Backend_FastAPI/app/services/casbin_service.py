# app/services/casbin_service.py
"""
Casbin Policy Management Service

This service provides high-level operations for managing Casbin policies with:
- Safety validation (prevent locking out admins)
- Batch operations
- Policy analysis
- Role management
"""

from typing import List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timezone

import casbin
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..casbin_config.policy_templates import (
    POLICY_TEMPLATES,
    SYSTEM_ROLES,
    CRITICAL_POLICIES,
    is_critical_policy,
    is_system_role,
    apply_template,
)
from .. import models


class ValidationSeverity(str, Enum):
    """Severity levels for policy validation warnings."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class PolicyValidationResult:
    """Result of policy validation check."""
    is_valid: bool
    is_safe: bool
    severity: ValidationSeverity
    warnings: List[str]
    affected_users: List[int]


@dataclass
class PolicyRule:
    """Represents a single Casbin policy rule."""
    subject: str
    object: str
    action: str


class CasbinPolicyService:
    """Service for managing Casbin policies with safety checks."""

    def __init__(self, db: AsyncSession, enforcer: casbin.AsyncEnforcer):
        """
        Initialize Casbin service.

        Args:
            db: Database session
            enforcer: Casbin enforcer instance
        """
        self.db = db
        self.enforcer = enforcer

    # =========================================================================
    # ROLE MANAGEMENT
    # =========================================================================

    async def get_all_roles(self) -> List[dict]:
        """
        Get all roles with their metadata.

        Returns:
            List of role dictionaries with:
            - name: Role identifier (e.g., "role:admin")
            - display_name: Human-readable name
            - description: Role description
            - is_system_role: Whether this is a core system role
            - policy_count: Number of policies for this role
        """
        roles_info = []

        # Get all unique subjects from policies
        all_policies = self.enforcer.get_policy()
        role_subjects = set(policy[0] for policy in all_policies if policy[0].startswith("role:"))

        # Add system roles info
        for system_role in SYSTEM_ROLES:
            policy_count = sum(1 for p in all_policies if p[0] == system_role["name"])
            roles_info.append({
                **system_role,
                "policy_count": policy_count,
            })

        # Add custom roles (roles not in SYSTEM_ROLES)
        system_role_names = {r["name"] for r in SYSTEM_ROLES}
        custom_roles = role_subjects - system_role_names

        for role_name in custom_roles:
            policy_count = sum(1 for p in all_policies if p[0] == role_name)
            roles_info.append({
                "name": role_name,
                "display_name": role_name.replace("role:", "").title(),
                "description": f"Custom role: {role_name}",
                "is_system_role": False,
                "template_id": None,
                "policy_count": policy_count,
            })

        return roles_info

    async def get_role_policies(self, role: str) -> List[PolicyRule]:
        """
        Get all policies for a specific role.

        Args:
            role: Role name (e.g., "role:manager")

        Returns:
            List of PolicyRule objects
        """
        all_policies = self.enforcer.get_policy()
        role_policies = [
            PolicyRule(subject=p[0], object=p[1], action=p[2])
            for p in all_policies
            if p[0] == role
        ]
        return role_policies

    # =========================================================================
    # USER ROLE ASSIGNMENT (g-rules)
    # =========================================================================

    async def assign_role_to_user(self, user_id: int, role: str) -> bool:
        """
        Assign a role to a user (create g-rule mapping user:ID -> role:NAME).

        Args:
            user_id: User ID
            role: Role name (e.g., "officer", "manager") - WITHOUT "role:" prefix

        Returns:
            True if assignment was created, False if already exists
        """
        user_subject = f"user:{user_id}"
        role_subject = f"role:{role}"
        return await self.enforcer.add_grouping_policy(user_subject, role_subject)

    async def remove_user_roles(self, user_id: int) -> int:
        """
        Remove ALL role assignments for a user.

        Args:
            user_id: User ID

        Returns:
            Number of role assignments removed
        """
        user_subject = f"user:{user_id}"
        removed_count = 0

        # Get all grouping policies (g-rules)
        # We filter manually because get_roles_for_user() might return inherited roles
        all_grouping = self.enforcer.get_grouping_policy()
        user_rules = [p for p in all_grouping if p[0] == user_subject]

        for rule in user_rules:
            # rule is (user_subject, role_subject)
            role_subject = rule[1]
            success = await self.enforcer.remove_grouping_policy(user_subject, role_subject)
            if success:
                removed_count += 1

        return removed_count

    # =========================================================================
    # POLICY VALIDATION
    # =========================================================================

    async def validate_policy_addition(
        self,
        subject: str,
        obj: str,
        action: str
    ) -> PolicyValidationResult:
        """
        Validate adding a new policy.

        Args:
            subject: Policy subject (e.g., "role:custom")
            obj: Resource path (e.g., "/api/leads/*")
            action: HTTP method or regex (e.g., "GET", ".*")

        Returns:
            PolicyValidationResult with warnings
        """
        warnings = []
        severity = ValidationSeverity.INFO

        # Check if policy already exists
        existing_policies = self.enforcer.get_policy()
        if [subject, obj, action] in existing_policies:
            return PolicyValidationResult(
                is_valid=False,
                is_safe=True,
                severity=ValidationSeverity.WARNING,
                warnings=["Policy already exists"],
                affected_users=[],
            )

        # Warn about overly permissive policies
        if obj == "/*" and action == ".*":
            warnings.append(
                "This grants full access to all resources. "
                "Only use for administrator roles."
            )
            severity = ValidationSeverity.WARNING

        # Warn about wildcard access to sensitive paths
        if "/api/admin" in obj and action == ".*":
            warnings.append(
                "This grants full access to admin endpoints. "
                "Ensure this is intentional."
            )
            severity = ValidationSeverity.WARNING

        return PolicyValidationResult(
            is_valid=True,
            is_safe=True,
            severity=severity,
            warnings=warnings,
            affected_users=[],
        )

    async def validate_policy_removal(
        self,
        subject: str,
        obj: str,
        action: str
    ) -> PolicyValidationResult:
        """
        Validate removing a policy with STRICT safety checks.

        Args:
            subject: Policy subject
            obj: Resource path
            action: HTTP method or regex

        Returns:
            PolicyValidationResult with safety status
        """
        warnings = []
        severity = ValidationSeverity.INFO

        # CRITICAL: Check if this is a protected policy
        if is_critical_policy(subject, obj, action):
            return PolicyValidationResult(
                is_valid=False,
                is_safe=False,
                severity=ValidationSeverity.CRITICAL,
                warnings=[
                    "⛔ CRITICAL: This is a system-critical policy and cannot be removed. "
                    "Removing this policy will lock all administrators out of the system!"
                ],
                affected_users=[],
            )

        # Check if this is the last admin wildcard policy
        if subject == "role:admin":
            admin_policies = [
                p for p in self.enforcer.get_policy()
                if p[0] == "role:admin"
            ]
            if len(admin_policies) == 1:
                warnings.append(
                    "⚠️ WARNING: This is the last policy for role:admin. "
                    "Removing it may lock administrators out."
                )
                severity = ValidationSeverity.CRITICAL

        # Get affected users (users who have this role)
        affected_users = await self._get_affected_users_by_role(subject)

        if len(affected_users) > 10:
            warnings.append(
                f"This change will affect {len(affected_users)} users with role {subject}"
            )
            severity = ValidationSeverity.WARNING

        return PolicyValidationResult(
            is_valid=True,
            is_safe=(severity != ValidationSeverity.CRITICAL),
            severity=severity,
            warnings=warnings,
            affected_users=affected_users,
        )

    async def _get_affected_users_by_role(self, role_subject: str) -> List[int]:
        """
        Get list of user IDs who have a specific role.

        Args:
            role_subject: Role identifier (e.g., "role:manager")

        Returns:
            List of user IDs
        """
        # Get grouping policies (user-role assignments)
        grouping_policies = self.enforcer.get_grouping_policy()

        # Extract role name from subject (e.g., "role:manager" -> "manager")
        if not role_subject.startswith("role:"):
            return []

        role_name = role_subject.replace("role:", "")

        # Find all users with this role from DB
        result = await self.db.execute(
            select(models.User.id).where(models.User.role == role_name)
        )
        user_ids = [row[0] for row in result.all()]

        return user_ids

    # =========================================================================
    # BATCH OPERATIONS
    # =========================================================================

    async def add_policies_batch(
        self,
        policies: List[Tuple[str, ...]],
        validate: bool = True,
        template_id: Optional[str] = None,
        applied_by: Optional[int] = None
    ) -> dict:
        """
        Add multiple policies in a batch with validation and template tracking.

        Args:
            policies: List of policy tuples. Each entry is either
                ``(subject, object, action)`` (3-tuple — eft defaults to
                ``"allow"`` for backward compatibility with admin UI
                payloads) or ``(subject, object, action, eft)`` (4-tuple,
                produced by ``apply_template`` post-B1 deny-first).
            validate: Whether to validate before adding.
            template_id: Template ID for tracking (optional).
            applied_by: User ID who applied this (optional).

        Returns:
            Dictionary with:
            - added: Number of policies successfully added
            - skipped: Number of policies skipped (duplicates)
            - errors: List of error messages
            - warnings: List of warnings
        """
        added = 0
        skipped = 0
        errors = []
        warnings = []
        # Track which policies were added for template tracking — keep
        # the 4-field shape so the SQL UPDATE matches v3 explicitly and
        # never touches a peer (sub, obj, act) row of opposite eft.
        added_policies: List[Tuple[str, str, str, str]] = []

        for entry in policies:
            if len(entry) == 3:
                subject, obj, action = entry
                eft = "allow"
            elif len(entry) == 4:
                subject, obj, action, eft = entry
            else:
                errors.append(
                    f"Invalid policy tuple length {len(entry)} (expected 3 or 4): {entry!r}"
                )
                continue

            # Validate if requested. Validation is eft-agnostic — the
            # checks (duplicate, conflict, critical) key on (subject,
            # object, action). A deny variant of an existing allow rule
            # is intentionally NOT a duplicate.
            if validate:
                validation = await self.validate_policy_addition(subject, obj, action)
                if not validation.is_valid:
                    skipped += 1
                    warnings.extend(validation.warnings)
                    continue

                warnings.extend(validation.warnings)

            # Add policy. casbin.AsyncEnforcer.add_policy accepts the
            # eft as the 4th positional argument; the canonical
            # auth_model.conf since B1 declares
            #   p = sub, obj, act, eft.
            try:
                success = await self.enforcer.add_policy(
                    subject, obj, action, eft
                )
                if success:
                    added += 1
                    added_policies.append((subject, obj, action, eft))
                else:
                    skipped += 1
                    warnings.append(
                        f"Policy already exists: {subject} {obj} {action} {eft}"
                    )
            except Exception as e:
                errors.append(
                    f"Failed to add policy {subject} {obj} {action} {eft}: {str(e)}"
                )

        # Update template tracking for added policies
        if added_policies and template_id:
            await self._update_template_tracking(added_policies, template_id, applied_by)

        return {
            "added": added,
            "skipped": skipped,
            "errors": errors,
            "warnings": warnings,
        }

    async def _update_template_tracking(
        self,
        policies: List[Tuple[str, str, str, str]],
        template_id: str,
        applied_by: Optional[int] = None
    ) -> None:
        """
        Update template tracking columns for policies.

        This is called after policies are added via enforcer to set:
        - template_id: Which template this policy came from
        - applied_at: When this policy was applied
        - applied_by: User ID who applied this policy

        IMPORTANT: We use AsyncSessionLocal instead of self.db because:
        - Casbin enforcer.add_policy() uses its own adapter with its own session
        - The DI session (self.db) is in a different transaction and can't see
          the row that enforcer committed
        - We need a fresh session that starts AFTER enforcer's commit

        Args:
            policies: List of ``(subject, object, action, eft)`` tuples
                (B1 4-field shape — eft is included in the WHERE clause
                so allow/deny variants of the same (sub, obj, act) get
                their own tracking row, never collide).
            template_id: Template identifier
            applied_by: User ID (optional)
        """
        from app.database import AsyncSessionLocal
        import logging
        log = logging.getLogger(__name__)

        try:
            # Use a fresh session to see the rows committed by enforcer
            async with AsyncSessionLocal() as fresh_session:
                for subject, obj, action, eft in policies:
                    result = await fresh_session.execute(
                        text("""
                            UPDATE casbin_rule
                            SET template_id = :template_id,
                                applied_at = :applied_at,
                                applied_by = :applied_by
                            WHERE ptype = 'p'
                              AND v0 = :subject
                              AND v1 = :obj
                              AND v2 = :action
                              AND v3 = :eft
                              AND template_id IS NULL
                        """),
                        {
                            "template_id": template_id,
                            # Naive UTC: asyncpg's TIMESTAMP WITHOUT TIME ZONE
                            # column rejects tz-aware values, so strip the
                            # tz after using the non-deprecated constructor.
                            "applied_at": datetime.now(timezone.utc).replace(tzinfo=None),
                            "applied_by": applied_by,
                            "subject": subject,
                            "obj": obj,
                            "action": action,
                            "eft": eft,
                        }
                    )
                    log.info(f"Tracking UPDATE for {subject} {obj} {action} {eft}: rowcount={result.rowcount}")
                
                # Commit the tracking update
                await fresh_session.commit()
                log.info(f"✅ Tracking columns committed for {len(policies)} policies")
        except Exception as e:
            # Non-critical: don't fail if tracking update fails
            # This can happen if tracking columns don't exist (e.g., migration not applied)
            # Just log and continue - the policy was already added by enforcer
            log.warning(f"⚠️ Failed to update tracking columns: {e}")

    async def remove_policies_batch(
        self,
        policies: List[Tuple[str, str, str]],
        validate: bool = True,
        force: bool = False
    ) -> dict:
        """
        Remove multiple policies in a batch with safety checks.

        Args:
            policies: List of (subject, object, action) tuples
            validate: Whether to validate before removing
            force: Skip safety checks (DANGEROUS - admin override only)

        Returns:
            Dictionary with removal results
        """
        removed = 0
        blocked = 0
        errors = []
        warnings = []

        for subject, obj, action in policies:
            # Validate if requested
            if validate and not force:
                validation = await self.validate_policy_removal(subject, obj, action)
                if not validation.is_safe:
                    blocked += 1
                    errors.append(f"Blocked for safety: {subject} {obj} {action}")
                    warnings.extend(validation.warnings)
                    continue

                warnings.extend(validation.warnings)

            # Remove policy
            try:
                success = await self.enforcer.remove_policy(subject, obj, action)
                if success:
                    removed += 1
                else:
                    warnings.append(f"Policy not found: {subject} {obj} {action}")
            except Exception as e:
                errors.append(f"Failed to remove policy {subject} {obj} {action}: {str(e)}")

        return {
            "removed": removed,
            "blocked": blocked,
            "errors": errors,
            "warnings": warnings,
        }

    # =========================================================================
    # TEMPLATE OPERATIONS
    # =========================================================================

    async def apply_template_to_role(
        self,
        template_id: str,
        role: str,
        validate: bool = True,
        applied_by: Optional[int] = None
    ) -> dict:
        """
        Apply a policy template to a role.

        Args:
            template_id: Template identifier (e.g., "officer")
            role: Role name (e.g., "role:custom")
            validate: Whether to validate before applying
            applied_by: User ID who applied this template (for audit trail)

        Returns:
            Dictionary with application results
        """
        try:
            # Get policies from template
            template_policies = apply_template(template_id, role)

            # Convert to 4-tuples (subject, object, action, eft) for the
            # batch operation. ``apply_template`` since B1 always
            # populates ``eft`` (default "allow", explicit "deny" for
            # accountant admission state-machine guards).
            policies_tuples = [
                (p["subject"], p["object"], p["action"], p["eft"])
                for p in template_policies
            ]

            # Apply batch with template tracking
            result = await self.add_policies_batch(
                policies_tuples,
                validate=validate,
                template_id=template_id,
                applied_by=applied_by
            )

            return {
                **result,
                "template_id": template_id,
                "role": role,
                "template_policy_count": len(template_policies),
            }

        except KeyError:
            return {
                "added": 0,
                "skipped": 0,
                "errors": [f"Template not found: {template_id}"],
                "warnings": [],
            }

    # =========================================================================
    # UTILITY METHODS
    # =========================================================================

    async def get_policy_count(self) -> dict:
        """
        Get count statistics for policies.

        Returns:
            Dictionary with:
            - total_policies: Total number of policies
            - total_roles: Number of unique roles
            - total_grouping_policies: Number of user-role assignments
        """
        all_policies = self.enforcer.get_policy()
        grouping_policies = self.enforcer.get_grouping_policy()

        unique_roles = set(p[0] for p in all_policies if p[0].startswith("role:"))

        return {
            "total_policies": len(all_policies),
            "total_roles": len(unique_roles),
            "total_grouping_policies": len(grouping_policies),
        }

    # =========================================================================
    # ADVANCED PERMISSION TOOLS
    # =========================================================================

    async def get_subjects_for_permission(self, obj: str, act: str) -> List[str]:
        """
        ✅ PATCHED FOR DoS (v15):
        Reverse permission lookup - Find all roles that can access a resource.

        SECURITY FIX:
        - Only loops through ROLES (not individual users)
        - Casbin's enforce() automatically handles role inheritance
        - Prevents DoS attack where 50k+ users could crash server

        Args:
            obj: Resource path (e.g., "/api/leads", "/api/admin/users")
            act: HTTP method (e.g., "GET", "POST", ".*")

        Returns:
            List of roles (e.g., ["role:admin", "role:manager"])

        Example:
            >>> await get_subjects_for_permission("/api/leads", "GET")
            ["role:admin", "role:manager", "role:officer"]

        PERFORMANCE:
            - OLD: O(n) where n = all users + roles (50,000+ iterations) ⚠️
            - NEW: O(r) where r = number of roles (~10 iterations) ✅
            - Speedup: ~5000x for systems with 50k users
        """
        allowed_subjects = []

        # CHỈ LẤY CÁC VAI TRÒ (VÀI CHỤC ROLES)
        # This returns only roles, not individual users - preventing DoS
        # Note: get_all_roles() is synchronous in pycasbin
        all_roles = self.enforcer.get_all_roles()

        # CHỈ LẶP QUA CÁC VAI TRÒ
        # Casbin's enforce() automatically handles role inheritance
        for role in all_roles:
            is_allowed = self.enforcer.enforce(role, obj, act)
            if is_allowed:
                allowed_subjects.append(role)

        return sorted(list(set(allowed_subjects)))

    # =========================================================================
    # TEMPLATE DRIFT DETECTION & SYNC (Phase 4 Fix)
    # Reference: AUTHORIZATION_DECISIONS.md Decision 14
    # =========================================================================

    async def detect_template_drift(self, role: str, template_id: str) -> dict:
        """
        Detect drift between template definition and actual DB policies.

        This is critical for audit and production maintenance.
        Drift can occur when:
        - Policies are added via UI without template
        - Policies are deleted manually
        - Template is updated but DB not synced

        Args:
            role: Role name (e.g., "role:officer")
            template_id: Template identifier (e.g., "officer")

        Returns:
            Dictionary with:
            - has_drift: True if template != DB
            - missing_in_db: Policies in template but not in DB
            - extra_in_db: Policies in DB but not in template
            - drift_percentage: How much drift (0-100%)
            - template_count: Number of policies in template
            - db_count: Number of policies in DB for this role
        """
        try:
            # Get template policies
            template_policies = apply_template(template_id, role)
            template_set = set(
                (p["subject"], p["object"], p["action"])
                for p in template_policies
            )

            # Get DB policies for this role
            all_policies = self.enforcer.get_policy()
            db_policies_for_role = [
                (p[0], p[1], p[2])
                for p in all_policies
                if p[0] == role
            ]
            db_set = set(db_policies_for_role)

            # Calculate drift
            missing_in_db = template_set - db_set
            extra_in_db = db_set - template_set

            total_unique = len(template_set | db_set)
            drift_count = len(missing_in_db) + len(extra_in_db)
            drift_percentage = (drift_count / total_unique * 100) if total_unique > 0 else 0

            return {
                "has_drift": bool(missing_in_db or extra_in_db),
                "missing_in_db": [
                    {"subject": s, "object": o, "action": a}
                    for s, o, a in missing_in_db
                ],
                "extra_in_db": [
                    {"subject": s, "object": o, "action": a}
                    for s, o, a in extra_in_db
                ],
                "drift_percentage": round(drift_percentage, 2),
                "template_count": len(template_set),
                "db_count": len(db_set),
                "role": role,
                "template_id": template_id,
            }

        except KeyError:
            # Handle special template IDs gracefully
            if template_id == "_legacy":
                # Legacy policies have no template to compare - not an error
                return {
                    "has_drift": False,
                    "info": "Legacy policies - no template to compare. Consider migrating to a proper template.",
                    "missing_in_db": [],
                    "extra_in_db": [],
                    "drift_percentage": 0,
                    "template_count": 0,
                    "db_count": 0,
                    "role": role,
                    "template_id": template_id,
                }
            elif template_id == "_manual":
                # Manual policies are intentionally outside templates
                return {
                    "has_drift": False,
                    "info": "Manual policies - added via UI, not linked to any template.",
                    "missing_in_db": [],
                    "extra_in_db": [],
                    "drift_percentage": 0,
                    "template_count": 0,
                    "db_count": 0,
                    "role": role,
                    "template_id": template_id,
                }
            # Unknown template - actual error
            return {
                "has_drift": True,
                "error": f"Template not found: {template_id}",
                "missing_in_db": [],
                "extra_in_db": [],
                "drift_percentage": 100.0,
                "template_count": 0,
                "db_count": 0,
                "role": role,
                "template_id": template_id,
            }

    async def detect_all_drift(self) -> dict:
        """
        Detect drift for all system roles.

        Returns:
            Dictionary with drift status for each role and overall health.
        """
        results = {}
        total_drift = 0
        roles_with_drift = 0

        for system_role in SYSTEM_ROLES:
            role_name = system_role["name"]
            template_id = system_role.get("template_id")

            if template_id:
                drift = await self.detect_template_drift(role_name, template_id)
                results[role_name] = drift

                if drift["has_drift"]:
                    roles_with_drift += 1
                    total_drift += drift["drift_percentage"]

        return {
            "roles": results,
            "summary": {
                "total_roles_checked": len(results),
                "roles_with_drift": roles_with_drift,
                "average_drift_percentage": round(total_drift / len(results), 2) if results else 0,
                "health_status": "HEALTHY" if roles_with_drift == 0 else "DRIFT_DETECTED",
            }
        }

    async def refresh_role_from_template(
        self,
        role: str,
        template_id: str,
        force: bool = False,
        applied_by: Optional[int] = None
    ) -> dict:
        """
        Force reset role to match template exactly.

        WARNING: This will:
        - Remove ALL current policies for the role
        - Apply fresh policies from template
        - Any manual additions will be LOST

        Args:
            role: Role name (e.g., "role:officer")
            template_id: Template identifier (e.g., "officer")
            force: Must be True to execute (safety check)
            applied_by: User ID who triggered this refresh (for audit trail)

        Returns:
            Dictionary with operation results
        """
        if not force:
            return {
                "success": False,
                "error": "Safety check: Set force=True to confirm destructive operation",
                "hint": "This will remove ALL current policies for the role and apply template fresh",
            }

        # Prevent refresh of admin role without extra safety
        if role == "role:admin" and not is_system_role(role):
            return {
                "success": False,
                "error": "Cannot refresh admin role - too dangerous",
            }

        try:
            # Get current policies before delete (for audit log)
            all_policies = self.enforcer.get_policy()
            current_policies = [p for p in all_policies if p[0] == role]
            current_count = len(current_policies)

            # Remove all policies for this role
            removed = 0
            for policy in current_policies:
                subject, obj, action = policy[0], policy[1], policy[2]

                # Skip critical policies
                if is_critical_policy(subject, obj, action):
                    continue

                success = await self.enforcer.remove_policy(subject, obj, action)
                if success:
                    removed += 1

            # Apply template fresh (with template tracking)
            result = await self.apply_template_to_role(
                template_id, role, validate=False, applied_by=applied_by
            )

            return {
                "success": True,
                "role": role,
                "template_id": template_id,
                "policies_removed": removed,
                "policies_before": current_count,
                "policies_added": result.get("added", 0),
                "policies_after": result.get("added", 0),
                "warnings": result.get("warnings", []),
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "role": role,
                "template_id": template_id,
            }

    async def sync_all_roles_from_templates(self, dry_run: bool = True) -> dict:
        """
        Sync all system roles to match their templates.

        Args:
            dry_run: If True, only report what would change (default: True)

        Returns:
            Dictionary with sync results for each role
        """
        results = {}

        for system_role in SYSTEM_ROLES:
            role_name = system_role["name"]
            template_id = system_role.get("template_id")

            if not template_id:
                results[role_name] = {"skipped": True, "reason": "No template defined"}
                continue

            # Skip admin to prevent lockout
            if role_name == "role:admin":
                results[role_name] = {"skipped": True, "reason": "Admin role not synced for safety"}
                continue

            # Detect drift first
            drift = await self.detect_template_drift(role_name, template_id)

            if not drift["has_drift"]:
                results[role_name] = {"skipped": True, "reason": "No drift detected"}
                continue

            if dry_run:
                results[role_name] = {
                    "dry_run": True,
                    "would_remove": len(drift["extra_in_db"]),
                    "would_add": len(drift["missing_in_db"]),
                    "drift": drift,
                }
            else:
                sync_result = await self.refresh_role_from_template(
                    role_name, template_id, force=True
                )
                results[role_name] = sync_result

        return {
            "dry_run": dry_run,
            "results": results,
            "hint": "Set dry_run=False to apply changes" if dry_run else "Changes applied",
        }
