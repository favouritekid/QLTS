# app/schemas/admission_round.py
"""Pydantic schemas for OfferingAdmissionRound (Phase 2 PR-2A)."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AdmissionRoundBase(BaseModel):
    """Common fields for create/update payloads."""

    round_code: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="UNIQUE per academic_info: DOT_1 / DOT_2 / BO_SUNG",
    )
    round_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description='Localized display: "Đợt 1 - 2026"',
    )
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    round_quota: Optional[int] = Field(
        None,
        ge=0,
        description="Submission slot cap. NULL = no cap",
    )
    admit_quota: Optional[int] = Field(
        None,
        ge=0,
        description="Admit slot cap. NULL = inherit round_quota",
    )
    is_active: bool = True


class AdmissionRoundCreate(AdmissionRoundBase):
    """Payload for POST /api/v2/admin/academic-info/{id}/rounds."""

    pass


class AdmissionRoundUpdate(BaseModel):
    """Partial update payload — all fields optional."""

    round_name: Optional[str] = Field(None, min_length=1, max_length=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    round_quota: Optional[int] = Field(None, ge=0)
    admit_quota: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None
    # v2.12 P1 fix #4 — admin override quota decrease past submission_count
    override: bool = Field(
        False,
        description="When True, allow round_quota decrease below submission_count "
                    "(audit log captures override + admin user_id).",
    )


class AdmissionRoundExtend(BaseModel):
    """Payload for POST /api/v2/admin/rounds/{id}/extend (SPEC §2.1.a Rule 2)."""

    end_date: date = Field(..., description="New end_date — must be later than current")
    extension_reason: str = Field(
        ...,
        min_length=10,
        description="Reason ≥10 chars mandatory per SPEC §2.1.a",
    )

    @field_validator("extension_reason")
    @classmethod
    def _strip_reason(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("extension_reason must be ≥10 chars after trimming")
        return v


class AdmissionRoundResponse(BaseModel):
    """Full round detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    academic_info_id: int
    round_code: str
    round_name: str
    start_date: Optional[date]
    end_date: Optional[date]
    round_quota: Optional[int]
    admit_quota: Optional[int]
    submission_count: int
    is_active: bool
    archived_at: Optional[datetime]

    # SPEC §2.1.a Rule 2 audit fields
    extended_at: Optional[datetime]
    extended_by_user_id: Optional[int]
    extension_reason: Optional[str]

    created_at: datetime
    updated_at: datetime


class AdmissionRoundListResponse(BaseModel):
    """List wrapper for GET /academic-info/{id}/rounds."""

    total: int
    items: List[AdmissionRoundResponse]
