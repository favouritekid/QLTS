# app/schemas/officer.py
from typing import List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

# --- Shared Models ---

class WorkloadStats(BaseModel):
    current_workload: int
    max_capacity: int
    utilization: float
    availability_status: str

class TrendPoint(BaseModel):
    date: str # YYYY-MM-DD
    assigned: int
    consultations: int
    converted: int

class FunnelStage(BaseModel):
    stage: str
    count: int
    fill: str 

class LeadPreview(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    lead_score: Optional[float] = 0
    updated_at: datetime
    stage_name: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class UpcomingConsultation(BaseModel):
    id: int
    lead_id: int
    lead_name: str
    scheduled_at: datetime
    status: str

# --- Request Models (Input) ---

class AvailabilityUpdate(BaseModel):
    availability_status: Literal["available", "busy", "offline"] = Field(
        ..., description="Trạng thái sẵn sàng nhận việc"
    )

# --- Response Models (Output) ---

class ActionableLists(BaseModel):
    high_score: List[LeadPreview]
    stale: List[LeadPreview]
    upcoming: List[UpcomingConsultation]

# 👇 Class gây lỗi đây, đảm bảo nó nằm ở đây
class OfficerDashboardStats(BaseModel):
    status_overview: WorkloadStats
    performance_trends: List[TrendPoint]
    sales_funnel: List[FunnelStage]
    actionable_lists: ActionableLists

class AvailabilityResponse(BaseModel):
    status: str
    availability_status: str
    user_id: int