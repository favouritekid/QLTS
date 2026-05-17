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


class VnHighSchoolRow(BaseModel):
    """Single CSV row payload for high school import (MOET format)."""
    name: str = Field(min_length=1, max_length=255)
    province: Optional[str] = Field(default=None, max_length=100)
    district: Optional[str] = Field(default=None, max_length=100)
    ward: Optional[str] = Field(default=None, max_length=100)
    kv_code: Optional[str] = Field(
        default=None,
        pattern=r"^KV[1-9](-NT)?$",
        description="Denormalized from vn_commune_area_map; optional if unknown",
    )


class VnHighSchoolResponse(VnHighSchoolRow):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    effective_from: date
    effective_to: Optional[date] = None


class CsvImportResponse(BaseModel):
    """Standard shape for both import endpoints."""
    inserted: int
    skipped_existing: int
    error_rows: list[dict] = Field(
        default_factory=list,
        description="Row-level validation errors {row_num, error}",
    )
