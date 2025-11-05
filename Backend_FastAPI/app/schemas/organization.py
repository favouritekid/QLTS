# app/schemas/organization.py
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    name: str
    type: str
    description: Optional[str] = None
    parent_id: Optional[int] = Field(default=None, gt=0)


class OrganizationUnitUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[int] = Field(default=None, gt=0)


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
