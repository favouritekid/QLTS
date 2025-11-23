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
    method: str
    # ✅ SỬA: Thêm strip_whitespace
    notes: str = Field(..., strip_whitespace=True)
    outcome: Optional[str] = None
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
    outcome: Optional[str] = None
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
        if v == "":
            return None
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
    assigned_officer_id: Optional[int] = None  # None = auto-assign, Integer = direct assign


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

    @field_validator("email", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        """Convert empty string to None so EmailStr validation passes."""
        if v == "":
            return None
        return v


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
