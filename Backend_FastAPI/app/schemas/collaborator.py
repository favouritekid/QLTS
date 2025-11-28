"""
Collaborator Schemas - Pydantic schemas cho API
"""
from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional
from datetime import datetime
from decimal import Decimal


# ============ Base Schemas ============

class CollaboratorBase(BaseModel):
    """Base schema cho Collaborator"""
    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: str = Field(..., min_length=10, max_length=20)
    phone2: Optional[str] = Field(None, max_length=20)

    # Thông tin định danh
    id_number: Optional[str] = Field(None, max_length=20)
    tax_code: Optional[str] = Field(None, max_length=20)
    bank_account: Optional[str] = Field(None, max_length=50)
    bank_name: Optional[str] = Field(None, max_length=100)
    bank_branch: Optional[str] = Field(None, max_length=100)

    # Địa chỉ
    address: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=100)
    district: Optional[str] = Field(None, max_length=100)

    # Phân loại
    collaborator_type: str = Field(default="individual", max_length=50)
    category: Optional[str] = Field(None, max_length=50)

    # Metadata
    notes: Optional[str] = Field(None, max_length=1000)
    metadata: Optional[dict] = None


# ============ Request Schemas ============

class CollaboratorCreate(CollaboratorBase):
    """Schema để tạo mới Collaborator"""
    pass


class CollaboratorUpdate(BaseModel):
    """Schema để cập nhật Collaborator"""
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, min_length=10, max_length=20)
    phone2: Optional[str] = Field(None, max_length=20)

    id_number: Optional[str] = Field(None, max_length=20)
    tax_code: Optional[str] = Field(None, max_length=20)
    bank_account: Optional[str] = Field(None, max_length=50)
    bank_name: Optional[str] = Field(None, max_length=100)
    bank_branch: Optional[str] = Field(None, max_length=100)

    address: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=100)
    district: Optional[str] = Field(None, max_length=100)

    collaborator_type: Optional[str] = Field(None, max_length=50)
    category: Optional[str] = Field(None, max_length=50)
    status: Optional[str] = Field(None, max_length=20)

    notes: Optional[str] = Field(None, max_length=1000)
    metadata: Optional[dict] = None


class CollaboratorStatusUpdate(BaseModel):
    """Schema để cập nhật trạng thái Collaborator"""
    status: str = Field(..., description="active, inactive, suspended")


# ============ Response Schemas ============

class CollaboratorResponse(CollaboratorBase):
    """Schema response đầy đủ cho Collaborator"""
    id: int
    code: str
    status: str
    is_active: bool

    # Thống kê
    total_leads: int
    successful_leads: int
    total_commission_earned: Decimal
    pending_commission: Decimal

    # Audit
    created_at: datetime
    updated_at: Optional[datetime] = None
    created_by_user_id: Optional[int] = None

    class Config:
        from_attributes = True


class CollaboratorListResponse(BaseModel):
    """Schema cho danh sách Collaborators"""
    id: int
    code: str
    full_name: str
    email: str
    phone: str
    category: Optional[str]
    status: str
    total_leads: int
    successful_leads: int
    pending_commission: Decimal
    created_at: datetime

    class Config:
        from_attributes = True


class CollaboratorStatsResponse(BaseModel):
    """Schema cho thống kê Collaborator"""
    collaborator_id: int
    collaborator_code: str
    collaborator_name: str

    # Thống kê lead
    total_leads: int
    successful_leads: int
    pending_leads: int
    conversion_rate: float  # Tỷ lệ chuyển đổi (%)

    # Thống kê hoa hồng
    total_commission_earned: Decimal
    pending_commission: Decimal
    paid_commission: Decimal

    # Thời gian
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============ Filter Schemas ============

class CollaboratorFilter(BaseModel):
    """Schema để filter Collaborators"""
    code: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    collaborator_type: Optional[str] = None
    city: Optional[str] = None

    # Pagination
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    # Sorting
    sort_by: Optional[str] = Field(default="created_at", description="Field to sort by")
    sort_order: Optional[str] = Field(default="desc", description="asc or desc")
