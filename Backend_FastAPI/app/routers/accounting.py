# app/routers/accounting.py
"""
Router for Accounting Period Management (Finance Module Phase 4).

Architecture Compliance:
- Router Layer: Orchestration only (no business logic)
- Transaction Management: Router calls db.commit() after service returns
- RBAC: All endpoints protected by CasbinAuth dependency
- Error Handling: Convert custom exceptions to HTTPException

Endpoints:
- GET /api/accounting/periods - List accounting periods
- POST /api/accounting/periods - Create accounting period (admin)
- GET /api/accounting/periods/{id} - Get period details
- PUT /api/accounting/periods/{id}/close - Close accounting period (admin)
- GET /api/accounting/periods/{id}/summary - Get period summary report
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app import database, models, schemas
from app.core import deps
from app.core.deps import CasbinAuth, require_admin
from app.core.rate_limits import limiter, RateLimits
from app.schemas import finance as finance_schemas
from app.services.accounting_service import AccountingPeriodService
from app.models.finance import AccountingPeriod
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/accounting", tags=["Finance - Accounting"])


# H1 cleanup (2026-05-14): the local ``def get_client_ip`` previously
# living here was dead code — never used as a slowapi ``key_func`` in
# this file and never imported elsewhere. The canonical XFF-aware
# implementation lives in ``app.core.client_ip`` and is consumed by
# ``admissions.py`` + ``admissions_magic_link.py`` only.


# ==============================================================================
# ACCOUNTING PERIOD ENDPOINTS
# ==============================================================================

@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/periods",
    response_model=List[finance_schemas.AccountingPeriodResponse],
    summary="List accounting periods",
)
async def list_periods(
    request: Request,
    year: Optional[int] = Query(None, ge=2020, le=2100, description="Filter by year"),
    is_closed: Optional[bool] = Query(None, description="Filter by closed status"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    List accounting periods with optional filters.

    **Security:**
    - Requires authentication
    - Requires 'accounting:read' permission
    """
    # Build query with filters
    query = select(AccountingPeriod).order_by(
        AccountingPeriod.period_year.desc(),
        AccountingPeriod.period_month.desc(),
    )

    if year is not None:
        query = query.where(AccountingPeriod.period_year == year)

    if is_closed is not None:
        query = query.where(AccountingPeriod.is_closed == is_closed)

    result = await db.execute(query)
    periods = list(result.scalars().all())

    return [_build_period_response(p) for p in periods]


@limiter.limit(RateLimits.DATA_WRITE)
@router.post(
    "/periods",
    response_model=finance_schemas.AccountingPeriodResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create accounting period",
)
async def create_period(
    request: Request,
    data: finance_schemas.AccountingPeriodCreate,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Create a new accounting period.

    **Business Rules:**
    - Only one open period allowed at a time
    - Previous period must be closed before creating new one
    - Month/year combination must be unique

    **Security:**
    - Requires admin role
    - Requires 'accounting:create' permission
    """
    accounting_service = AccountingPeriodService(db)

    try:
        period, _ = await accounting_service.create_period(
            month=data.month,
            year=data.year,
            user_id=current_user.id,
        )

        await db.commit()

        log.info(
            "accounting_period_created",
            period_id=period.id,
            month=data.month,
            year=data.year,
            user_id=current_user.id,
        )

        await db.refresh(period)
        return _build_period_response(period)

    except BadRequest as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/periods/current",
    response_model=Optional[finance_schemas.AccountingPeriodResponse],
    summary="Get current open period",
)
async def get_current_period(
    request: Request,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get the current open accounting period.

    **Returns:**
    - Current open period or null if none exists

    **Security:**
    - Requires authentication
    - Requires 'accounting:read' permission
    """
    accounting_service = AccountingPeriodService(db)

    period = await accounting_service.get_current_period()

    if not period:
        return None

    return _build_period_response(period)


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/periods/{period_id}",
    response_model=finance_schemas.AccountingPeriodResponse,
    summary="Get period details",
)
async def get_period(
    request: Request,
    period_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get accounting period details.

    **Security:**
    - Requires authentication
    - Requires 'accounting:read' permission
    """
    # Get period by ID
    query = select(AccountingPeriod).where(AccountingPeriod.id == period_id)
    result = await db.execute(query)
    period = result.scalars().first()

    if not period:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Accounting period {period_id} not found"
        )

    return _build_period_response(period)


@limiter.limit(RateLimits.DATA_WRITE)
@router.put(
    "/periods/{period_id}/close",
    response_model=finance_schemas.AccountingPeriodResponse,
    summary="Close accounting period",
)
async def close_period(
    request: Request,
    period_id: int,
    notes: Optional[str] = Query(None, max_length=500, description="Closing notes"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Close an accounting period.

    **Business Rules:**
    - Only open periods can be closed
    - All pending payments should be resolved
    - Period cannot be reopened after closing

    **Security:**
    - Requires admin role
    - Requires 'accounting:close' permission
    """
    # Get period by ID first
    query = select(AccountingPeriod).where(AccountingPeriod.id == period_id)
    result = await db.execute(query)
    period = result.scalars().first()

    if not period:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Accounting period {period_id} not found"
        )

    accounting_service = AccountingPeriodService(db)

    try:
        period, _ = await accounting_service.close_period(
            month=period.period_month,
            year=period.period_year,
            user_id=current_user.id,
            notes=notes,
        )

        await db.commit()

        log.info(
            "accounting_period_closed",
            period_id=period_id,
            user_id=current_user.id,
        )

        await db.refresh(period)
        return _build_period_response(period)

    except ResourceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BusinessRuleViolation as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/periods/{period_id}/summary",
    summary="Get period summary report",
)
async def get_period_summary(
    request: Request,
    period_id: int,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get summary report for an accounting period.

    **Returns:**
    - Total payments received
    - Total refunds issued
    - Net revenue
    - Period status

    **Security:**
    - Requires authentication
    - Requires 'accounting:read' permission
    """
    # Get period by ID
    query = select(AccountingPeriod).where(AccountingPeriod.id == period_id)
    result = await db.execute(query)
    period = result.scalars().first()

    if not period:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Accounting period {period_id} not found"
        )

    return {
        "period_id": period.id,
        "period_key": period.period_key,
        "month": period.period_month,
        "year": period.period_year,
        "is_closed": period.is_closed,
        "total_payments": str(period.total_payments),
        "total_refunds": str(period.total_refunds),
        "net_revenue": str(period.net_revenue),
        "opened_at": period.created_at.isoformat() if period.created_at else None,
        "closed_at": period.closed_at.isoformat() if period.closed_at else None,
    }


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

def _build_period_response(period) -> finance_schemas.AccountingPeriodResponse:
    """Build AccountingPeriodResponse from AccountingPeriod model."""
    return finance_schemas.AccountingPeriodResponse(
        id=period.id,
        month=period.period_month,
        year=period.period_year,
        is_closed=period.is_closed,
        closed_at=period.closed_at,
        closed_by_id=period.closed_by_id,
        total_payments=period.total_payments,
        total_refunds=period.total_refunds,
        net_revenue=period.net_revenue,
        created_at=period.created_at,
    )
