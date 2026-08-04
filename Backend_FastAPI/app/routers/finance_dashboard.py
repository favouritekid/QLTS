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

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
import structlog

from app import database, models
from app.core.constants import UserRole
from app.core.deps import (
    CasbinAuth,
    finance_scope_unit_id,
    require_finance_staff,
)
from app.core.rate_limits import get_user_id_key, limiter, RateLimits
from app.schemas import finance as finance_schemas
from app.services.finance_report_service import FinanceReportService
from app.repositories.fee_repository import InvoiceRepository
from app.models.finance import (
    Fee, Invoice, Payment, RefundRequest, OverpaymentRecord,
    FeeStatusEnum, PaymentStatusEnum,
    RefundStatusEnum, OverpaymentStatusEnum,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/finance", tags=["Finance - Dashboard"])


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/debt-report",
    response_model=finance_schemas.DebtReportResponse,
    summary="Get debt report grouped by admission profile",
)
async def get_debt_report(
    request: Request,
    unit_id: Optional[int] = Query(None, description="Admin-only unit filter"),
    academic_year: Optional[int] = Query(
        None, description="Filter by fee academic year"
    ),
    round_id: Optional[int] = Query(
        None, description="Filter by applied_rules admission_round_id"
    ),
    fee_type: Optional[str] = Query(None, description="Filter by fee type"),
    aging: Optional[str] = Query(None, pattern="^(0_30|31_60|over_60)$"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """Return debtor rows and summary totals.

    Non-admin callers are always scoped to their own unit. Admin may optionally
    pass ``unit_id`` to narrow the report.
    """
    # Admin may optionally narrow by unit_id; non-admins are hard-scoped to their
    # own unit (and denied if they have none — avoids the NULL-unit IDOR leak).
    if current_user.role == UserRole.ADMIN:
        scoped_unit_id = unit_id
    else:
        scoped_unit_id = finance_scope_unit_id(current_user)
    report_service = FinanceReportService(db)
    return await report_service.get_debt_report(
        unit_id=scoped_unit_id,
        academic_year=academic_year,
        round_id=round_id,
        fee_type=fee_type,
        aging=aging,
    )


@router.get(
    "/debt-report/export",
    summary="Xuất báo cáo công nợ (xlsx/csv)",
)
# Thứ tự @router trên / @limiter dưới + khoá per-user — xem ghi chú ở
# invoices.py::export_tuition_list.
@limiter.limit(RateLimits.DATA_EXPORT, key_func=get_user_id_key)
async def export_debt_report(
    request: Request,
    format: str = Query(
        "xlsx", pattern="^(xlsx|csv)$", description="xlsx (mặc định) | csv"
    ),
    unit_id: Optional[int] = Query(None, description="Admin-only unit filter"),
    academic_year: Optional[int] = Query(None),
    round_id: Optional[int] = Query(None),
    fee_type: Optional[str] = Query(None),
    aging: Optional[str] = Query(None, pattern="^(0_30|31_60|over_60)$"),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
    _finance_staff: models.User = Depends(require_finance_staff),
) -> Response:
    """Xuất báo cáo công nợ ra tệp — cùng nguồn số liệu với màn hình.

    Trước đây CSV được dựng ở TRÌNH DUYỆT: header là khoá kỹ thuật tiếng Anh,
    không BOM (Excel tiếng Việt mojibake), ô tiền bọc thành chuỗi nên không
    cộng được, tên tệp cố định nên xuất nhiều lần đè lên nhau.

    Scope giống hệt ``get_debt_report``: admin có thể chọn đơn vị, người khác bị
    ép về đơn vị của mình.
    """
    if current_user.role == UserRole.ADMIN:
        scoped_unit_id = unit_id
    else:
        scoped_unit_id = finance_scope_unit_id(current_user)

    report_service = FinanceReportService(db)
    content, media_type, filename = await report_service.build_debt_report_export(
        fmt=format,
        exporter_name=current_user.full_name or current_user.username,
        unit_id=scoped_unit_id,
        academic_year=academic_year,
        round_id=round_id,
        fee_type=fee_type,
        aging=aging,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@limiter.limit(RateLimits.DATA_READ)
@router.get(
    "/dashboard",
    response_model=finance_schemas.FinanceDashboardStats,
    summary="Get finance dashboard statistics",
)
async def get_dashboard_stats(
    request: Request,
    start_date: Optional[date] = Query(
        None, description="Start date for period collections (YYYY-MM-DD)"
    ),
    end_date: Optional[date] = Query(
        None, description="End date for period collections (YYYY-MM-DD)"
    ),
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = CasbinAuth,
):
    """
    Get finance dashboard statistics.

    **Query Parameters:**
    - start_date: Optional start of period_collections range (default: 7 days ago)
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
    unit_id = finance_scope_unit_id(current_user)
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
    base_invoice_query = (
        select(Invoice).join(Fee).join(models.AdmissionProfile).join(models.Lead)
    )
    base_payment_query = (
        select(Payment)
        .join(Invoice)
        .join(Fee)
        .join(models.AdmissionProfile)
        .join(models.Lead)
    )

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
        .where(
            Fee.status.in_(pending_fees_statuses),
            # F4: a withdrawn / awaiting-refund profile owes nothing — its
            # leftover 'invoiced'/'partial' fees (e.g. a refund-reopened invoice
            # not yet cancelled) must NOT count as a receivable on the dashboard.
            models.AdmissionProfile.status.notin_(
                ("withdrawn", "withdrawal_pending")
            ),
        )
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
        pending_payments_query = pending_payments_query.where(
            models.Lead.unit_id == unit_id
        )
    result = await db.execute(pending_payments_query)
    pending_payments_count = result.scalar() or 0

    # 3 + 3.5. Overdue + outstanding money — computed in the repository (Backend
    # rule #1/#4: no db.execute / raw SQL in routers). Penalty-aware remaining
    # (amount + penalty - paid, clamped ≥ 0) over OVERDUE_DERIVED_STATUSES; the
    # overdue slice adds due_date < today so overdue ⊆ outstanding.
    money = await InvoiceRepository(db).get_collection_money_totals(
        unit_id=unit_id, today=today
    )
    overdue_invoices_count = money["overdue_invoices_count"]
    overdue_amount = money["overdue_amount"]
    outstanding_total = money["outstanding_total"]

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

    # 5.9. F3 — net out PROCESSED refunds so "collections" match
    # AccountingPeriod.net_revenue (a refunded payment is not revenue; the gross
    # sums above still count it because process_approved_refund leaves
    # payment.status='verified'). Refunds are matched by ``refunded_at`` within
    # the SAME window as each collection metric. Net can go slightly negative in
    # a window where refunds of prior-period payments exceed new collections —
    # that is the correct net-outflow figure, left unclamped.
    async def _refunds_processed(*conds) -> Decimal:
        rq = (
            select(func.coalesce(func.sum(RefundRequest.amount), 0))
            .join(Payment, RefundRequest.payment_id == Payment.id)
            .join(Invoice, Payment.invoice_id == Invoice.id)
            .join(Fee, Invoice.fee_id == Fee.id)
            .join(models.AdmissionProfile)
            .join(models.Lead)
            .where(RefundRequest.status == "refunded", *conds)
        )
        if unit_id is not None:
            rq = rq.where(models.Lead.unit_id == unit_id)
        return Decimal(str((await db.execute(rq)).scalar() or 0))

    today_collections -= await _refunds_processed(
        RefundRequest.refunded_at >= today_start,
        RefundRequest.refunded_at <= today_end,
    )
    monthly_collections -= await _refunds_processed(
        func.date(RefundRequest.refunded_at) >= month_start,
    )
    period_collections -= await _refunds_processed(
        RefundRequest.refunded_at >= period_start_dt,
        RefundRequest.refunded_at <= period_end_dt,
    )

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
        outstanding_total=outstanding_total,
        today_collections=today_collections,
        monthly_collections=monthly_collections,
        period_collections=period_collections,
        period_start=effective_start,
        period_end=effective_end,
        pending_overpayments_count=pending_overpayments_count,
        pending_refunds_count=pending_refunds_count,
    )
