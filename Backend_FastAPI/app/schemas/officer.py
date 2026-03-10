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
    enrolled: int = 0
    lost: int = 0

class OutcomeBreakdown(BaseModel):
    positive: int = 0
    negative: int = 0
    neutral: int = 0


class LossBreakdownItem(BaseModel):
    """Loss reason breakdown item for funnel analytics."""
    reason_code: str           # e.g., "PRICE_HIGH", "NO_CONTACT"
    count: int                 # Number of leads lost with this reason
    percentage: float          # Percentage of total losses at this stage


class VelocityStats(BaseModel):
    """Stage velocity statistics - time spent in each stage."""
    avg_days: float            # Average days spent in stage
    min_days: float            # Minimum days
    max_days: float            # Maximum days
    sample_size: int           # Number of transitions measured


class EstimatedLostRevenue(BaseModel):
    """Estimated lost revenue for funnel analytics."""
    lost_leads_count: int              # Number of leads lost at this stage
    avg_tuition: float                 # Average tuition fee (VND)
    total_lost_revenue: float          # Total lost revenue = lost_leads × avg_tuition
    leads_with_tuition: int            # Leads that have offering with tuition data


class FunnelSuggestion(BaseModel):
    """AI-powered suggestion for funnel optimization."""
    id: str                            # Unique suggestion ID (e.g., "bottleneck_stg02")
    type: Literal["bottleneck", "slow_stage", "high_loss", "loss_reason"]
    priority: Literal["critical", "high", "medium", "low"]
    stage_id: Optional[str] = None     # Related stage (if applicable)
    stage_name: Optional[str] = None   # Stage name for display
    title: str                         # Short title (e.g., "Điểm nghẽn tại Tư vấn")
    description: str                   # Detailed description
    metric_value: Optional[float] = None  # The metric that triggered this suggestion
    metric_label: Optional[str] = None    # Label for the metric (e.g., "Conversion: 35%")
    action_label: Optional[str] = None    # Suggested action button label
    action_url: Optional[str] = None      # URL for the action (e.g., leads filtered by stage)


class FunnelStage(BaseModel):
    stage_id: str                      # e.g. "stg05"
    stage_name: str                    # e.g. "Đã nộp học phí"
    stage_order: int                   # For frontend sorting
    lead_count: int                    # Actual count at this stage
    is_final_stage: bool = False       # For separating outcomes
    fill: Optional[str] = None
    conversion_rate: Optional[float] = None  # Historical conversion %
    outcome_breakdown: Optional[OutcomeBreakdown] = None  # positive/negative/neutral counts
    early_exit_count: int = 0          # FINAL leads (negative) at non-final stages
    move_forward: int = 0              # lead_count - early_exit_count
    loss_breakdown: Optional[List[LossBreakdownItem]] = None  # Phase 2: Loss reason analytics
    velocity: Optional[VelocityStats] = None  # Phase 2: Time in stage analytics
    estimated_lost_revenue: Optional[EstimatedLostRevenue] = None  # Phase 2: Lost revenue analytics

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
    
    # Activity-based Win Rate (Officer performance)
    win_rate: float = 0.0  # Won / (Won + Lost) in period
    win_rate_trend: Optional[TrendInfo] = None

    # Cohort-based New Lead Conversion (renamed from conversion_rate)
    new_lead_conversion_rate: float = 0.0  # Converted / Total leads created in range
    new_lead_conversion_rate_trend: Optional[TrendInfo] = None
    
    # Average response time (hours)
    avg_response_time: float
    avg_response_time_trend: TrendInfo

    # SLA Compliance Rate (% leads responded within SLA target hours)
    sla_compliance_rate: float = 0.0
    sla_compliance_rate_trend: Optional[TrendInfo] = None

    # Consultation Effectiveness (% of consulted final leads that converted)
    consultation_effectiveness: float = 0.0
    consultation_effectiveness_trend: Optional[TrendInfo] = None

    # Average consultations per day in selected period
    consultations_avg_per_day: float = 0.0
    # Leads created in period that are still active (for period analysis)
    active_leads_in_period: int = 0

    # Daily Quality KPIs (Phase D — spec §15.7)
    verified_consultations_daily: int = 0
    quality_rate_daily: Optional[float] = None  # NULL when H_D = 0
    followup_commitment_rate: Optional[float] = None  # NULL when V_D_non_final = 0

    # Rolling Quality KPIs (data has 7/3 day lag)
    progress_rate_d7: Optional[float] = None  # NULL when insufficient data
    progress_rate_d7_date: Optional[str] = None  # ISO date of actual D (today - 7)
    rollback_rate_d3: Optional[float] = None
    rollback_rate_d3_date: Optional[str] = None  # ISO date of actual D (today - 3)


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
    # Contact info for quick actions (Zalo, Phone)
    phone: Optional[str] = None
    last_contact_at: Optional[datetime] = None


class OfficerDashboardEnhanced(BaseModel):
    """Enhanced dashboard response with KPIs and priority actions."""
    kpis: KPIStats
    status_overview: WorkloadStats
    priority_actions: List[PriorityAction]
    performance_trends: List[TrendPoint]
    sales_funnel: List[FunnelStage]
    funnel_net_conversion_trend: Optional[TrendInfo] = None
    funnel_suggestions: List[FunnelSuggestion] = []
    actionable_lists: ActionableLists
    # Phase 6: Annual target progress (rolling targets)
    annual_progress: Optional["AnnualProgressInfo"] = None


# =============================================================================
# PHASE 6: Annual Progress Info (Rolling Targets)
# =============================================================================

class AnnualProgressInfo(BaseModel):
    """Annual target progress with rolling monthly target calculation."""
    kpi_code: str  # e.g., "enrollments"
    fiscal_year: int
    annual_target: float
    achieved_ytd: float  # Year-to-date achievement
    remaining: float  # annual_target - achieved_ytd
    progress_pct: float  # (achieved_ytd / annual_target) * 100
    months_left: int  # Months remaining in the year
    monthly_target: float  # Rolling target = remaining / months_left
    status: str  # "in_progress", "completed", "at_risk", "overdue"
    on_track: bool  # True if progress >= expected pace
    surplus: Optional[float] = None  # Only if status == "completed"
    last_sync_at: Optional[datetime] = None  # Last YTD sync timestamp


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
    """Leaderboard response (weekly or custom date range)."""
    week_start: str  # ISO date string (period start)
    week_end: Optional[str] = None  # ISO date string (period end, for custom range)
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