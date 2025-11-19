# app/schemas/organization.py
"""
Organization Schemas - Refactored for 3-tier architecture.

Hierarchy:
    MajorProgram (Level 1) -> ProgramOffering (Level 2) -> OfferingAcademicInfo (Level 3)
"""
from enum import Enum
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# --- Enum cho các loại đơn vị (không đổi) ---
class OrganizationUnitType(str, Enum):
    """
    Các loại đơn vị tổ chức.

    Để thêm loại mới: thêm vào enum này và update frontend UnitDialog.tsx
    """
    TRUONG = "Trường"
    PHONG_BAN = "Phòng ban"
    TRUNG_TAM = "Trung tâm"
    KHOA = "Khoa"
    TO = "Tổ"
    BO_MON = "Bộ môn"

    @classmethod
    def values(cls) -> List[str]:
        """Trả về danh sách các giá trị hợp lệ"""
        return [item.value for item in cls]


# =============================================================================
# SCHEMA VALIDATION CHO JSON (CẤP 3)
# =============================================================================

class AdmissionCriterion(BaseModel):
    """Schema validation cho admission_criteria JSON field"""
    id: str = Field(..., description="Unique ID (e.g., 'hocba_2025')")
    method_name: str = Field(..., max_length=100, description="Tên phương thức tuyển sinh")
    program_type: Optional[str] = Field(None, max_length=100, description="Loại hình (e.g., 'Chính quy')")
    subject_groups: Optional[List[str]] = Field(None, max_items=10, description="Tổ hợp môn (e.g., ['A00', 'D07'])")
    min_score: Optional[float] = Field(None, ge=0, description="Điểm tối thiểu")
    conditions: Optional[str] = Field(None, max_length=1000, description="Điều kiện")
    profile_requirements: Optional[str] = Field(None, max_length=1000, description="Yêu cầu hồ sơ")

    @field_validator('subject_groups')
    @classmethod
    def validate_subject_groups(cls, v):
        if v:
            for group in v:
                if not re.match(r'^[A-Z0-9]{2,3}$', group):
                    raise ValueError(f'Invalid subject group format: {group}. Must be like A00, D07')
        return v


# =============================================================================
# CẤP 3: OfferingAcademicInfo
# =============================================================================

class OfferingAcademicInfoBase(BaseModel):
    academic_year: int = Field(..., ge=2000, le=2100, description="Năm học")
    tuition_fee_per_year: Optional[Decimal] = Field(None, ge=0, description="Học phí một năm (VND)")
    annual_admission_quota: Optional[int] = Field(None, ge=0, description="Chỉ tiêu tuyển sinh")
    is_published: bool = Field(default=False, description="Đã công bố?")
    admission_criteria: Optional[List[AdmissionCriterion]] = Field(None, description="Tiêu chí tuyển sinh")
    target_audience: Optional[str] = Field(None, max_length=1000, description="Đối tượng phù hợp")
    cutoff_score_previous_year: Optional[Decimal] = Field(None, ge=0, description="Điểm chuẩn năm trước")

    @field_validator('admission_criteria', mode='before')
    @classmethod
    def normalize_admission_criteria(cls, value):
        """
        Normalize admission_criteria to handle both formats:
        - Old format: {"criteria": [...]}  (from migration)
        - New format: [...]  (direct list)

        This validator runs BEFORE Pydantic tries to parse the field,
        and works with from_attributes=True when loading from ORM models.
        """
        if value is None:
            return None
        # If it's a dict with 'criteria' key, extract the list
        if isinstance(value, dict) and 'criteria' in value:
            return value['criteria']
        # Otherwise return as-is (should be a list already)
        return value


class OfferingAcademicInfoCreate(OfferingAcademicInfoBase):
    offering_id: int = Field(..., gt=0)


class OfferingAcademicInfoUpdate(BaseModel):
    academic_year: Optional[int] = Field(None, ge=2000, le=2100)
    tuition_fee_per_year: Optional[Decimal] = Field(None, ge=0)
    annual_admission_quota: Optional[int] = Field(None, ge=0)
    is_published: Optional[bool] = None
    admission_criteria: Optional[List[AdmissionCriterion]] = None
    target_audience: Optional[str] = Field(None, max_length=1000)
    cutoff_score_previous_year: Optional[Decimal] = Field(None, ge=0)


class OfferingAcademicInfo(OfferingAcademicInfoBase):
    id: int
    offering_id: int
    is_deleted: bool = Field(default=False, description="Soft delete flag")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by_user_id: Optional[int] = None
    updated_by_user_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# CẤP 2: ProgramOffering
# =============================================================================

class ProgramOfferingBase(BaseModel):
    offering_type: str = Field(..., max_length=100, description="Loại hình (e.g., 'Chính quy')")
    duration_semesters: Optional[int] = Field(None, ge=0, description="Số học kỳ")
    total_credits: Optional[int] = Field(None, ge=0, description="Tổng số tín chỉ")
    is_active: bool = Field(default=True)


