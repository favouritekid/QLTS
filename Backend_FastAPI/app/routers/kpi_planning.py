# app/routers/kpi_planning.py
"""
KPI Planning Admin API — Phase A6

CRUD endpoints for KPI Planning (reverse-funnel engine):
- Create/List/Get/Update/Delete plans
- Preview (dry-run, no persist)
- Regenerate derived KPIs

ARCHITECTURE: Pattern A (Router → Service → Repository)
IDOR: All resource access via deps.py dependencies (spec §2.6).
      Admin sees all. Manager sees only own unit. 404 on scope violation.
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import deps
from app.database import get_db
from app.models import User
from app.models.config import KpiPlan, KpiPlanMonth
from app.repositories.kpi_planning_repository import KpiPlanningRepository
from app.schemas.kpi_planning import (
    BatchOverrideRequest,
    BatchOverrideResponse,
    HolidayCreate,
    HolidayListResponse,
    HolidayResponse,
    HolidaySeedResponse,
    HolidayStatusResponse,
    HolidayUpdate,
    KpiPlanCloneRequest,
    KpiPlanCreate,
    KpiPlanListResponse,
    KpiPlanPreview,
    KpiPlanPreviewResponse,
    KpiPlanResponse,
    KpiPlanUpdate,
    MonthOverrideRequest,
    MonthOverrideResponse,
    MonthResetRequest,
    WorkingDaysOverrideRequest,
)
from app.services import kpi_planning_service
from app.services.calendar_service import get_holiday_status

router = APIRouter(
    prefix="/api/admin/kpi-planning",
    tags=["Admin - KPI Planning"],
)

# =============================================================================
# SECURITY GATEWAY DEPENDENCIES
# =============================================================================
AdminDep = Depends(deps.require_admin)
AdminOrManagerDep = Depends(deps.require_admin_or_manager)


# =============================================================================
# PLAN CRUD
# =============================================================================

@router.post(
    "/plans",
    response_model=KpiPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new KPI plan",
)
async def create_plan(
    data: KpiPlanCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """
    Create a new KPI plan with auto-generated 12 monthly KPI records.

    - Admin only (Manager cannot create plans).
    - Validates seasonal_weights, annual_enrollment_target, guardrails.
    - Distributes M_t via Largest Remainder Method (sum == annual_target).
    - Computes 4 derived KPIs per month.
    """
    plan, callback = await kpi_planning_service.create_plan(
        db,
        unit_id=data.unit_id,
        fiscal_year=data.fiscal_year,
        annual_target=data.annual_enrollment_target,
        sla_target=data.sla_target,
        response_time_target=data.response_time_target,
        seasonal_weights=data.seasonal_weights,
        officer_id=data.officer_id,
        created_by=current_user.id,
    )
    await db.commit()
    await db.refresh(plan)
    if callback:
        await callback()
    return plan


@router.get(
    "/plans",
    response_model=KpiPlanListResponse,
    summary="List KPI plans",
)
async def list_plans(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminOrManagerDep],
    fiscal_year: Optional[int] = Query(None, ge=2020, le=2100),
    unit_id: Optional[int] = Query(None),
    officer_id: Optional[int] = Query(None),
    is_active: Optional[bool] = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """
    List KPI plans with pagination and filters.

    IDOR: Manager sees only their own unit's plans (scope_unit_id forced).
    Admin sees all.
    """
    repo = KpiPlanningRepository(db)

    # IDOR: Manager scope forced at query layer
    scope_unit_id = None
    if current_user.role == "manager":
        scope_unit_id = current_user.unit_id

    plans, total = await repo.list_plans(
        fiscal_year=fiscal_year,
        unit_id=unit_id,
        officer_id=officer_id,
        is_active=is_active,
        scope_unit_id=scope_unit_id,
        skip=skip,
        limit=limit,
    )

    return KpiPlanListResponse(items=plans, total=total, skip=skip, limit=limit)


@router.get(
    "/plans/{plan_id}",
    response_model=KpiPlanResponse,
    summary="Get KPI plan detail with 12 months",
)
async def get_plan(
    plan: Annotated[KpiPlan, Depends(deps.get_kpi_plan_for_user)],
):
    """
    Get a single KPI plan with all 12 monthly breakdowns.

    IDOR enforced by get_kpi_plan_for_user dependency.
    """
    return plan


@router.put(
    "/plans/{plan_id}",
    response_model=KpiPlanResponse,
    summary="Update KPI plan",
)
async def update_plan(
    data: KpiPlanUpdate,
    plan: Annotated[KpiPlan, Depends(deps.get_kpi_plan_for_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """
    Update plan metadata (target, weights, guardrails) and regenerate derived KPIs.

    Admin only. IDOR enforced by dependency.
    Note: Full mid-year redistribute logic is Phase B6.
    """
    plan, callback = await kpi_planning_service.update_plan(
        db,
        plan=plan,
        annual_target=data.annual_enrollment_target,
        sla_target=data.sla_target,
        response_time_target=data.response_time_target,
        seasonal_weights=data.seasonal_weights,
    )
    await db.commit()
    await db.refresh(plan)
    if callback:
        await callback()
    return plan


@router.delete(
    "/plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete KPI plan",
)
async def delete_plan(
    plan: Annotated[KpiPlan, Depends(deps.get_kpi_plan_for_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """
    Soft-delete a KPI plan (set is_active = FALSE).

    Admin only. IDOR enforced by dependency.
    Note: Full KpiConfig cleanup (source_plan_id) is Phase B7.
    """
    _, callback = await kpi_planning_service.deactivate_plan(db, plan)
    await db.commit()
    if callback:
        await callback()


# =============================================================================
# CLONE PLAN (P5)
# =============================================================================

@router.post(
    "/plans/{plan_id}/clone",
    response_model=KpiPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Clone KPI plan to a new fiscal year",
)
async def clone_plan(
    data: KpiPlanCloneRequest,
    plan: Annotated[KpiPlan, Depends(deps.get_kpi_plan_for_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """
    Clone an existing KPI plan into a new fiscal year.

    Copies targets, weights, and guardrails. Generates 12 new months
    with recalculated working days for the target year.
    Admin only. IDOR enforced by dependency.
    """
    new_plan, callback = await kpi_planning_service.clone_plan(
        db,
        source_plan=plan,
        target_fiscal_year=data.fiscal_year,
        created_by=current_user.id,
    )
    await db.commit()
    await db.refresh(new_plan)
    if callback:
        await callback()
    return new_plan


# =============================================================================
# REGENERATE
# =============================================================================

@router.post(
    "/plans/{plan_id}/regenerate",
    response_model=KpiPlanResponse,
    summary="Force recalculate derived KPIs",
)
async def regenerate_plan(
    plan: Annotated[KpiPlan, Depends(deps.get_kpi_plan_for_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """
    Force recalculate all derived KPIs without changing inputs.
    Skips fields in overridden_fields (per-field granularity).

    Admin only. IDOR enforced by dependency.
    """
    plan, callback = await kpi_planning_service.generate_monthly_kpis(db, plan.id)
    await db.commit()
    await db.refresh(plan)
    if callback:
        await callback()
    return plan


# =============================================================================
# PREVIEW (dry-run, no persist)
# =============================================================================

@router.post(
    "/plans/preview",
    response_model=KpiPlanPreviewResponse,
    summary="Preview KPI plan (dry-run)",
)
async def preview_plan(
    data: KpiPlanPreview,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminOrManagerDep],
):
    """
    Dry-run: compute 12 monthly KPIs without creating any DB records.

    Frontend calls this endpoint (debounced 300ms) when admin adjusts
    weights slider. All computation is server-side (Thin Client Doctrine).
    """
    result = await kpi_planning_service.preview_plan(
        db,
        unit_id=data.unit_id,
        fiscal_year=data.fiscal_year,
        annual_target=data.annual_enrollment_target,
        sla_target=data.sla_target,
        response_time_target=data.response_time_target,
        seasonal_weights=data.seasonal_weights,
    )
    return result


# =============================================================================
# HOLIDAY STATUS (Phase A9)
# =============================================================================

@router.get(
    "/holidays/status/{year}",
    response_model=HolidayStatusResponse,
    summary="Check holiday calendar completeness for a year",
)
async def holiday_status(
    year: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminOrManagerDep],
):
    """
    Check if holiday_calendar is sufficiently seeded for the given year.

    Returns total holidays, whether lunar holidays are present, and a warning
    message if the calendar is incomplete. Used by Admin Dashboard to show
    a banner when holidays need to be configured for the next year.
    """
    return await get_holiday_status(db, year)


# =============================================================================
# MONTHLY OVERRIDE (Phase B1)
# =============================================================================

@router.put(
    "/months/{month_id}/override",
    response_model=MonthOverrideResponse,
    summary="Override derived KPI fields for a plan month",
)
async def override_month(
    data: MonthOverrideRequest,
    month: Annotated[KpiPlanMonth, Depends(deps.get_kpi_plan_month_for_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminOrManagerDep],
):
    """
    Override 1+ derived KPI fields for a specific plan month.

    Merges into overridden_fields — existing overrides on other fields are kept.
    Requires reason (>= 5 chars). IDOR enforced by dependency.
    """
    result, callback = await kpi_planning_service.override_month_kpi(
        db, plan_month=month, overrides=data.overrides,
        reason=data.reason, user_id=current_user.id,
    )
    await db.commit()
    await db.refresh(result)
    if callback:
        await callback()
    return result


@router.post(
    "/months/{month_id}/reset",
    response_model=MonthOverrideResponse,
    summary="Reset override for a plan month",
)
async def reset_month(
    data: MonthResetRequest,
    month: Annotated[KpiPlanMonth, Depends(deps.get_kpi_plan_month_for_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminOrManagerDep],
):
    """
    Reset overrides and recalculate derived KPIs.

    fields=null → reset ALL overrides, recalculate everything.
    fields=["consultations_daily"] → reset only that field.
    IDOR enforced by dependency.
    """
    result, callback = await kpi_planning_service.reset_month_override(
        db, plan_month=month, fields=data.fields, user_id=current_user.id,
    )
    await db.commit()
    await db.refresh(result)
    if callback:
        await callback()
    return result


@router.put(
    "/months/batch-override",
    response_model=BatchOverrideResponse,
    summary="Override same fields for multiple plan months",
)
async def batch_override_months(
    data: BatchOverrideRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """
    Apply the same overrides to multiple plan months (e.g. T6-T9).

    Admin only. Each month_id is validated via IDOR (404 if not found or
    plan inactive). Atomic — all succeed or none.
    """
    from app.repositories.kpi_planning_repository import KpiPlanningRepository

    repo = KpiPlanningRepository(db)
    updated_months = []

    for month_id in data.month_ids:
        pm = await repo.get_month_with_plan(month_id)
        if pm is None or not pm.plan.is_active:
            from app.utils.exceptions import ResourceNotFoundError
            raise ResourceNotFoundError(detail=f"KPI Plan Month {month_id} not found")

        result, _ = await kpi_planning_service.override_month_kpi(
            db, plan_month=pm, overrides=data.overrides,
            reason=data.reason, user_id=current_user.id,
        )
        updated_months.append(result)

    await db.commit()
    for m in updated_months:
        await db.refresh(m)

    return BatchOverrideResponse(updated=len(updated_months), months=updated_months)


# =============================================================================
# WORKING DAYS OVERRIDE (spec §7)
# =============================================================================

@router.put(
    "/months/{month_id}/working-days",
    response_model=MonthOverrideResponse,
    summary="Override working days for a plan month",
)
async def override_working_days(
    data: WorkingDaysOverrideRequest,
    month: Annotated[KpiPlanMonth, Depends(deps.get_kpi_plan_month_for_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """
    Override working_days for a specific plan month and regenerate derived KPIs.
    Admin only. IDOR enforced by dependency.
    """
    from datetime import datetime as dt, timezone as tz
    from decimal import Decimal

    overridden = dict(month.overridden_fields or {})
    month.working_days = data.working_days
    overridden["working_days"] = True
    month.overridden_fields = overridden
    month.override_reason = data.reason
    month.overridden_by = current_user.id
    month.overridden_at = dt.now(tz.utc)

    # Regenerate derived KPIs with new working_days
    derived = kpi_planning_service.compute_derived_kpis(
        month.enrollment_target, data.working_days,
        float(month.k_factor), month.lead_forecast, month.close_forecast,
    )
    for field, value in derived.items():
        if field not in overridden:
            setattr(month, field, value)

    await db.flush()
    await db.commit()
    await db.refresh(month)
    return month


# =============================================================================
# HOLIDAY CRUD (spec §7)
# =============================================================================

@router.get(
    "/holidays",
    response_model=HolidayListResponse,
    summary="List holidays",
)
async def list_holidays(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminOrManagerDep],
    year: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """List holidays with optional year filter. Admin/Manager."""
    from sqlalchemy import select, func
    from app.models.config import HolidayCalendar

    query = select(HolidayCalendar)
    count_query = select(func.count(HolidayCalendar.id))
    if year is not None:
        query = query.where(HolidayCalendar.year == year)
        count_query = count_query.where(HolidayCalendar.year == year)

    total = (await db.execute(count_query)).scalar_one()
    result = await db.execute(
        query.order_by(HolidayCalendar.date).offset(skip).limit(limit)
    )
    items = list(result.scalars().all())
    return HolidayListResponse(items=items, total=total)


@router.post(
    "/holidays",
    response_model=HolidayResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create holiday",
)
async def create_holiday(
    data: HolidayCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """Create a new holiday entry. Admin only."""
    from datetime import date as date_cls
    from sqlalchemy.exc import IntegrityError
    from fastapi import HTTPException
    from app.models.config import HolidayCalendar

    try:
        parsed_date = date_cls.fromisoformat(data.date)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Ngày không hợp lệ: {data.date}. Dùng YYYY-MM-DD.")

    holiday = HolidayCalendar(
        date=parsed_date,
        name=data.name,
        year=parsed_date.year,
        is_recurring=data.is_recurring,
        created_by=current_user.id,
    )
    db.add(holiday)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Ngày lễ {data.date} đã tồn tại")
    await db.refresh(holiday)
    return holiday


@router.put(
    "/holidays/{holiday_id}",
    response_model=HolidayResponse,
    summary="Update holiday",
)
async def update_holiday(
    holiday_id: int,
    data: HolidayUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """Update an existing holiday. Admin only."""
    from datetime import date as date_cls
    from app.models.config import HolidayCalendar
    from app.utils.exceptions import ResourceNotFoundError

    holiday = await db.get(HolidayCalendar, holiday_id)
    if not holiday:
        raise ResourceNotFoundError(detail="Holiday not found")

    if data.date is not None:
        try:
            parsed_date = date_cls.fromisoformat(data.date)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=f"Ngày không hợp lệ: {data.date}")
        holiday.date = parsed_date
        holiday.year = parsed_date.year
    if data.name is not None:
        holiday.name = data.name
    if data.is_recurring is not None:
        holiday.is_recurring = data.is_recurring

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            from fastapi import HTTPException
            raise HTTPException(status_code=409, detail=f"Ngày lễ {data.date} đã tồn tại")
        raise
    await db.refresh(holiday)
    return holiday


@router.delete(
    "/holidays/{holiday_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete holiday",
)
async def delete_holiday(
    holiday_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """Delete a holiday entry. Admin only."""
    from app.models.config import HolidayCalendar
    from app.utils.exceptions import ResourceNotFoundError

    holiday = await db.get(HolidayCalendar, holiday_id)
    if not holiday:
        raise ResourceNotFoundError(detail="Holiday not found")

    await db.delete(holiday)
    await db.commit()


@router.post(
    "/holidays/seed/{year}",
    response_model=HolidaySeedResponse,
    summary="Seed recurring holidays for a new year",
)
async def seed_holidays(
    year: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminDep],
):
    """
    Copy recurring holidays (is_recurring=TRUE) to create entries for the given year.
    Skips dates that already exist. Admin only.
    """
    from datetime import date as date_cls
    from sqlalchemy import select
    from app.models.config import HolidayCalendar

    # Find all recurring holidays
    result = await db.execute(
        select(HolidayCalendar).where(HolidayCalendar.is_recurring == True)  # noqa: E712
    )
    recurring = result.scalars().all()

    seeded = 0
    seen_dates = set()
    for h in recurring:
        try:
            new_date = date_cls(year, h.date.month, h.date.day)
        except ValueError:
            continue  # e.g. Feb 29 in non-leap year

        if new_date in seen_dates:
            continue
        seen_dates.add(new_date)

        # Check if already exists
        existing = await db.execute(
            select(HolidayCalendar.id).where(HolidayCalendar.date == new_date)
        )
        if existing.scalar_one_or_none() is not None:
            continue

        db.add(HolidayCalendar(
            date=new_date,
            name=h.name,
            year=year,
            is_recurring=True,
            created_by=current_user.id,
        ))
        seeded += 1

    await db.commit()
    return HolidaySeedResponse(year=year, seeded=seeded)


# =============================================================================
# FAIRNESS ANALYTICS (Phase P2-1)
# =============================================================================

@router.get(
    "/fairness",
    summary="Assignment fairness analytics",
)
async def fairness_analytics(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, AdminOrManagerDep],
    unit_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
):
    """
    Analyze assignment_decision_log for fairness metrics.
    Admin sees all units. Manager sees only own unit (IDOR: 404 on mismatch).
    """
    from datetime import datetime as dt
    from zoneinfo import ZoneInfo
    from fastapi import HTTPException
    from app.services.fairness_service import get_fairness_analytics
    from app.utils.exceptions import ResourceNotFoundError

    VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

    # IDOR: Manager must have unit_id and can only see own unit
    effective_unit = unit_id
    if current_user.role == "manager":
        if not current_user.unit_id:
            raise ResourceNotFoundError(detail="Fairness analytics not found")
        if unit_id is not None and unit_id != current_user.unit_id:
            raise ResourceNotFoundError(detail="Fairness analytics not found")  # 404, not 403
        effective_unit = current_user.unit_id

    # Parse dates with error handling
    parsed_from = None
    parsed_to = None
    try:
        if date_from:
            parsed_from = dt.fromisoformat(date_from).replace(tzinfo=VN_TZ)
        if date_to:
            parsed_to = dt.fromisoformat(date_to).replace(tzinfo=VN_TZ)
    except ValueError:
        raise HTTPException(status_code=400, detail="date_from/date_to phải đúng format YYYY-MM-DD")

    return await get_fairness_analytics(
        db, unit_id=effective_unit, date_from=parsed_from, date_to=parsed_to,
    )
