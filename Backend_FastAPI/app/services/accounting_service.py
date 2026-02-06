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

Event Idempotency (Section 3.9 M14):
- Uses ProcessedEvent table to prevent duplicate event processing
- Same event can be processed by multiple consumers
"""

from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Callable
import structlog

from sqlalchemy import select, func, and_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance import (
    AccountingPeriod,
    ProcessedEvent,
    PaymentTransaction,
    TransactionTypeEnum,
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

        # Query for payments
        payment_query = (
            select(func.coalesce(func.sum(PaymentTransaction.amount), 0))
            .where(
                and_(
                    PaymentTransaction.transaction_type == TransactionTypeEnum.payment.value,
                    func.date(PaymentTransaction.created_at) >= first_day,
                    func.date(PaymentTransaction.created_at) <= last_day,
                )
            )
        )
        payment_result = await self.db.execute(payment_query)
        total_payments = Decimal(payment_result.scalar() or 0)

        # Query for refunds (negative amounts)
        refund_query = (
            select(func.coalesce(func.sum(func.abs(PaymentTransaction.amount)), 0))
            .where(
                and_(
                    PaymentTransaction.transaction_type == TransactionTypeEnum.refund.value,
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


class EventIdempotencyService:
    """
    Service for event idempotency management.

    Used to prevent duplicate processing of gateway callbacks
    and other system events.

    Security (Section 3.9 M14):
    - Unique constraint on (event_id, consumer_id)
    - Allows same event to be processed by multiple consumers
    """

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db

    async def is_processed(
        self,
        event_id: str,
        consumer_id: str,
    ) -> bool:
        """
        Check if event has been processed by this consumer.

        Args:
            event_id: Unique event identifier
            consumer_id: Consumer/service identifier

        Returns:
            True if event was already processed
        """
        query = select(
            exists().where(
                and_(
                    ProcessedEvent.event_id == event_id,
                    ProcessedEvent.consumer_id == consumer_id,
                )
            )
        )
        result = await self.db.execute(query)
        return result.scalar()

    async def mark_processed(
        self,
        event_id: str,
        event_type: str,
        consumer_id: str,
        result: str,
        payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        event_version: Optional[str] = None,
    ) -> ProcessedEvent:
        """
        Mark an event as processed.

        Args:
            event_id: Unique event identifier
            event_type: Type of event (e.g., 'vnpay_callback')
            consumer_id: Consumer/service identifier
            result: Processing result ('success', 'failed', 'skipped')
            payload: Original event payload
            error_message: Error message if failed
            event_version: Event schema version

        Returns:
            ProcessedEvent record

        Raises:
            ConflictError: If event already processed by this consumer
        """
        # Check if already processed (race condition protection)
        if await self.is_processed(event_id, consumer_id):
            raise ConflictError(
                f"Event {event_id} already processed by {consumer_id}"
            )

        processed = ProcessedEvent(
            event_id=event_id,
            event_type=event_type,
            event_version=event_version,
            consumer_id=consumer_id,
            processing_result=result,
            event_payload=payload,
            error_message=error_message,
        )

        self.db.add(processed)
        await self.db.flush()
        await self.db.refresh(processed)

        log.info(
            "event_processed",
            event_id=event_id,
            event_type=event_type,
            consumer_id=consumer_id,
            result=result,
        )

        return processed

    async def process_with_idempotency(
        self,
        event_id: str,
        event_type: str,
        consumer_id: str,
        processor_fn: Callable,
        payload: Optional[Dict[str, Any]] = None,
        event_version: Optional[str] = None,
    ) -> Tuple[Any, bool]:
        """
        Process an event with idempotency protection.

        If event already processed, returns (None, True).
        Otherwise processes and marks as processed.

        Args:
            event_id: Unique event identifier
            event_type: Type of event
            consumer_id: Consumer/service identifier
            processor_fn: Async function to process the event
            payload: Original event payload
            event_version: Event schema version

        Returns:
            Tuple of (processor_result, was_duplicate)
        """
        # Check if already processed
        if await self.is_processed(event_id, consumer_id):
            log.info(
                "event_duplicate_skipped",
                event_id=event_id,
                consumer_id=consumer_id,
            )
            return None, True

        # Process the event
        result = None
        error_message = None
        processing_result = "success"

        try:
            result = await processor_fn()
        except Exception as e:
            processing_result = "failed"
            error_message = str(e)
            raise
        finally:
            # Always mark as processed (even on failure)
            await self.mark_processed(
                event_id=event_id,
                event_type=event_type,
                consumer_id=consumer_id,
                result=processing_result,
                payload=payload,
                error_message=error_message,
                event_version=event_version,
            )

        return result, False

    async def get_processed_events(
        self,
        event_type: Optional[str] = None,
        consumer_id: Optional[str] = None,
        result: Optional[str] = None,
        skip: int = 0,
        limit: int = 50,
    ) -> List[ProcessedEvent]:
        """
        Query processed events with filters.

        Args:
            event_type: Filter by event type
            consumer_id: Filter by consumer
            result: Filter by processing result
            skip: Pagination offset
            limit: Pagination limit

        Returns:
            List of ProcessedEvent records
        """
        query = (
            select(ProcessedEvent)
            .order_by(ProcessedEvent.processed_at.desc())
            .offset(skip)
            .limit(limit)
        )

        if event_type:
            query = query.where(ProcessedEvent.event_type == event_type)

        if consumer_id:
            query = query.where(ProcessedEvent.consumer_id == consumer_id)

        if result:
            query = query.where(ProcessedEvent.processing_result == result)

        db_result = await self.db.execute(query)
        return list(db_result.scalars().all())
