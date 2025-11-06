# app/schemas/lead.py
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .organization import Major, OrganizationUnitShallow
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


class Consultation(ConsultationBase):
    id: int
    consultation_date: datetime
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
    email: EmailStr  # EmailStr đã tự động strip và validate
    phone: str = Field(..., min_length=1, max_length=20, strip_whitespace=True)
    source: str = Field(..., min_length=1, max_length=50, strip_whitespace=True)
    unit_id: int
    major_id: Optional[int] = None


class LeadCreate(LeadBase):
    pass


class LeadUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    source: Optional[str] = None
    unit_id: Optional[int] = None
    major_id: Optional[int] = None
    consultation_status_id: Optional[str] = None
    education_level: Optional[str] = None
    gpa: Optional[float] = None
    location: Optional[str] = None
    officer_rating: Optional[int] = None
    officer_summary: Optional[str] = None


class Lead(LeadBase):
    id: int
    status: str
    lead_score: int
    created_at: datetime
    updated_at: datetime
    assigned_at: Optional[datetime] = None
    assigned_officer_id: Optional[int] = None
    consultation_status_id: Optional[str] = None
    pipeline_stage_id: Optional[str] = None

    major: Optional[Major] = None
    # THAY ĐỔI Ở ĐÂY: Sử dụng OrganizationUnitShallow
    unit: Optional[OrganizationUnitShallow] = None
    assigned_officer: Optional[User] = None
    pipeline_stage: Optional[PipelineStage] = None
    consultation_status: Optional[ConsultationStatus] = None

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
