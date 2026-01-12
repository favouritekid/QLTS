# app/schemas/admission_path.py
"""
Admission Path Schemas.

Pydantic schemas for AdmissionPath API request/response.

FRONTEND_ARCHITECTURE_V3.md Compliance:
- Response includes control fields: status, available_actions, can_*, validation_errors
- FE reads these, not computes them
"""

from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# STATUS ENUM
# =============================================================================

AdmissionPathStatus = Literal["draft", "active", "inactive", "archived"]
VisibilityStatus = Literal["internal", "public"]
DocumentSource = Literal["shared", "method_override"]


# =============================================================================
# NESTED SCHEMAS (for response)
# =============================================================================

class AdmissionMethodNested(BaseModel):
    """Nested admission method info."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str
    requires_gpa: bool
    requires_subject_scores: bool


class OfferingAcademicInfoNested(BaseModel):
    """Nested academic info with offering details."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    academic_year: int
    annual_admission_quota: Optional[int] = None
    # offering details will be added when needed


class UserNested(BaseModel):
    """Nested user info for activator."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    full_name: str


class SubjectGroupNested(BaseModel):
    """Nested subject group info for criteria."""
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str


class AdmissionCriteriaNested(BaseModel):
    """
    Nested criteria info for AdmissionPath response.
    
    Used by LeadApplicationForm to initialize subject scores.
    """
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    code: str
    name: str
    
    # Thresholds
    min_gpa: Optional[float] = None
    min_score: Optional[float] = None
    
    # Rule Engine config
    required_subject_count: Optional[int] = None
    subject_selection_mode: str = "fixed"
    scoring_method: str = "sum"
    
    # Subject groups for score initialization
    subject_groups: List[SubjectGroupNested] = Field(
        default_factory=list,
        description="Allowed subject groups for this criteria (A00, D01, etc.)"
    )


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class AdmissionPathCreate(BaseModel):
    """Request schema for creating a new AdmissionPath."""
    academic_info_id: int
    admission_method_id: int
    display_name: Optional[str] = None
    display_order: int = 0
    visibility: VisibilityStatus = "internal"


class AdmissionPathUpdate(BaseModel):
    """Request schema for updating an AdmissionPath."""
    display_name: Optional[str] = None
    display_order: Optional[int] = None
    visibility: Optional[VisibilityStatus] = None


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class AdmissionPathResponse(BaseModel):
    """
    Response schema for AdmissionPath.
    
    FRONTEND_ARCHITECTURE_V3.md Compliance:
    - available_actions: FE checks this, not user.role
    - can_edit, can_activate: FE reads, not computes
    - validation_errors: Why activation is blocked
    """
    model_config = ConfigDict(from_attributes=True)
    
    # Core fields
    id: int
    status: AdmissionPathStatus
    display_name: Optional[str] = None
    display_order: int
    visibility: VisibilityStatus
    
    # Relationships
    academic_info: Optional[OfferingAcademicInfoNested] = None
    admission_method: Optional[AdmissionMethodNested] = None
    
    # Nested criteria (for LeadApplicationForm - GAP-D fix)
    criteria: Optional[AdmissionCriteriaNested] = None
    
    # Audit fields
    activated_at: Optional[datetime] = None
    activator: Optional[UserNested] = None
    created_at: datetime
    updated_at: datetime
    
    # === CONTROL FIELDS (Required by FRONTEND_ARCHITECTURE_V3.md) ===
    available_actions: List[str] = Field(
        default_factory=list,
        description="Actions available for this path: save, activate, deactivate, archive"
    )
    can_edit: bool = Field(
        default=True,
        description="Whether the path can be edited"
    )
    can_activate: bool = Field(
        default=False,
        description="Whether the path can be activated"
    )
    validation_errors: List[str] = Field(
        default_factory=list,
        description="Reasons why activation is blocked"
    )


class AdmissionPathListResponse(BaseModel):
    """Response for list of paths with pagination."""
    total: int
    items: List[AdmissionPathResponse]


# =============================================================================
# ACADEMIC YEAR SCHEMAS
# =============================================================================

class AcademicYearListResponse(BaseModel):
    """Response for academic years endpoint."""
    years: List[int]
    current_year: int


# =============================================================================
# DOCUMENT RESOLUTION SCHEMAS
# =============================================================================

class ResolvedDocumentResponse(BaseModel):
    """
    Response for a single resolved document.
    
    Shows whether document is from shared config or method-specific override.
    """
    model_config = ConfigDict(from_attributes=True)
    
    document_type_id: int
    document_type_code: str
    document_type_name: str
    is_mandatory: bool
    requires_upload: bool
    submission_format: Optional[str] = None
    display_order: int = 0
    source: DocumentSource = Field(
        description="Where this doc requirement comes from: shared or method_override"
    )


class ResolvedDocumentListResponse(BaseModel):
    """Response for resolved documents endpoint."""
    path_id: int
    offering_type_id: int
    admission_method_id: int
    documents: List[ResolvedDocumentResponse]


# =============================================================================
# ACTIVATION SCHEMAS
# =============================================================================

class ActivationValidationResponse(BaseModel):
    """Response for activation validation check."""
    can_activate: bool
    validation_errors: List[str] = Field(
        default_factory=list,
        description="List of reasons why activation is blocked"
    )


class ActivationRequest(BaseModel):
    """Request for activating a path (optional notes)."""
    notes: Optional[str] = None


# =============================================================================
# COVERAGE MATRIX SCHEMAS
# =============================================================================

class CoverageRow(BaseModel):
    """
    Single row in coverage matrix = one AdmissionPath.
    
    Used by Config Console to show path readiness status.
    """
    path_id: int
    method_name: str
    method_code: str
    status: AdmissionPathStatus
    
    # Readiness indicators
    has_criteria: bool = Field(
        description="Whether criteria_id is set"
    )
    has_documents: bool = Field(
        description="Whether document group exists for method"
    )
    has_quota: bool = Field(
        description="Whether quota > 0"
    )
    
    # Computed from above
    can_activate: bool = Field(
        description="has_criteria AND has_documents AND has_quota"
    )
    
    # Validation errors if cannot activate
    validation_errors: List[str] = Field(default_factory=list)


class CoverageMatrixResponse(BaseModel):
    """
    Response for coverage matrix view.
    
    Shows all paths for an academic_info with their readiness status.
    FE uses this to display audit table and bulk activate button.
    """
    academic_info_id: int
    rows: List[CoverageRow]
    
    # Summary
    total_paths: int
    paths_ready: int
    all_ready: bool = Field(
        description="True only if all paths can be activated"
    )

