# app/schemas/priority_config.py
"""Pydantic schemas for priority_area_config + priority_object_config
admin CRUD (Q9 #07 PR3).

Mirrors the migration phase1_08b column set + the CHECK regex
constraints (validated at Pydantic boundary so admin gets a 422 with
a helpful message instead of a 500 from PG)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# PriorityAreaConfig — KV rates per academic_year
# ---------------------------------------------------------------------------


class PriorityAreaConfigBase(BaseModel):
    academic_year: int = Field(ge=2020, le=2100)
    area_code: str = Field(
        pattern=r"^KV[1-9](-NT)?$",
        description="Canonical: KV1 / KV2-NT / KV2 / KV3 (hyphen)",
    )
    area_name: str = Field(min_length=1, max_length=100)
    bonus_points: Decimal = Field(ge=0, le=99.99, decimal_places=2)
    description: Optional[str] = None
    effective_from: Optional[date] = Field(
        default=None,
        description="Defaults to CURRENT_DATE if omitted",
    )
    effective_to: Optional[date] = None


class PriorityAreaConfigCreate(PriorityAreaConfigBase):
    pass


class PriorityAreaConfigUpdate(BaseModel):
    """PATCH — all fields optional; service applies via model_dump(exclude_unset)."""
    area_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    bonus_points: Optional[Decimal] = Field(
        default=None, ge=0, le=99.99, decimal_places=2
    )
    description: Optional[str] = None
    effective_to: Optional[date] = None


class PriorityAreaConfigResponse(PriorityAreaConfigBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# PriorityObjectConfig — UT rates per academic_year + sub_code
# ---------------------------------------------------------------------------


class PriorityObjectConfigBase(BaseModel):
    academic_year: int = Field(ge=2020, le=2100)
    group_code: str = Field(
        pattern=r"^UT[1-9]$",
        description="Canonical: UT1 / UT2 (extensible UT3+ if Bộ thêm)",
    )
    sub_code: str = Field(
        pattern=r"^[0-9]{2}$",
        description="2-digit numeric per TT 05/2021 Phụ lục 01: '01'..'07'",
    )
    description: str = Field(min_length=1)
    bonus_points: Decimal = Field(ge=0, le=99.99, decimal_places=2)
    evidence_doc_type: Optional[str] = Field(default=None, max_length=100)
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None


class PriorityObjectConfigCreate(PriorityObjectConfigBase):
    pass


class PriorityObjectConfigUpdate(BaseModel):
    description: Optional[str] = Field(default=None, min_length=1)
    bonus_points: Optional[Decimal] = Field(
        default=None, ge=0, le=99.99, decimal_places=2
    )
    evidence_doc_type: Optional[str] = Field(default=None, max_length=100)
    effective_to: Optional[date] = None


class PriorityObjectConfigResponse(PriorityObjectConfigBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Clone-from-year + seed-defaults requests
# ---------------------------------------------------------------------------


class PriorityConfigCloneRequest(BaseModel):
    from_year: int = Field(ge=2020, le=2100)
    to_year: int = Field(ge=2020, le=2100)


class PriorityConfigCloneResponse(BaseModel):
    cloned_areas: int
    cloned_objects: int


class PriorityConfigSeedDefaultsRequest(BaseModel):
    """One-shot helper for admin to populate TT 05/2021 baseline rates
    for a target year. Skips if any row already exists for the year
    (idempotent — admin must explicitly delete + re-seed to override).
    """
    academic_year: int = Field(ge=2020, le=2100)


class PriorityConfigSeedDefaultsResponse(BaseModel):
    inserted_areas: int
    inserted_objects: int
    skipped_existing: bool
