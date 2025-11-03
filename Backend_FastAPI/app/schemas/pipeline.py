# app/schemas/pipeline.py
from typing import List, Optional  # <-- THÊM Optional

from pydantic import BaseModel, Field, ConfigDict


# --- Schemas cho PipelineStage ---

class PipelineStageBase(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    order: int = Field(..., gt=0)


class PipelineStageCreate(PipelineStageBase):
    id: str = Field(..., min_length=3, max_length=50)


class PipelineStageUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    order: Optional[int] = Field(None, gt=0)


class PipelineStage(PipelineStageBase):
    id: str

    model_config = ConfigDict(from_attributes=True)


# --- Schemas cho ConsultationStatus ---

class ConsultationStatusBase(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    color_code: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")  # Validate mã màu HEX
    stage_id: str


class ConsultationStatusCreate(ConsultationStatusBase):
    id: str = Field(..., min_length=3, max_length=50)


class ConsultationStatusUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    color_code: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    stage_id: Optional[str] = None


class ConsultationStatus(ConsultationStatusBase):
    id: str

    model_config = ConfigDict(from_attributes=True)


# --- Schema chung ---

class FullPipeline(BaseModel):
    # Dùng schema PipelineStage và ConsultationStatus
    stages: List[PipelineStage]
    statuses: List[ConsultationStatus]