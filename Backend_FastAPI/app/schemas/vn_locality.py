# app/schemas/vn_locality.py
"""Pydantic schemas for vn_commune_area_map + vn_high_school admin
CSV import (Q9 #07 PR4).

Both shape mirror the migration phase1_08b column set. Read endpoints
(searchable dropdowns) ship in PR5 candidate FE."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class VnCommuneAreaMapRow(BaseModel):
    """Single CSV row payload for commune import (BNV format)."""
    commune_code: str = Field(min_length=1, max_length=20)
    province: str = Field(min_length=1, max_length=100)
    # district allows empty: the post-2025 2-tier model (Tỉnh → Xã) drops the
    # district level, so current-era commune rows carry district="". The DB
    # column is NOT NULL but accepts ''. (Legacy 3-tier rows still populate it.)
    district: str = Field(default="", max_length=100)
    ward: str = Field(min_length=1, max_length=100)
    area_code: str = Field(pattern=r"^KV[1-9](-NT)?$")


class VnCommuneAreaMapResponse(VnCommuneAreaMapRow):
    model_config = ConfigDict(from_attributes=True)

    id: int
    effective_from: date
    effective_to: Optional[date] = None


# =============================================================================
# Admin CRUD (PR-A — UI quản lý commune KV). Temporal half-open: đổi KV đi qua
# /replace-area (retire dòng cũ + insert dòng mới), KHÔNG update area_code tại chỗ.
# =============================================================================


class VnCommuneAreaMapCreate(VnCommuneAreaMapRow):
    """Tạo dòng KV mới. Kế thừa field CSV row + cho override effective_from."""

    effective_from: Optional[date] = None


class VnCommuneAreaMapUpdate(BaseModel):
    """PATCH metadata — KHÔNG nhận ``area_code``/``commune_code`` (đổi KV =
    /replace-area để giữ lịch sử temporal). ``effective_to=null`` tường minh =
    re-activate (service chặn nếu tạo 2 dòng active cùng ``commune_code``)."""

    province: Optional[str] = Field(default=None, min_length=1, max_length=100)
    district: Optional[str] = Field(default=None, max_length=100)
    ward: Optional[str] = Field(default=None, min_length=1, max_length=100)
    effective_to: Optional[date] = None


class VnCommuneAreaMapReplaceArea(BaseModel):
    """Đổi KV theo kiểu temporal: retire dòng active cũ (``effective_to`` =
    ``effective_from`` mới) + insert dòng active mới cùng
    ``commune_code/province/district/ward`` với ``area_code`` mới."""

    area_code: str = Field(pattern=r"^KV[1-9](-NT)?$")
    effective_from: Optional[date] = None


class VnCommuneAreaMapListResponse(BaseModel):
    """Paginated list cho bảng admin (commune ~nghìn dòng)."""

    items: list[VnCommuneAreaMapResponse]
    total: int
    page: int
    page_size: int


# VnHighSchoolRow + VnHighSchoolResponse DROPPED phase1_09 (Q9 #07 PR5 v1.3).
# Replaced by VnSchool family schemas (TBD in Phase B.1 import script
# + Phase D candidate FE). See Documents/Q9_07_PR5_REDESIGN.md v1.3.


class CsvImportResponse(BaseModel):
    """Standard shape for both import endpoints."""
    inserted: int
    skipped_existing: int
    error_rows: list[dict] = Field(
        default_factory=list,
        description="Row-level validation errors {row_num, error}",
    )


# =============================================================================
# Phase D.0b — VnSchool search (candidate FE dropdown)
# =============================================================================


class VnSchoolSearchItem(BaseModel):
    """Single search result item — minimal fields for FE dropdown."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    moet_school_code: str
    moet_province_code: str
    name: str
    address: Optional[str] = None
    province: str
    district: Optional[str] = None
    level: str
    is_dtnt: bool
    current_kv: Optional[str] = Field(
        default=None,
        description="Latest active KV (effective_to_year IS NULL). NULL if no active assignment.",
    )


class VnSchoolSearchResponse(BaseModel):
    """Paginated search response."""
    items: list[VnSchoolSearchItem]
    total: int
    limit: int
    offset: int


# =============================================================================
# Admin CRUD trường học (PR-B). Co-locate ở đây (cùng file VnSchoolSearchItem).
# DELETE school = deactivate (is_active=false), KHÔNG hard-delete (FK
# vn_school_kv_assignment.school_id CASCADE). merged_into_id/merge_effective_date
# read-only (để script merger lo) — KHÔNG trong CRUD.
# =============================================================================

VnSchoolLevel = Literal["THCS", "THPT", "THCS_THPT", "TRUNG_HOC_NGHE", "OTHER"]
_KV_CODE_PATTERN = r"^KV[1-9](-NT)?$"


class VnSchoolCreate(BaseModel):
    moet_school_code: str = Field(min_length=1, max_length=10)
    moet_province_code: str = Field(min_length=1, max_length=3)
    moet_district_code: Optional[str] = Field(default=None, max_length=5)
    name: str = Field(min_length=1, max_length=255)
    address: Optional[str] = None
    province: str = Field(min_length=1, max_length=100)
    district: Optional[str] = Field(default=None, max_length=100)
    ward: Optional[str] = Field(default=None, max_length=100)
    level: VnSchoolLevel
    is_dtnt: bool = False


class VnSchoolUpdate(BaseModel):
    """PATCH — KHÔNG đổi moet_school_code/moet_province_code (định danh MOET) và
    KHÔNG đổi is_active (dùng DELETE=deactivate)."""

    moet_district_code: Optional[str] = Field(default=None, max_length=5)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    address: Optional[str] = None
    province: Optional[str] = Field(default=None, min_length=1, max_length=100)
    district: Optional[str] = Field(default=None, max_length=100)
    ward: Optional[str] = Field(default=None, max_length=100)
    level: Optional[VnSchoolLevel] = None
    is_dtnt: Optional[bool] = None


class VnSchoolAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    moet_school_code: str
    moet_province_code: str
    moet_district_code: Optional[str] = None
    name: str
    address: Optional[str] = None
    province: str
    district: Optional[str] = None
    ward: Optional[str] = None
    level: str
    is_dtnt: bool
    is_active: bool
    current_kv: Optional[str] = None


class VnSchoolListResponse(BaseModel):
    items: list[VnSchoolAdminResponse]
    total: int
    page: int
    page_size: int


class VnSchoolProvinceItem(BaseModel):
    """Distinct {moet_province_code, province} từ vn_school active — cho FE filter
    (administrative getProvinces KHÔNG có moet_province_code)."""

    moet_province_code: str
    province: str


# --- KV assignment (vn_school_kv_assignment) ---


class VnSchoolKvAssignmentCreate(BaseModel):
    kv_code: str = Field(pattern=_KV_CODE_PATTERN)
    effective_from_year: int = Field(ge=2000, le=2100)
    effective_to_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    source: str = Field(default="manual_admin", min_length=1, max_length=50)
    notes: Optional[str] = None


class VnSchoolKvAssignmentUpdate(BaseModel):
    kv_code: Optional[str] = Field(default=None, pattern=_KV_CODE_PATTERN)
    effective_from_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    effective_to_year: Optional[int] = Field(default=None, ge=2000, le=2100)
    source: Optional[str] = Field(default=None, min_length=1, max_length=50)
    notes: Optional[str] = None


class VnSchoolKvAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    school_id: int
    kv_code: str
    effective_from_year: int
    effective_to_year: Optional[int] = None
    source: str
    notes: Optional[str] = None
