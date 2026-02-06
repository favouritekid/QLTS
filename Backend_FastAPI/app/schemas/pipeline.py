# app/schemas/pipeline.py
from datetime import datetime
from typing import List, Optional

# ✅ 1. Thêm import ConfigDict
from pydantic import BaseModel, ConfigDict, Field

from ..models.pipeline import OutcomeTypeEnum, StatusTypeEnum, SelectableModeEnum


# =====================================================================
# PIPELINE STAGE SCHEMAS
# =====================================================================


class PipelineStageBase(BaseModel):
    """Base schema for PipelineStage (common fields)."""
    name: str = Field(..., min_length=3, max_length=255, description="Stage display name")
    order: int = Field(..., ge=0, description="Position in pipeline (0-based)")
    is_final_stage: bool = Field(
        default=False,
        description="Whether this is a final stage (Won/Lost/Closed)"
    )
    color_code: str = Field(
        default="#6B7280",
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Hex color code for UI (e.g., #3B82F6)"
    )
    # ✅ 2. Thêm config để ép Pydantic dùng value của Enum
    model_config = ConfigDict(use_enum_values=True, from_attributes=True)


class PipelineStageCreate(PipelineStageBase):
    """Schema for creating a new pipeline stage."""
    id: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-z0-9_]+$",
        description="Unique stage identifier (lowercase, numbers, underscores only)"
    )


class PipelineStageUpdate(BaseModel):
    """Schema for updating an existing pipeline stage."""
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    order: Optional[int] = Field(None, ge=0)
    is_final_stage: Optional[bool] = None
    color_code: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")

    model_config = ConfigDict(use_enum_values=True)


class PipelineStage(PipelineStageBase):
    """Schema for returning a pipeline stage (with ID)."""
    id: str

    # Optional computed fields (for analytics)
    lead_count: Optional[int] = Field(
        None,
        description="Number of leads in this stage (computed)"
    )
    conversion_rate: Optional[float] = Field(
        None,
        description="Conversion rate from this stage (computed)"
    )

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# =====================================================================
# CONSULTATION STATUS SCHEMAS
# =====================================================================


class ConsultationStatusBase(BaseModel):
    """Base schema for ConsultationStatus (common fields)."""
    name: str = Field(..., min_length=3, max_length=255, description="Status display name")
    color_code: str = Field(
        ...,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="Hex color code for UI (e.g., #FF5733)"
    )
    # ✅ FSM v3.0: stage_id is nullable for universal statuses
    stage_id: Optional[str] = Field(None, description="Parent pipeline stage ID (NULL for universal)")
    outcome_type: OutcomeTypeEnum = Field(
        default=OutcomeTypeEnum.neutral,
        description="Outcome classification: positive/neutral/negative"
    )

    # ✅ FSM v3.0: New fields
    code: Optional[str] = Field(None, description="Machine-readable code (e.g., NOT_CONTACTED)")
    is_final: bool = Field(default=False, description="Whether this status marks end of lead lifecycle")
    status_type: StatusTypeEnum = Field(
        default=StatusTypeEnum.transition,
        description="Status type: transition/activity/system"
    )
    selectable_mode: SelectableModeEnum = Field(
        default=SelectableModeEnum.user,
        description="Who can select: user/role/system"
    )
    is_universal: bool = Field(
        default=False,
        description="True for activity statuses that bypass FSM"
    )
    updates_pipeline: bool = Field(
        default=True,
        description="False if only records activity, doesn't change pipeline"
    )
    counts_for_funnel: bool = Field(
        default=True,
        description="True if counted in funnel analytics"
    )
    phase: str = Field(
        default="consultation",
        description="Phase: consultation, admission, fee, enrolled, universal"
    )
    description: Optional[str] = Field(None, description="Optional status description")
    display_order: int = Field(default=0, description="Sort order for displaying statuses")

    # ✅ DEPRECATED fields (kept for backward compatibility)
    is_final_status: Optional[bool] = Field(default=None, description="DEPRECATED: Use is_final")
    legacy_status: Optional[str] = Field(default=None, description="DEPRECATED")
    selectable_by_user: Optional[str] = Field(default=None, description="DEPRECATED: Use selectable_mode")
    counts_for_kpi: Optional[bool] = Field(default=None, description="DEPRECATED: Use counts_for_funnel")

    model_config = ConfigDict(use_enum_values=True, from_attributes=True)


