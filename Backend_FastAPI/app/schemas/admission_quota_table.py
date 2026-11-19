# app/schemas/admission_quota_table.py
"""GĐ2-A — API bảng chỉ tiêu năm / nhóm ngành (đặc tả GĐ2 bản 3 §11: ``/api/admission-config/quota-tables/{năm}``).

Tên trường tiếng Anh (owner 17-11: API mới GĐ1b+ tiếng Anh). Không trường nào mang dữ liệu cá nhân. Giới hạn độ dài / số
phần tử là giới hạn KỸ THUẬT chống thân request phình (không phải con số nghiệp vụ): số chỉ tiêu / trần do Admin nhập.
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuotaGroupMemberIn(BaseModel):
    """Một ngành (học vụ = ngành + năm) thuộc nhóm, kèm chỉ tiêu năm của ngành (ghi vào cột có sẵn
    ``offering_academic_info.annual_admission_quota``)."""

    offering_academic_info_id: int = Field(..., ge=1)
    annual_admission_quota: int = Field(..., ge=0)

    model_config = ConfigDict(extra="forbid")


class QuotaGroupIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=255)
    ceiling: int = Field(..., ge=0, description="Trần chỉ tiêu năm của nhóm (số người tối đa) — số nhà trường giao")
    members: List[QuotaGroupMemberIn] = Field(default_factory=list, max_length=500)

    model_config = ConfigDict(extra="forbid")

    @field_validator("code", "name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("không được để trống")
        return v


class QuotaTablePut(BaseModel):
    """Thay TOÀN BỘ nội dung bảng chỉ tiêu của năm (nhóm, trần, thành viên, chỉ tiêu ngành của thành viên).

    ``version`` = phiên bản bảng đang xem; ``0`` = năm chưa có bảng (tạo mới). Lệch ⇒ 409, không ghi gì."""

    version: int = Field(..., ge=0)
    groups: List[QuotaGroupIn] = Field(..., max_length=200)

    model_config = ConfigDict(extra="forbid")


class QuotaTableLockIn(BaseModel):
    version: int = Field(..., ge=1)

    model_config = ConfigDict(extra="forbid")


class QuotaTableUnlockIn(BaseModel):
    version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=1, max_length=1000, description="Lý do mở khoá — bắt buộc, lưu vết")

    model_config = ConfigDict(extra="forbid")

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("lý do mở khoá không được để trống")
        return v


class GroupUsageOut(BaseModel):
    """Số chỗ đã dùng của nhóm — SỐ THAM KHẢO (ca biên B14): quyết định cuối là phép đếm lúc khoá lần xét."""

    publish_count: int
    approved_count: int
    used: int


class QuotaGroupMemberOut(BaseModel):
    offering_academic_info_id: int
    offering_id: int
    major_code: Optional[str] = None
    major_name: Optional[str] = None
    offering_type: Optional[str] = None
    annual_admission_quota: Optional[int] = None


class QuotaGroupOut(BaseModel):
    id: int
    code: str
    name: str
    ceiling: int
    usage: GroupUsageOut
    members: List[QuotaGroupMemberOut]


class QuotaTableOut(BaseModel):
    academic_year: int
    status: str
    version: int
    locked_by_user_id: Optional[int] = None
    locked_at: Optional[datetime] = None
    #: GĐ2-F1 — thao tác người xem làm được trên bảng (``edit`` / ``lock`` / ``unlock``): CÙNG hàm với cổng ghi
    #: (``admission_quota_table_service.quota_table_actions``). Giao diện hiện nút theo cờ này, không theo ``status``.
    available_actions: List[Literal["edit", "lock", "unlock"]]
    groups: List[QuotaGroupOut]