class ProgramOfferingCreate(ProgramOfferingBase):
    program_id: int = Field(..., gt=0)


class ProgramOfferingUpdate(BaseModel):
    offering_type: Optional[str] = Field(None, max_length=100)
    duration_semesters: Optional[int] = Field(None, ge=0)
    total_credits: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class ProgramOffering(ProgramOfferingBase):
    id: int
    program_id: int
    # ✅ Removed academic_info_history to prevent MissingGreenlet error
    # Frontend should load academic info on-demand using dedicated endpoints
    # This avoids loading 30,000+ historical records unnecessarily
    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# CẤP 1: MajorProgram
# =============================================================================

class MajorProgramBase(BaseModel):
    name: str = Field(..., max_length=255, description="Tên ngành (e.g., 'Cao đẳng CNTT')")
    degree_level: str = Field(..., max_length=50, description="Trình độ (e.g., 'Cao đẳng')")
    code: str = Field(..., max_length=50, description="Mã ngành (e.g., '6480201')")
    unit_id: int = Field(..., gt=0)
    is_active: bool = Field(default=True)


class MajorProgramCreate(MajorProgramBase):
    pass


class MajorProgramUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    degree_level: Optional[str] = Field(None, max_length=50)
    unit_id: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None
    # 'code' (Mã ngành) không cho phép cập nhật


class MajorProgram(MajorProgramBase):
    id: int
    offerings: List[ProgramOffering] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# ORGANIZATION UNIT SCHEMAS (Cập nhật để sử dụng MajorProgram)
# =============================================================================

# Bước 1: Schema "Nông" (Shallow) không có bất kỳ quan hệ nào
class OrganizationUnitShallow(BaseModel):
    id: int
    name: str
    type: str
    parent_id: Optional[int] = None
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


# Bước 2: Create/Update schemas
class OrganizationUnitCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=200)
    type: str
    description: Optional[str] = Field(None, max_length=500)
    parent_id: Optional[int] = Field(default=None, gt=0)

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate that type is one of the allowed values"""
        if v not in OrganizationUnitType.values():
            allowed = ", ".join(OrganizationUnitType.values())
            raise ValueError(
                f"Loại đơn vị không hợp lệ. Các loại cho phép: {allowed}"
            )
        return v

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate and clean name"""
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Tên đơn vị phải có ít nhất 3 ký tự")
        return v


class OrganizationUnitUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=200)
    type: Optional[str] = None
    description: Optional[str] = Field(None, max_length=500)
    parent_id: Optional[int] = Field(default=None, gt=0)

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: Optional[str]) -> Optional[str]:
        """Validate that type is one of the allowed values"""
        if v is not None and v not in OrganizationUnitType.values():
            allowed = ", ".join(OrganizationUnitType.values())
            raise ValueError(
                f"Loại đơn vị không hợp lệ. Các loại cho phép: {allowed}"
            )
        return v

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        """Validate and clean name"""
        if v is not None:
            v = v.strip()
            if len(v) < 3:
                raise ValueError("Tên đơn vị phải có ít nhất 3 ký tự")
        return v


# Bước 3: Schema "Sâu" (Deep) để trả về cho API
class OrganizationUnit(BaseModel):
    id: int
    name: str
    type: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    is_active: bool

    # Audit trail
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    parent: Optional[OrganizationUnitShallow] = None
    children: List['OrganizationUnit'] = Field(default_factory=list)
    major_programs: List[MajorProgram] = Field(default_factory=list)  # Cập nhật từ 'majors' sang 'major_programs'

    model_config = ConfigDict(from_attributes=True)


# Required for forward reference
OrganizationUnit.model_rebuild()


# =============================================================================
# TREE WITH AGGREGATION SCHEMAS (Cập nhật cho 3-tier)
# =============================================================================

class MajorWithStats(BaseModel):
    """Major information with aggregated statistics"""
    id: int
    name: str
    code: str
    degree_level: str
    total_admission_quota: Optional[int] = Field(None, description="Total admission quota for current year")
    tuition_fee: Optional[Decimal] = Field(None, description="Tuition fee per year")

    model_config = ConfigDict(from_attributes=True)


class UnitAggregatedStats(BaseModel):
    """Aggregated statistics for a unit (including descendants)"""
    total_majors: int = Field(default=0, description="Total number of majors (direct + descendants)")
    direct_majors: int = Field(default=0, description="Number of direct majors")
    total_admission_quota: Optional[int] = Field(None, description="Total admission quota (sum of all majors)")
    avg_tuition_fee: Optional[Decimal] = Field(None, description="Average tuition fee")
    min_tuition_fee: Optional[Decimal] = Field(None, description="Minimum tuition fee")
    max_tuition_fee: Optional[Decimal] = Field(None, description="Maximum tuition fee")


