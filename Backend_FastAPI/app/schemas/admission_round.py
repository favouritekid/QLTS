# app/schemas/admission_round.py
"""Pydantic schemas for OfferingAdmissionRound (Phase 2 v8.2 PR-2A v2).

Year-level round entity. Quota fields (round_quota, admit_quota,
submission_count) ship trên admission_path (PR-2B v2), KHÔNG trên đây.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AdmissionRoundBase(BaseModel):
    """Common fields for create/update payloads."""

    round_code: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Pure string (Q8 v8.2): DOT_1 / DOT_2 / DOT_3 / BO_SUNG / DOT_1_VLVH",
    )
    round_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description='Localized display: "Đợt 1 - 2026"',
    )
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: bool = True


class AdmissionRoundCreate(AdmissionRoundBase):
    """Payload for POST /api/v2/admin/years/{academic_year}/rounds."""

    pass


class AdmissionRoundUpdate(BaseModel):
    """Partial update payload — all fields optional. Time-window/lifecycle
    only Phase 2 (Q3 v8.2 — notification template defer Phase 3)."""

    round_name: Optional[str] = Field(None, min_length=1, max_length=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None


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


class AdmissionRoundBulkCreateItem(BaseModel):
    """Individual round in bulk-create payload."""

    round_code: str = Field(..., min_length=1, max_length=20)
    round_name: str = Field(..., min_length=1, max_length=100)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: bool = True


class AdmissionRoundBulkCreate(BaseModel):
    """Payload for POST /api/v2/admin/years/{academic_year}/rounds/bulk-create.

    Idempotent transaction: skip duplicates by (academic_year, round_code),
    create new rounds atomically. Re-runnable safely. Per-item duplicate
    check + skip + continue; non-duplicate errors abort entire txn (router
    db.commit() không chạy → rollback) — atomic-on-error, partial-success-
    on-duplicate semantic (P2-3 v8.2 wording fix).
    """

    rounds: List[AdmissionRoundBulkCreateItem] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="List rounds to create atomically (e.g., 4 đợt năm 2026)",
    )


class AdmissionRoundResponse(BaseModel):
    """Full round detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    academic_year: int
    round_code: str
    round_name: str
    start_date: Optional[date]
    end_date: Optional[date]
    is_active: bool
    archived_at: Optional[datetime]

    # SPEC §2.1.a Rule 2 audit fields
    extended_at: Optional[datetime]
    extended_by_user_id: Optional[int]
    extension_reason: Optional[str]

    created_at: datetime
    updated_at: datetime


class AdmissionRoundListResponse(BaseModel):
    """List wrapper for GET /years/{academic_year}/rounds."""

    total: int
    items: List[AdmissionRoundResponse]


class AdmissionRoundBulkCreateResponse(BaseModel):
    """Bulk-create result summary."""

    requested: int
    created: int
    skipped_duplicates: int
    items: List[AdmissionRoundResponse]
