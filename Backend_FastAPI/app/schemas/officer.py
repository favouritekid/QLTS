# app/schemas/officer.py
from typing import Annotated, Dict, List, Optional, Literal
from datetime import date, datetime
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


class LeadsSnapshotDrillDownFilters(BaseModel):
    stage_id: Optional[str] = None
    status_codes: Optional[List[str]] = None
    loss_reason_code: Optional[str] = None


class ConsultationsDrillDownFilters(BaseModel):
    stage_id: Optional[str] = None
    loss_reason_code: Optional[str] = None
    consultation_kind: Optional[Literal["human", "system"]] = None
    response_breach_only: Optional[bool] = None


class TransitionsDrillDownFilters(BaseModel):
    stage_id: Optional[str] = None
    outcome: Optional[Literal["positive", "negative", "neutral"]] = None
    final_only: Optional[bool] = None
    consulted_only: Optional[bool] = None


class CohortsDrillDownFilters(BaseModel):
    cohort_result: Optional[Literal["converted", "lost", "open"]] = None


DrillDownMetricKey = Literal[
    "active_leads",
    "funnel_stage",
    "consultations_today",
    "consultations_avg_per_day",
    "loss_reason",
    "avg_response_time",
    "bottleneck",
    "slow_stage",
    "high_loss",
    "win_rate",
    "enrollments_monthly",
    "consultation_effectiveness",
    "new_lead_conversion",
]


class LeadsSnapshotDrillDownDescriptor(BaseModel):
    target: Literal["leads_snapshot"]
    exactness: Literal["exact"] = "exact"
    metric_key: Literal["active_leads", "funnel_stage"]
    filters: Optional[LeadsSnapshotDrillDownFilters] = None


class ConsultationsDrillDownDescriptor(BaseModel):
    target: Literal["consultations"]
    exactness: Literal["exact"] = "exact"
    metric_key: Literal["consultations_today", "consultations_avg_per_day", "loss_reason", "avg_response_time"]
    filters: Optional[ConsultationsDrillDownFilters] = None


class TransitionsDrillDownDescriptor(BaseModel):
    target: Literal["transitions"]
    exactness: Literal["exact"] = "exact"
    metric_key: Literal["bottleneck", "slow_stage", "high_loss", "win_rate", "enrollments_monthly", "consultation_effectiveness"]
    filters: Optional[TransitionsDrillDownFilters] = None


class CohortsDrillDownDescriptor(BaseModel):
    target: Literal["cohorts"]
    exactness: Literal["exact"] = "exact"
    metric_key: Literal["new_lead_conversion"]
    filters: Optional[CohortsDrillDownFilters] = None


DrillDownDescriptor = Annotated[
    LeadsSnapshotDrillDownDescriptor
    | ConsultationsDrillDownDescriptor
    | TransitionsDrillDownDescriptor
    | CohortsDrillDownDescriptor,
    Field(discriminator="target"),
]


class DrillDownMetadata(BaseModel):
    """Common metadata for all drill-down responses."""
    metric_key: DrillDownMetricKey
    exactness: Literal["exact"] = "exact"
    effective_scope: Optional[dict] = None
    effective_date_context: Optional[dict] = None
    page: int
    page_size: int
    total_count: int


class ConsultationDrillDownRow(BaseModel):
    """Row for consultations drill-down."""
    consultation_id: int
    lead_id: int
    lead_name: Optional[str] = None
    officer_id: Optional[int] = None
    officer_name: Optional[str] = None
    consultation_date: Optional[str] = None
    loss_reason_code: Optional[str] = None
    loss_reason_note: Optional[str] = None
    status: Optional[str] = None


class TransitionDrillDownRow(BaseModel):
    """Row for transitions drill-down."""
    history_id: int
    lead_id: int
    lead_name: Optional[str] = None
    changed_at: Optional[str] = None
    changed_by: Optional[str] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    old_stage_id: Optional[str] = None
    new_stage_id: Optional[str] = None
    old_stage_name: Optional[str] = None
    new_stage_name: Optional[str] = None
    loss_reason_code: Optional[str] = None
    outcome: Optional[str] = None  # "positive" | "negative" | "neutral"


