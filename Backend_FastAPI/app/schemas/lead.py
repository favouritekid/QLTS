# app/schemas/lead.py
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from .collaborator import CollaboratorShallow
from .organization import ProgramOffering, OrganizationUnitShallow
from .pipeline import ConsultationStatus, PipelineStage

# Import các schema cần thiết để lồng vào
from .user import User

# -----------------
# SCHEMAS HÀNH ĐỘNG VÀ DỮ LIỆU PHỤ
# -----------------


class ConsultationBase(BaseModel):
    method: Optional[str] = "phone"  # Default to phone
    notes: Optional[str] = Field(None, strip_whitespace=True)
    duration_minutes: Optional[int] = None


class ConsultationCreate(ConsultationBase):
    status_id: str
    consultation_date: Optional[datetime] = None  # Optional, defaults to NOW
    scheduled_at: Optional[datetime] = None  # Quick Disposition: follow-up time
    # Loss Reason - required for final negative status (validated in service)
    loss_reason_code: Optional[str] = Field(
        None,
        max_length=50,
        description="Structured loss reason code (e.g., PRICE_HIGH, NO_CONTACT)"
    )
    loss_reason_note: Optional[str] = Field(
        None,
        max_length=200,
        description="Additional note for loss reason"
    )


class ConsultationUpdate(BaseModel):
    """
    Schema for updating a consultation.
    All fields are optional - only provided fields will be updated.
    """
    method: Optional[str] = None
    notes: Optional[str] = Field(None, strip_whitespace=True)
    duration_minutes: Optional[int] = None
    status_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    # Loss Reason - required for final negative status (validated in service)
    loss_reason_code: Optional[str] = Field(
        None,
        max_length=50,
        description="Structured loss reason code (e.g., PRICE_HIGH, NO_CONTACT)"
    )
    loss_reason_note: Optional[str] = Field(
        None,
        max_length=200,
        description="Additional note for loss reason"
    )


class Consultation(ConsultationBase):
    id: int
    consultation_date: datetime
    scheduled_at: Optional[datetime] = None  # Quick Disposition: follow-up time
    officer_id: int
    consultation_status_id: Optional[str] = None
    officer: Optional[User] = None
    consultation_status: Optional[ConsultationStatus] = None
    # Loss reason — stored directly on Consultation (source of truth)
    loss_reason_code: Optional[str] = None
    loss_reason_note: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ConsultationCreateResult(BaseModel):
    """Response for POST create consultation — includes terminal guard info."""
    consultation: Consultation
    status_updated: bool = Field(
        ..., description="Whether the lead status was actually updated"
    )
    terminal_guard_reason: Optional[str] = Field(
        None,
        description="Reason status was not updated (soft-terminal guard)"
    )


class AssignmentLog(BaseModel):
    id: int
    method: Optional[str] = None
    timestamp: datetime
    reason: Optional[str] = None
    officer_id: int
    officer: Optional[User] = None

    model_config = ConfigDict(from_attributes=True)


class TimelineItem(BaseModel):
    type: Literal["consultation", "assignment"]
    timestamp: datetime
    data: Union[Consultation, AssignmentLog]


class LeadInsights(BaseModel):
    engagement_score: int
    fit_score: int
    urgency_score: int
    overall_score: int
    officer_rating: Optional[int] = None
    officer_summary: Optional[str] = None


class AssignLead(BaseModel):
    officer_id: int


class LeadAction(BaseModel):
    action: Literal["reject", "reassign"]
    # ✅ SỬA: Thêm strip_whitespace
    reason: str = Field(..., strip_whitespace=True)


# -----------------
# ADMISSION PROFILE SHALLOW (for Lead response)
# -----------------


class AdmissionProfileShallow(BaseModel):
    """Shallow schema for AdmissionProfile when nested in Lead response.
    
    Provides essential info for UI navigation without full profile details.
    Frontend uses this to show 'View Profile' vs 'Create Profile' button.
    """
    id: int
    status: str  # draft, submitted, approved, rejected, etc.
    student_code: Optional[str] = None  # If enrolled
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# -----------------
# SCHEMAS CHÍNH CỦA LEAD
# -----------------


