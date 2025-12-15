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
    stage_id: str  # e.g. "stg05"
    stage: str     # e.g. "Đã chốt deal"
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


# =============================================================================
# PHASE 1: Enhanced Dashboard KPI Schemas
# =============================================================================

class TrendInfo(BaseModel):
    """Trend information for KPI comparisons."""
    value: float  # Percentage change or absolute difference
    direction: Literal["up", "down", "neutral"]
    comparison: str  # e.g., "vs hôm qua", "vs TB tuần"


class KPIStats(BaseModel):
    """Core KPI statistics for officer dashboard."""
    # Today's consultations
    consultations_today: int
    consultations_target: int = 10  # Default daily target
    consultations_trend: TrendInfo
    
    # Active leads (non-final status)
    active_leads: int
    active_leads_trend: TrendInfo
    
    # Conversion rate (this month)
    conversion_rate: float  # Percentage
    conversion_rate_trend: TrendInfo
    
    # Average response time (hours)
    avg_response_time: float
    avg_response_time_trend: TrendInfo


class PriorityAction(BaseModel):
    """AI-powered priority action suggestion."""
    id: str  # Unique action ID
    type: Literal["hot_lead", "overdue", "scheduled", "follow_up", "new_lead"]
    priority: Literal["urgent", "high", "medium"]
    lead_id: int
    lead_name: str
    lead_score: Optional[float] = 0
    reason: str  # AI-generated explanation
    due_at: Optional[datetime] = None
    days_since_contact: Optional[int] = None


class OfficerDashboardEnhanced(BaseModel):
    """Enhanced dashboard response with KPIs and priority actions."""
    kpis: KPIStats
    status_overview: WorkloadStats
    priority_actions: List[PriorityAction]
    performance_trends: List[TrendPoint]
    sales_funnel: List[FunnelStage]
    actionable_lists: ActionableLists


# =============================================================================
# PHASE 4: Leaderboard Schemas
# =============================================================================

class LeaderboardEntry(BaseModel):
    """Single entry in the leaderboard."""
    rank: int
    user_id: int
    username: str
    full_name: str
    consultations: int
    is_current_user: bool = False
    rank_change: Optional[int] = None  # +2 = up 2 spots, -1 = down 1, None = new


class WeeklyLeaderboard(BaseModel):
    """Weekly leaderboard response."""
    week_start: str  # ISO date string
    total_officers: int
    current_user_rank: int
    leaderboard: List[LeaderboardEntry]


# =============================================================================
# PHASE 6: Team Stats for Performance Comparison
# =============================================================================

class TeamStats(BaseModel):
    """Team average statistics for performance comparison."""
    team_avg_consultations: float  # Daily average across all officers
    team_avg_conversions: float  # Daily average conversions
    officer_rank_percentile: int  # Current officer's percentile rank (0-100)
    total_officers: int
    period_days: int = 30