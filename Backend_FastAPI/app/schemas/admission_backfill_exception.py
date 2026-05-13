# app/schemas/admission_backfill_exception.py
"""Pydantic schemas cho admin backfill exception queue (Phase 3 PR-3D-B BE-2).

Q-P3-09: admin reviews unresolved auto-mapping exceptions left by Phase 1
backfill scripts. Each row carries (profile_id, exception_type, details JSONB)
plus resolution audit (resolved_at / by / notes).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class AdmissionBackfillExceptionResponse(BaseModel):
    """GET response shape for a single backfill exception."""

    id: int
    profile_id: int
    exception_type: str
    details: dict[str, Any]
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by_user_id: Optional[int] = None
    resolved_by_username: Optional[str] = Field(
        None,
        description="Denormalized username for queue UI; populated from "
        "selectinload-ed resolved_by relation.",
    )
    resolution_notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class BackfillExceptionListResponse(BaseModel):
    """Paginated list payload."""

    items: list[AdmissionBackfillExceptionResponse]
    total: int = Field(..., description="Total matching rows (pre-pagination)")
    limit: int
    offset: int


class BackfillExceptionResolveRequest(BaseModel):
    """PATCH /api/v2/admin/admission-backfill-exceptions/{id}/resolve."""

    resolution_notes: str = Field(..., min_length=5, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class BackfillExceptionBulkResolveRequest(BaseModel):
    """POST /api/v2/admin/admission-backfill-exceptions/bulk-resolve."""

    exception_ids: list[int] = Field(..., min_length=1, max_length=500)
    resolution_notes: str = Field(..., min_length=5, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class BackfillBulkResolveResponse(BaseModel):
    """Counters returned after a bulk resolve operation."""

    requested: int
    resolved: int
    skipped_already_resolved: int
    missing: int
    missing_ids: list[int] = Field(default_factory=list)
