# app/schemas/lead.py
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

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


class Consultation(ConsultationBase):
    id: int
    consultation_date: datetime
    scheduled_at: Optional[datetime] = None  # Quick Disposition: follow-up time
    officer_id: int
    consultation_status_id: Optional[str] = None
    officer: Optional[User] = None
    consultation_status: Optional[ConsultationStatus] = None

    model_config = ConfigDict(from_attributes=True)


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
    gpa: Optional[float] = None
    location: Optional[str] = None
    assigned_officer_id: Optional[int] = None  # None = auto-assign, Integer = direct assign
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
    gpa: Optional[float] = None
    location: Optional[str] = None
    officer_rating: Optional[int] = None
    officer_summary: Optional[str] = None
    # Fit Score fields
    birth_year: Optional[int] = Field(None, ge=1900, le=2100)
    location_proximity: Optional[int] = Field(None, ge=0, le=2)
    occupation_relevance: Optional[int] = Field(None, ge=0, le=2)
    academic_performance: Optional[int] = Field(None, ge=0, le=3)

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
        Normalize and validate Vietnam phone numbers on update.
        All fields optional on update, so None is always allowed.
        """
        from app.utils.phone_helpers import normalize_vietnam_phone, validate_vietnam_phone
        
        # Allow None for all fields on update
        if v is None:
            return None
        
        # Allow empty string, convert to None
        if isinstance(v, str) and v.strip() == "":
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

    offering: Optional[ProgramOffering] = None
    # THAY ĐỔI Ở ĐÂY: Sử dụng OrganizationUnitShallow
    unit: Optional[OrganizationUnitShallow] = None
    assigned_officer: Optional[User] = None
    pipeline_stage: Optional[PipelineStage] = None
    consultation_status: Optional[ConsultationStatus] = None
    # Sử dụng ApplicationShallow để tránh cyclic reference (Lead -> Application -> Lead)
    application: Optional["ApplicationShallow"] = None

    model_config = ConfigDict(from_attributes=True)


class LeadsPage(BaseModel):
    total_count: int
    leads: List[Lead]


class BulkAssignLeadsSchema(BaseModel):
    lead_ids: List[int] = Field(..., min_length=1)


class BulkUpdateStageSchema(BaseModel):
    """Schema for bulk updating leads pipeline stage."""
    lead_ids: List[int] = Field(..., min_length=1)
    pipeline_stage_id: str = Field(..., min_length=1)


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
# APPLICATION SCHEMAS (HỒ SƠ TUYỂN SINH)
# -----------------


class ChecklistItem(BaseModel):
    """Item trong checklist hồ sơ tuyển sinh."""

    code: str = Field(..., min_length=1, max_length=100)
    label: str = Field(..., min_length=1, max_length=255)
    status: Literal["missing", "submitted", "verified", "rejected"]
    submission_type: Literal["N/A", "photocopy", "notarized", "original", "incomplete"]
    notes: str = Field(default="", max_length=500)


class ApplicationDocuments(BaseModel):
    """Cấu trúc JSON documents trong Application."""

    scores: Optional[Dict[str, Optional[float]]] = None  # vd: {"Toan": 8.5, "Van": 7.0}
    checklist: Optional[List[ChecklistItem]] = None


class ApplicationBase(BaseModel):
    """Base schema cho Application."""

    status: Literal["pending", "missing_documents", "completed", "passed", "failed"] = "pending"
    major_program_id: Optional[int] = None
    program_offering_id: Optional[int] = None
    criterion_id: Optional[str] = Field(None, max_length=100)
    documents: Optional[ApplicationDocuments] = None


class ApplicationShallow(ApplicationBase):
    """Schema response cho Application khi được nested trong Lead (không có lead relationship để tránh vòng lặp)."""

    id: int
    lead_id: int
    created_at: datetime
    updated_at: datetime

    # Legacy field
    officer_id: Optional[int] = None

    # Relationships (không có lead để tránh cyclic reference)
    officer: Optional[User] = None

    model_config = ConfigDict(from_attributes=True)


class ApplicationCreate(BaseModel):
    """Schema để tạo Application mới (chỉ cần lead_id)."""

    lead_id: int


class ApplicationUpdate(BaseModel):
    """Schema để cập nhật Application."""

    status: Optional[Literal["pending", "missing_documents", "completed", "passed", "failed"]] = None
    major_program_id: Optional[int] = None
    program_offering_id: Optional[int] = None
    criterion_id: Optional[str] = Field(None, max_length=100)
    documents: Optional[ApplicationDocuments] = None


class Application(ApplicationBase):
    """Schema response cho Application."""

    id: int
    lead_id: int
    created_at: datetime
    updated_at: datetime

    # Legacy field
    officer_id: Optional[int] = None

    # Relationships (optional)
    officer: Optional[User] = None
    lead: Optional["Lead"] = None  # Forward reference

    model_config = ConfigDict(from_attributes=True)


# Rebuild models to resolve forward references
Lead.model_rebuild()
Application.model_rebuild()
