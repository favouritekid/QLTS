# app/schemas/path_subject_group.py
"""Pydantic schemas cho PathSubjectGroupConfig + Item (Phase 2 v8.2 PR-2D)."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    is_principal: Optional[bool] = None
    min_subject_score: Optional[Decimal] = Field(default=None, ge=0)


class PathSubjectGroupItemResponse(PathSubjectGroupItemBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    path_subject_group_config_id: int
    created_at: datetime
    updated_at: datetime


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


class PathSubjectGroupConfigListResponse(BaseModel):
    total: int
    items: List[PathSubjectGroupConfigResponse]


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
