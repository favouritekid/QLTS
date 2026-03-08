# app/services/kpi_service.py
"""
KPI Service - Phase 1 & 6

Provides functions for:
1. Getting KPI targets with inheritance (global → unit → officer)
2. Calculating rolling monthly targets
3. Syncing YTD progress (for Celery job)
4. Generating auto recommendations (Phase 7)
"""
import structlog
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app import models

log = structlog.get_logger(__name__)


# =============================================================================
# DEFAULT KPI VALUES (fallback if no config exists)
# =============================================================================

DEFAULT_KPIS = {
    "consultations_daily": 10,
    "conversion_rate": 15,  # percentage
    "response_time_hours": 2,
    "enrollments_monthly": 7,
    "enrollments_annual": 80,
    "sla_compliance_rate": 80,  # 80% target
    "consultation_effectiveness": 50,  # 50% target
}


# =============================================================================
# KPI CONFIG RETRIEVAL (with inheritance)
# =============================================================================

async def get_kpi_target(
    db: AsyncSession,
    kpi_code: str,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    period_type: str = "daily"
) -> int:
    """
    Get KPI target value with inheritance.
    
    REFACTORED: Uses KpiRepository for data access.
    
    Priority order:
    1. Officer-specific (if officer_id provided)
    2. Unit-level (if unit_id provided)
    3. Global default (unit_id IS NULL, officer_id IS NULL)
    4. Hardcoded default (if no config exists)
    """
    from ..repositories import KpiRepository
    
    repo = KpiRepository(db)
    default = DEFAULT_KPIS.get(kpi_code, 0)
    
    target = await repo.get_kpi_target_with_inheritance(
        kpi_code=kpi_code,
        officer_id=officer_id,
        unit_id=unit_id,
        period_type=period_type,
        default=default
    )
    
    log.debug("KPI target resolved", kpi_code=kpi_code, value=target)
    return target


async def get_all_kpi_targets(
    db: AsyncSession,
    officer_id: Optional[int] = None,
    unit_id: Optional[int] = None,
) -> Dict[str, int]:
    """
    Get all configured KPI targets for an officer/unit.
    
    Returns dict of kpi_code -> target_value
    """
    targets = {}
    
    for kpi_code in DEFAULT_KPIS.keys():
        # Determine period_type based on kpi_code
        if "daily" in kpi_code or kpi_code == "response_time_hours":
            period_type = "daily"
        elif "annual" in kpi_code:
            period_type = "annual"
        else:
            period_type = "monthly"
        
        targets[kpi_code] = await get_kpi_target(
            db, kpi_code, officer_id, unit_id, period_type
        )
    
    return targets


# =============================================================================
# ROLLING TARGET CALCULATION (Phase 6)
# =============================================================================

