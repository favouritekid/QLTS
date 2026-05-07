# app/routers/admin_v2_system_config.py
"""Admin v2 — system_config CRUD endpoints (#184 Wave 1 PR-1D /
phase1_13).

Closes B4 P0 blocker — exposes the runtime config table to admin
via HTTP. Mirrors the T0-5 admin_v2_casbin pattern: ``/api/v2/admin``
prefix, ``Depends(require_admin)`` for write, ``ADMIN_WRITE`` rate
limit, structlog audit.

Endpoints
---------
* ``GET /api/v2/admin/system-config`` — list all config rows.
  Read-permissive (any active user) since some keys (e.g.
  ``current_intake_year``) need to flow into FE storefront.
* ``GET /api/v2/admin/system-config/{key}`` — single row.
* ``PATCH /api/v2/admin/system-config/{key}`` — admin-only mutate.
  ``BusinessRuleViolation`` from service layer is translated to
  403 by the global exception handler.

Sensitive keys MUST NOT be stored in ``system_config`` (use env
vars / encrypted secrets) because the read path is permissive.
"""
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import database, models
from app.core.deps import get_current_active_user, require_admin
from app.core.rate_limits import RateLimits, limiter
from app.schemas.system_config import (
    SystemConfigListResponse,
    SystemConfigResponse,
    SystemConfigUpdate,
)
from app.services import activity_service
from app.services.system_config_service import SystemConfigService


log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/admin/system-config",
    tags=["Admin v2 - System Config"],
)


@router.get("", response_model=SystemConfigListResponse)
async def list_system_config(
    db: AsyncSession = Depends(database.get_db),
    _user: models.User = Depends(get_current_active_user),
):
    """List all config rows ordered by key.

    Read-permissive — FE storefront may need ``current_intake_year``
    for anonymous flows; service guard rejects mutation only.
    """
    service = SystemConfigService(db)
    rows = await service.list_all()
    return SystemConfigListResponse(
        total=len(rows),
        items=[SystemConfigResponse.model_validate(r) for r in rows],
    )


@router.get("/{key}", response_model=SystemConfigResponse)
async def get_system_config(
    key: str,
    db: AsyncSession = Depends(database.get_db),
    _user: models.User = Depends(get_current_active_user),
):
    """Fetch a single config row by key. 404 when key absent."""
    service = SystemConfigService(db)
    row = await service.get_by_key(key)
    return SystemConfigResponse.model_validate(row)


@limiter.limit(RateLimits.ADMIN_WRITE)
@router.patch("/{key}", response_model=SystemConfigResponse)
async def patch_system_config(
    request: Request,
    key: str,
    payload: SystemConfigUpdate,
    db: AsyncSession = Depends(database.get_db),
    current_admin: models.User = Depends(require_admin),
):
    """Admin-only update.

    Service raises ``BusinessRuleViolation`` if a non-admin
    somehow reaches this (defense-in-depth — the
    ``Depends(require_admin)`` already 403s before the service runs).
    """
    service = SystemConfigService(db)
    row, post_commit = await service.update(key, payload, current_admin)

    # Audit row — admin-write changelog beyond the system_config
    # row's own ``updated_at`` / ``updated_by_user_id`` columns.
    await activity_service.log_activity(
        db=db,
        action="system_config_update",
        resource_type="system_config",
        actor_id=current_admin.id,
        description=f"system_config updated: key='{key}'",
        changes={
            "key": key,
            "value_set": payload.value,
            "description_set": payload.description,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    await db.commit()
    if post_commit:
        await post_commit()

    log.info(
        "system_config_updated",
        actor_id=current_admin.id,
        key=key,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

    return SystemConfigResponse.model_validate(row)
