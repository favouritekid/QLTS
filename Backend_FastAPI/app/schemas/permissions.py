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
    validate: bool = Field(True, description="Whether to validate before applying")
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
    validate: bool = Field(True, description="Whether to validate before applying")


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
