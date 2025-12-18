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
    
    Priority order:
    1. Officer-specific (if officer_id provided)
    2. Unit-level (if unit_id provided)
    3. Global default (unit_id IS NULL, officer_id IS NULL)
    4. Hardcoded default (if no config exists)
    
    Args:
        db: Database session
        kpi_code: KPI identifier (e.g., 'consultations_daily')
        officer_id: Optional officer ID for officer-specific target
        unit_id: Optional unit ID for unit-level target
        period_type: Period type ('daily', 'monthly', etc.)
    
    Returns:
        Target value as integer
    """
    # 1. Try officer-specific
    if officer_id:
        result = await db.execute(
            select(models.KpiConfig.target_value)
            .where(
                models.KpiConfig.officer_id == officer_id,
                models.KpiConfig.kpi_code == kpi_code,
                models.KpiConfig.period_type == period_type,
                models.KpiConfig.is_active == True,
            )
        )
        target = result.scalar_one_or_none()
        if target is not None:
            log.debug("KPI target found", level="officer", officer_id=officer_id, kpi_code=kpi_code, value=target)
            return target

    # 2. Try unit-level
    if unit_id:
        result = await db.execute(
            select(models.KpiConfig.target_value)
            .where(
                models.KpiConfig.unit_id == unit_id,
                models.KpiConfig.officer_id.is_(None),
                models.KpiConfig.kpi_code == kpi_code,
                models.KpiConfig.period_type == period_type,
                models.KpiConfig.is_active == True,
            )
        )
        target = result.scalar_one_or_none()
        if target is not None:
            log.debug("KPI target found", level="unit", unit_id=unit_id, kpi_code=kpi_code, value=target)
            return target

    # 3. Try global default
    result = await db.execute(
        select(models.KpiConfig.target_value)
        .where(
            models.KpiConfig.unit_id.is_(None),
            models.KpiConfig.officer_id.is_(None),
            models.KpiConfig.kpi_code == kpi_code,
            models.KpiConfig.period_type == period_type,
            models.KpiConfig.is_active == True,
        )
    )
    target = result.scalar_one_or_none()
    if target is not None:
        log.debug("KPI target found", level="global", kpi_code=kpi_code, value=target)
        return target

    # 4. Fallback to hardcoded default
    default = DEFAULT_KPIS.get(kpi_code, 0)
    log.debug("KPI target using hardcoded default", kpi_code=kpi_code, value=default)
    return default


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
    
    # Get officer's unit_id for fallback
    user = await db.get(models.User, officer_id)
    unit_id = user.unit_id if user else None
    
    # Try to find annual target (officer → unit → org)
    result = await db.execute(
        select(models.KpiTarget)
        .where(
            or_(
                models.KpiTarget.officer_id == officer_id,
                and_(
                    models.KpiTarget.unit_id == unit_id,
                    models.KpiTarget.officer_id.is_(None)
                ) if unit_id else False,
                and_(
                    models.KpiTarget.unit_id.is_(None),
                    models.KpiTarget.officer_id.is_(None)
                )
            ),
            models.KpiTarget.kpi_code == kpi_code,
            models.KpiTarget.fiscal_year == fiscal_year,
            models.KpiTarget.is_active == True,
        )
        .order_by(
            # Priority: officer-specific first, then unit, then global
            models.KpiTarget.officer_id.desc().nulls_last(),
            models.KpiTarget.unit_id.desc().nulls_last(),
        )
        .limit(1)
    )
    target_record = result.scalar_one_or_none()
    
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
    
    Returns:
        Dict of kpi_code -> actual YTD value
    """
    if fiscal_year is None:
        fiscal_year = datetime.now(timezone.utc).year
    
    synced = {}
    
    # Sync enrollments YTD
    enrollments_query = (
        select(models.Lead)
        .join(models.ConsultationStatus)
        .where(
            models.Lead.assigned_officer_id == officer_id,
            models.ConsultationStatus.is_final_status == True,
            models.ConsultationStatus.outcome_type == "positive",
            models.Lead.updated_at >= datetime(fiscal_year, 1, 1, tzinfo=timezone.utc),
            models.Lead.updated_at < datetime(fiscal_year + 1, 1, 1, tzinfo=timezone.utc),
        )
    )
    result = await db.execute(enrollments_query)
    enrollments_ytd = len(result.scalars().all())
    synced["enrollments"] = enrollments_ytd
    
    # Update kpi_target record
    from sqlalchemy import update
    await db.execute(
        update(models.KpiTarget)
        .where(
            models.KpiTarget.officer_id == officer_id,
            models.KpiTarget.kpi_code == "enrollments",
            models.KpiTarget.fiscal_year == fiscal_year,
        )
        .values(
            achieved_ytd=enrollments_ytd,
            last_sync_at=datetime.now(timezone.utc),
        )
    )
    
    log.info(
        "Synced officer YTD",
        officer_id=officer_id,
        fiscal_year=fiscal_year,
        synced=synced,
    )
    
    return synced