class CohortDrillDownRow(BaseModel):
    """Row for cohorts drill-down."""
    lead_id: int
    lead_name: Optional[str] = None
    created_at: Optional[str] = None
    current_status: Optional[str] = None
    cohort_result: Optional[str] = None  # "converted" | "lost" | "open"
    officer_id: Optional[int] = None
    officer_name: Optional[str] = None


class DrillDownResponse(BaseModel):
    """Generic drill-down response with metadata + rows."""
    metadata: DrillDownMetadata
    rows: list  # Actual type varies by endpoint


class FunnelSuggestion(BaseModel):
    """AI-powered suggestion for funnel optimization."""
    id: str
    type: Literal["bottleneck", "slow_stage", "high_loss", "loss_reason"]
    priority: Literal["critical", "high", "medium", "low"]
    stage_id: Optional[str] = None
    stage_name: Optional[str] = None
    title: str
    description: str
    metric_value: Optional[float] = None
    metric_label: Optional[str] = None
    action_label: Optional[str] = None
    action_url: Optional[str] = None       # Backward compat — frontend uses drill_down
    drill_down: Optional[DrillDownDescriptor] = None


class FunnelStage(BaseModel):
    stage_id: str                      # e.g. "stg05"
    stage_name: str                    # e.g. "Xử lý học phí"
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

# Main response model — must be defined after component schemas above
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
    is_unit_target: bool = False  # P1: True when target comes from unit plan (not officer-specific)
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
    avg_response_time_target: Optional[float] = None  # From KpiPlan.response_time_target

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

    # Catalog-driven targets (comparable flag from METRIC_CATALOG)
    win_rate_target: Optional[float] = None
    new_lead_conversion_rate_target: Optional[float] = None
    sla_compliance_rate_target: Optional[float] = None
    consultation_effectiveness_target: Optional[float] = None

    # All targets for frontend canShowTarget() gating
    metric_targets: Optional[Dict[str, float]] = None

    # Enrollments monthly (count of leads enrolled in period)
    enrollments_monthly: int = 0
    enrollments_monthly_target: Optional[float] = None

    # Daily Quality KPIs (Phase D — spec §15.7)
    verified_consultations_daily: int = 0
    quality_rate_daily: Optional[float] = None  # NULL when H_D = 0
    followup_commitment_rate: Optional[float] = None  # NULL when V_D_non_final = 0

    # Rolling Quality KPIs (data has 7/3 day lag)
    progress_rate_d7: Optional[float] = None  # NULL when insufficient data
    progress_rate_d7_date: Optional[date] = None  # actual D (today - 7)
    rollback_rate_d3: Optional[float] = None
    rollback_rate_d3_date: Optional[date] = None  # actual D (today - 3)


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
    resolution_kind: Optional[str] = None  # "assigned" | "inherited_estimate" | None
    expected_progress_pct: Optional[float] = None  # Seasonal-aware expected % at current month

    # R3: Team breakdown (only present in aggregated/manager response)
    officer_count: Optional[int] = None
    officers_at_risk: Optional[int] = None
    officers_overdue: Optional[int] = None


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
    is_current_user: bool = False  # True only for the actual logged-in user
    is_focus_officer: bool = False  # True for the drill-down target (may differ from current user)
    rank_change: Optional[int] = None  # +2 = up 2 spots, -1 = down 1, None = new


class WeeklyLeaderboard(BaseModel):
    """Leaderboard response (weekly or custom date range)."""
    week_start: str  # ISO date string (period start)
    week_end: Optional[str] = None  # ISO date string (period end, for custom range)
    total_officers: int
    current_user_rank: Optional[int] = None
    leaderboard: List[LeaderboardEntry]


# =============================================================================
# Distribution Panel ("Điểm bận") — giải trình phân phối lead của đơn vị
# =============================================================================

class OfficerArchetype(BaseModel):
    """Nhãn kiểu officer suy ra từ tỉ lệ các đòn bẩy tải."""
    key: str
    label: str


