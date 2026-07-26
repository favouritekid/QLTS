# app/services/accounting_service.py
"""
Accounting Period Service - Business logic for ledger period management.

Architecture Compliance:
- Service Layer: Pure business logic, no HTTP dependencies
- Security: Period integrity checks
- Transactions: Services use db.add()/db.flush(), Router commits
- Error Handling: Raise custom exceptions

Business Rules (Section 3.9 H7):
- Previous period must be closed before opening a new one
- No transactions can be recorded for closed periods
- Period totals are calculated and locked when closed
"""

from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Callable
import structlog

from sqlalchemy import select, func, and_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.cash_ledger import CASH_INFLOW_TYPES, CASH_OUTFLOW_TYPES
from app.models.finance import (
    AccountingPeriod,
    PaymentTransaction,
)
from app.utils.exceptions import (
    ResourceNotFoundError,
    BadRequest,
    BusinessRuleViolation,
    ConflictError,
)
from app.config import settings

log = structlog.get_logger(__name__)


class AccountingPeriodService:
    """
    Service for accounting period management.

    Responsibilities:
    - Create new accounting periods
    - Close periods (calculate totals, lock transactions)
    - Validate period transitions
    - Provide period lookups
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    # ==========================================================================
    # PERIOD MANAGEMENT
    # ==========================================================================

    async def create_period(
        self,
        month: int,
        year: int,
        user_id: int,
        notes: Optional[str] = None,
    ) -> Tuple[AccountingPeriod, Optional[Callable]]:
        """
        Create a new accounting period.

        Business Rule H7: Previous period must be closed.

        Args:
            month: Period month (1-12)
            year: Period year
            user_id: User creating period
            notes: Optional notes

        Returns:
            Tuple of (AccountingPeriod, post_commit_callback)

        Raises:
            BadRequest: If month/year invalid
            BusinessRuleViolation: If previous period not closed
            ConflictError: If period already exists
        """
        # Validate month
        if month < 1 or month > 12:
            raise BadRequest("Month must be between 1 and 12")

        # Check if period already exists
        existing = await self.get_period(month, year)
        if existing:
            raise ConflictError(
                f"Accounting period {year}-{month:02d} already exists"
            )

        # H7: Check previous period is closed
        prev_month, prev_year = self._get_previous_period(month, year)
        prev_period = await self.get_period(prev_month, prev_year)

        if prev_period and not prev_period.is_closed:
            raise BusinessRuleViolation(
                f"Cannot create period {year}-{month:02d}. "
                f"Previous period {prev_year}-{prev_month:02d} is not closed."
            )

        # Create period
        period = AccountingPeriod(
            period_month=month,
            period_year=year,
            is_closed=False,
            total_revenue=Decimal("0"),
            total_payments=Decimal("0"),
            total_refunds=Decimal("0"),
            notes=notes,
        )

        self.db.add(period)
        await self.db.flush()
        await self.db.refresh(period)

        log.info(
            "accounting_period_created",
            period_id=period.id,
            period_key=period.period_key,
            user_id=user_id,
        )

        return period, None

    async def close_period(
        self,
        month: int,
        year: int,
        user_id: int,
        notes: Optional[str] = None,
    ) -> Tuple[AccountingPeriod, Optional[Callable]]:
        """
        Close an accounting period.

        Closing a period:
        1. Calculates and stores period totals
        2. Prevents future transactions for this period
        3. Validates no previous period is still open

        Args:
            month: Period month (1-12)
            year: Period year
            user_id: User closing period
            notes: Optional closing notes

        Returns:
            Tuple of (AccountingPeriod, post_commit_callback)

        Raises:
            ResourceNotFoundError: If period not found
            BusinessRuleViolation: If period already closed or has unclosed previous periods
        """
        period = await self.get_period(month, year)
        if not period:
            raise ResourceNotFoundError(
                f"Accounting period {year}-{month:02d} not found"
            )

        if period.is_closed:
            raise BusinessRuleViolation(
                f"Period {year}-{month:02d} is already closed"
            )

        # Check all previous periods are closed
        unclosed = await self._get_unclosed_periods_before(month, year)
        if unclosed:
            period_keys = [p.period_key for p in unclosed]
            raise BusinessRuleViolation(
                f"Cannot close period {year}-{month:02d}. "
                f"Previous periods not closed: {period_keys}"
            )

        # Calculate period totals
        totals = await self._calculate_period_totals(month, year)

        # Update period
        period.is_closed = True
        period.closed_at = datetime.now(timezone.utc)
        period.closed_by_id = user_id
        period.total_payments = totals["payments"]
        period.total_refunds = totals["refunds"]
        period.total_revenue = totals["payments"] - totals["refunds"]

        if notes:
            period.notes = f"{period.notes or ''}\n[Closing] {notes}"

        await self.db.flush()

        log.info(
            "accounting_period_closed",
            period_id=period.id,
            period_key=period.period_key,
            total_payments=str(period.total_payments),
            total_refunds=str(period.total_refunds),
            net_revenue=str(period.net_revenue),
            user_id=user_id,
        )

        return period, None

    async def reopen_period(
        self,
        month: int,
        year: int,
        user_id: int,
        reason: str,
    ) -> Tuple[AccountingPeriod, Optional[Callable]]:
        """
        Reopen a closed accounting period (admin only).

        This is an exceptional operation that requires audit logging.

        Args:
            month: Period month
            year: Period year
            user_id: Admin user reopening
            reason: Reason for reopening (required)

        Returns:
            Tuple of (AccountingPeriod, post_commit_callback)

        Raises:
            ResourceNotFoundError: If period not found
            BusinessRuleViolation: If period not closed or newer periods exist
        """
        period = await self.get_period(month, year)
        if not period:
            raise ResourceNotFoundError(
                f"Accounting period {year}-{month:02d} not found"
            )

        if not period.is_closed:
            raise BusinessRuleViolation(
                f"Period {year}-{month:02d} is not closed"
            )

        # Check no newer periods exist
        newer = await self._get_periods_after(month, year)
        if newer:
            raise BusinessRuleViolation(
                f"Cannot reopen period {year}-{month:02d}. "
                f"Newer periods exist: {[p.period_key for p in newer]}"
            )

        if not reason or not reason.strip():
            raise BadRequest("Reason for reopening is required")

        # Reopen period
        period.is_closed = False
        period.notes = (
            f"{period.notes or ''}\n"
            f"[{datetime.now(timezone.utc).isoformat()}] "
            f"Reopened by user {user_id}. Reason: {reason}"
        )

        await self.db.flush()

        log.warning(
            "accounting_period_reopened",
            period_id=period.id,
            period_key=period.period_key,
            reason=reason,
            user_id=user_id,
        )

        return period, None

    # ==========================================================================
    # PERIOD QUERIES
    # ==========================================================================

    async def get_period(
        self,
        month: int,
        year: int,
    ) -> Optional[AccountingPeriod]:
        """Get period by month and year."""
        query = select(AccountingPeriod).where(
            and_(
                AccountingPeriod.period_month == month,
                AccountingPeriod.period_year == year,
            )
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_current_period(self) -> Optional[AccountingPeriod]:
        """Get the current (most recent open) period."""
        query = (
            select(AccountingPeriod)
            .where(AccountingPeriod.is_closed == False)
            .order_by(
                AccountingPeriod.period_year.desc(),
                AccountingPeriod.period_month.desc(),
            )
            .limit(1)
        )
        result = await self.db.execute(query)
        return result.scalars().first()

    async def get_period_for_date(
        self,
        target_date: date,
    ) -> Optional[AccountingPeriod]:
        """Get period for a specific date."""
        return await self.get_period(target_date.month, target_date.year)

    async def get_all_periods(
        self,
        skip: int = 0,
        limit: int = 24,
    ) -> List[AccountingPeriod]:
        """Get all periods, ordered by date descending."""
        query = (
            select(AccountingPeriod)
            .order_by(
                AccountingPeriod.period_year.desc(),
                AccountingPeriod.period_month.desc(),
            )
            .offset(skip)
            .limit(limit)
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def can_record_transaction(
        self,
        transaction_date: date,
    ) -> Tuple[bool, str]:
        """
        Check if transactions can be recorded for a date.

        Args:
            transaction_date: Date of the transaction

        Returns:
            Tuple of (can_record, reason)
        """
        period = await self.get_period(transaction_date.month, transaction_date.year)

        if not period:
            return True, "No period defined, transactions allowed"

        if period.is_closed:
            return False, f"Period {period.period_key} is closed"

        return True, "Period is open"

    # ==========================================================================
    # HELPER METHODS
    # ==========================================================================

    def _get_previous_period(
        self,
        month: int,
        year: int,
    ) -> Tuple[int, int]:
        """Get previous month/year."""
        if month == 1:
            return 12, year - 1
        return month - 1, year

    async def _get_unclosed_periods_before(
        self,
        month: int,
        year: int,
    ) -> List[AccountingPeriod]:
        """Get all unclosed periods before the given month/year."""
        query = (
            select(AccountingPeriod)
            .where(
                and_(
                    AccountingPeriod.is_closed == False,
                    (
                        (AccountingPeriod.period_year < year) |
                        (
                            (AccountingPeriod.period_year == year) &
                            (AccountingPeriod.period_month < month)
                        )
                    ),
                )
            )
            .order_by(
                AccountingPeriod.period_year,
                AccountingPeriod.period_month,
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _get_periods_after(
        self,
        month: int,
        year: int,
    ) -> List[AccountingPeriod]:
        """Get all periods after the given month/year."""
        query = (
            select(AccountingPeriod)
            .where(
                (AccountingPeriod.period_year > year) |
                (
                    (AccountingPeriod.period_year == year) &
                    (AccountingPeriod.period_month > month)
                )
            )
            .order_by(
                AccountingPeriod.period_year,
                AccountingPeriod.period_month,
            )
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def _calculate_period_totals(
        self,
        month: int,
        year: int,
    ) -> Dict[str, Decimal]:
        """
        Calculate payment totals for a period.

        Sums all PaymentTransactions where created_at is within the period.
        """
        from datetime import date
        from calendar import monthrange

        # Period date range
        first_day = date(year, month, 1)
        last_day = date(year, month, monthrange(year, month)[1])

        # Tiền VÀO + tiền RA lấy danh sách loại giao dịch từ NGUỒN DUY NHẤT
        # ``app.constants.cash_ledger`` — dùng chung với báo cáo tuần tuyển sinh và
        # Excel tổng hợp năm. Trước đây hàm này chỉ đếm ``payment`` và ``refund``,
        # BỎ HẲN ``reversal`` (đảo ghi nhận khi kế toán huỷ lô import nhầm) ⇒ một
        # lô bị huỷ vẫn nằm nguyên trong doanh thu của kỳ, trong khi hai báo cáo
        # kia đã trừ ⇒ ba con số cho cùng một câu hỏi.
        payment_query = (
            select(func.coalesce(func.sum(PaymentTransaction.amount), 0))
            .where(
                and_(
                    PaymentTransaction.transaction_type.in_(CASH_INFLOW_TYPES),
                    func.date(PaymentTransaction.created_at) >= first_day,
                    func.date(PaymentTransaction.created_at) <= last_day,
                )
            )
        )
        payment_result = await self.db.execute(payment_query)
        total_payments = Decimal(payment_result.scalar() or 0)

        # Tiền RA gồm ``refund`` (hoàn cho thí sinh) VÀ ``reversal`` (đảo lô).
        # Cả hai lưu amount ÂM nên lấy ABS của tổng.
        refund_query = (
            select(func.coalesce(func.abs(func.sum(PaymentTransaction.amount)), 0))
            .where(
                and_(
                    PaymentTransaction.transaction_type.in_(CASH_OUTFLOW_TYPES),
                    func.date(PaymentTransaction.created_at) >= first_day,
                    func.date(PaymentTransaction.created_at) <= last_day,
                )
            )
        )
        refund_result = await self.db.execute(refund_query)
        total_refunds = Decimal(refund_result.scalar() or 0)

        return {
            "payments": total_payments,
            "refunds": total_refunds,
        }
