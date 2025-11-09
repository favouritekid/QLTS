# app/schemas/permissions.py
from typing import List, Optional
from pydantic import BaseModel, Field


class Policy(BaseModel):
    """Schema để đọc một policy."""

    subject: str
    object: str
    action: str


class PolicyCreate(BaseModel):
    """Schema để tạo một policy mới."""

    subject: str = Field(..., description="Chủ thể, vd: 'role:manager' hoặc 'user:123'")
    object: str = Field(
        ..., description="Đối tượng, vd: '/api/leads/*' hoặc '/api/admin/users'"
    )
    action: str = Field(..., description="Hành động, vd: 'GET', 'POST', '*'")


class RoleAssignment(BaseModel):
    """Schema để gán vai trò cho người dùng."""

    user_id: int = Field(..., gt=0)
    role: str = Field(..., description="Vai trò (đã có tiền tố), vd: 'role:officer'")


class GroupingPolicyCreate(BaseModel):
    """Schema để tạo grouping policy (kế thừa role hoặc gán role)."""

    subject: str = Field(..., description="Subject, vd: 'role:support' hoặc 'user:5'")
    parent_role: str = Field(..., description="Parent role để kế thừa, vd: 'role:user'")


# ============================================================================
# NEW SCHEMAS FOR POLICY MANAGEMENT SYSTEM
# ============================================================================


class RoleInfo(BaseModel):
    """Schema for role information."""

    name: str = Field(..., description="Role identifier (e.g., role:admin)")
    display_name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Role description")
    is_system_role: bool = Field(..., description="Whether this is a core system role")
    template_id: Optional[str] = Field(None, description="Associated template ID")
    policy_count: int = Field(..., description="Number of policies for this role")


class PolicyRule(BaseModel):
    """Schema for a single policy rule."""

    subject: str = Field(..., description="Policy subject (e.g., role:manager)")
    object: str = Field(..., description="Resource path (e.g., /api/leads/*)")
    action: str = Field(..., description="HTTP method or regex (e.g., GET, .*)")


class TemplateInfo(BaseModel):
    """Schema for policy template information."""

    id: str = Field(..., description="Template identifier")
    display_name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Template description")
    category: str = Field(..., description="Template category (core/custom)")
    policies: List[PolicyRule] = Field(..., description="List of policy rules in template")


class PolicyBatchRequest(BaseModel):
    """Schema for batch policy operations."""

    policies: List[PolicyCreate] = Field(..., description="List of policies to add/remove")
    run_validation: bool = Field(True, description="Whether to validate before applying")
    dry_run: bool = Field(False, description="Preview changes without applying")


class PolicyBatchResult(BaseModel):
    """Schema for batch operation result."""

    added: int = Field(0, description="Number of policies successfully added")
    removed: int = Field(0, description="Number of policies successfully removed")
    skipped: int = Field(0, description="Number of policies skipped (duplicates)")
    blocked: int = Field(0, description="Number of policies blocked by safety checks")
    errors: List[str] = Field([], description="List of error messages")
    warnings: List[str] = Field([], description="List of warnings")


class PolicyValidationRequest(BaseModel):
    """Schema for policy validation request."""

    subject: str
    object: str
    action: str
    operation: str = Field("add", description="Operation type: add or remove")


class PolicyValidationResult(BaseModel):
    """Schema for policy validation result."""

    is_valid: bool = Field(..., description="Whether the policy is valid")
    is_safe: bool = Field(..., description="Whether the operation is safe")
    severity: str = Field(..., description="Severity level: info, warning, critical")
    warnings: List[str] = Field([], description="List of warnings")
    affected_users: List[int] = Field([], description="User IDs affected by this change")


class TemplateApplicationRequest(BaseModel):
    """Schema for applying a template to a role."""

    template_id: str = Field(..., description="Template identifier")
    role: str = Field(..., description="Role to apply template to (e.g., role:custom)")
    run_validation: bool = Field(True, description="Whether to validate before applying")


class PolicyStatistics(BaseModel):
    """Schema for policy statistics."""

    total_policies: int
    total_roles: int
    total_grouping_policies: int


class RolesListResponse(BaseModel):
    """Schema for roles list endpoint response."""

    roles: List[RoleInfo]


class TemplatesListResponse(BaseModel):
    """Schema for templates list endpoint response."""

    templates: List[TemplateInfo]


# ============================================================================
# ADVANCED PERMISSION TOOLS SCHEMAS
# ============================================================================


class WhoCanAccessResponse(BaseModel):
    """Schema for reverse permission lookup response."""

    object: str = Field(..., description="Resource path that was queried")
    action: str = Field(..., description="Action that was queried")
    allowed_subjects: List[str] = Field(
        ..., description="List of subjects (roles/users) with access"
    )
    total_count: int = Field(..., description="Number of subjects with access")


class PermissionSimulateRequest(BaseModel):
    """Schema for permission simulation request."""

    subject: str = Field(..., description="Subject to test (e.g., role:manager, user:123)")
    object: str = Field(..., description="Resource path (e.g., /api/leads)")
    action: str = Field(..., description="HTTP method (e.g., GET, POST)")


class PermissionSimulateResponse(BaseModel):
    """Schema for permission simulation response."""

    subject: str = Field(..., description="Subject that was tested")
    object: str = Field(..., description="Resource that was tested")
    action: str = Field(..., description="Action that was tested")
    is_allowed: bool = Field(..., description="Whether permission is granted")
    message: str = Field(..., description="Human-readable result message")


class FeatureStatus(BaseModel):
    """Schema for a single feature's status."""

    feature_id: str = Field(..., description="Feature identifier")
    display_name: str = Field(..., description="Human-readable feature name")
    enabled: bool = Field(..., description="Whether feature is currently enabled")
    policy_count: int = Field(..., description="Number of policies in this feature")


class RoleFeaturesResponse(BaseModel):
    """Schema for role features list response."""

    role: str = Field(..., description="Role name (e.g., role:manager)")
    features: List[FeatureStatus] = Field(..., description="List of feature statuses")


class ToggleFeatureRequest(BaseModel):
    """Schema for feature toggle request."""

    feature_id: str = Field(..., description="Feature identifier to toggle")
    enabled: bool = Field(..., description="Whether to enable or disable the feature")


class PolicySuggestionsResponse(BaseModel):
    """Schema for policy autocomplete suggestions."""

    subjects: List[str] = Field(..., description="List of unique subjects in policies")
    objects: List[str] = Field(..., description="List of unique objects/resources in policies")
    actions: List[str] = Field(..., description="List of unique actions in policies")


class PermissionExplainResponse(BaseModel):
    """Schema for permission explanation (shows policy sources)."""

    role: str = Field(..., description="Role name being explained")
    policies_from_template: List[PolicyRule] = Field(
        ..., description="Policies inherited from system templates"
    )
    policies_from_features: List[PolicyRule] = Field(
        ..., description="Policies from enabled features"
    )
    policies_manual: List[PolicyRule] = Field(
        ..., description="Policies added manually (not from templates/features)"
    )
    policies_inherited: List[PolicyRule] = Field(
        default_factory=list, description="Policies inherited from other roles via grouping policies"
    )
