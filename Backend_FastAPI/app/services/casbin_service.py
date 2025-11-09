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

import casbin
from sqlalchemy import select
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
        policies: List[Tuple[str, str, str]],
        validate: bool = True
    ) -> dict:
        """
        Add multiple policies in a batch with validation.

        Args:
            policies: List of (subject, object, action) tuples
            validate: Whether to validate before adding

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

        for subject, obj, action in policies:
            # Validate if requested
            if validate:
                validation = await self.validate_policy_addition(subject, obj, action)
                if not validation.is_valid:
                    skipped += 1
                    warnings.extend(validation.warnings)
                    continue

                warnings.extend(validation.warnings)

            # Add policy
            try:
                success = await self.enforcer.add_policy(subject, obj, action)
                if success:
                    added += 1
                else:
                    skipped += 1
                    warnings.append(f"Policy already exists: {subject} {obj} {action}")
            except Exception as e:
                errors.append(f"Failed to add policy {subject} {obj} {action}: {str(e)}")

        return {
            "added": added,
            "skipped": skipped,
            "errors": errors,
            "warnings": warnings,
        }

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
        validate: bool = True
    ) -> dict:
        """
        Apply a policy template to a role.

        Args:
            template_id: Template identifier (e.g., "officer")
            role: Role name (e.g., "role:custom")
            validate: Whether to validate before applying

        Returns:
            Dictionary with application results
        """
        try:
            # Get policies from template
            template_policies = apply_template(template_id, role)

            # Convert to tuples for batch operation
            policies_tuples = [
                (p["subject"], p["object"], p["action"])
                for p in template_policies
            ]

            # Apply batch
            result = await self.add_policies_batch(policies_tuples, validate=validate)

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
