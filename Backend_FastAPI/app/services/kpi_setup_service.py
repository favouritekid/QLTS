# app/services/kpi_setup_service.py
"""
KPI Setup — Coverage Report (Phase 1: Read-Only Dashboard).

Orchestration layer: no new KPI logic. Reuses existing services/repos.
"""
import structlog
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.repositories import KpiRepository
from app.repositories.user_repository import UserRepository
from app.services import calendar_service
from app.services.kpi_service import compute_progress_status
from app.services.kpi_planning_service import DEFAULT_ENROLLMENT_WEIGHTS

log = structlog.get_logger(__name__)


async def get_coverage_report(
    db: AsyncSession,
    fiscal_year: int,
    scope_unit_id: Optional[int] = None,
) -> dict:
    """
    Build KPI coverage report for admin dashboard.

    Args:
        db: Async DB session
        fiscal_year: Target fiscal year
        scope_unit_id: IDOR filter — manager sees own unit only, admin sees all (None)

    Returns:
        dict matching CoverageReport schema
    """
    kpi_repo = KpiRepository(db)
    user_repo = UserRepository(db)

    # 1. Holiday status
    holiday_info = await calendar_service.get_holiday_status(db, fiscal_year)
    holiday_status = {
        "total_holidays": holiday_info["total_holidays"],
        "is_complete": holiday_info["is_complete"],
        "reason_code": "missing_holiday" if not holiday_info["is_complete"] else None,
    }

    # 2. Load active units
    unit_query = select(models.OrganizationUnit).where(
        models.OrganizationUnit.is_active == True,
    )
    if scope_unit_id is not None:
        unit_query = unit_query.where(models.OrganizationUnit.id == scope_unit_id)
    unit_query = unit_query.order_by(models.OrganizationUnit.name)
    unit_result = await db.execute(unit_query)
    units = list(unit_result.scalars().all())

    # 3. Load ALL active unit-level plans (no pagination — coverage needs full set)
    plan_query = select(models.KpiPlan).where(
        models.KpiPlan.fiscal_year == fiscal_year,
        models.KpiPlan.is_active == True,
        models.KpiPlan.officer_id.is_(None),  # unit plans only
    )
    plan_result = await db.execute(plan_query)
    plans = list(plan_result.scalars().all())
    plans_by_unit: Dict[int, models.KpiPlan] = {p.unit_id: p for p in plans}

    # 4. Load ALL active KpiTargets for enrollments_annual
    targets = await kpi_repo.list_targets(
        fiscal_year=fiscal_year,
        kpi_code="enrollments_annual",
        is_active=True,
        unit_id=scope_unit_id,
    )

    # Organize targets by scope
    officer_targets: Dict[int, models.KpiTarget] = {}  # officer_id -> target
    unit_targets: Dict[int, models.KpiTarget] = {}     # unit_id -> target (officer_id=NULL)
    global_target: Optional[models.KpiTarget] = None
    for t in targets:
        if t.officer_id is not None:
            officer_targets[t.officer_id] = t
        elif t.unit_id is not None:
            unit_targets[t.unit_id] = t
        else:
            global_target = t

    # 5. Load officers per unit + collect all officer IDs
    all_officer_ids: List[int] = []
    officers_by_unit: Dict[int, List[models.User]] = {}
    for unit in units:
        officers = await user_repo.get_officers_by_unit(unit.id)
        officers_by_unit[unit.id] = officers
        all_officer_ids.extend(o.id for o in officers)

    # 6. Batch YTD counts for inherited officers (those without custom target)
    inherited_officer_ids = [oid for oid in all_officer_ids if oid not in officer_targets]
    ytd_grouped: Dict[int, int] = {}
    if inherited_officer_ids:
        ytd_grouped = await kpi_repo.count_enrollments_ytd_grouped(
            inherited_officer_ids, fiscal_year
        )

    # 7. Current time reference for status calculation
    now = datetime.now(timezone.utc)
    ref_year = now.year
    ref_month = now.month

    # 8. Build per-unit coverage
    warnings: List[dict] = []
    unit_coverages: List[dict] = []

    for unit in units:
        plan = plans_by_unit.get(unit.id)
        unit_officers = officers_by_unit.get(unit.id, [])
        officer_count = len(unit_officers)

        # Seasonal weights for status computation
        seasonal_weights = None
        if plan and plan.seasonal_weights and len(plan.seasonal_weights) == 12:
            seasonal_weights = plan.seasonal_weights
        elif plan:
            seasonal_weights = [DEFAULT_ENROLLMENT_WEIGHTS[m] for m in range(1, 13)]

        officer_rows: List[dict] = []
        for officer in unit_officers:
            custom_target = officer_targets.get(officer.id)

            if custom_target:
                # Officer has custom KpiTarget
                source = "custom"
                target_id = custom_target.id
                annual = custom_target.annual_target
                ytd = custom_target.achieved_ytd
            elif plan and officer_count > 0:
                # Inherit from unit plan
                source = "inherited"
                target_id = None
                annual = plan.annual_enrollment_target // officer_count
                ytd = ytd_grouped.get(officer.id, 0)
            elif unit.id in unit_targets and officer_count > 0:
                # Inherit from unit-scoped KpiTarget
                ut = unit_targets[unit.id]
                source = "inherited"
                target_id = None
                annual = ut.annual_target // officer_count
                ytd = ytd_grouped.get(officer.id, 0)
            elif global_target and officer_count > 0:
                # Inherit from global target
                source = "inherited_global"
                target_id = None
                annual = global_target.annual_target // officer_count
                ytd = ytd_grouped.get(officer.id, 0)
            else:
                source = "none"
                target_id = None
                annual = 0
                ytd = ytd_grouped.get(officer.id, 0)

            progress_pct = round((ytd / annual * 100), 1) if annual > 0 else 0.0
            status = compute_progress_status(
                ytd=ytd, annual=annual,
                fiscal_year=fiscal_year, ref_year=ref_year, ref_month=ref_month,
                seasonal_weights=seasonal_weights,
            )

            officer_rows.append({
                "officer_id": officer.id,
                "officer_name": officer.full_name or officer.username,
                "target_source": source,
                "target_id": target_id,
                "annual_target": annual,
                "achieved_ytd": ytd,
                "progress_pct": progress_pct,
                "status": status,
            })

            # Warning: officer with no target
            if source == "none":
                warnings.append({
                    "reason_code": "officer_no_target",
                    "action_hint": "assign_target",
                    "section": 2,
                    "detail": f"Cán bộ {officer_rows[-1]['officer_name']} chưa có chỉ tiêu KPI.",
                    "entity_id": officer.id,
                })

        total_officer_target = sum(o["annual_target"] for o in officer_rows)
        target_gap = (plan.annual_enrollment_target - total_officer_target) if plan else 0

        unit_coverages.append({
            "unit_id": unit.id,
            "unit_name": unit.name,
            "plan_id": plan.id if plan else None,
            "plan_status": "active" if plan else None,
            "annual_target": plan.annual_enrollment_target if plan else None,
            "officers": officer_rows,
            "total_officer_target": total_officer_target,
            "target_gap": target_gap,
        })

        # Warning: unit without plan
        if not plan:
            warnings.append({
                "reason_code": "missing_unit_plan",
                "action_hint": "create_plan",
                "section": 1,
                "detail": f"Đơn vị '{unit.name}' chưa có KPI Plan cho năm {fiscal_year}.",
                "entity_id": unit.id,
            })

        # Warning: target gap
        if plan and target_gap != 0:
            warnings.append({
                "reason_code": "officer_target_mismatch",
                "action_hint": "review_targets",
                "section": 2,
                "detail": f"Đơn vị '{unit.name}': tổng chỉ tiêu officer ({total_officer_target}) chênh lệch {target_gap} so với plan ({plan.annual_enrollment_target}).",
                "entity_id": unit.id,
            })

    # Holiday warning
    if not holiday_info["is_complete"]:
        warnings.insert(0, {
            "reason_code": "missing_holiday",
            "action_hint": "seed_holidays",
            "section": 0,
            "detail": holiday_info.get("warning", f"Chưa cấu hình đầy đủ ngày lễ cho năm {fiscal_year}."),
            "entity_id": None,
        })

    # Stale sync warning — check if any custom target has last_sync_at > 24h ago
    stale_threshold = datetime.now(timezone.utc).timestamp() - 86400
    for t in targets:
        if t.officer_id and t.last_sync_at:
            if t.last_sync_at.timestamp() < stale_threshold:
                warnings.append({
                    "reason_code": "stale_sync",
                    "action_hint": "sync_ytd",
                    "section": 3,
                    "detail": "Dữ liệu YTD chưa được đồng bộ trong 24h qua.",
                    "entity_id": None,
                })
                break  # One warning is enough

    # 9. Build summary
    total_units = len(units)
    units_with_plan = sum(1 for u in unit_coverages if u["plan_id"] is not None)
    total_officers = sum(len(u["officers"]) for u in unit_coverages)
    officers_with_target = sum(
        1 for u in unit_coverages
        for o in u["officers"]
        if o["target_source"] != "none"
    )
    total_annual_target = sum(
        o["annual_target"] for u in unit_coverages for o in u["officers"]
    )
    total_achieved_ytd = sum(
        o["achieved_ytd"] for u in unit_coverages for o in u["officers"]
    )
    overall_progress = round(
        (total_achieved_ytd / total_annual_target * 100), 1
    ) if total_annual_target > 0 else 0.0

    return {
        "fiscal_year": fiscal_year,
        "holiday_status": holiday_status,
        "units": unit_coverages,
        "warnings": warnings,
        "summary": {
            "total_units": total_units,
            "units_with_plan": units_with_plan,
            "total_officers": total_officers,
            "officers_with_target": officers_with_target,
            "total_annual_target": total_annual_target,
            "total_achieved_ytd": total_achieved_ytd,
            "progress_pct": overall_progress,
        },
    }
