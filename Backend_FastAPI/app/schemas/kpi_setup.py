# app/schemas/kpi_setup.py
"""
KPI Setup — Coverage Report schemas (Phase 1: Read-Only Dashboard).
"""
from typing import List, Optional

from pydantic import BaseModel


class HolidayStatusCoverage(BaseModel):
    total_holidays: int
    is_complete: bool
    reason_code: Optional[str] = None  # "missing_holiday" | None


class OfficerCoverage(BaseModel):
    officer_id: int
    officer_name: str
    target_source: str  # "custom" | "inherited" | "inherited_global" | "none"
    target_id: Optional[int] = None  # KpiTarget.id if custom
    plan_id: Optional[int] = None  # KpiPlan.id if officer has own plan
    annual_target: int
    achieved_ytd: int
    progress_pct: float
    status: str  # "in_progress" | "completed" | "at_risk" | "overdue" | "not_started"


class UnitCoverage(BaseModel):
    unit_id: int
    unit_name: str
    plan_id: Optional[int] = None
    plan_status: Optional[str] = None  # "active" | None
    annual_target: Optional[int] = None
    seasonal_weights: Optional[List[float]] = None  # 12 floats from unit plan, for preview
    officers: List[OfficerCoverage]
    total_officer_target: int
    target_gap: int  # plan target - sum(officer targets)


class CoverageWarning(BaseModel):
    reason_code: str  # missing_holiday, missing_unit_plan, officer_no_target, officer_target_mismatch, stale_sync
    action_hint: str  # seed_holidays, create_plan, assign_target, review_targets, sync_ytd
    section: int  # 0-3
    detail: str
    entity_id: Optional[int] = None


class CoverageSummary(BaseModel):
    total_units: int
    units_with_plan: int
    total_officers: int
    officers_with_target: int  # custom + inherited (not "none")
    total_annual_target: int
    total_achieved_ytd: int
    progress_pct: float


class CoverageReport(BaseModel):
    fiscal_year: int
    holiday_status: HolidayStatusCoverage
    units: List[UnitCoverage]
    warnings: List[CoverageWarning]
    summary: CoverageSummary
