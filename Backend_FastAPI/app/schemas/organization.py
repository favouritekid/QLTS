# app/schemas/organization.py
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --- Enum cho các loại đơn vị (có thể mở rộng) ---
class OrganizationUnitType(str, Enum):
    """
    Các loại đơn vị tổ chức.

    Để thêm loại mới: thêm vào enum này và update frontend UnitDialog.tsx
    """
    PHONG_BAN = "Phòng ban"
    TRUNG_TAM = "Trung tâm"
    KHOA = "Khoa"
    TO = "Tổ"
    BO_MON = "Bộ môn"

    @classmethod
    def values(cls) -> List[str]:
        """Trả về danh sách các giá trị hợp lệ"""
        return [item.value for item in cls]


# --- Schemas cho Major (Không đổi) ---
class MajorBase(BaseModel):
    name: str
    code: str
    unit_id: int


class MajorCreate(MajorBase):
    pass


class MajorUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    unit_id: Optional[int] = None


class Major(MajorBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


# --- TÁI CẤU TRÚC HOÀN TOÀN SCHEMAS CHO ORGANIZATIONUNIT ---


# Bước 1: Tạo một schema "Nông" (Shallow) không có bất kỳ quan hệ nào.
# Schema này sẽ được sử dụng bên trong các quan hệ lồng nhau để phá vỡ vòng lặp.
class OrganizationUnitShallow(BaseModel):
    id: int
    name: str
    type: str
    parent_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


# Bước 2: Tạo schema Create/Update không cần quan hệ lồng nhau.
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


# Bước 3: Tạo schema "Sâu" (Deep) để trả về cho API.
# Schema này sẽ sử dụng schema "Nông" cho các thuộc tính đệ quy.
class OrganizationUnit(BaseModel):
    id: int
    name: str
    type: str
    description: Optional[str] = None
    parent_id: Optional[int] = None

    # === ĐÂY LÀ PHẦN SỬA LỖI QUAN TRỌNG NHẤT ===
    parent: Optional[OrganizationUnitShallow] = None
    children: List[OrganizationUnitShallow] = []
    # === KẾT THÚC SỬA LỖI ===

    majors: List[Major] = []

    model_config = ConfigDict(from_attributes=True)