class OrganizationTreeNodeWithAggregation(BaseModel):
    """Organization unit tree node with majors and aggregated data"""
    id: int
    name: str
    type: str
    description: Optional[str] = None
    parent_id: Optional[int] = None
    is_active: bool

    # Direct majors of this unit (3-tier structure)
    majors: List[MajorWithStats] = Field(default_factory=list, description="Direct majors belonging to this unit")

    # Aggregated statistics (includes descendants)
    stats: UnitAggregatedStats = Field(default_factory=UnitAggregatedStats, description="Aggregated statistics")

    # Children nodes
    children: List['OrganizationTreeNodeWithAggregation'] = Field(default_factory=list, description="Child organization units")

    model_config = ConfigDict(from_attributes=True)


# Required for forward reference
OrganizationTreeNodeWithAggregation.model_rebuild()


# =============================================================================
# BACKWARD COMPATIBILITY (Optional - for gradual migration)
# =============================================================================
# These old schemas can be removed after full migration

# Deprecated: Use MajorProgram instead
Major = MajorProgram
MajorCreate = MajorProgramCreate
MajorUpdate = MajorProgramUpdate
MajorBase = MajorProgramBase

# Deprecated: Use OfferingAcademicInfo instead
MajorAcademicInfo = OfferingAcademicInfo
MajorAcademicInfoCreate = OfferingAcademicInfoCreate
MajorAcademicInfoUpdate = OfferingAcademicInfoUpdate
MajorAcademicInfoBase = OfferingAcademicInfoBase


# =============================================================================
# SYSTEM CONFIGURATION SCHEMAS
# =============================================================================

# --- ConfigDegreeLevel (Trình độ đào tạo) ---

class ConfigDegreeLevelBase(BaseModel):
    """Base schema for degree level configuration."""
    code: str = Field(..., min_length=1, max_length=50, description="Unique code (e.g., 'cao_dang')")
    name: str = Field(..., min_length=1, max_length=100, description="Display name (e.g., 'Cao đẳng')")
    display_order: int = Field(default=0, description="Display order in dropdown (lower = higher priority)")
    is_active: bool = Field(default=True, description="Soft delete flag")


class ConfigDegreeLevelCreate(ConfigDegreeLevelBase):
    """Schema for creating a new degree level."""
    pass


class ConfigDegreeLevelUpdate(BaseModel):
    """Schema for updating a degree level."""
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class ConfigDegreeLevel(ConfigDegreeLevelBase):
    """Full schema for degree level (includes ID)."""
    id: int = Field(..., description="Primary key")

    model_config = ConfigDict(from_attributes=True)


# --- ConfigOfferingType (Loại hình đào tạo) ---

class ConfigOfferingTypeBase(BaseModel):
    """Base schema for offering type configuration."""
    code: str = Field(..., min_length=1, max_length=50, description="Unique code (e.g., 'chinh_quy')")
    name: str = Field(..., min_length=1, max_length=100, description="Display name (e.g., 'Chính quy')")
    display_order: int = Field(default=0, description="Display order in dropdown (lower = higher priority)")
    is_active: bool = Field(default=True, description="Soft delete flag")


class ConfigOfferingTypeCreate(ConfigOfferingTypeBase):
    """Schema for creating a new offering type."""
    pass


class ConfigOfferingTypeUpdate(BaseModel):
    """Schema for updating an offering type."""
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class ConfigOfferingType(ConfigOfferingTypeBase):
    """Full schema for offering type (includes ID)."""
    id: int = Field(..., description="Primary key")

    model_config = ConfigDict(from_attributes=True)


# --- ConfigDocumentType (Loại tài liệu tuyển sinh) ---

class ConfigDocumentTypeBase(BaseModel):
    """Base schema for document type configuration."""
    code: str = Field(..., min_length=1, max_length=50, description="Unique code (e.g., 'hoc_ba')")
    name: str = Field(..., min_length=1, max_length=100, description="Display name (e.g., 'Học bạ')")
    description: Optional[str] = Field(None, max_length=500, description="Detailed description")
    display_order: int = Field(default=0, description="Display order in dropdown (lower = higher priority)")
    is_active: bool = Field(default=True, description="Soft delete flag")


class ConfigDocumentTypeCreate(ConfigDocumentTypeBase):
    """Schema for creating a new document type."""
    pass


class ConfigDocumentTypeUpdate(BaseModel):
    """Schema for updating a document type."""
    code: Optional[str] = Field(None, min_length=1, max_length=50)
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class ConfigDocumentType(ConfigDocumentTypeBase):
    """Full schema for document type (includes ID)."""
    id: int = Field(..., description="Primary key")

    model_config = ConfigDict(from_attributes=True)


# --- Distribution Schemas ---
class DistributionRuleBase(BaseModel):
    offering_id: int
    unit_id: int
    weight: int = 1
    priority: int = 1
    is_active: bool = True

class DistributionRuleCreate(DistributionRuleBase):
    pass

class DistributionRuleUpdate(BaseModel):
    weight: Optional[int] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None

class DistributionRuleResponse(DistributionRuleBase):
    id: int
    # Để hiển thị tên cho đẹp
    offering_name: Optional[str] = None 
    unit_name: Optional[str] = None

    class Config:
        from_attributes = True