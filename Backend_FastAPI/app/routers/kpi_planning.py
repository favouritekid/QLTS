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
    KpiPlanCreate,
    KpiPlanListResponse,
    KpiPlanPreview,
    KpiPlanPreviewResponse,
    KpiPlanResponse,
    KpiPlanUpdate,
)
from app.services import kpi_planning_service

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
