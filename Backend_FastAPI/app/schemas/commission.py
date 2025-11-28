"""
Commission Schemas - Pydantic schemas cho API
"""
from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
from decimal import Decimal
from enum import Enum


# ============ Enums ============

class CommissionStatus(str, Enum):
    """Trạng thái hoa hồng"""
    PENDING = "pending"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class CommissionType(str, Enum):
    """Loại hoa hồng"""
    ENROLLMENT = "enrollment"
    REFERRAL = "referral"
    BONUS = "bonus"


class CalculationType(str, Enum):
    """Loại tính toán"""
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"


# ============ Commission Schemas ============

class CommissionBase(BaseModel):
    """Base schema cho Commission"""
    commission_type: CommissionType = CommissionType.ENROLLMENT
    notes: Optional[str] = Field(None, max_length=1000)


class CommissionCreate(BaseModel):
    """Schema để tạo Commission (tự động từ hệ thống)"""
    collaborator_id: int
    lead_id: int
    application_id: Optional[int] = None
    policy_id: Optional[int] = None
    base_amount: Decimal = Field(..., ge=0)
    commission_type: CommissionType = CommissionType.ENROLLMENT
    notes: Optional[str] = None


class CommissionApprove(BaseModel):
    """Schema để phê duyệt Commission"""
    notes: Optional[str] = Field(None, max_length=1000)


class CommissionReject(BaseModel):
    """Schema để từ chối Commission"""
    rejection_reason: str = Field(..., min_length=1, max_length=500)


class CommissionPay(BaseModel):
    """Schema để thanh toán Commission"""
    notes: Optional[str] = Field(None, max_length=1000)


class CommissionResponse(BaseModel):
    """Schema response cho Commission"""
    id: int
    code: str

    # Liên kết
    collaborator_id: int
    lead_id: int
    application_id: Optional[int]
    policy_id: Optional[int]

    # Loại
    commission_type: CommissionType

    # Số tiền
    base_amount: Decimal
    commission_rate: Optional[Decimal]
    commission_amount: Decimal

    # Trạng thái
    status: CommissionStatus

    # Ngày tháng
    earned_at: datetime
    approved_at: Optional[datetime]
    paid_at: Optional[datetime]

    # Người xử lý
    approved_by_user_id: Optional[int]
    paid_by_user_id: Optional[int]

    # Ghi chú
    notes: Optional[str]
    rejection_reason: Optional[str]

    # Audit
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class CommissionListResponse(BaseModel):
    """Schema cho danh sách Commissions"""
    id: int
    code: str
    collaborator_id: int
    lead_id: int
    commission_type: CommissionType
    commission_amount: Decimal
    status: CommissionStatus
    earned_at: datetime
    created_at: datetime

    class Config:
        from_attributes = True


# ============ Commission Policy Schemas ============

class CommissionPolicyBase(BaseModel):
    """Base schema cho CommissionPolicy"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    calculation_type: CalculationType = CalculationType.PERCENTAGE

    # Giá trị (tùy theo calculation_type)
    percentage_value: Optional[Decimal] = Field(None, ge=0, le=100)
    fixed_amount: Optional[Decimal] = Field(None, ge=0)

    # Điều kiện
    applicable_scope: Optional[dict] = None
    collaborator_categories: Optional[list] = None
    minimum_tuition: Optional[Decimal] = Field(None, ge=0)

    # Hiệu lực
    effective_start_date: datetime
    effective_end_date: Optional[datetime] = None

    # Ưu tiên
    priority: int = Field(default=0, ge=0)

    @validator('percentage_value')
    def validate_percentage(cls, v, values):
        if values.get('calculation_type') == CalculationType.PERCENTAGE and v is None:
            raise ValueError('percentage_value is required for PERCENTAGE calculation type')
        return v

    @validator('fixed_amount')
    def validate_fixed_amount(cls, v, values):
        if values.get('calculation_type') == CalculationType.FIXED_AMOUNT and v is None:
            raise ValueError('fixed_amount is required for FIXED_AMOUNT calculation type')
        return v


class CommissionPolicyCreate(CommissionPolicyBase):
    """Schema để tạo CommissionPolicy"""
    pass


class CommissionPolicyUpdate(BaseModel):
    """Schema để cập nhật CommissionPolicy"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    calculation_type: Optional[CalculationType] = None
    percentage_value: Optional[Decimal] = Field(None, ge=0, le=100)
    fixed_amount: Optional[Decimal] = Field(None, ge=0)
    applicable_scope: Optional[dict] = None
    collaborator_categories: Optional[list] = None
    minimum_tuition: Optional[Decimal] = Field(None, ge=0)
    effective_start_date: Optional[datetime] = None
    effective_end_date: Optional[datetime] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0)


class CommissionPolicyResponse(CommissionPolicyBase):
    """Schema response cho CommissionPolicy"""
    id: int
    code: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime]
    created_by_user_id: Optional[int]

    class Config:
        from_attributes = True


# ============ Filter Schemas ============

class CommissionFilter(BaseModel):
    """Schema để filter Commissions"""
    collaborator_id: Optional[int] = None
    lead_id: Optional[int] = None
    status: Optional[CommissionStatus] = None
    commission_type: Optional[CommissionType] = None

    # Date range
    earned_from: Optional[datetime] = None
    earned_to: Optional[datetime] = None

    # Pagination
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    # Sorting
    sort_by: Optional[str] = Field(default="earned_at", description="Field to sort by")
    sort_order: Optional[str] = Field(default="desc", description="asc or desc")