async def get_annual_target_progress(
    db: AsyncSession,
    officer_id: int,
    kpi_code: str = "enrollments",
    fiscal_year: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get annual target progress for an officer.
    
    Returns:
        {
            "annual_target": 80,
            "achieved_ytd": 67,
            "remaining": 13,
            "progress_pct": 83.75,
            "months_left": 1,
            "monthly_target": 13.0,
            "status": "in_progress",  # or "completed", "at_risk"
            "on_track": True,
            "last_sync_at": datetime
        }
    """
    if fiscal_year is None:
        fiscal_year = datetime.now(timezone.utc).year
    
    # ✅ REFACTORED: Use repository for data access
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    # Get officer's unit_id for fallback
    unit_id = await repo.get_user_unit_id(officer_id)
    
    # Try to find annual target (officer → unit → org)
    target_record = await repo.get_annual_target_with_priority(
        officer_id=officer_id,
        kpi_code=kpi_code,
        fiscal_year=fiscal_year,
        unit_id=unit_id,
    )
    
    if not target_record:
        return None
    
    annual = target_record.annual_target
    ytd = target_record.achieved_ytd
    remaining = max(0, annual - ytd)
    
    # Calculate months remaining
    now = datetime.now(timezone.utc)
    current_month = now.month
    months_left = 12 - current_month + 1  # Include current month
    
    # Calculate monthly target
    if ytd >= annual:
        status = "completed"
        monthly_target = 0
        surplus = ytd - annual
    elif months_left <= 0:
        status = "overdue"
        monthly_target = remaining
        surplus = 0
    else:
        monthly_target = remaining / months_left
        surplus = 0
        # Determine if on track
        expected_ytd = (annual / 12) * current_month
        if ytd >= expected_ytd * 0.9:
            status = "in_progress"
        else:
            status = "at_risk"
    
    progress_pct = (ytd / annual * 100) if annual > 0 else 0
    on_track = status != "at_risk"
    
    return {
        "kpi_code": kpi_code,
        "fiscal_year": fiscal_year,
        "annual_target": annual,
        "achieved_ytd": ytd,
        "remaining": remaining,
        "progress_pct": round(progress_pct, 1),
        "months_left": months_left,
        "monthly_target": round(monthly_target, 1),
        "status": status,
        "on_track": on_track,
        "surplus": surplus if status == "completed" else None,
        "last_sync_at": target_record.last_sync_at,
    }


async def calculate_monthly_target(
    db: AsyncSession,
    officer_id: int,
    kpi_code: str,
    month: int,
    year: int
) -> Dict[str, Any]:
    """
    Calculate rolling monthly target based on annual target and YTD progress.
    
    Formula: (annual_target - achieved_ytd) / months_remaining
    
    Returns:
        {
            "status": "in_progress" | "completed" | "overdue",
            "target": float,  # If in_progress
            "surplus": float,  # If completed
            "remaining": float,  # If overdue
        }
    """
    progress = await get_annual_target_progress(db, officer_id, kpi_code, year)
    
    if not progress:
        # No annual target configured, use default monthly
        default_monthly = DEFAULT_KPIS.get(f"{kpi_code}_monthly", 7)
        return {
            "status": "in_progress",
            "target": default_monthly,
        }
    
    if progress["status"] == "completed":
        return {
            "status": "completed",
            "surplus": progress["surplus"],
        }
    
    if month > 12:
        return {
            "status": "overdue",
            "remaining": progress["remaining"],
        }
    
    months_left = 12 - month + 1
    remaining = progress["remaining"]
    
    return {
        "status": "in_progress",
        "target": round(remaining / months_left, 1) if months_left > 0 else remaining,
    }


# =============================================================================
# YTD SYNC (for Celery job)
# =============================================================================

async def sync_officer_ytd(
    db: AsyncSession,
    officer_id: int,
    fiscal_year: Optional[int] = None,
) -> Dict[str, int]:
    """
    Sync achieved_ytd for an officer from actual data.
    Should be called by Celery job daily.
    
    ✅ REFACTORED: Uses KpiRepository for data access.
    
    Uses PipelineStage + ConsultationStatus for consistency with funnel chart:
    - PipelineStage.is_final_stage == True (lead has completed the funnel)
    - ConsultationStatus.counts_for_funnel == True (successful conversion)
    
    Returns:
        Dict of kpi_code -> actual YTD value
    """
    from ..repositories import KpiRepository
    
    if fiscal_year is None:
        fiscal_year = datetime.now(timezone.utc).year
    
    synced = {}
    repo = KpiRepository(db)
    
    # Sync enrollments YTD via repository
    # Count leads that reached FINAL pipeline stage with counts_for_funnel=True
    enrollments_ytd = await repo.count_enrollments_ytd(officer_id, fiscal_year)
    synced["enrollments"] = enrollments_ytd
    
    # Update kpi_target record via repository
    await repo.update_achieved_ytd(
        officer_id=officer_id,
        kpi_code="enrollments",
        fiscal_year=fiscal_year,
        ytd_value=enrollments_ytd,
    )
    
    log.info(
        "Synced officer YTD",
        officer_id=officer_id,
        fiscal_year=fiscal_year,
        synced=synced,
    )
    
    return synced


# =============================================================================
# KPI CONFIG CRUD (Admin Operations) - Pattern A
# =============================================================================

# Custom Exceptions
class DuplicateConfigError(Exception):
    """Raised when attempting to create a duplicate KPI config."""
    pass


class ConfigNotFoundError(Exception):
    """Raised when KPI config is not found."""
    pass


class TargetNotFoundError(Exception):
    """Raised when KPI target is not found."""
    pass


class DuplicateTargetError(Exception):
    """Raised when attempting to create a duplicate KPI target."""
    pass


# Type alias for callback
from typing import Callable, Awaitable, Tuple
Callback = Callable[[], Awaitable[None]]


async def list_kpi_configs(
    db: AsyncSession,
    kpi_code: Optional[str] = None,
    unit_id: Optional[int] = None,
    is_active: bool = True,
) -> List[models.KpiConfig]:
    """List KPI configurations with filters."""
    from ..repositories import KpiRepository
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
) -> Tuple[models.KpiConfig, Callback]:
    """
    Create a new KPI configuration.
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        DuplicateConfigError: If active config already exists for this scope
    """
    from ..repositories import KpiRepository
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
    config = models.KpiConfig(
        kpi_code=kpi_code,
        target_value=target_value,
        period_type=period_type,
        unit_id=unit_id,
        officer_id=officer_id,
        is_active=True,
    )
    db.add(config)
    
    # ✅ REFACTORED: Add flush/refresh as per guidelines
    await db.flush()
    await db.refresh(config)
    
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
) -> Tuple[models.KpiConfig, Callback]:
    """
    Update an existing KPI configuration.
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        ConfigNotFoundError: If config not found
    """
    # ✅ REFACTORED: Use repository for data access
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    config = await repo.get_config_by_id(config_id)
    if not config:
        raise ConfigNotFoundError(f"Config {config_id} not found")
    
    changes = []
    if target_value is not None and config.target_value != target_value:
        old_value = config.target_value
        config.target_value = target_value
        changes.append(f"target_value: {old_value} → {target_value}")
    
    if is_active is not None and config.is_active != is_active:
        config.is_active = is_active
        changes.append(f"is_active: {is_active}")
    
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
) -> Tuple[models.KpiConfig, Callback]:
    """
    Soft delete a KPI configuration (set is_active=False).
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        ConfigNotFoundError: If config not found
    """
    # ✅ REFACTORED: Use repository for data access
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    config = await repo.get_config_by_id(config_id)
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


async def list_kpi_targets(
    db: AsyncSession,
    fiscal_year: Optional[int] = None,
    kpi_code: Optional[str] = None,
    is_active: bool = True,
) -> List[models.KpiTarget]:
    """List annual KPI targets with filters."""
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    return await repo.list_targets(fiscal_year=fiscal_year, kpi_code=kpi_code, is_active=is_active)


async def create_kpi_target(
    db: AsyncSession,
    kpi_code: str,
    annual_target: int,
    fiscal_year: int,
    unit_id: Optional[int] = None,
    officer_id: Optional[int] = None,
    created_by: Optional[models.User] = None,
) -> Tuple[models.KpiTarget, Callback]:
    """
    Create an annual KPI target.
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        DuplicateTargetError: If active target already exists for this scope + year
    """
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    # Check for duplicates
    existing = await repo.check_duplicate_target_exists(
        kpi_code=kpi_code,
        fiscal_year=fiscal_year,
        unit_id=unit_id,
        officer_id=officer_id,
    )
    
    if existing:
        # Build scope description for error message
        if officer_id:
            scope = f"Cán bộ #{officer_id}"
        elif unit_id:
            scope = f"Đơn vị #{unit_id}"
        else:
            scope = "Toàn cục"
        
        raise DuplicateTargetError(
            f"Mục tiêu năm {fiscal_year} cho '{kpi_code}' phạm vi {scope} đã tồn tại"
        )
    
    target = models.KpiTarget(
        kpi_code=kpi_code,
        annual_target=annual_target,
        fiscal_year=fiscal_year,
        unit_id=unit_id,
        officer_id=officer_id,
        is_active=True,
        achieved_ytd=0,
    )
    db.add(target)
    
    # ✅ REFACTORED: Add flush/refresh as per guidelines
    await db.flush()
    await db.refresh(target)
    
    async def callback():
        log.info(
            "KPI target created",
            target_id=target.id,
            kpi_code=kpi_code,
            fiscal_year=fiscal_year,
            created_by=created_by.id if created_by else None,
        )
    
    return target, callback


async def update_kpi_target(
    db: AsyncSession,
    target_id: int,
    annual_target: Optional[int] = None,
    is_active: Optional[bool] = None,
    updated_by: Optional[models.User] = None,
) -> Tuple[models.KpiTarget, Callback]:
    """
    Update an existing KPI target.
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        TargetNotFoundError: If target not found
    """
    # ✅ REFACTORED: Use repository for data access
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    target = await repo.get_target_by_id(target_id)
    if not target:
        raise TargetNotFoundError(f"Target {target_id} not found")
    
    changes = []
    if annual_target is not None and target.annual_target != annual_target:
        old_value = target.annual_target
        target.annual_target = annual_target
        changes.append(f"annual_target: {old_value} → {annual_target}")
    
    if is_active is not None and target.is_active != is_active:
        target.is_active = is_active
        changes.append(f"is_active: {is_active}")
    
    async def callback():
        if changes:
            log.info(
                "KPI target updated",
                target_id=target_id,
                changes=changes,
                updated_by=updated_by.id if updated_by else None,
            )
    
    return target, callback


async def delete_kpi_target(
    db: AsyncSession,
    target_id: int,
    deleted_by: Optional[models.User] = None,
) -> Tuple[models.KpiTarget, Callback]:
    """
    Soft delete a KPI target (set is_active=False).
    
    Pattern A: Returns (result, callback) for transaction control.
    
    Raises:
        TargetNotFoundError: If target not found
    """
    # ✅ REFACTORED: Use repository for data access
    from ..repositories import KpiRepository
    repo = KpiRepository(db)
    
    target = await repo.get_target_by_id(target_id)
    if not target:
        raise TargetNotFoundError(f"Target {target_id} not found")
    
    target.is_active = False
    
    async def callback():
        log.info(
            "KPI target deleted",
            target_id=target_id,
            deleted_by=deleted_by.id if deleted_by else None,
        )
    
    return target, callback

