# app/schemas/pipeline.py
from datetime import datetime
from typing import List, Optional

# ✅ 1. Thêm import ConfigDict
from pydantic import BaseModel, ConfigDict, Field

from ..models.pipeline import OutcomeTypeEnum


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
    stage_id: str = Field(..., description="Parent pipeline stage ID")
    outcome_type: OutcomeTypeEnum = Field(
        default=OutcomeTypeEnum.neutral,
        description="Outcome classification: positive/neutral/negative"
    )
    is_final_status: bool = Field(
        default=False,
        description="Whether this status marks end of lead lifecycle"
    )
    legacy_status: Optional[str] = Field(
        default=None,
        description="Maps to lead.status for backward compatibility. Valid values: new, assigned, contacted, qualified, unqualified, converted, rejected"
    )

    # ✅ QUAN TRỌNG NHẤT: Fix lỗi "invalid input value ... NEUTRAL"
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
    is_final_status: Optional[bool] = None
    legacy_status: Optional[str] = Field(
        default=None,
        description="Maps to lead.status for backward compatibility"
    )

    model_config = ConfigDict(use_enum_values=True)


class ConsultationStatus(ConsultationStatusBase):
    """Schema for returning a consultation status (with ID)."""
    id: str

    # Optional computed fields
    lead_count: Optional[int] = Field(
        None,
        description="Number of leads with this status (computed)"
    )

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