class ConsultationStatusCreate(ConsultationStatusBase):
    """Schema for creating a new consultation status."""
    id: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-z0-9_]+$",
        description="Unique status identifier (lowercase, numbers, underscores only)"
    )


class ConsultationStatusUpdate(BaseModel):
    """Schema for updating an existing consultation status."""
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    color_code: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    stage_id: Optional[str] = None
    outcome_type: Optional[OutcomeTypeEnum] = None

    # ✅ FSM v3.0 fields
    code: Optional[str] = None
    is_final: Optional[bool] = None
    status_type: Optional[StatusTypeEnum] = None
    selectable_mode: Optional[SelectableModeEnum] = None
    is_universal: Optional[bool] = None
    updates_pipeline: Optional[bool] = None
    counts_for_funnel: Optional[bool] = None
    phase: Optional[str] = None
    description: Optional[str] = None
    display_order: Optional[int] = None

    # DEPRECATED fields
    is_final_status: Optional[bool] = None
    legacy_status: Optional[str] = None
    selectable_by_user: Optional[str] = None
    counts_for_kpi: Optional[bool] = None

    model_config = ConfigDict(use_enum_values=True)


class ConsultationStatus(ConsultationStatusBase):
    """Schema for returning a consultation status (with ID)."""
    id: str

    # Optional computed fields
    lead_count: Optional[int] = Field(
        None,
        description="Number of leads with this status (computed)"
    )
    
    # ✅ NEW: Include nested stage for Frontend Logic (Previous/Next Order)
    stage: Optional["PipelineStage"] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# =====================================================================
# ALLOWED TRANSITION SCHEMAS
# =====================================================================


class AllowedTransitionBase(BaseModel):
    """Base schema for AllowedTransition."""
    from_status_id: str = Field(..., description="Source status ID")
    to_status_id: str = Field(..., description="Destination status ID")
    
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class AllowedTransitionCreate(AllowedTransitionBase):
    """Schema for creating a new allowed transition."""
    pass


class AllowedTransitionUpdate(BaseModel):
    """Schema for updating an allowed transition (rarely used)."""
    from_status_id: Optional[str] = None
    to_status_id: Optional[str] = None
    
    model_config = ConfigDict(use_enum_values=True)


class AllowedTransition(AllowedTransitionBase):
    """Schema for returning an allowed transition."""
    id: int
    created_at: datetime
    updated_at: datetime

    # Optional nested objects
    from_status: Optional[ConsultationStatus] = None
    to_status: Optional[ConsultationStatus] = None

    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# =====================================================================
# FULL PIPELINE SCHEMA
# =====================================================================


class FullPipeline(BaseModel):
    """
    Complete pipeline structure with all stages and statuses.

    Used for rendering pipeline board and analytics.
    """
    stages: List[PipelineStage] = Field(
        ...,
        description="All pipeline stages (ordered)"
    )
    statuses: List[ConsultationStatus] = Field(
        ...,
        description="All consultation statuses (grouped by stage)"
    )
    # Thêm transitions vào FullPipeline (nếu cần thiết cho UI sau này)
    allowed_transitions: List[AllowedTransition] = Field(
        default=[],
        description="All configured allowed transitions"
    )

    # Optional analytics data
    total_leads: Optional[int] = Field(
        None,
        description="Total number of leads in pipeline"
    )
    conversion_rate: Optional[float] = Field(
        None,
        description="Overall pipeline conversion rate"
    )
    avg_time_in_pipeline_days: Optional[float] = Field(
        None,
        description="Average time in pipeline"
    )
    
    model_config = ConfigDict(use_enum_values=True)