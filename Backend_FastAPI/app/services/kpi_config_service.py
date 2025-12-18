# app/services/kpi_config_service.py
"""
KPI Configuration Service - Pattern A Implementation

Business logic layer between Router and Repository.
Following standard: Router → Service → Repository
"""

from typing import List, Optional, Tuple, Callable, Any, Awaitable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.models.config import KpiConfig, KpiTarget
from app.repositories import KpiRepository

log = structlog.get_logger(__name__)

# Type alias for callback
Callback = Callable[[], Awaitable[None]]


class DuplicateConfigError(Exception):
    """Raised when attempting to create a duplicate KPI config."""
    pass


class ConfigNotFoundError(Exception):
    """Raised when KPI config is not found."""
    pass


class TargetNotFoundError(Exception):
    """Raised when KPI target is not found."""
    pass


# =============================================================================
# KPI CONFIG CRUD
# =============================================================================

async def list_kpi_configs(
    db: AsyncSession,
    kpi_code: Optional[str] = None,
    unit_id: Optional[int] = None,
    is_active: bool = True,
) -> List[KpiConfig]:
    """
    List KPI configurations with filters.
    
    Args:
        db: Database session
        kpi_code: Optional filter by KPI code
        unit_id: Optional filter by unit
        is_active: Filter by active status
        
    Returns:
        List of KpiConfig objects
    """
    repo = KpiRepository(db)
    return await repo.list_configs(kpi_code=kpi_code, unit_id=unit_id, is_active=is_active)


async def create_kpi_config(
    db: AsyncSession,
    kpi_code: str,
    target_value: int,
    period_type: str = "daily",
    unit_id: Optional[int] = None,
    officer_id: Optional[int] = None,
    created_by: Optional[models.User] = None,
) -> Tuple[KpiConfig, Callback]:
    """
    Create a new KPI configuration.
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Args:
        db: Database session
        kpi_code: KPI identifier
        target_value: Target value
        period_type: Period type (daily, monthly, annual)
        unit_id: Optional unit scope
        officer_id: Optional officer scope
        created_by: User creating the config
        
    Returns:
        Tuple of (KpiConfig, callback)
        
    Raises:
        DuplicateConfigError: If active config already exists for this scope
    """
    repo = KpiRepository(db)
    
    # Check for duplicates
    existing = await repo.check_duplicate_exists(
        kpi_code=kpi_code,
        period_type=period_type,
        unit_id=unit_id,
        officer_id=officer_id,
    )
    
    if existing:
        raise DuplicateConfigError(
            f"Active config already exists for {kpi_code} with this scope"
        )
    
    # Create config
    config = KpiConfig(
        kpi_code=kpi_code,
        target_value=target_value,
        period_type=period_type,
        unit_id=unit_id,
        officer_id=officer_id,
        is_active=True,
    )
    db.add(config)
    
    # Post-commit callback (for notifications, logging, etc.)
    async def callback():
        log.info(
            "KPI config created",
            config_id=config.id,
            kpi_code=kpi_code,
            created_by=created_by.id if created_by else None,
        )
    
    return config, callback


async def update_kpi_config(
    db: AsyncSession,
    config_id: int,
    target_value: Optional[int] = None,
    is_active: Optional[bool] = None,
    updated_by: Optional[models.User] = None,
) -> Tuple[KpiConfig, Callback]:
    """
    Update an existing KPI configuration.
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Args:
        db: Database session
        config_id: Config ID to update
        target_value: New target value (optional)
        is_active: New active status (optional)
        updated_by: User performing the update
        
    Returns:
        Tuple of (KpiConfig, callback)
        
    Raises:
        ConfigNotFoundError: If config not found
    """
    config = await db.get(KpiConfig, config_id)
    if not config:
        raise ConfigNotFoundError(f"Config {config_id} not found")
    
    # Track changes
    changes = []
    
    if target_value is not None and config.target_value != target_value:
        old_value = config.target_value
        config.target_value = target_value
        changes.append(f"target_value: {old_value} → {target_value}")
    
    if is_active is not None and config.is_active != is_active:
        config.is_active = is_active
        changes.append(f"is_active: {is_active}")
    
    # Post-commit callback
    async def callback():
        if changes:
            log.info(
                "KPI config updated",
                config_id=config_id,
                changes=changes,
                updated_by=updated_by.id if updated_by else None,
            )
    
    return config, callback


async def delete_kpi_config(
    db: AsyncSession,
    config_id: int,
    deleted_by: Optional[models.User] = None,
) -> Tuple[KpiConfig, Callback]:
    """
    Soft delete a KPI configuration (set is_active=False).
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Args:
        db: Database session
        config_id: Config ID to delete
        deleted_by: User performing the delete
        
    Returns:
        Tuple of (KpiConfig, callback)
        
    Raises:
        ConfigNotFoundError: If config not found
    """
    config = await db.get(KpiConfig, config_id)
    if not config:
        raise ConfigNotFoundError(f"Config {config_id} not found")
    
    config.is_active = False
    
    async def callback():
        log.info(
            "KPI config deleted",
            config_id=config_id,
            deleted_by=deleted_by.id if deleted_by else None,
        )
    
    return config, callback


# =============================================================================
# KPI TARGET CRUD (Annual targets)
# =============================================================================

async def list_kpi_targets(
    db: AsyncSession,
    fiscal_year: Optional[int] = None,
    kpi_code: Optional[str] = None,
) -> List[KpiTarget]:
    """
    List annual KPI targets with filters.
    
    Args:
        db: Database session
        fiscal_year: Optional filter by year
        kpi_code: Optional filter by KPI code
        
    Returns:
        List of KpiTarget objects
    """
    repo = KpiRepository(db)
    return await repo.list_targets(fiscal_year=fiscal_year, kpi_code=kpi_code)


async def create_kpi_target(
    db: AsyncSession,
    kpi_code: str,
    annual_target: int,
    fiscal_year: int,
    unit_id: Optional[int] = None,
    officer_id: Optional[int] = None,
    created_by: Optional[models.User] = None,
) -> Tuple[KpiTarget, Callback]:
    """
    Create an annual KPI target.
    
    Pattern A: Returns (result, callback) for transaction control.
    """
    target = KpiTarget(
        kpi_code=kpi_code,
        annual_target=annual_target,
        fiscal_year=fiscal_year,
        unit_id=unit_id,
        officer_id=officer_id,
        is_active=True,
        achieved_ytd=0,
    )
    db.add(target)
    
    async def callback():
        log.info(
            "KPI target created",
            target_id=target.id,
            kpi_code=kpi_code,
            fiscal_year=fiscal_year,
            created_by=created_by.id if created_by else None,
        )
    
    return target, callback
