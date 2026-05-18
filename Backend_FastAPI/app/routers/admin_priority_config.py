# app/routers/admin_priority_config.py
"""Admin priority_area_config + priority_object_config CRUD endpoints (Q9 #07 PR3).

Year-scoped routes following the ``admin_v2_admission_round`` pattern:
* ``/api/v2/admin/priority-config/years/{academic_year}/areas``
* ``/api/v2/admin/priority-config/years/{academic_year}/objects``
* ``/api/v2/admin/priority-config/areas/{area_id}`` (PATCH / DELETE)
* ``/api/v2/admin/priority-config/objects/{object_id}`` (PATCH / DELETE)
* ``/api/v2/admin/priority-config/clone`` (POST — copy active rows year→year)
* ``/api/v2/admin/priority-config/seed-defaults`` (POST — TT 05/2021 baseline)

All endpoints require ``require_admin`` — these are quy chế tuyển sinh
parameters, not per-unit operational data.
"""
import structlog
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import database
from app.core.deps import require_admin
from app.schemas.priority_config import (
    PriorityAreaConfigCreate,
    PriorityAreaConfigResponse,
    PriorityAreaConfigUpdate,
    PriorityConfigCloneRequest,
    PriorityConfigCloneResponse,
    PriorityConfigSeedDefaultsRequest,
    PriorityConfigSeedDefaultsResponse,
    PriorityObjectConfigCreate,
    PriorityObjectConfigResponse,
    PriorityObjectConfigUpdate,
)
from app.services.priority_config_service import PriorityConfigService


log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/admin/priority-config",
    tags=["Admin v2 - Priority Config"],
)


# =============================================================================
# Area endpoints
# =============================================================================


@router.get(
    "/years/{academic_year}/areas",
    response_model=list[PriorityAreaConfigResponse],
)
async def list_areas(
    academic_year: int,
    active_only: bool = True,
    db: AsyncSession = Depends(database.get_db),
    _user=Depends(require_admin),
) -> list[PriorityAreaConfigResponse]:
    service = PriorityConfigService(db)
    rows = await service.list_areas(academic_year, active_only=active_only)
    return [PriorityAreaConfigResponse.model_validate(r) for r in rows]