class LeadBase(BaseModel):
    # ✅ SỬA: Thêm validation cho tất cả các trường string
    full_name: str = Field(..., min_length=1, max_length=255, strip_whitespace=True)
    email: Optional[EmailStr] = None  # Email is optional - not all leads have email
    phone: str = Field(..., min_length=1, max_length=20, strip_whitespace=True)
    phone2: Optional[str] = Field(None, max_length=20, strip_whitespace=True)  # Số điện thoại phụ
    source: str = Field(..., min_length=1, max_length=50, strip_whitespace=True)
    unit_id: Optional[int] = None  # Optional - can be auto-determined from offering or user's unit
    offering_id: Optional[int] = None

    @field_validator("email", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        """Convert empty string to None so EmailStr validation passes."""
        if v == "" or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    @field_validator("phone", "phone2", mode="before")
    @classmethod
    def normalize_and_validate_phone(cls, v, info):
        """
        Normalize and validate Vietnam phone numbers.
        
        - Normalizes +84/84 prefix to 0
        - Validates against Vietnam phone regex: ^0(3|5|7|8|9|2)\\d{8,9}$
        - Allows None/empty for phone2 (optional field)
        """
        from app.utils.phone_helpers import normalize_vietnam_phone, validate_vietnam_phone
        
        # Allow None for optional fields (phone2)
        if v is None:
            return None
        
        # Allow empty string for phone2, convert to None
        if isinstance(v, str) and v.strip() == "":
            if info.field_name == "phone2":
                return None
            # phone is required, empty string will fail min_length validation
            return v
        
        # Normalize the phone number
        normalized = normalize_vietnam_phone(v)
        if normalized is None:
            return v  # Let min_length validation handle it
        
        # Validate against Vietnam format
        if not validate_vietnam_phone(normalized, normalize=False):
            raise ValueError(
                f"Số điện thoại không hợp lệ. Vui lòng nhập số điện thoại Việt Nam "
                f"(VD: 0901234567, +84901234567)"
            )
        
        return normalized

    @field_validator("phone2", mode="after")
    @classmethod
    def phone2_must_differ_from_phone(cls, v, info):
        """Ensure phone2 is different from phone."""
        if v is None:
            return v
        
        # Access phone from data (already validated)
        phone = info.data.get("phone")
        if phone and v == phone:
            raise ValueError("Số điện thoại phụ phải khác số điện thoại chính")
        
        return v


class LeadCreate(LeadBase):
    """
    Schema for creating a new Lead.

    unit_id determination (in order of priority):
    1. Officer/Manager: Always use their own unit (unit_id from form is ignored)
    2. Admin with offering_id: Use distribution config if exists, else fallback to unit_id
    3. Admin without offering_id: Must provide unit_id

    Role-based behavior:
    - Admin: Can set any unit_id, can assign to any officer or use auto-assignment
    - Manager: unit defaults to their unit, can assign to officers in their unit
    - Officer: unit forced to their unit, auto-assigned to themselves

    assigned_officer_id:
    - None (default): Use automatic distribution/assignment (Celery task)
    - Integer: Directly assign to specified officer (skip auto-assignment)
    """
    education_level: Optional[str] = None
    gpa: Optional[float] = Field(None, ge=0.0, le=10.0, description="GPA on 0-10 scale")
    location: Optional[str] = None
    assigned_officer_id: Optional[int] = None  # None = auto-assign, Integer = direct assign
    referrer_id: Optional[int] = None  # CTV referrer for source="referral"
    # Fit Score fields (Officer input)
    birth_year: Optional[int] = Field(None, ge=1900, le=2100)
    location_proximity: int = Field(0, ge=0, le=2, description="0=Xa, 1=Lân cận, 2=Gần")
    occupation_relevance: int = Field(0, ge=0, le=2, description="0=Không liên quan, 1=Gián tiếp, 2=Trực tiếp")
    academic_performance: int = Field(0, ge=0, le=3, description="0=Yếu, 1=TB, 2=Khá, 3=Giỏi")


class LeadUpdate(BaseModel):
    full_name: Optional[str] = None
    phone2: Optional[str] = Field(None, max_length=20, strip_whitespace=True)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    unit_id: Optional[int] = None
    offering_id: Optional[int] = None
    consultation_status_id: Optional[str] = None
    education_level: Optional[str] = None
    gpa: Optional[float] = Field(None, ge=0.0, le=10.0, description="GPA on 0-10 scale")
    location: Optional[str] = None
    officer_rating: Optional[int] = Field(None, ge=1, le=5, description="Officer rating 1-5 stars")
    officer_summary: Optional[str] = None
    # Fit Score fields
    birth_year: Optional[int] = Field(None, ge=1900, le=2100)
    location_proximity: Optional[int] = Field(None, ge=0, le=2)
    occupation_relevance: Optional[int] = Field(None, ge=0, le=2)
    academic_performance: Optional[int] = Field(None, ge=0, le=3)
    referrer_id: Optional[int] = None  # CTV referrer for source="referral"
    # Optimistic locking - optional, when provided will check for concurrent updates
    version: Optional[int] = Field(None, description="Optimistic locking version")

    @field_validator("email", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        """Convert empty string to None so EmailStr validation passes."""
        if v == "" or (isinstance(v, str) and v.strip() == ""):
            return None
        return v

    @field_validator("full_name", mode="before")
    @classmethod
    def validate_full_name(cls, v):
        """Strip whitespace and reject empty string for full_name."""
        if v is None:
            return None
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                raise ValueError("Họ tên không được để trống")
        return v

    @field_validator("phone", "phone2", mode="before")
    @classmethod
    def normalize_and_validate_phone(cls, v, info):
        """
        Normalize and validate Vietnam phone numbers on update.
        All fields optional on update, so None is always allowed.
        """
        from app.utils.phone_helpers import normalize_vietnam_phone, validate_vietnam_phone

        # Allow None for all fields on update
        if v is None:
            return None

        # For primary phone, reject empty string instead of coercing to None
        if isinstance(v, str) and v.strip() == "":
            if info.field_name == "phone":
                raise ValueError("Số điện thoại chính không được để trống")
            return None

        # Normalize the phone number
        normalized = normalize_vietnam_phone(v)
        if normalized is None:
            return None

        # Validate against Vietnam format
        if not validate_vietnam_phone(normalized, normalize=False):
            raise ValueError(
                f"Số điện thoại không hợp lệ. Vui lòng nhập số điện thoại Việt Nam "
                f"(VD: 0901234567, +84901234567)"
            )

        return normalized

    @model_validator(mode="after")
    def phone2_must_differ_from_phone(self):
        """Ensure phone2 is different from phone when both are provided."""
        if self.phone is not None and self.phone2 is not None and self.phone2 == self.phone:
            raise ValueError("Số điện thoại phụ phải khác số điện thoại chính")
        return self


class LeadStatusUpdate(BaseModel):
    """
    Schema for updating lead consultation status (FSM v3.0 compliant).

    Used by PATCH /api/leads/{lead_id}/status endpoint.
    This schema is validated by the FSM engine before being applied.
    """
    consultation_status_id: str = Field(
        ...,
        description="Target consultation status ID (validated by FSM engine)"
    )
    version: int = Field(
        ...,
        ge=1,
        description="Current lead version for optimistic locking"
    )
    loss_reason_code: Optional[str] = Field(
        None,
        description="Required when transitioning to a final negative status"
    )

    model_config = ConfigDict(from_attributes=True)


class Lead(LeadBase):
    id: int
    status: str
    # Assignment workflow status: pending, assigned, failed, reassign_pending
    assignment_status: str = "pending"
    lead_score: int
    created_at: datetime
    updated_at: datetime
    assigned_at: Optional[datetime] = None
    assigned_officer_id: Optional[int] = None
    consultation_status_id: Optional[str] = None
    pipeline_stage_id: Optional[str] = None
    next_activity_at: Optional[datetime] = None  # Quick Disposition: bubble-up sorting
    # Optimistic locking version
    version: int = 1
    # Fit Score fields
    birth_year: Optional[int] = None
    location_proximity: int = 0
    occupation_relevance: int = 0
    academic_performance: int = 0
    # Education fields (were missing from response)
    education_level: Optional[str] = None
    gpa: Optional[float] = None
    location: Optional[str] = None
    
    # =========================================================================
    # CACHED METRICS (Lead Insights Upgrade)
    # Auto-updated by LeadCacheService after consultation changes
    # =========================================================================
    last_consultation_at: Optional[datetime] = None
    consultation_count: int = 0
    cached_urgency_score: int = 50
    is_hot_lead: bool = False
    is_overdue: bool = False
    # Officer input fields (from LeadUpdate)
    officer_rating: Optional[int] = None
    officer_summary: Optional[str] = None
    # =========================================================================

    # Collaborator system
    referrer_id: Optional[int] = None
    validity_status: Optional[str] = None
    created_via: Optional[str] = None

    offering: Optional[ProgramOffering] = None
    # THAY ĐỔI Ở ĐÂY: Sử dụng OrganizationUnitShallow
    unit: Optional[OrganizationUnitShallow] = None
    assigned_officer: Optional[User] = None
    pipeline_stage: Optional[PipelineStage] = None
    consultation_status: Optional[ConsultationStatus] = None
    admission_profiles: List[AdmissionProfileShallow] = Field(
        default_factory=list,
        description=(
            "Per-academic-year admission profiles, ordered most-recent "
            "first."
        ),
    )
    # Collaborator referrer (nested)
    referrer: Optional[CollaboratorShallow] = None

    model_config = ConfigDict(from_attributes=True)


class LeadDetail(Lead):
    """Lead response for GET /leads/{id} with thin-client gate flags.

    Populated by lead_service._populate_lead_detail_fields() based on
    admission_service.check_lead_level_admission_eligibility(). Other lead
    endpoints (list/create/update) continue returning plain ``Lead`` and
    do not carry these fields.

    Blocker codes emitted for ``create_admission``:
      forbidden, already_has_profile, invalid_lead_status, missing_offering,
      no_consultation, consultation_missing_status, consultation_universal_status.
    """
    permissions: Dict[str, bool] = Field(
        default_factory=dict,
        description="Permission flags computed per-user (e.g. create_admission).",
    )
    available_actions: List[str] = Field(
        default_factory=list,
        description="Actions currently allowed (subset of permissions keys where value=True).",
    )
    action_blockers: Dict[str, str] = Field(
        default_factory=dict,
        description="Map action_name → blocker_code for disabled actions.",
    )

    model_config = ConfigDict(from_attributes=True)


class LeadReopenRequest(BaseModel):
    """Body cho POST /leads/{lead_id}/reopen — mở lại lead đã ngừng tư vấn.

    Chỉ manager/admin (role-gate ở backend Casbin + IDOR). ``reason`` bắt buộc, lưu
    nguyên văn để audit. Xem Documents/LEAD_REOPEN_WORKFLOW_PLAN.md.
    """
    # Strip whitespace TRƯỚC khi đếm min_length → "     " (5 dấu cách) bị chặn ngay ở
    # Pydantic (422) thay vì lọt tới service rồi mới reject (400) — nhất quán mã lỗi.
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(
        ...,
        min_length=5,
        max_length=500,
        description="Lý do mở lại (bắt buộc, tối thiểu 5 ký tự).",
    )


class LeadsSummary(BaseModel):
    """Aggregate stats over the entire filtered set (not just current page)."""
    new_count: int = 0
    high_score_count: int = 0
    converted_count: int = 0
    conversion_rate: float = 0.0


class EffectiveScope(BaseModel):
    """Scope context returned with leads page so UI knows what data it's seeing."""
    scope_kind: Optional[str] = None
    label: Optional[str] = None
    forced_by_role: bool = False
    includes_descendants: bool = False


class LeadsPage(BaseModel):
    total_count: int
    leads: List[Lead]
    summary: Optional[LeadsSummary] = None
    effective_scope: Optional[EffectiveScope] = None


class BulkAssignLeadsSchema(BaseModel):
    lead_ids: List[int] = Field(..., min_length=1)


class BulkUpdateStageSchema(BaseModel):
    """Schema for bulk updating leads pipeline stage."""
    lead_ids: List[int] = Field(..., min_length=1)
    pipeline_stage_id: str = Field(..., min_length=1)


class BulkStageSkippedItem(BaseModel):
    """Single skipped lead in bulk stage update."""
    lead_id: int
    reason: str


class BulkUpdateStageResult(BaseModel):
    """Response for bulk stage update with skip diagnostics."""
    message: str
    updated_count: int
    skipped: List[BulkStageSkippedItem] = Field(default_factory=list)


class BulkDeleteSchema(BaseModel):
    """Schema for bulk deleting leads."""
    lead_ids: List[int] = Field(..., min_length=1)


class LeadImportError(BaseModel):
    row_number: int  # Số dòng trong file gốc (bắt đầu từ 1 hoặc 2 tùy header)
    error_message: str
    row_data: Optional[Dict[str, Any]] = None  # Dữ liệu gốc của dòng bị lỗi (tùy chọn)


class LeadImportResult(BaseModel):
    total_rows_processed: int
    successful_imports: int
    failed_imports: int
    created_lead_ids: List[int] = []
    errors: List[LeadImportError] = []


# -----------------
# WORKFLOW CONTEXT SCHEMA (Phase-Based Workflow)
# -----------------


class WorkflowAllowedStatus(BaseModel):
    """Status option in workflow context."""
    id: str
    name: str
    phase: str
    color_code: str
    outcome_type: str
    is_universal: bool


class WorkflowContext(BaseModel):
    """
    Workflow context for a lead - provides frontend with allowed actions.
    
    Used by frontend to:
    - Filter status dropdown options
    - Show/hide phase-specific UI elements
    - Validate user actions before API call
    """
    lead_id: int
    current_phase: str = Field(..., description="Current workflow phase: consultation, admission, fee, enrolled")
    current_status_id: Optional[str] = None
    current_stage_id: Optional[str] = None
    
    # Allowed statuses for current phase
    allowed_statuses: List[WorkflowAllowedStatus] = Field(
        default_factory=list,
        description="Statuses user can select based on current phase and role"
    )
    
    # Locked actions (for UI to disable buttons)
    is_terminal_phase: bool = Field(
        default=False,
        description="True if lead is in enrolled phase (no further transitions)"
    )
    can_change_status: bool = Field(
        default=True,
        description="False if status changes are locked"
    )
    
    # Admission profile info (for phase derivation)
    has_admission_profile: bool = False
    admission_status: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


# Rebuild models to resolve forward references
Lead.model_rebuild()
