# app/schemas/vn_locality.py
"""Pydantic schemas for vn_commune_area_map + vn_high_school admin
CSV import (Q9 #07 PR4).

Both shape mirror the migration phase1_08b column set. Read endpoints
(searchable dropdowns) ship in PR5 candidate FE."""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class VnCommuneAreaMapRow(BaseModel):
    """Single CSV row payload for commune import (BNV format)."""
    commune_code: str = Field(min_length=1, max_length=20)
    province: str = Field(min_length=1, max_length=100)
    district: str = Field(min_length=1, max_length=100)
    ward: str = Field(min_length=1, max_length=100)
    area_code: str = Field(pattern=r"^KV[1-9](-NT)?$")


class VnCommuneAreaMapResponse(VnCommuneAreaMapRow):
    model_config = ConfigDict(from_attributes=True)

    id: int
    effective_from: date
    effective_to: Optional[date] = None


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
