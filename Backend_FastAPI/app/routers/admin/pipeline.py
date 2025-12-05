# app/routers/admin/pipeline.py
"""
Pipeline Management Admin Router

Handles all pipeline workflow operations including:
- Pipeline Stages (workflow phases)
- Consultation Statuses (states within stages)
- Allowed Transitions (workflow rules)
- Lead Status Revert (admin override)

PHASE 2C: Extracted from monolithic admin.py
Dependencies: pipeline_service, lead_service (from PHASE 1)

Complexity: MEDIUM (state machine logic, workflow rules)
"""
from app.core.rate_limits import limiter, RateLimits  # ✅ Rate limiting

from typing import List, Optional

import structlog
from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models, schemas
from app.core import deps
from app.services import lead_service, pipeline_service
from app.utils.exceptions import BadRequest, ResourceNotFoundError

log = structlog.get_logger(__name__)

# Router definition
router = APIRouter(tags=["Admin - Pipeline Management"])

# Permission dependency
PermissionDep = Depends(deps.check_permission)


# ============================================================================
# PIPELINE STAGES MANAGEMENT
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/pipeline-stages",
    response_model=List[schemas.PipelineStage],
)
async def get_all_pipeline_stages_list(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy danh sách tất cả Giai đoạn (Stages) trong Pipeline."""
    # Gọi service function đã có (trả về List[dict] từ cache/DB)
    # Pydantic sẽ tự động chuyển đổi List[dict] -> List[schemas.PipelineStage]
    stages_data = await pipeline_service.get_all_pipeline_stages(db)
    return stages_data


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/pipeline-stages",
    response_model=schemas.PipelineStage,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_pipeline_stage(
    request: Request,
    stage_in: schemas.PipelineStageCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Giai đoạn (Stage) mới trong Pipeline."""
    stage, callback = await pipeline_service.create_pipeline_stage(db, stage_in, current_user=current_admin)
    await db.commit()
    await callback()

    # ✅ NOTIFICATION 2.0: Dispatch PIPELINE_CONFIG_UPDATED
    try:
        from app.services.notification_dispatcher import dispatch
        from app.core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.PIPELINE_CONFIG_UPDATED,
            payload={
                "config_type": "pipeline_stage",
                "operation": "create",
                "resource_id": stage.id,
                "resource_name": stage.name,
                "actor_id": current_admin.id,
            },
            dedupe_key=f"pipeline_config:create:stage:{stage.id}"
        )
    except Exception as e:
        log.warning("Failed to dispatch PIPELINE_CONFIG_UPDATED", error=str(e))

    return stage


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/pipeline-stages/{stage_id}",
    response_model=schemas.PipelineStage,
)
async def get_pipeline_stage_details(
    request: Request,
    stage_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một Giai đoạn (Stage)."""
    return await pipeline_service.get_pipeline_stage(db, stage_id)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/pipeline-stages/{stage_id}",
    response_model=schemas.PipelineStage,
)
async def update_existing_pipeline_stage(
    request: Request,
    stage_id: str,
    stage_in: schemas.PipelineStageUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một Giai đoạn (Stage)."""
    stage, callback = await pipeline_service.update_pipeline_stage(db, stage_id, stage_in, current_user=current_admin)
    await db.commit()
    await callback()

    # ✅ NOTIFICATION 2.0: Dispatch PIPELINE_CONFIG_UPDATED
    try:
        from app.services.notification_dispatcher import dispatch
        from app.core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.PIPELINE_CONFIG_UPDATED,
            payload={
                "config_type": "pipeline_stage",
                "operation": "update",
                "resource_id": stage_id,
                "resource_name": stage.name,
                "actor_id": current_admin.id,
            },
            dedupe_key=f"pipeline_config:update:stage:{stage_id}"
        )
    except Exception as e:
        log.warning("Failed to dispatch PIPELINE_CONFIG_UPDATED", error=str(e))

    return stage


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/pipeline-stages/{stage_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_existing_pipeline_stage(
    request: Request,
    stage_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xoá một Giai đoạn (Stage). (Chỉ thành công nếu không có Status nào liên kết)"""
    _, callback = await pipeline_service.delete_pipeline_stage(db, stage_id, current_user=current_admin)
    await db.commit()
    await callback()

    # ✅ NOTIFICATION 2.0: Dispatch PIPELINE_CONFIG_UPDATED
    try:
        from app.services.notification_dispatcher import dispatch
        from app.core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.PIPELINE_CONFIG_UPDATED,
            payload={
                "config_type": "pipeline_stage",
                "operation": "delete",
                "resource_id": stage_id,
                "resource_name": stage_id,
                "actor_id": current_admin.id,
            },
            dedupe_key=f"pipeline_config:delete:stage:{stage_id}"
        )
    except Exception as e:
        log.warning("Failed to dispatch PIPELINE_CONFIG_UPDATED", error=str(e))

    return None


# ============================================================================
# CONSULTATION STATUSES MANAGEMENT
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/consultation-statuses",
    response_model=List[schemas.ConsultationStatus],
)
async def get_all_consultation_statuses_list(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy danh sách tất cả Trạng thái tư vấn (Consultation Statuses)."""
    # Gọi service function đã có (trả về List[dict] từ cache/DB)
    # Pydantic sẽ tự động chuyển đổi List[dict] -> List[schemas.ConsultationStatus]
    statuses_data = await pipeline_service.get_all_consultation_statuses(db)
    return statuses_data


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/consultation-statuses",
    response_model=schemas.ConsultationStatus,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_consultation_status(
    request: Request,
    status_in: schemas.ConsultationStatusCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Trạng thái tư vấn (Status) mới."""
    consultation_status, callback = await pipeline_service.create_consultation_status(db, status_in, current_user=current_admin)
    await db.commit()
    await callback()

    # ✅ NOTIFICATION 2.0: Dispatch PIPELINE_CONFIG_UPDATED
    try:
        from app.services.notification_dispatcher import dispatch
        from app.core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.PIPELINE_CONFIG_UPDATED,
            payload={
                "config_type": "consultation_status",
                "operation": "create",
                "resource_id": consultation_status.id,
                "resource_name": consultation_status.name,
                "actor_id": current_admin.id,
            },
            dedupe_key=f"pipeline_config:create:status:{consultation_status.id}"
        )
    except Exception as e:
        log.warning("Failed to dispatch PIPELINE_CONFIG_UPDATED", error=str(e))

    return consultation_status


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/consultation-statuses/{status_id}",
    response_model=schemas.ConsultationStatus,
)
async def get_consultation_status_details(
    request: Request,
    status_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy chi tiết một Trạng thái tư vấn (Status)."""
    return await pipeline_service.get_consultation_status(db, status_id)


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.put(
    "/consultation-statuses/{status_id}",
    response_model=schemas.ConsultationStatus,
)
async def update_existing_consultation_status(
    request: Request,
    status_id: str,
    status_in: schemas.ConsultationStatusUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Cập nhật một Trạng thái tư vấn (Status)."""
    consultation_status, callback = await pipeline_service.update_consultation_status(db, status_id, status_in, current_user=current_admin)
    await db.commit()
    await callback()

    # ✅ NOTIFICATION 2.0: Dispatch PIPELINE_CONFIG_UPDATED
    try:
        from app.services.notification_dispatcher import dispatch
        from app.core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.PIPELINE_CONFIG_UPDATED,
            payload={
                "config_type": "consultation_status",
                "operation": "update",
                "resource_id": status_id,
                "resource_name": consultation_status.name,
                "actor_id": current_admin.id,
            },
            dedupe_key=f"pipeline_config:update:status:{status_id}"
        )
    except Exception as e:
        log.warning("Failed to dispatch PIPELINE_CONFIG_UPDATED", error=str(e))

    return consultation_status


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/consultation-statuses/{status_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_existing_consultation_status(
    request: Request,
    status_id: str,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xoá một Trạng thái tư vấn (Status). (Chỉ thành công nếu không có Lead nào sử dụng)"""
    _, callback = await pipeline_service.delete_consultation_status(db, status_id, current_user=current_admin)
    await db.commit()
    await callback()

    # ✅ NOTIFICATION 2.0: Dispatch PIPELINE_CONFIG_UPDATED
    try:
        from app.services.notification_dispatcher import dispatch
        from app.core.events import SystemEvents
        await dispatch(
            db=db,
            event=SystemEvents.PIPELINE_CONFIG_UPDATED,
            payload={
                "config_type": "consultation_status",
                "operation": "delete",
                "resource_id": status_id,
                "resource_name": status_id,
                "actor_id": current_admin.id,
            },
            dedupe_key=f"pipeline_config:delete:status:{status_id}"
        )
    except Exception as e:
        log.warning("Failed to dispatch PIPELINE_CONFIG_UPDATED", error=str(e))

    return None


# ============================================================================
# ALLOWED TRANSITIONS MANAGEMENT
# ============================================================================


@limiter.limit(RateLimits.ADMIN_READ)  # 300/hour
@router.get(
    "/allowed-transitions",
    response_model=List[schemas.AllowedTransition],
)
async def get_all_allowed_transitions(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Lấy danh sách tất cả Allowed Transitions (workflow rules)."""
    transitions = await pipeline_service.get_all_allowed_transitions(db)
    return transitions


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/allowed-transitions",
    response_model=schemas.AllowedTransition,
    status_code=status.HTTP_201_CREATED,
)
async def create_new_allowed_transition(
    request: Request,
    transition_in: schemas.AllowedTransitionCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Tạo một Allowed Transition mới."""
    transition, callback = await pipeline_service.create_allowed_transition(db, transition_in, current_user=current_admin)
    await db.commit()
    await callback()
    return transition


@limiter.limit(RateLimits.ADMIN_DELETE)  # 50/hour
@router.delete(
    "/allowed-transitions/{transition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_existing_allowed_transition(
    request: Request,
    transition_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = PermissionDep,
):
    """(Admin only) Xoá một Allowed Transition."""
    _, callback = await pipeline_service.delete_allowed_transition(db, transition_id, current_user=current_admin)
    await db.commit()
    await callback()
    return None


# ============================================================================
# LEAD STATUS OPERATIONS
# ============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)  # 100/hour
@router.post(
    "/leads/{lead_id}/revert-status",
    response_model=schemas.Lead,
    tags=["Admin - Lead Management"],
    summary="Admin reverts the last status change of a Lead",
)
async def admin_revert_lead_status(
    request: Request,
    lead_id: int,
    current_user: models.User = PermissionDep,
    reason: Optional[str] = Body(
        None, embed=True, description="Reason for reverting the status"
    ),
    db: AsyncSession = Depends(database.get_db),
):
    """
    (Admin only) Hoàn tác thay đổi trạng thái cuối cùng của một Lead.

    Endpoint này cho phép admin hoàn tác thay đổi trạng thái cuối cùng
    của một lead, giúp sửa lỗi hoặc điều chỉnh workflow.

    Args:
        lead_id: ID of the lead to revert status
        current_user: Current admin user (injected by PermissionDep)
        reason: Optional reason for reverting
        db: Database session

    Returns:
        Updated lead with reverted status

    Raises:
        HTTPException 404: Lead not found or no history to revert
        HTTPException 400: Invalid revert operation
        HTTPException 500: Internal server error
    """
    try:
        # Admin permission already checked by PermissionDep
        updated_lead = await lead_service.revert_last_status(
            db=db, lead_id=lead_id, admin_user=current_user, reason=reason
        )
        return updated_lead
    except (BadRequest, ResourceNotFoundError) as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        log.error(
            "Error reverting lead status via API",
            lead_id=lead_id,
            admin_id=current_user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to revert lead status.",
        )