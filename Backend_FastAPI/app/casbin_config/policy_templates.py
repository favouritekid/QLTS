# app/config/policy_templates.py
"""
Policy Templates Configuration

This module defines reusable policy templates for common permission patterns.
Templates can be applied to roles to quickly set up standard permission sets.

Each template contains:
- display_name: Human-readable name
- description: What permissions this template grants
- category: Group similar templates together
- policies: List of policy rules (subject placeholder will be replaced)
"""

from typing import Dict, List, TypedDict


class PolicyRule(TypedDict):
    """Type definition for a single policy rule."""
    subject: str  # Placeholder: {role} will be replaced
    object: str   # Resource path (e.g., /api/leads/*)
    action: str   # HTTP method or regex (e.g., GET, POST, .*)


class PolicyTemplate(TypedDict):
    """Type definition for a policy template."""
    display_name: str
    description: str
    category: str
    policies: List[PolicyRule]


# =============================================================================
# CORE ROLE TEMPLATES (Based on system defaults)
# =============================================================================

OFFICER_TEMPLATE: PolicyTemplate = {
    "display_name": "Officer (Lead Access)",
    "description": "Standard permissions for sales officers: view and manage assigned leads",
    "category": "core",
    "policies": [
        # Lead access
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{lead_id}", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{lead_id}/consultations", "action": "POST"},
        {"subject": "{role}", "object": "/api/leads/{lead_id}/action", "action": "POST"},
        # Pipeline access (for consultation statuses in QuickDisposition)
        {"subject": "{role}", "object": "/api/pipeline/stages", "action": "GET"},
        {"subject": "{role}", "object": "/api/pipeline/all", "action": "GET"},
        {"subject": "{role}", "object": "/api/pipeline/allowed-next-statuses", "action": "GET"},
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{notification_id}", "action": "DELETE"},
    ]
}

MANAGER_TEMPLATE: PolicyTemplate = {
    "display_name": "Manager (User & Lead Manager)",
    "description": "Manager permissions: full lead management + user administration",
    "category": "core",
    "policies": [
        # Inherit all officer permissions
        *OFFICER_TEMPLATE["policies"],
        # Additional manager permissions
        {"subject": "{role}", "object": "/api/admin/users", "action": ".*"},
        {"subject": "{role}", "object": "/api/leads/*", "action": ".*"},
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
    ]
}

ADMIN_TEMPLATE: PolicyTemplate = {
    "display_name": "Administrator (Full Access)",
    "description": "Complete system access with no restrictions",
    "category": "core",
    "policies": [
        # Wildcard access to everything
        {"subject": "{role}", "object": "/*", "action": ".*"},
    ]
}

# =============================================================================
# CUSTOM ROLE TEMPLATES (Business-specific)
# =============================================================================

