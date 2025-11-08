# app/casbin_config/__init__.py
"""
Casbin policy management configuration package.
Contains policy templates and Casbin-related configurations.
"""

from .policy_templates import (
    POLICY_TEMPLATES,
    CRITICAL_POLICIES,
    SYSTEM_ROLES,
    apply_template,
    is_critical_policy,
)

__all__ = [
    "POLICY_TEMPLATES",
    "CRITICAL_POLICIES",
    "SYSTEM_ROLES",
    "apply_template",
    "is_critical_policy",
]
