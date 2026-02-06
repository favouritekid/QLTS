# app/routers/pipeline.py
from typing import List

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import database, models, schemas
from ..core.deps import CasbinAuth  # ✅ Phase 2.2: Use standard alias
from ..services import pipeline_service
from app.core.rate_limits import limiter, RateLimits

router = APIRouter(tags=["Pipeline"])


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/stages", response_model=List[schemas.PipelineStage])
async def get_pipeline_stages(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Lấy danh sách tất cả các giai đoạn Pipeline (chỉ đọc)."""
    stages = await pipeline_service.get_all_pipeline_stages(db)
    return stages


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/all", response_model=schemas.FullPipeline)
async def get_full_pipeline(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    # <<< SỬA Ở ĐÂY: Đổi dependency để kiểm tra quyền >>>
    current_user: models.User = CasbinAuth,  # Yêu cầu Casbin check
    # Hoặc dùng: current_user: models.User = deps.OfficerRequired, # Nếu chỉ officer trở lên
):
    """Lấy toàn bộ cấu trúc Pipeline (Stages và Statuses)."""
    stages = await pipeline_service.get_all_pipeline_stages(db)
    statuses = await pipeline_service.get_all_consultation_statuses(db)
    return {"stages": stages, "statuses": statuses}


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/allowed-next-statuses", response_model=List[schemas.ConsultationStatus])
async def get_allowed_next_statuses(
    request: Request,
    current_status_id: str | None = None,
    lead_id: int | None = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get allowed next statuses using Phase-Based FSM Engine (Spec v3.0 compliant).

    Uses FSM engine with:
    - 7-step validation logic
    - Phase guards (user/role cannot cross phases)
    - Trigger type enforcement (hide system statuses)
    - NULL status rule (new lead → only NOT_CONTACTED)

    **Query Parameters:**
    - current_status_id (optional): Current consultation status ID
    - lead_id (optional): Lead ID to derive phase from admission_profile

    **Returns:**
    - List of allowed ConsultationStatus objects

    **Architecture:**
    - Dumb Router: Just coordinates FSM engine + returns result
    - Smart FSM Engine: Contains all business logic
    """
    from ..services.fsm_engine import get_next_statuses_for_lead
    from ..services.phase_manager import derive_phase_from_admission

    # Derive lead phase
    lead_phase = "consultation"  # Default phase for new/consultation leads

    if lead_id:
        # Get lead to derive phase
        lead = await db.get(
            models.Lead,
            lead_id,
            options=[selectinload(models.Lead.admission_profile)]
        )
        if lead and lead.admission_profile:
            lead_phase = derive_phase_from_admission(lead.admission_profile).value

    # ✅ USE NEW FSM ENGINE (Spec v3.0 compliant)
    return await get_next_statuses_for_lead(
        db=db,
        current_status_id=current_status_id,
        lead_phase=lead_phase,
        user_role=current_user.role
    )