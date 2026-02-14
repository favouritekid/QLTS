# app/routers/installment_plans.py
"""
Router for Installment Plan Management (Finance Module Phase 4).

Architecture Compliance:
- Router Layer: Orchestration only (no business logic)
- RBAC: All endpoints protected by CasbinAuth dependency

Endpoints:
- GET /api/installment-plans - List installment plans
- GET /api/installment-plans/{id} - Get installment plan details
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app import database, models
from app.core.deps import CasbinAuth
from app.core.rate_limits import limiter, RateLimits
from app.schemas import finance as finance_schemas
from app.models.finance import InstallmentPlan

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/installment-plans", tags=["Finance - Installment Plans"])


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "",
    response_model=List[finance_schemas.InstallmentPlanResponse],
    summary="List installment plans",
)
async def list_installment_plans(
    request: Request,
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    List available installment plans.

    **Security:**
    - Requires authentication
    - No IDOR check (installment plans are global configuration)
    """
    query = select(InstallmentPlan).order_by(InstallmentPlan.installment_count)

    if is_active is not None:
        query = query.where(InstallmentPlan.is_active == is_active)

    result = await db.execute(query)
    plans = list(result.scalars().all())

    return [_build_plan_response(plan) for plan in plans]


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/{plan_id}",
    response_model=finance_schemas.InstallmentPlanResponse,
    summary="Get installment plan details",
)
async def get_installment_plan(
    request: Request,
    plan_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get installment plan details.

    **Security:**
    - Requires authentication
    """
    query = select(InstallmentPlan).where(InstallmentPlan.id == plan_id)
    result = await db.execute(query)
    plan = result.scalars().first()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Installment plan {plan_id} not found"
        )

    return _build_plan_response(plan)


def _build_plan_response(plan: InstallmentPlan) -> finance_schemas.InstallmentPlanResponse:
    """Build InstallmentPlanResponse from InstallmentPlan model."""
    return finance_schemas.InstallmentPlanResponse(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        description=plan.description,
        installment_count=plan.installment_count,
        schedule=[
            finance_schemas.InstallmentScheduleItem(**item)
            for item in plan.schedule
        ],
        penalty_type=plan.penalty_type,
        penalty_rate=plan.penalty_rate,
        grace_period_days=plan.grace_period_days,
        is_active=plan.is_active,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )
