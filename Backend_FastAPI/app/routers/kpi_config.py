# app/routers/kpi_config.py
"""
KPI Configuration Admin API - Phase 5

CRUD endpoints for managing KPI configurations:
- List all KPI configs
- Create new config
- Update existing config
- Delete config

Admin-only access.

ARCHITECTURE: Pattern A (Router → Service → Repository)
"""
from typing import Annotated, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.core import deps
from app import models
from app.models.config import KpiConfig, KpiTarget
from app.services import kpi_service

router = APIRouter(prefix="/api/admin/kpi-config", tags=["Admin - KPI Configuration"])

# Permission dependency for Casbin RBAC
PermissionDep = Depends(deps.check_permission)


# =============================================================================
# SCHEMAS
# =============================================================================

class KpiConfigBase(BaseModel):
    """Base schema for KPI configuration."""
    kpi_code: str = Field(..., description="KPI identifier, e.g., 'consultations_daily'")
    target_value: int = Field(..., ge=0, description="Target value")
    period_type: str = Field(default="daily", description="daily, monthly, annual")
    unit_id: Optional[int] = Field(None, description="Unit ID for unit-level config (None = global)")
    officer_id: Optional[int] = Field(None, description="Officer ID for officer-specific config")
    

class KpiConfigCreate(KpiConfigBase):
    """Create KPI configuration."""
    pass


class KpiConfigUpdate(BaseModel):
    """Update KPI configuration."""
    target_value: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


class KpiConfigResponse(KpiConfigBase):
    """KPI configuration response."""
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class KpiTargetBase(BaseModel):
    """Base schema for annual KPI target."""
    kpi_code: str
    annual_target: int = Field(..., ge=0)
    fiscal_year: int
    unit_id: Optional[int] = None
    officer_id: Optional[int] = None


class KpiTargetCreate(KpiTargetBase):
    """Create annual KPI target."""
    pass


class KpiTargetResponse(KpiTargetBase):
    """Annual KPI target response."""
    id: int
    achieved_ytd: int
    is_active: bool
    last_sync_at: Optional[datetime]
    created_at: datetime
    
    class Config:
        from_attributes = True


# =============================================================================
# KPI CONFIG ENDPOINTS (Pattern A: Router → Service → Repository)
# =============================================================================

@router.get(
    "/configs",
    response_model=List[KpiConfigResponse],
    summary="List all KPI configurations"
)
async def list_kpi_configs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, PermissionDep],
    kpi_code: Optional[str] = None,
    unit_id: Optional[int] = None,
    is_active: bool = True,
):
    """List KPI configurations with optional filters. Admin only."""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    return await kpi_service.list_kpi_configs(
        db, kpi_code=kpi_code, unit_id=unit_id, is_active=is_active
    )


@router.post(
    "/configs",
    response_model=KpiConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create KPI configuration"
)
async def create_kpi_config(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, PermissionDep],
    data: KpiConfigCreate,
):
    """Create a new KPI configuration. Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        config, callback = await kpi_service.create_kpi_config(
            db,
            kpi_code=data.kpi_code,
            target_value=data.target_value,
            period_type=data.period_type,
            unit_id=data.unit_id,
            officer_id=data.officer_id,
            created_by=current_user,
        )
        await db.commit()
        await db.refresh(config)
        await callback()
        return config
    except kpi_service.DuplicateConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put(
    "/configs/{config_id}",
    response_model=KpiConfigResponse,
    summary="Update KPI configuration"
)
async def update_kpi_config(
    config_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, PermissionDep],
    data: KpiConfigUpdate,
):
    """Update an existing KPI configuration. Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        config, callback = await kpi_service.update_kpi_config(
            db,
            config_id=config_id,
            target_value=data.target_value,
            is_active=data.is_active,
            updated_by=current_user,
        )
        await db.commit()
        await db.refresh(config)
        await callback()
        return config
    except kpi_service.ConfigNotFoundError:
        raise HTTPException(status_code=404, detail="Config not found")


@router.delete(
    "/configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete KPI configuration"
)
async def delete_kpi_config(
    config_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, PermissionDep],
):
    """Delete a KPI configuration (soft delete). Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        config, callback = await kpi_service.delete_kpi_config(
            db, config_id=config_id, deleted_by=current_user
        )
        await db.commit()
        await callback()
    except kpi_service.ConfigNotFoundError:
        raise HTTPException(status_code=404, detail="Config not found")


# =============================================================================
# KPI TARGET ENDPOINTS (Annual) - Pattern A
# =============================================================================

@router.get(
    "/targets",
    response_model=List[KpiTargetResponse],
    summary="List annual KPI targets"
)
async def list_kpi_targets(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, PermissionDep],
    fiscal_year: Optional[int] = None,
    kpi_code: Optional[str] = None,
    is_active: bool = True,
):
    """List annual KPI targets. Admin/Manager only."""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    return await kpi_service.list_kpi_targets(
        db, fiscal_year=fiscal_year, kpi_code=kpi_code, is_active=is_active
    )


@router.post(
    "/targets",
    response_model=KpiTargetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annual KPI target"
)
async def create_kpi_target(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, PermissionDep],
    data: KpiTargetCreate,
):
    """Create an annual KPI target for tracking YTD progress. Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        target, callback = await kpi_service.create_kpi_target(
            db,
            kpi_code=data.kpi_code,
            annual_target=data.annual_target,
            fiscal_year=data.fiscal_year,
            unit_id=data.unit_id,
            officer_id=data.officer_id,
            created_by=current_user,
        )
        await db.commit()
        await db.refresh(target)
        await callback()
        return target
    except kpi_service.DuplicateTargetError as e:
        raise HTTPException(status_code=400, detail=str(e))


class KpiTargetUpdate(BaseModel):
    """Update annual KPI target."""
    annual_target: Optional[int] = Field(None, ge=0)
    is_active: Optional[bool] = None


@router.put(
    "/targets/{target_id}",
    response_model=KpiTargetResponse,
    summary="Update annual KPI target"
)
async def update_kpi_target(
    target_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, PermissionDep],
    data: KpiTargetUpdate,
):
    """Update an existing annual KPI target. Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        target, callback = await kpi_service.update_kpi_target(
            db,
            target_id=target_id,
            annual_target=data.annual_target,
            is_active=data.is_active,
            updated_by=current_user,
        )
        await db.commit()
        await db.refresh(target)
        await callback()
        return target
    except kpi_service.TargetNotFoundError:
        raise HTTPException(status_code=404, detail="Target not found")


@router.delete(
    "/targets/{target_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete annual KPI target"
)
async def delete_kpi_target(
    target_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[models.User, PermissionDep],
):
    """Delete an annual KPI target (soft delete). Admin only."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        target, callback = await kpi_service.delete_kpi_target(
            db, target_id=target_id, deleted_by=current_user
        )
        await db.commit()
        await callback()
    except kpi_service.TargetNotFoundError:
        raise HTTPException(status_code=404, detail="Target not found")

