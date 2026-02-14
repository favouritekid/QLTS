# app/routers/finance_dashboard.py
"""
Router for Finance Dashboard (Finance Module Phase 4).

Architecture Compliance:
- Router Layer: Orchestration only (no business logic)
- RBAC: All endpoints protected by CasbinAuth dependency
- IDOR Protection: Unit-based access control

Endpoints:
- GET /api/finance/dashboard - Get finance dashboard statistics
"""

from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
import structlog

from app import database, models
from app.core.constants import UserRole
from app.core.deps import CasbinAuth
from app.core.rate_limits import limiter, RateLimits
from app.schemas import finance as finance_schemas
from app.models.finance import (
    Fee, Invoice, Payment, RefundRequest, OverpaymentRecord,
    FeeStatusEnum, InvoiceStatusEnum, PaymentStatusEnum,
    RefundStatusEnum, OverpaymentStatusEnum,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/finance", tags=["Finance - Dashboard"])


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/dashboard",
    response_model=finance_schemas.FinanceDashboardStats,
    summary="Get finance dashboard statistics",
)
async def get_dashboard_stats(
    request: Request,
    start_date: Optional[date] = Query(None, description="Start date for period collections (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date for period collections (YYYY-MM-DD)"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get finance dashboard statistics.

    **Query Parameters:**
    - start_date: Optional start date for period_collections calculation (default: 7 days ago)
    - end_date: Optional end date for period_collections calculation (default: today)

    **Returns:**
    - pending_fees_count: Number of fees pending payment
    - pending_fees_amount: Total amount of pending fees
    - pending_payments_count: Number of payments awaiting verification
    - overdue_invoices_count: Number of overdue invoices
    - overdue_amount: Total overdue amount
    - today_collections: Total collections today
    - monthly_collections: Total collections this month
    - period_collections: Total collections for custom date range
    - pending_overpayments_count: Number of unresolved overpayments
    - pending_refunds_count: Number of pending refund requests

    **Security:**
    - IDOR protection: Only accessible for user's unit
    - Requires 'finance:read' permission
    """
    unit_id = None if current_user.role == UserRole.ADMIN else current_user.unit_id
    today = date.today()
    month_start = date(today.year, today.month, 1)
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())

    # Default date range: 7 days if not specified
    effective_start = start_date if start_date else today - timedelta(days=6)
    effective_end = end_date if end_date else today
    period_start_dt = datetime.combine(effective_start, datetime.min.time())
    period_end_dt = datetime.combine(effective_end, datetime.max.time())

    # Build base conditions for IDOR
    base_fee_query = select(Fee).join(models.AdmissionProfile).join(models.Lead)
    base_invoice_query = select(Invoice).join(Fee).join(models.AdmissionProfile).join(models.Lead)
    base_payment_query = select(Payment).join(Invoice).join(Fee).join(models.AdmissionProfile).join(models.Lead)

    if unit_id is not None:
        base_fee_query = base_fee_query.where(models.Lead.unit_id == unit_id)
        base_invoice_query = base_invoice_query.where(models.Lead.unit_id == unit_id)
        base_payment_query = base_payment_query.where(models.Lead.unit_id == unit_id)

    # 1. Pending fees count and amount
    pending_fees_statuses = [
        FeeStatusEnum.calculated.value,
        FeeStatusEnum.invoiced.value,
        FeeStatusEnum.partial.value,
    ]
    # Note: remaining_amount is a @property, not a column.
    # Must calculate as: final_amount - paid_amount - waived_amount
    pending_fees_query = (
        select(
            func.count(Fee.id).label("count"),
            func.coalesce(
                func.sum(Fee.final_amount - Fee.paid_amount - Fee.waived_amount),
                0
            ).label("amount")
        )
        .join(models.AdmissionProfile)
        .join(models.Lead)
        .where(Fee.status.in_(pending_fees_statuses))
    )
    if unit_id is not None:
        pending_fees_query = pending_fees_query.where(models.Lead.unit_id == unit_id)
    result = await db.execute(pending_fees_query)
    pending_fees = result.one()
    pending_fees_count = pending_fees.count or 0
    pending_fees_amount = Decimal(str(pending_fees.amount or 0))

    # 2. Pending payments count (verification queue)
    pending_payments_query = (
        select(func.count(Payment.id))
        .join(Invoice)
        .join(Fee)
        .join(models.AdmissionProfile)
        .join(models.Lead)
        .where(
            and_(
                Payment.status == PaymentStatusEnum.pending.value,
                Payment.intent_id.is_(None),  # Manual payments only
            )
        )
    )
    if unit_id is not None:
        pending_payments_query = pending_payments_query.where(models.Lead.unit_id == unit_id)
    result = await db.execute(pending_payments_query)
    pending_payments_count = result.scalar() or 0

    # 3. Overdue invoices count and amount
    overdue_query = (
        select(
            func.count(Invoice.id).label("count"),
            func.coalesce(func.sum(Invoice.amount - Invoice.paid_amount), 0).label("amount")
        )
        .join(Fee)
        .join(models.AdmissionProfile)
        .join(models.Lead)
        .where(
            and_(
                Invoice.due_date < today,
                Invoice.status.in_([
                    InvoiceStatusEnum.draft.value,
                    InvoiceStatusEnum.issued.value,
                ])
            )
        )
    )
    if unit_id is not None:
        overdue_query = overdue_query.where(models.Lead.unit_id == unit_id)
    result = await db.execute(overdue_query)
    overdue = result.one()
    overdue_invoices_count = overdue.count or 0
    overdue_amount = Decimal(str(overdue.amount or 0))

    # 4. Today's collections (verified payments today)
    today_query = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(Invoice)
        .join(Fee)
        .join(models.AdmissionProfile)
        .join(models.Lead)
        .where(
            and_(
                Payment.status == PaymentStatusEnum.verified.value,
                Payment.verified_at >= today_start,
                Payment.verified_at <= today_end,
            )
        )
    )
    if unit_id is not None:
        today_query = today_query.where(models.Lead.unit_id == unit_id)
    result = await db.execute(today_query)
    today_collections = Decimal(str(result.scalar() or 0))

    # 5. Monthly collections (verified payments this month)
    monthly_query = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(Invoice)
        .join(Fee)
        .join(models.AdmissionProfile)
        .join(models.Lead)
        .where(
            and_(
                Payment.status == PaymentStatusEnum.verified.value,
                func.date(Payment.verified_at) >= month_start,
            )
        )
    )
    if unit_id is not None:
        monthly_query = monthly_query.where(models.Lead.unit_id == unit_id)
    result = await db.execute(monthly_query)
    monthly_collections = Decimal(str(result.scalar() or 0))

    # 5.5. Period collections (custom date range)
    period_query = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(Invoice)
        .join(Fee)
        .join(models.AdmissionProfile)
        .join(models.Lead)
        .where(
            and_(
                Payment.status == PaymentStatusEnum.verified.value,
                Payment.verified_at >= period_start_dt,
                Payment.verified_at <= period_end_dt,
            )
        )
    )
    if unit_id is not None:
        period_query = period_query.where(models.Lead.unit_id == unit_id)
    result = await db.execute(period_query)
    period_collections = Decimal(str(result.scalar() or 0))

    # 6. Pending overpayments count
    overpayments_query = (
        select(func.count(OverpaymentRecord.id))
        .join(models.AdmissionProfile)
        .join(models.Lead)
        .where(OverpaymentRecord.status == OverpaymentStatusEnum.pending.value)
    )
    if unit_id is not None:
        overpayments_query = overpayments_query.where(models.Lead.unit_id == unit_id)
    result = await db.execute(overpayments_query)
    pending_overpayments_count = result.scalar() or 0

    # 7. Pending refunds count
    refunds_query = (
        select(func.count(RefundRequest.id))
        .join(Payment)
        .join(Invoice)
        .join(Fee)
        .join(models.AdmissionProfile)
        .join(models.Lead)
        .where(RefundRequest.status == RefundStatusEnum.pending.value)
    )
    if unit_id is not None:
        refunds_query = refunds_query.where(models.Lead.unit_id == unit_id)
    result = await db.execute(refunds_query)
    pending_refunds_count = result.scalar() or 0

    return finance_schemas.FinanceDashboardStats(
        pending_fees_count=pending_fees_count,
        pending_fees_amount=pending_fees_amount,
        pending_payments_count=pending_payments_count,
        overdue_invoices_count=overdue_invoices_count,
        overdue_amount=overdue_amount,
        today_collections=today_collections,
        monthly_collections=monthly_collections,
        period_collections=period_collections,
        period_start=effective_start,
        period_end=effective_end,
        pending_overpayments_count=pending_overpayments_count,
        pending_refunds_count=pending_refunds_count,
    )
