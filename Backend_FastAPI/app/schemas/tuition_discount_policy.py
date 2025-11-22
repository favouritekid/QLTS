# app/schemas/tuition_discount_policy.py
"""
Pydantic schemas for TuitionDiscountPolicy - Quản lý chính sách ưu đãi học phí.

Cấu trúc JSON fields:
- applicable_scope: Phạm vi ngành/chương trình áp dụng
- target_criteria: Điều kiện đối tượng sinh viên được hưởng
"""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# =============================================================================
# ENUMS
# =============================================================================

class DiscountType(str, Enum):
    """Loại ưu đãi"""
    AMOUNT = "amount"           # Giảm số tiền cố định (VND)
    PERCENTAGE = "percentage"   # Giảm theo phần trăm (%)


# =============================================================================
# JSON FIELD SCHEMAS (for validation)
# =============================================================================

class ApplicableScope(BaseModel):
    """Schema cho phạm vi áp dụng chính sách"""
    all_programs: Optional[bool] = Field(
        False,
        description="Áp dụng cho tất cả chương trình"
    )
    degree_levels: Optional[List[str]] = Field(
        None,
        description="Danh sách trình độ áp dụng (vd: ['Cao đẳng', 'Trung cấp'])"
    )
    major_program_ids: Optional[List[int]] = Field(
        None,
        description="Danh sách ID ngành áp dụng"
    )
    major_program_codes: Optional[List[str]] = Field(
        None,
        description="Danh sách mã ngành áp dụng (vd: ['6480201', '6510301'])"
    )
    is_heavy_only: Optional[bool] = Field(
        False,
        description="Chỉ áp dụng cho ngành nặng nhọc, độc hại"
    )
    offering_ids: Optional[List[int]] = Field(
        None,
        description="Danh sách ID loại hình đào tạo áp dụng"
    )


class TargetCriteria(BaseModel):
    """Schema cho điều kiện đối tượng sinh viên"""
    priority_types: Optional[List[str]] = Field(
        None,
        description="Loại đối tượng ưu tiên (vd: ['con_thuong_binh', 'ho_ngheo'])"
    )
    regions: Optional[List[str]] = Field(
        None,
        description="Vùng miền (vd: ['mien_nui', 'vung_sau'])"
    )
    min_gpa: Optional[float] = Field(
        None,
        ge=0,
        le=10,
        description="Điểm trung bình tối thiểu"
    )
    gender: Optional[str] = Field(
        None,
        description="Giới tính (male/female)"
    )
    age_max: Optional[int] = Field(
        None,
        ge=0,
        description="Tuổi tối đa"
    )


# =============================================================================
# BASE SCHEMA
# =============================================================================

class TuitionDiscountPolicyBase(BaseModel):
    """Base schema với các field chung"""
    code: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Mã chính sách duy nhất (vd: 'EARLY_BIRD_2025')"
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Tên chính sách hiển thị"
    )
    description: Optional[str] = Field(
        None,
        max_length=2000,
        description="Mô tả chi tiết"
    )
    discount_type: DiscountType = Field(
        ...,
        description="Loại ưu đãi: 'amount' hoặc 'percentage'"
    )
    discount_value: Decimal = Field(
        ...,
        ge=0,
        description="Giá trị ưu đãi (VND hoặc %)"
    )
    valid_from: Optional[date] = Field(
        None,
        description="Ngày bắt đầu hiệu lực"
    )
    valid_to: Optional[date] = Field(
        None,
        description="Ngày kết thúc hiệu lực"
    )
    applicable_scope: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Phạm vi áp dụng (JSON)"
    )
    target_criteria: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Điều kiện đối tượng (JSON)"
    )
    is_stackable: bool = Field(
        False,
        description="Có thể cộng dồn với ưu đãi khác"
    )
    priority: int = Field(
        0,
        ge=0,
        description="Độ ưu tiên (cao hơn = áp dụng trước)"
    )
    max_usage: Optional[int] = Field(
        None,
        ge=0,
        description="Giới hạn số lượt sử dụng"
    )
    is_active: bool = Field(
        True,
        description="Trạng thái hoạt động"
    )

    @field_validator('code')
    @classmethod
    def validate_code(cls, v: str) -> str:
        """Chuẩn hóa mã: uppercase, thay khoảng trắng bằng underscore"""
        return v.strip().upper().replace(' ', '_')

    @model_validator(mode='after')
    def validate_discount_value(self):
        """Kiểm tra giá trị ưu đãi phù hợp với loại"""
        if self.discount_type == DiscountType.PERCENTAGE:
            if self.discount_value > 100:
                raise ValueError("Phần trăm ưu đãi không được vượt quá 100%")
        return self

    @model_validator(mode='after')
    def validate_date_range(self):
        """Kiểm tra ngày bắt đầu phải trước ngày kết thúc"""
        if self.valid_from and self.valid_to:
            if self.valid_from > self.valid_to:
                raise ValueError("Ngày bắt đầu phải trước ngày kết thúc")
        return self


