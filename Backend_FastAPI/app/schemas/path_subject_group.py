# app/schemas/path_subject_group.py
"""Pydantic schemas cho PathSubjectGroupConfig + Item (Phase 2 v8.2 PR-2D)."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class PathSubjectGroupItemBase(BaseModel):
    subject_group_subject_id: int = Field(..., description="FK to subject_group_subject")
    is_principal: bool = Field(default=False, description="Môn chính cho weighted scoring")
    min_subject_score: Optional[Decimal] = Field(
        default=None, ge=0,
        description="Per-item override; NULL = inherit từ config",
    )


class PathSubjectGroupItemCreate(PathSubjectGroupItemBase):
    pass


class PathSubjectGroupItemUpdate(BaseModel):
    # ``bool`` (NOT ``Optional[bool]``): omit the field to leave is_principal
    # unchanged (default applies, then ``model_dump(exclude_unset=True)`` drops
    # it); an EXPLICIT null is rejected as 422 by the type itself. Using ``bool``
    # also keeps the OpenAPI / generated-client contract honest (``boolean``, not
    # ``boolean | null``) — a runtime-only validator on Optional[bool] would
    # still advertise the field as nullable.
    is_principal: bool = False
    min_subject_score: Optional[Decimal] = Field(default=None, ge=0)


class PathSubjectGroupItemResponse(PathSubjectGroupItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    path_subject_group_config_id: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("min_subject_score", when_used="json")
    def _ser_min_subject_score(self, v: Optional[Decimal]) -> Optional[float]:
        # Pydantic v2 serializes Decimal→string by default; FE parses score as
        # z.number(). Emit JSON number (mirror application_fee serializer).
        return float(v) if v is not None else None


class PathSubjectGroupConfigBase(BaseModel):
    subject_group_id: int = Field(..., description="FK to subject_group")
    min_score: Optional[Decimal] = Field(default=None, ge=0)
    min_subject_score: Optional[Decimal] = Field(default=None, ge=0)
    group_quota: Optional[int] = Field(
        default=None, ge=0,
        description="Tier 3 quota: ∑(group_quota in path) ≤ path.admit_quota",
    )


class PathSubjectGroupConfigCreate(PathSubjectGroupConfigBase):
    """Create config — items optional inline."""
    items: List[PathSubjectGroupItemCreate] = Field(default_factory=list)


class PathSubjectGroupConfigUpdate(BaseModel):
    """Partial update — score thresholds + quota."""
    min_score: Optional[Decimal] = Field(default=None, ge=0)
    min_subject_score: Optional[Decimal] = Field(default=None, ge=0)
    group_quota: Optional[int] = Field(default=None, ge=0)


class PathSubjectGroupConfigResponse(PathSubjectGroupConfigBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    admission_path_id: int
    items: List[PathSubjectGroupItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_serializer("min_score", "min_subject_score", when_used="json")
    def _ser_scores(self, v: Optional[Decimal]) -> Optional[float]:
        # Decimal→JSON number for FE z.number() (see item serializer note).
        return float(v) if v is not None else None


class PathSubjectGroupConfigListResponse(BaseModel):
    total: int
    items: List[PathSubjectGroupConfigResponse]


# ============================================================
# Admin enriched read schema (#7 — subject-group config tab)
# ============================================================
# The admin GET hand-builds these (see admin_v2_path_subject_group.list_configs)
# with float() scores, so they declare score fields as float — NOT Decimal —
# and carry subject_group label + per-subject detail the AddChoiceDialog-style
# UI needs. The base list response (above) only has bare config+items and would
# strip these enriched fields under response_model.


class PathSubjectGroupConfigSubjectAdmin(BaseModel):
    """One subject of the config's subject_group (for principal-item UI)."""
    subject_id: int
    subject_code: str
    subject_name: str
    subject_group_subject_id: int  # = SubjectGroupSubject.id (item target)
    max_score: float
    min_possible_score: float
    position: int = 0


class PathSubjectGroupConfigAdminResponse(PathSubjectGroupConfigResponse):
    # Override score fields → float (admin GET builds them via float()).
    min_score: Optional[float] = None
    min_subject_score: Optional[float] = None
    subject_group_code: Optional[str] = None
    subject_group_name: Optional[str] = None
    subjects: List[PathSubjectGroupConfigSubjectAdmin] = Field(default_factory=list)


class PathSubjectGroupConfigAdminListResponse(BaseModel):
    total: int
    items: List[PathSubjectGroupConfigAdminResponse]


# ============================================================
# Clone endpoint (Q6 v8.2 deep-copy)
# ============================================================


class ClonePathsRequest(BaseModel):
    """Payload for POST /api/v2/admin/rounds/{target_round_id}/clone-paths-from/{source_round_id}."""

    academic_info_ids: Optional[List[int]] = Field(
        default=None,
        description="Optional filter — clone chỉ paths thuộc các academic_info này. NULL = clone all.",
    )
    criteria_code_template: Optional[str] = Field(
        default=None,
        max_length=255,
        description=(
            "Template cho cloned criteria.code, e.g., '{source_code}_{round_code}'. "
            "NULL = auto '{source_code}_R{target_round_id}' fallback."
        ),
    )


class ClonePathsResponseItem(BaseModel):
    source_path_id: int
    cloned_path_id: int
    source_criteria_code: str
    cloned_criteria_code: str


class ClonePathsResponse(BaseModel):
    """Audit-friendly response cho deep-copy clone."""

    source_round_id: int
    target_round_id: int
    cloned_count: int
    skipped_count: int = Field(
        ..., description="Paths skipped (already exist trong target round)",
    )
    items: List[ClonePathsResponseItem]
