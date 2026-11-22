# app/schemas/thcs_school_mapping.py
"""Schema công cụ ghép tên trường THCS gõ tay (đề xuất danh mục THCS Phần B, owner 22-11).

KHÔNG có dữ liệu cá nhân thí sinh: nhóm chỉ mang tên trường (các cách viết gốc) và số đếm.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.vn_locality import VnSchoolAdminResponse, VnSchoolCreate


class ThcsNameVariant(BaseModel):
    text: str
    row_count: int


class ThcsGroupMapping(BaseModel):
    school_id: int
    school_name: str
    moet_school_code: str
    school_level: str
    school_is_active: bool
    usable: bool = Field(description="Trường còn hoạt động + đúng cấp THCS / liên cấp ⇒ lượt áp ghép dùng được")
    mapped_by_user_id: int
    mapped_at: datetime


class ThcsNameGroup(BaseModel):
    normalized_name: str
    variants: list[ThcsNameVariant]
    row_count: int = Field(description="Số dòng THCS gõ tay (hồ sơ chưa rút)")
    profile_count: int = Field(description="Số hồ sơ chưa rút có dòng thuộc nhóm")
    eligible_profile_count: int = Field(
        description="Số hồ sơ thuộc phạm vi lượt áp ghép (nháp + chờ xét, năm 2026; chưa xét Quyết định)"
    )
    same_year_row_count: int = Field(description="Số dòng năm bắt đầu = năm kết thúc (y→y)")
    mapping: Optional[ThcsGroupMapping] = None


class ThcsNameGroupSummary(BaseModel):
    group_count: int
    mapped_group_count: int
    row_count: int
    profile_count: int
    blank_name_row_count: int


class ThcsNameGroupListResponse(BaseModel):
    items: list[ThcsNameGroup]
    total: int
    page: int
    page_size: int
    summary: ThcsNameGroupSummary


class ThcsMapRequest(BaseModel):
    normalized_name: str = Field(min_length=1, max_length=255)
    school_id: int = Field(gt=0)


class ThcsUnmapRequest(BaseModel):
    normalized_name: str = Field(min_length=1, max_length=255)


class ThcsMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    normalized_name: str
    school_id: int
    mapped_by_user_id: int
    mapped_at: datetime


class ThcsCreateSchoolFromGroupRequest(BaseModel):
    """Tạo trường MỚI (luôn mã nội bộ NB — để trống ``moet_school_code``) rồi ghép nhóm với trường ấy, MỘT giao
    dịch. Luật mã / mã xã: ``VnSchoolService.create_school`` (đúng luật Commit 1)."""

    normalized_name: str = Field(min_length=1, max_length=255)
    school: VnSchoolCreate


class ThcsCreateSchoolFromGroupResponse(BaseModel):
    school: VnSchoolAdminResponse
    mapping: ThcsMappingResponse


class ThcsMappingApplyRequest(BaseModel):
    """``dry_run`` MẶC ĐỊNH ``True``. Chế độ thật: cần cờ ``THCS_MAPPING_APPLY_ENABLED`` (409 nếu tắt) VÀ hai số của
    lượt chạy thử ngay trước (lệch ⇒ 409, không ghi gì)."""

    dry_run: bool = True
    expected_rows_to_change: Optional[int] = Field(default=None, ge=0)
    expected_profiles_to_change: Optional[int] = Field(default=None, ge=0)


class ThcsMappingApplyResult(BaseModel):
    dry_run: bool
    applied: bool
    apply_enabled: bool = Field(description="Cờ cho phép chạy thật (giao diện ẩn / khoá nút áp thật khi False)")
    eligible_statuses: list[str]
    academic_year: int = Field(description="Năm tuyển sinh lượt áp ghép được chạm (owner câu 2)")
    rows_to_change: int
    profiles_to_change: int
    draft_rows_to_change: int = Field(description="Trong số dòng sẽ đổi: dòng ở hồ sơ NHÁP")
    draft_profiles_to_change: int = Field(
        description="Trong số hồ sơ sẽ đổi: hồ sơ NHÁP — cán bộ đang mở form sẽ gặp xung đột phiên bản khi lưu"
    )
    same_year_rows: int = Field(description="Trong số dòng sẽ đổi: dòng y→y (năm bắt đầu = năm kết thúc)")
    same_year_profiles: int
    manual_kv_override_profiles: int = Field(
        description="Hồ sơ sẽ đổi đang ở chế độ KV ấn định tay — đổi lịch sử học làm ấn định ấy hết hiệu lực"
    )
    skipped_status_profiles: int
    skipped_status_rows: int
    skipped_year_profiles: int = Field(description="Hồ sơ đúng trạng thái nhưng khác năm tuyển sinh — không chạm")
    skipped_year_rows: int
    skipped_decision_profiles: int = Field(description="Hồ sơ gắn Quyết định / dấu AppSheet — không chạm")
    unmapped_rows: int = Field(description="Dòng THCS gõ tay ở hồ sơ đủ điều kiện mà nhóm chưa ghép (dùng được)")
    unusable_mappings: int = Field(description="Dòng ghép trỏ tới trường đã ngừng / sai cấp — bỏ qua")