# =============================================================================
# CREATE / UPDATE SCHEMAS
# =============================================================================

class TuitionDiscountPolicyCreate(TuitionDiscountPolicyBase):
    """Schema cho tạo mới chính sách"""
    pass


class TuitionDiscountPolicyUpdate(BaseModel):
    """Schema cho cập nhật chính sách (tất cả field đều optional)"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    discount_type: Optional[DiscountType] = None
    discount_value: Optional[Decimal] = Field(None, ge=0)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    applicable_scope: Optional[Dict[str, Any]] = None
    target_criteria: Optional[Dict[str, Any]] = None
    is_stackable: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0)
    max_usage: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None

    @model_validator(mode='after')
    def validate_discount_value(self):
        """Kiểm tra giá trị ưu đãi nếu được cung cấp"""
        if self.discount_type == DiscountType.PERCENTAGE and self.discount_value:
            if self.discount_value > 100:
                raise ValueError("Phần trăm ưu đãi không được vượt quá 100%")
        return self


# =============================================================================
# RESPONSE SCHEMA
# =============================================================================

class TuitionDiscountPolicy(TuitionDiscountPolicyBase):
    """Schema đầy đủ với các field từ DB"""
    id: int
    current_usage: int = Field(0, description="Số lượt đã sử dụng")
    created_at: datetime
    updated_at: datetime
    created_by_user_id: Optional[int] = None
    updated_by_user_id: Optional[int] = None

    # Computed fields
    is_expired: Optional[bool] = Field(None, description="Đã hết hạn chưa")
    is_within_validity: Optional[bool] = Field(None, description="Đang trong thời gian hiệu lực")
    has_quota_remaining: Optional[bool] = Field(None, description="Còn quota sử dụng")

    model_config = ConfigDict(from_attributes=True)


class TuitionDiscountPolicyWithCreator(TuitionDiscountPolicy):
    """Schema với thông tin người tạo"""
    created_by_name: Optional[str] = None
    updated_by_name: Optional[str] = None


# =============================================================================
# LIST / PAGINATION SCHEMAS
# =============================================================================

class TuitionDiscountPolicyListResponse(BaseModel):
    """Response cho danh sách chính sách"""
    items: List[TuitionDiscountPolicy]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================================================
# UTILITY SCHEMAS
# =============================================================================

class DiscountCalculationRequest(BaseModel):
    """Request tính toán ưu đãi cho sinh viên"""
    student_priority_type: Optional[str] = None
    student_region: Optional[str] = None
    student_gpa: Optional[float] = None
    major_program_id: Optional[int] = None
    major_program_code: Optional[str] = None
    offering_id: Optional[int] = None
    is_heavy_program: bool = False
    tuition_fee: Decimal = Field(..., description="Học phí gốc")


class AppliedDiscount(BaseModel):
    """Chi tiết một ưu đãi được áp dụng"""
    policy_id: int
    policy_code: str
    policy_name: str
    discount_type: DiscountType
    discount_value: Decimal
    discount_amount: Decimal = Field(..., description="Số tiền giảm thực tế")


class DiscountCalculationResponse(BaseModel):
    """Response kết quả tính toán ưu đãi"""
    original_tuition: Decimal
    total_discount: Decimal
    final_tuition: Decimal
    applied_policies: List[AppliedDiscount]