AUDITOR_TEMPLATE: PolicyTemplate = {
    "display_name": "Auditor (Report Analyst)",
    "description": "Read-only access to reports, statistics, and activity logs",
    "category": "custom",
    "policies": [
        # Read-only access to analytics
        {"subject": "{role}", "object": "/api/admin/activity-logs", "action": "GET"},
        {"subject": "{role}", "object": "/api/admin/statistics", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{lead_id}", "action": "GET"},
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{notification_id}", "action": "DELETE"},
    ]
}

LEAD_VIEWER_TEMPLATE: PolicyTemplate = {
    "display_name": "Lead Viewer (Read Only)",
    "description": "View-only access to leads module without modification rights",
    "category": "custom",
    "policies": [
        {"subject": "{role}", "object": "/api/leads", "action": "GET"},
        {"subject": "{role}", "object": "/api/leads/{lead_id}", "action": "GET"},
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
    ]
}

USER_MANAGER_TEMPLATE: PolicyTemplate = {
    "display_name": "User Manager",
    "description": "Manage users (create, edit, delete) without lead access",
    "category": "custom",
    "policies": [
        {"subject": "{role}", "object": "/api/admin/users", "action": ".*"},
        {"subject": "{role}", "object": "/api/admin/users/*", "action": ".*"},
        # Profile access
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        # Notification access
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{notification_id}", "action": "DELETE"},
    ]
}

BASIC_USER_TEMPLATE: PolicyTemplate = {
    "display_name": "Basic User",
    "description": "Minimal permissions: profile and notifications only",
    "category": "core",
    "policies": [
        {"subject": "{role}", "object": "/api/profile", "action": "GET"},
        {"subject": "{role}", "object": "/api/profile", "action": "PUT"},
        {"subject": "{role}", "object": "/api/notifications", "action": "GET"},
        {"subject": "{role}", "object": "/api/notifications/mark-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/mark-all-as-read", "action": "POST"},
        {"subject": "{role}", "object": "/api/notifications/{notification_id}", "action": "DELETE"},
    ]
}

# =============================================================================
# TEMPLATE REGISTRY
# =============================================================================

POLICY_TEMPLATES: Dict[str, PolicyTemplate] = {
    # Core templates (system roles)
    "admin": ADMIN_TEMPLATE,
    "manager": MANAGER_TEMPLATE,
    "officer": OFFICER_TEMPLATE,
    "user": BASIC_USER_TEMPLATE,

    # Custom templates (business-specific)
    "auditor": AUDITOR_TEMPLATE,
    "lead_viewer": LEAD_VIEWER_TEMPLATE,
    "user_manager": USER_MANAGER_TEMPLATE,
}

# =============================================================================
# SYSTEM ROLES (Cannot be deleted or modified)
# =============================================================================

SYSTEM_ROLES = [
    {
        "name": "role:admin",
        "display_name": "Administrator",
        "description": "Full system access with all permissions",
        "is_system_role": True,
        "template_id": "admin",
    },
    {
        "name": "role:manager",
        "display_name": "Manager",
        "description": "Manage users and leads with elevated permissions",
        "is_system_role": True,
        "template_id": "manager",
    },
    {
        "name": "role:officer",
        "display_name": "Officer",
        "description": "Sales officer with lead management capabilities",
        "is_system_role": True,
        "template_id": "officer",
    },
    {
        "name": "role:user",
        "display_name": "User",
        "description": "Basic user with minimal permissions",
        "is_system_role": True,
        "template_id": "user",
    },
]

# =============================================================================
# CRITICAL POLICIES (Cannot be deleted - will lock system)
# =============================================================================

CRITICAL_POLICIES = [
    # Admin wildcard access - removing this locks all admins out
    ("role:admin", "/*", ".*"),
]


def get_template(template_id: str) -> PolicyTemplate:
    """
    Get a policy template by ID.

    Args:
        template_id: Template identifier (e.g., "officer", "manager")

    Returns:
        PolicyTemplate dict

    Raises:
        KeyError: If template not found
    """
    return POLICY_TEMPLATES[template_id]


def apply_template(template_id: str, role: str) -> List[PolicyRule]:
    """
    Apply a template to a specific role, replacing {role} placeholder.

    Args:
        template_id: Template identifier
        role: Role name (with prefix, e.g., "role:custom")

    Returns:
        List of policy rules with role substituted

    Example:
        >>> apply_template("officer", "role:custom")
        [
            {"subject": "role:custom", "object": "/api/leads", "action": "GET"},
            ...
        ]
    """
    template = get_template(template_id)
    policies = []

    for policy in template["policies"]:
        policies.append({
            "subject": policy["subject"].replace("{role}", role),
            "object": policy["object"],
            "action": policy["action"],
        })

    return policies


def is_system_role(role: str) -> bool:
    """
    Check if a role is a system role (cannot be deleted).

    Args:
        role: Role name (e.g., "role:admin")

    Returns:
        True if system role, False otherwise
    """
    return any(r["name"] == role for r in SYSTEM_ROLES)


def is_critical_policy(subject: str, obj: str, action: str) -> bool:
    """
    Check if a policy is critical (cannot be deleted).

    Args:
        subject: Policy subject (e.g., "role:admin")
        obj: Policy object (e.g., "/*")
        action: Policy action (e.g., ".*")

    Returns:
        True if critical policy, False otherwise
    """
    return (subject, obj, action) in CRITICAL_POLICIES


# =============================================================================
# FEATURE-BASED PERMISSION MAP (Business-Level Abstraction)
# =============================================================================

class FeatureDefinition(TypedDict):
    """Type definition for a feature permission set."""
    display_name: str
    policies: List[PolicyRule]


FEATURE_MAP: Dict[str, FeatureDefinition] = {
    "view_leads": {
        "display_name": "Xem Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads", "action": "GET"},
            {"subject": "{role}", "object": "/api/leads/{lead_id}", "action": "GET"},
        ]
    },
    "edit_leads": {
        "display_name": "Sửa Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads/{lead_id}", "action": "PUT"},
            {"subject": "{role}", "object": "/api/leads/{lead_id}", "action": "PATCH"},
        ]
    },
    "create_leads": {
        "display_name": "Tạo Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads", "action": "POST"},
        ]
    },
    "delete_leads": {
        "display_name": "Xóa Leads",
        "policies": [
            {"subject": "{role}", "object": "/api/leads/{lead_id}", "action": "DELETE"},
        ]
    },
    "manage_users": {
        "display_name": "Quản lý Users",
        "policies": [
            {"subject": "{role}", "object": "/api/admin/users", "action": ".*"},
            {"subject": "{role}", "object": "/api/admin/users/*", "action": ".*"},
        ]
    },
    "view_reports": {
        "display_name": "Xem Báo cáo",
        "policies": [
            {"subject": "{role}", "object": "/api/admin/statistics", "action": "GET"},
            {"subject": "{role}", "object": "/api/admin/activity-logs", "action": "GET"},
        ]
    },
    "manage_notifications": {
        "display_name": "Quản lý Thông báo",
        "policies": [
            {"subject": "{role}", "object": "/api/notifications", "action": ".*"},
            {"subject": "{role}", "object": "/api/notifications/*", "action": ".*"},
        ]
    },
}