class OfficerDistributionEntry(BaseModel):
    """Một dòng trong bảng điểm bận.

    Mọi con số tải đến TRỰC TIẾP từ ``assignment_service.compute_unit_officer_loads``
    — cùng hàm engine chia lead dùng, nên KHÔNG thể lệch.
    """
    rank: int
    user_id: int
    username: str
    full_name: str
    unit_id: Optional[int] = None
    unit_name: Optional[str] = None
    # Chế độ chấm điểm engine áp cho ĐƠN VỊ của dòng này (per-unit, vì ngưỡng
    # history fairness tính riêng từng đơn vị). Đây mới là giá trị chính xác;
    # trường cùng tên ở cấp panel chỉ là tóm tắt.
    scoring_mode: Optional[str] = None

    # --- Số liệu tải (nguyên bản từ engine) ---
    workload: int                  # Lead đang giữ (tổng non-final)
    max_capacity: int              # Khả năng nhận
    weight: int                    # Ưu tiên kỳ cựu (×N)
    self_sourced: int              # Lead tự tìm
    tuition_hold: int              # Hồ sơ đã đóng tiền
    dist_load: int                 # Lead hệ thống tính
    deducted: int                  # Không tính = workload - dist_load
    real_util_pct: float           # dist_load/cap  (cơ sở sắp xếp, %)
    fill_pct: float                # workload/cap   (chỗ đầy thật, %)
    eff_util_pct: float            # ĐIỂM BẬN = dist_load/(cap*weight), %
    score: float                   # điểm sắp xếp thực tế của engine
    overload_gate_pct: float       # (workload-tuition)/cap, ngưỡng dừng 80%

    # --- Cờ trạng thái ---
    overloaded: bool
    at_capacity: bool
    eligible_for_assignment: bool  # False = offline/busy/đầy tải ⇒ ngoài luồng chia
    availability_status: str

    # --- Diễn giải (backend tính, thin-client) ---
    archetype: OfficerArchetype
    diagnosis: str
    boost: Optional[str] = None    # 🔒 CHỈ set cho chính người đang xem
    is_current_user: bool = False


class OfficerDistributionPanel(BaseModel):
    """Bảng điểm bận của (các) đơn vị trong phạm vi người xem."""
    unit_id: Optional[int] = None
    total_officers: int
    # legacy | member | fairness | member_fairness | "mixed" | None.
    # ⚠️ Chỉ là TÓM TẮT: chấm điểm chạy per-unit, nên khi phạm vi trải nhiều đơn
    # vị có mode khác nhau giá trị này = "mixed"; muốn chính xác đọc
    # ``entries[].scoring_mode``. None = không đơn vị nào có pool chấm điểm.
    scoring_mode: Optional[str] = None
    flags_snapshot: Dict[str, bool]
    entries: List[OfficerDistributionEntry]


# =============================================================================
# PHASE 6: Team Stats for Performance Comparison
# =============================================================================

class TeamStats(BaseModel):
    """Team average statistics for performance comparison."""
    team_avg_consultations: float  # Daily average across all officers
    officer_rank_percentile: int  # Current officer's percentile rank (0-100)
    total_officers: int
    period_days: int = 30


# =============================================================================
# GAP 2: Monthly KPI Plan Breakdown (Officer self-tracking)
# =============================================================================

class OfficerPlanMonthSummary(BaseModel):
    """Monthly breakdown row for officer KPI plan.

    Fields suffixed _target are plan values. Fields suffixed _actual are
    synced from real data.  Unsuffixed legacy fields kept for compatibility.
    """
    month: int
    enrollment_target: int
    enrollment_actual: Optional[int] = None
    working_days: int
    consultations_daily: Optional[int] = None          # plan target: daily consultations
    consultations_actual_avg: Optional[float] = None   # actual: avg consultations/day (sync)
    consultations_monthly_total: Optional[int] = None  # plan-derived: daily * working_days
    conversion_rate: Optional[float] = None            # plan target (NOT actual)
    conversion_rate_actual: Optional[float] = None     # actual conversion rate (sync)
    win_rate: Optional[float] = None                   # plan target (NOT actual)
    win_rate_actual: Optional[float] = None            # actual win rate (sync)


class OfficerKpiPlanResponse(BaseModel):
    """Officer KPI plan with monthly breakdown. Source = KpiPlanMonth actuals."""
    fiscal_year: int
    annual_target: int
    achieved_ytd: int
    progress_pct: float
    months: List[OfficerPlanMonthSummary]
    source: Literal["officer", "unit"]
