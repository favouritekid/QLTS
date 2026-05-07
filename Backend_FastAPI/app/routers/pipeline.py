# app/routers/pipeline.py
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .. import database, models, schemas
from ..core.deps import CasbinAuth, LeadListFilter, get_lead_list_filter  # ✅ Phase 2.2: Use standard alias
from ..services import pipeline_service
from app.core.rate_limits import limiter, RateLimits

router = APIRouter(tags=["Pipeline"])


@limiter.limit(RateLimits.DATA_READ)
@router.get("/loss-reasons", response_model=List[schemas.LossReason])
async def get_loss_reasons(
    request: Request,
    current_user: models.User = CasbinAuth,
):
    """Get all loss reason codes (read-only taxonomy)."""
    return pipeline_service.get_loss_reasons()


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
    current_user: models.User = CasbinAuth,  # Casbin RBAC check
):
    """Lấy toàn bộ cấu trúc Pipeline (Stages và Statuses)."""
    stages = await pipeline_service.get_all_pipeline_stages(db)
    statuses = await pipeline_service.get_all_consultation_statuses(db)
    return {"stages": stages, "statuses": statuses}


@limiter.limit(RateLimits.DATA_READ)  # 1000/hour
@router.get("/board")
async def get_pipeline_board(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    # ✅ Role-scope: officer sees own leads, manager sees unit, admin sees all
    lead_filter: LeadListFilter = Depends(get_lead_list_filter),
    unit_id: Optional[int] = Query(None, description="Filter leads by organization unit"),
    officer_id: Optional[int] = Query(None, description="Filter leads by assigned officer"),
    date_from: Optional[str] = Query(None, description="Filter leads from this date (ISO format)"),
    date_to: Optional[str] = Query(None, description="Filter leads until this date (ISO format)"),
    include_leads: bool = Query(True, description="Include lead details in each stage"),
    include_stats: bool = Query(True, description="Include conversion stats"),
):
    """
    Pipeline board endpoint: stages + leads grouped by stage + analytics.

    Supports filtering by unit, officer, and date range.
    Returns full board data for Kanban rendering.

    **RBAC:** Officers see only their leads, Managers see their unit only.
    """
    # Apply role-enforced scope (same pattern as leads list endpoint)
    effective_officer_id = None
    if lead_filter.assigned_officer_id:
        effective_officer_id = int(lead_filter.assigned_officer_id.split(",")[0])
    effective_unit_id = lead_filter.unit_id

    return await pipeline_service.get_pipeline_board(
        db,
        unit_id=effective_unit_id or unit_id,
        officer_id=effective_officer_id or officer_id,
        date_from=date_from,
        date_to=date_to,
        include_leads=include_leads,
        include_stats=include_stats,
    )


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
        # Get lead to derive phase. Wave 4 #15b: relationship is plural
        # (``admission_profiles``); resolve the current-intake-year profile
        # via the helper before deriving phase.
        from ..services.system_config_service import SystemConfigService

        lead = await db.get(
            models.Lead,
            lead_id,
            options=[selectinload(models.Lead.admission_profiles)]
        )
        if lead:
            current_year = await SystemConfigService(db).get_value(
                "current_intake_year", 2026
            )
            if isinstance(current_year, str):
                current_year = int(current_year)
            current_profile = lead.current_admission_profile(current_year)
            if current_profile:
                lead_phase = derive_phase_from_admission(current_profile).value

    # ✅ USE NEW FSM ENGINE (Spec v3.0 compliant)
    return await get_next_statuses_for_lead(
        db=db,
        current_status_id=current_status_id,
        lead_phase=lead_phase,
        user_role=current_user.role
    )