@router.post(
    "/years/{academic_year}/areas",
    response_model=PriorityAreaConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_area(
    academic_year: int,
    payload: PriorityAreaConfigCreate,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> PriorityAreaConfigResponse:
    # Force consistency: path param wins over body to prevent admin
    # accidentally posting to /years/2026 with year=2027 in payload.
    data = payload.model_dump()
    data["academic_year"] = academic_year
    service = PriorityConfigService(db)
    row, callback = await service.create_area(data)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "priority_area_config_created",
        id=row.id, academic_year=academic_year, area_code=row.area_code,
        bonus_points=str(row.bonus_points), actor=user.id,
    )
    return PriorityAreaConfigResponse.model_validate(row)


@router.patch(
    "/areas/{area_id}",
    response_model=PriorityAreaConfigResponse,
)
async def update_area(
    area_id: int,
    payload: PriorityAreaConfigUpdate,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> PriorityAreaConfigResponse:
    data = payload.model_dump(exclude_unset=True)
    service = PriorityConfigService(db)
    row, callback = await service.update_area(area_id, data)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "priority_area_config_updated",
        id=row.id, changed_keys=list(data.keys()), actor=user.id,
    )
    return PriorityAreaConfigResponse.model_validate(row)


@router.delete(
    "/areas/{area_id}",
    response_model=PriorityAreaConfigResponse,
)
async def retire_area(
    area_id: int,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> PriorityAreaConfigResponse:
    """Soft-delete via effective_to = today (temporal versioning)."""
    service = PriorityConfigService(db)
    row, callback = await service.retire_area(area_id)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "priority_area_config_retired",
        id=row.id, effective_to=str(row.effective_to), actor=user.id,
    )
    return PriorityAreaConfigResponse.model_validate(row)


# =============================================================================
# Object endpoints
# =============================================================================


@router.get(
    "/years/{academic_year}/objects",
    response_model=list[PriorityObjectConfigResponse],
)
async def list_objects(
    academic_year: int,
    active_only: bool = True,
    db: AsyncSession = Depends(database.get_db),
    _user=Depends(require_admin),
) -> list[PriorityObjectConfigResponse]:
    service = PriorityConfigService(db)
    rows = await service.list_objects(academic_year, active_only=active_only)
    return [PriorityObjectConfigResponse.model_validate(r) for r in rows]


@router.post(
    "/years/{academic_year}/objects",
    response_model=PriorityObjectConfigResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_object(
    academic_year: int,
    payload: PriorityObjectConfigCreate,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> PriorityObjectConfigResponse:
    data = payload.model_dump()
    data["academic_year"] = academic_year
    service = PriorityConfigService(db)
    row, callback = await service.create_object(data)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "priority_object_config_created",
        id=row.id, academic_year=academic_year, sub_code=row.sub_code,
        bonus_points=str(row.bonus_points), actor=user.id,
    )
    return PriorityObjectConfigResponse.model_validate(row)


@router.patch(
    "/objects/{object_id}",
    response_model=PriorityObjectConfigResponse,
)
async def update_object(
    object_id: int,
    payload: PriorityObjectConfigUpdate,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> PriorityObjectConfigResponse:
    data = payload.model_dump(exclude_unset=True)
    service = PriorityConfigService(db)
    row, callback = await service.update_object(object_id, data)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "priority_object_config_updated",
        id=row.id, changed_keys=list(data.keys()), actor=user.id,
    )
    return PriorityObjectConfigResponse.model_validate(row)


@router.delete(
    "/objects/{object_id}",
    response_model=PriorityObjectConfigResponse,
)
async def retire_object(
    object_id: int,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> PriorityObjectConfigResponse:
    service = PriorityConfigService(db)
    row, callback = await service.retire_object(object_id)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "priority_object_config_retired",
        id=row.id, effective_to=str(row.effective_to), actor=user.id,
    )
    return PriorityObjectConfigResponse.model_validate(row)


# =============================================================================
# Helpers: clone-from-year + seed-defaults
# =============================================================================


@router.post(
    "/clone",
    response_model=PriorityConfigCloneResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clone_from_year(
    payload: PriorityConfigCloneRequest,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> PriorityConfigCloneResponse:
    """Copy all ACTIVE area + object rows from from_year to to_year.
    Skips any (to_year, code) already active — re-run safe."""
    service = PriorityConfigService(db)
    result, callback = await service.clone_from_year(
        from_year=payload.from_year, to_year=payload.to_year
    )
    await db.commit()
    if callback:
        await callback()
    log.info(
        "priority_config_cloned",
        from_year=payload.from_year, to_year=payload.to_year,
        cloned_areas=result["cloned_areas"], cloned_objects=result["cloned_objects"],
        actor=user.id,
    )
    return PriorityConfigCloneResponse(**result)


@router.post(
    "/seed-defaults",
    response_model=PriorityConfigSeedDefaultsResponse,
    status_code=status.HTTP_201_CREATED,
)
async def seed_tt_05_2021_defaults(
    payload: PriorityConfigSeedDefaultsRequest,
    db: AsyncSession = Depends(database.get_db),
    user=Depends(require_admin),
) -> PriorityConfigSeedDefaultsResponse:
    """One-shot helper to bootstrap TT 05/2021 baseline rates for a
    target year. Idempotent — skips if any active row already exists."""
    service = PriorityConfigService(db)
    result, callback = await service.seed_tt_05_2021_defaults(payload.academic_year)
    await db.commit()
    if callback:
        await callback()
    log.info(
        "priority_config_seeded_tt_05_2021",
        academic_year=payload.academic_year,
        inserted_areas=result["inserted_areas"],
        inserted_objects=result["inserted_objects"],
        skipped_existing=result["skipped_existing"],
        actor=user.id,
    )
    return PriorityConfigSeedDefaultsResponse(**result)
