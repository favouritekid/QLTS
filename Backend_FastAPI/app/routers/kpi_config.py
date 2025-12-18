# app/routers/kpi_config.py
"""
KPI Configuration Admin API - Phase 5

CRUD endpoints for managing KPI configurations:
- List all KPI configs
- Create new config
- Update existing config
- Delete config

Admin-only access.
"""
from typing import Annotated, List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.database import get_db
from app.core import deps
from app import models
from app.models.config import KpiConfig, KpiTarget

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
# KPI CONFIG ENDPOINTS
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
    """
    List KPI configurations with optional filters.
    Admin only.
    """
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    query = select(KpiConfig)
    
    if kpi_code:
        query = query.where(KpiConfig.kpi_code == kpi_code)
    if unit_id is not None:
        query = query.where(KpiConfig.unit_id == unit_id)
    if is_active is not None:
        query = query.where(KpiConfig.is_active == is_active)
    
    query = query.order_by(KpiConfig.kpi_code, KpiConfig.unit_id, KpiConfig.officer_id)
    
    result = await db.execute(query)
    return result.scalars().all()


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
    """
    Create a new KPI configuration.
    
    Scope is determined by unit_id and officer_id:
    - Both None = Global default
    - unit_id only = Unit-level
    - officer_id = Officer-specific
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Check for existing active config with same scope
    existing_query = select(KpiConfig).where(
        KpiConfig.kpi_code == data.kpi_code,
        KpiConfig.unit_id == data.unit_id,
        KpiConfig.officer_id == data.officer_id,
        KpiConfig.period_type == data.period_type,
        KpiConfig.is_active == True,
    )
    existing = (await db.execute(existing_query)).scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Active config already exists for this scope. Update or deactivate it first."
        )
    
    config = KpiConfig(
        kpi_code=data.kpi_code,
        target_value=data.target_value,
        period_type=data.period_type,
        unit_id=data.unit_id,
        officer_id=data.officer_id,
        is_active=True,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    
    return config


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
    """Update an existing KPI configuration."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    config = await db.get(KpiConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    
    if data.target_value is not None:
        config.target_value = data.target_value
    if data.is_active is not None:
        config.is_active = data.is_active
    
    await db.commit()
    await db.refresh(config)
    
    return config


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
    """Delete a KPI configuration (soft delete by setting is_active=False)."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    config = await db.get(KpiConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    
    config.is_active = False
    await db.commit()


# =============================================================================
# KPI TARGET ENDPOINTS (Annual)
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
):
    """List annual KPI targets."""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    query = select(KpiTarget).where(KpiTarget.is_active == True)
    
    if fiscal_year:
        query = query.where(KpiTarget.fiscal_year == fiscal_year)
    if kpi_code:
        query = query.where(KpiTarget.kpi_code == kpi_code)
    
    query = query.order_by(KpiTarget.fiscal_year.desc(), KpiTarget.kpi_code)
    
    result = await db.execute(query)
    return result.scalars().all()


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
    """Create an annual KPI target for tracking YTD progress."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    target = KpiTarget(
        kpi_code=data.kpi_code,
        annual_target=data.annual_target,
        fiscal_year=data.fiscal_year,
        unit_id=data.unit_id,
        officer_id=data.officer_id,
        is_active=True,
        achieved_ytd=0,
    )
    db.add(target)
    await db.commit()
    await db.refresh(target)
    
    return target
