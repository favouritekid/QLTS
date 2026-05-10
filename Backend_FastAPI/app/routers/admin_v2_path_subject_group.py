# app/routers/admin_v2_path_subject_group.py
"""Admin v2 — PathSubjectGroupConfig CRUD + clone endpoint (Phase 2 v8.2 PR-2D)."""

import structlog
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import require_admin
from app.core.rate_limits import RateLimits, limiter
from app.schemas.path_subject_group import (
    ClonePathsRequest,
    ClonePathsResponse,
    PathSubjectGroupConfigCreate,
    PathSubjectGroupConfigListResponse,
    PathSubjectGroupConfigResponse,
    PathSubjectGroupConfigUpdate,
    PathSubjectGroupItemCreate,
    PathSubjectGroupItemResponse,
)
from app.services import activity_service
from app.services.path_clone_service import PathCloneService
from app.services.path_subject_group_service import PathSubjectGroupService


log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/admin",
    tags=["Admin v2 - Path Subject Group"],
)


# =============================================================================
# CRUD: PathSubjectGroupConfig
# =============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.post(
    "/admission-paths/{admission_path_id}/subject-group-configs",
    response_model=PathSubjectGroupConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_config(
    request: Request,
    admission_path_id: int,
    payload: PathSubjectGroupConfigCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Create path subject group config với items."""
    service = PathSubjectGroupService(db)
    config = await service.create_config(admission_path_id, payload)
    await db.commit()
    await db.refresh(config, ["items"])

    await activity_service.log_activity(
        db=db,
        action="path_subject_group_config_create",
        resource_type="path_subject_group_config",
        resource_id=config.id,
        actor_id=current_admin.id,
        description=(
            f"Created config path={admission_path_id}, "
            f"subject_group={payload.subject_group_id}"
        ),
    )
    return config


@router.get(
    "/admission-paths/{admission_path_id}/subject-group-configs",
    response_model=PathSubjectGroupConfigListResponse,
)
async def list_configs(
    request: Request,
    admission_path_id: int,
    db: AsyncSession = Depends(database.get_db),
    _admin: models.User = Depends(require_admin),
):
    """List all configs trên a given admission_path."""
    service = PathSubjectGroupService(db)
    configs = await service.repo.list_configs_by_path(admission_path_id)
    return PathSubjectGroupConfigListResponse(total=len(configs), items=configs)


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.patch(
    "/path-subject-group-configs/{config_id}",
    response_model=PathSubjectGroupConfigResponse,
)
async def update_config(
    request: Request,
    config_id: int,
    payload: PathSubjectGroupConfigUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Update score thresholds + group_quota (Tier 3 re-validation)."""
    service = PathSubjectGroupService(db)
    config = await service.update_config(config_id, payload)
    await db.commit()
    await db.refresh(config, ["items"])

    await activity_service.log_activity(
        db=db,
        action="path_subject_group_config_update",
        resource_type="path_subject_group_config",
        resource_id=config_id,
        actor_id=current_admin.id,
        description=f"Updated config {config_id}",
    )
    return config


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.delete(
    "/path-subject-group-configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_config(
    request: Request,
    config_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Delete config + cascade items."""
    service = PathSubjectGroupService(db)
    await service.delete_config(config_id)
    await db.commit()

    await activity_service.log_activity(
        db=db,
        action="path_subject_group_config_delete",
        resource_type="path_subject_group_config",
        resource_id=config_id,
        actor_id=current_admin.id,
        description=f"Deleted config {config_id}",
    )


# =============================================================================
# Item endpoints
# =============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.post(
    "/path-subject-group-configs/{config_id}/items",
    response_model=PathSubjectGroupItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    request: Request,
    config_id: int,
    payload: PathSubjectGroupItemCreate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Add single item to existing config (composite invariant guard)."""
    service = PathSubjectGroupService(db)
    item = await service.add_item(config_id, payload)
    await db.commit()
    return item


# =============================================================================
# Clone endpoint (Q6 v8.2 deep-copy)
# =============================================================================


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.post(
    "/rounds/{target_round_id}/clone-paths-from/{source_round_id}",
    response_model=ClonePathsResponse,
)
async def clone_paths_from_round(
    request: Request,
    target_round_id: int,
    source_round_id: int,
    payload: ClonePathsRequest,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Deep-copy admission paths từ source round to target round (Q6 v8.2).

    Atomic transaction: clone criteria + criteria_subject_group +
    admission_path + path_subject_group_config + items.
    ON CONFLICT (3-col UNIQUE) skip; return cloned + skipped counts + IDs.
    """
    service = PathCloneService(db)
    response = await service.clone_paths_from_round(
        target_round_id=target_round_id,
        source_round_id=source_round_id,
        payload=payload,
    )
    await db.commit()

    await activity_service.log_activity(
        db=db,
        action="admission_paths_cloned",
        resource_type="offering_admission_round",
        resource_id=target_round_id,
        actor_id=current_admin.id,
        description=(
            f"Cloned {response.cloned_count} paths từ round {source_round_id} "
            f"→ round {target_round_id} (skipped {response.skipped_count})"
        ),
    )
    return response
