# app/schemas/kpi_planning.py
"""
KPI Planning Schemas — Phase A6

Request/Response models for KPI Planning CRUD + Preview endpoints.
Follows project conventions: BaseModel + ConfigDict(from_attributes=True).
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# REQUEST SCHEMAS
# =============================================================================

class KpiPlanCreate(BaseModel):
    """Create a new KPI plan (spec §7: POST /plans)."""
    unit_id: int = Field(..., description="Organization unit ID (required — no global plans)")
    fiscal_year: int = Field(..., ge=2020, le=2100)
    annual_enrollment_target: int = Field(..., ge=1, le=10000, description="Annual enrollment target")
    sla_target: float = Field(default=85.0, ge=0, le=100, description="SLA compliance target (%)")
    response_time_target: float = Field(default=2.0, ge=1, le=48, description="Response time target (hours)")
    seasonal_weights: Optional[List[float]] = Field(
        None,
        description="12 floats summing to ~1.0. NULL = use defaults.",
        min_length=12,
        max_length=12,
    )
    officer_id: Optional[int] = Field(None, description="Officer ID. NULL = unit plan.")


class KpiPlanUpdate(BaseModel):
    """Update an existing KPI plan (spec §7: PUT /plans/{id})."""
    annual_enrollment_target: Optional[int] = Field(None, ge=1, le=10000)
    sla_target: Optional[float] = Field(None, ge=0, le=100)
    response_time_target: Optional[float] = Field(None, ge=1, le=48)
    seasonal_weights: Optional[List[float]] = Field(
        None, min_length=12, max_length=12,
    )


class KpiPlanPreview(BaseModel):
    """Preview KPI plan dry-run (spec §7: POST /plans/preview). No persist."""
    unit_id: int
    fiscal_year: int = Field(..., ge=2020, le=2100)
    annual_enrollment_target: int = Field(..., ge=1, le=10000)
    sla_target: float = Field(default=85.0, ge=0, le=100)
    response_time_target: float = Field(default=2.0, ge=1, le=48)
    seasonal_weights: Optional[List[float]] = Field(
        None, min_length=12, max_length=12,
    )


# =============================================================================
# RESPONSE SCHEMAS
# =============================================================================

class KpiPlanMonthResponse(BaseModel):
    """Response schema for a single plan month (12 per plan)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    month: int

    # Distributable inputs
    enrollment_target: int
    working_days: int
    weight: float

    # Historical factors
    k_factor: float
    lead_forecast: Optional[int] = None
    close_forecast: Optional[int] = None

    # Derived KPI targets (nullable — NULL = not computable, UI shows "N/A")
    consultations_daily: Optional[int] = None
    conversion_rate: Optional[float] = None
    win_rate: Optional[float] = None
    consultation_effectiveness: Optional[float] = None

    # Override tracking
    overridden_fields: dict = Field(default_factory=dict)
    override_reason: Optional[str] = None
    overridden_by: Optional[int] = None
    overridden_at: Optional[datetime] = None

    # Actuals (filled by sync job)
    actual_enrollments: Optional[int] = None
    actual_consultations_avg: Optional[float] = None
    actual_conversion_rate: Optional[float] = None
    actual_win_rate: Optional[float] = None
    actual_consultation_effectiveness: Optional[float] = None
    actual_sla_compliance_rate: Optional[float] = None


class KpiPlanResponse(BaseModel):
    """Response schema for a KPI plan (with months)."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    unit_id: int
    officer_id: Optional[int] = None
    fiscal_year: int
    annual_enrollment_target: int
    sla_target: float
    response_time_target: float
    seasonal_weights: Optional[List[float]] = None
    is_active: bool
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    months: List[KpiPlanMonthResponse] = Field(default_factory=list)


class KpiPlanListResponse(BaseModel):
    """Paginated list response for KPI plans."""
    items: List[KpiPlanResponse]
    total: int
    skip: int
    limit: int


class KpiPlanPreviewMonth(BaseModel):
    """Preview month — no ID, not persisted."""
    month: int
    enrollment_target: int
    working_days: int
    weight: float
    k_factor: float
    lead_forecast: Optional[int] = None
    close_forecast: Optional[int] = None
    consultations_daily: Optional[int] = None
    conversion_rate: Optional[float] = None
    win_rate: Optional[float] = None
    consultation_effectiveness: Optional[float] = None


class KpiPlanPreviewResponse(BaseModel):
    """Preview response — dry-run, no DB records created."""
    annual_enrollment_target: int
    sla_target: float
    response_time_target: float
    months: List[KpiPlanPreviewMonth]
