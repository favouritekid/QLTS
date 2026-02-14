# app/routers/admin/installment_plans.py
"""
Installment Plan Admin Router

Quản lý phương án trả góp (CRUD):
- GET: Danh sách tất cả plans (active + inactive)
- POST: Tạo plan mới
- PUT: Cập nhật plan
- DELETE: Soft/hard delete plan
"""
from typing import List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import CasbinAuth
from app.core.rate_limits import limiter, RateLimits
from app.schemas import finance as finance_schemas
from app.models.finance import InstallmentPlan, Fee

log = structlog.get_logger(__name__)

router = APIRouter(tags=["Admin - Installment Plans"])


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


# =============================================================================
# CRUD ENDPOINTS
# =============================================================================

@limiter.limit(RateLimits.ADMIN_READ)
@router.get(
    "/installment-plans",
    response_model=List[finance_schemas.InstallmentPlanResponse],
    summary="Lấy danh sách phương án trả góp (admin)",
)
async def list_installment_plans(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Lấy danh sách tất cả phương án trả góp (bao gồm inactive).
    Endpoint admin - trả ALL plans cho quản lý.
    """
    query = select(InstallmentPlan).order_by(InstallmentPlan.installment_count)
    result = await db.execute(query)
    plans = list(result.scalars().all())

    return [_build_plan_response(plan) for plan in plans]


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.post(
    "/installment-plans",
    response_model=finance_schemas.InstallmentPlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo phương án trả góp mới",
)
async def create_installment_plan(
    request: Request,
    plan_data: finance_schemas.InstallmentPlanCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Tạo phương án trả góp mới."""
    # Check duplicate code
    existing = await db.execute(
        select(InstallmentPlan).where(InstallmentPlan.code == plan_data.code)
    )
    if existing.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Phương án với mã '{plan_data.code}' đã tồn tại"
        )

    plan = InstallmentPlan(
        code=plan_data.code,
        name=plan_data.name,
        description=plan_data.description,
        installment_count=plan_data.installment_count,
        schedule=[item.model_dump() for item in plan_data.schedule],
        penalty_type=plan_data.penalty_type,
        penalty_rate=plan_data.penalty_rate,
        grace_period_days=plan_data.grace_period_days,
        is_active=plan_data.is_active,
    )
    db.add(plan)
    await db.commit()
    await db.refresh(plan)

    log.info("installment_plan_created", plan_id=plan.id, code=plan.code, by=current_user.id)

    return _build_plan_response(plan)


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.put(
    "/installment-plans/{plan_id}",
    response_model=finance_schemas.InstallmentPlanResponse,
    summary="Cập nhật phương án trả góp",
)
async def update_installment_plan(
    request: Request,
    plan_id: int,
    plan_data: finance_schemas.InstallmentPlanUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Cập nhật phương án trả góp.

    Nếu plan đang được tham chiếu bởi fee, không cho phép thay đổi
    installment_count và schedule.
    """
    result = await db.execute(
        select(InstallmentPlan).where(InstallmentPlan.id == plan_id)
    )
    plan = result.scalars().first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy phương án với ID {plan_id}"
        )

    update_data = plan_data.model_dump(exclude_unset=True)

    # Check if plan is in use by any fee
    if "installment_count" in update_data or "schedule" in update_data:
        fee_exists = await db.execute(
            select(exists().where(Fee.installment_plan_id == plan_id))
        )
        if fee_exists.scalar():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể thay đổi lịch trả góp của phương án đang được sử dụng"
            )

    # Cross-validate schedule length against installment_count
    # Handles edge case: schedule sent without installment_count (direct API)
    if "schedule" in update_data and update_data["schedule"] is not None:
        expected_count = update_data.get("installment_count", plan.installment_count)
        actual_count = len(update_data["schedule"])
        if actual_count != expected_count:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Schedule must have exactly {expected_count} items, got {actual_count}"
            )

    # Apply partial update
    for field, value in update_data.items():
        if field == "schedule" and value is not None:
            setattr(plan, field, [item.model_dump() for item in value])
        else:
            setattr(plan, field, value)

    await db.commit()
    await db.refresh(plan)

    log.info("installment_plan_updated", plan_id=plan.id, code=plan.code, by=current_user.id)

    return _build_plan_response(plan)


@limiter.limit(RateLimits.ADMIN_DELETE)
@router.delete(
    "/installment-plans/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa phương án trả góp",
)
async def delete_installment_plan(
    request: Request,
    plan_id: int,
    hard_delete: bool = Query(False, description="Xóa vĩnh viễn (mặc định: soft delete)"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Xóa phương án trả góp.

    - **hard_delete=false** (mặc định): Soft delete - đánh dấu is_active=false
    - **hard_delete=true**: Xóa vĩnh viễn khỏi database
    """
    result = await db.execute(
        select(InstallmentPlan).where(InstallmentPlan.id == plan_id)
    )
    plan = result.scalars().first()
    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy phương án với ID {plan_id}"
        )

    if hard_delete:
        await db.delete(plan)
        log.info("installment_plan_hard_deleted", plan_id=plan_id, code=plan.code, by=current_user.id)
    else:
        plan.is_active = False
        log.info("installment_plan_soft_deleted", plan_id=plan_id, code=plan.code, by=current_user.id)

    await db.commit()
