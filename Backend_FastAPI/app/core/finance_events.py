# app/core/finance_events.py
"""
Finance Module Domain Events.

Domain events represent significant business occurrences in the Finance Module.
They are used for:
- Cross-module communication (Finance → Admission)
- Audit trail generation
- Triggering side effects (notifications, status updates)
- Integration with external systems

Architecture:
- Events are immutable value objects (dataclasses)
- Each event has a unique event_id for idempotency
- Events include correlation_id for distributed tracing
- ProcessedEvent table tracks which events have been handled

Event Types:
- FeeCalculated: Fee has been calculated for a profile
- InvoiceIssued: Invoice has been issued and is payable
- PaymentReceived: Payment has been recorded (pending verification)
- PaymentVerified: Payment has been verified (funds confirmed)
- PaymentRejected: Payment has been rejected
- FeeFullyPaid: Fee has been completely paid (enrollment trigger)
- RefundProcessed: Refund has been issued
- PeriodClosed: Accounting period has been closed

Usage:
    from app.core.finance_events import FeeCalculated, emit_event

    # Create and emit event
    event = FeeCalculated(
        fee_id=123,
        admission_profile_id=456,
        fee_type="tuition",
        final_amount=Decimal("9000000"),
    )
    await emit_event(event)
"""

from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4
import structlog

log = structlog.get_logger(__name__)


def _utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def _new_event_id() -> str:
    """Generate unique event ID."""
    return str(uuid4())


# =============================================================================
# BASE EVENT CLASS
# =============================================================================

@dataclass
class DomainEvent:
    """
    Base class for all domain events.

    Attributes:
        event_id: Unique identifier for idempotency
        event_version: Schema version for backwards compatibility
        occurred_at: When the event occurred (UTC)
        correlation_id: Optional ID for tracing related events
        caused_by_user_id: User who triggered the action
    """
    event_id: str = field(default_factory=_new_event_id)
    event_version: int = 1
    occurred_at: datetime = field(default_factory=_utc_now)
    correlation_id: Optional[str] = None
    caused_by_user_id: Optional[int] = None

    @property
    def event_type(self) -> str:
        """Get event type name."""
        return self.__class__.__name__

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for storage."""
        data = asdict(self)
        # Convert datetime and Decimal for JSON serialization
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
            elif isinstance(value, Decimal):
                data[key] = str(value)
            elif isinstance(value, date):
                data[key] = value.isoformat()
        return data


# =============================================================================
# FEE EVENTS
# =============================================================================

@dataclass
class FeeCalculated(DomainEvent):
    """
    Emitted when a fee is calculated for an admission profile.

    Triggers:
    - Lead status update to sts14 (Chờ học phí)
    - Invoice generation (if installment plan specified)
    - Notification to applicant
    """
    fee_id: int = 0
    admission_profile_id: int = 0
    fee_type: str = ""  # tuition, application, enrollment, etc.
    base_amount: Decimal = Decimal("0")
    total_discount: Decimal = Decimal("0")
    final_amount: Decimal = Decimal("0")
    installment_count: int = 1
    applied_discounts: List[Dict[str, Any]] = field(default_factory=list)
    academic_year: int = 0


@dataclass
class FeeWaived(DomainEvent):
    """
    Emitted when part of a fee is waived.

    Triggers:
    - Recalculate remaining balance
    - Update invoice amounts if applicable
    """
    fee_id: int = 0
    waived_amount: Decimal = Decimal("0")
    total_waived: Decimal = Decimal("0")
    remaining_amount: Decimal = Decimal("0")
    reason: str = ""


@dataclass
class FeeCancelled(DomainEvent):
    """
    Emitted when a fee is cancelled.

    Triggers:
    - Cancel all associated invoices
    - Void any pending payments
    """
    fee_id: int = 0
    admission_profile_id: int = 0
    reason: str = ""


@dataclass
class FeeFullyPaid(DomainEvent):
    """
    Emitted when a fee is fully paid (critical event).

    This is the key event that triggers enrollment eligibility.

    Triggers:
    - Lead status update (sts10 for tuition, sts13 for application)
    - Enrollment eligibility check
    - Notification to applicant and officer
    """
    fee_id: int = 0
    admission_profile_id: int = 0
    fee_type: str = ""
    total_paid: Decimal = Decimal("0")
    paid_at: datetime = field(default_factory=_utc_now)


# =============================================================================
# INVOICE EVENTS
# =============================================================================

@dataclass
class InvoiceIssued(DomainEvent):
    """
    Emitted when an invoice is issued and becomes payable.

    Triggers:
    - Notification to applicant with payment details
    - Due date reminder scheduling
    """
    invoice_id: int = 0
    fee_id: int = 0
    invoice_number: str = ""
    installment_no: int = 1
    amount: Decimal = Decimal("0")
    due_date: date = field(default_factory=date.today)


@dataclass
class InvoicePaid(DomainEvent):
    """
    Emitted when an invoice is fully paid.

    Triggers:
    - Receipt generation
    - Cancel due date reminders
    """
    invoice_id: int = 0
    fee_id: int = 0
    invoice_number: str = ""
    amount: Decimal = Decimal("0")
    paid_at: datetime = field(default_factory=_utc_now)


@dataclass
class InvoiceOverdue(DomainEvent):
    """
    Emitted when an invoice becomes overdue.

    Triggers:
    - Penalty calculation
    - Overdue notification to applicant
    - Escalation to officer
    """
    invoice_id: int = 0
    fee_id: int = 0
    invoice_number: str = ""
    amount: Decimal = Decimal("0")
    due_date: date = field(default_factory=date.today)
    days_overdue: int = 0


@dataclass
class InvoiceCancelled(DomainEvent):
    """
    Emitted when an invoice is cancelled.

    Triggers:
    - Update fee invoiced status
    - Cancel scheduled reminders
    """
    invoice_id: int = 0
    fee_id: int = 0
    invoice_number: str = ""
    reason: str = ""


# =============================================================================
# PAYMENT EVENTS
# =============================================================================

@dataclass
class PaymentReceived(DomainEvent):
    """
    Emitted when a payment is recorded (before verification).

    For manual payments, this goes to pending status.
    For online payments, this is auto-verified.

    Triggers:
    - Notification to verifier (for manual payments)
    - Audit log entry
    """
    payment_id: int = 0
    invoice_id: int = 0
    fee_id: int = 0
    amount: Decimal = Decimal("0")
    method_code: str = ""
    reference_code: Optional[str] = None
    is_online: bool = False
    requires_verification: bool = True


@dataclass
class PaymentVerified(DomainEvent):
    """
    Emitted when a payment is verified (funds confirmed).

    This updates invoice and fee paid amounts.

    Triggers:
    - Update invoice paid_amount
    - Update fee paid_amount
    - Check if fee is fully paid
    - Receipt generation
    """
    payment_id: int = 0
    invoice_id: int = 0
    fee_id: int = 0
    amount: Decimal = Decimal("0")
    remaining_on_invoice: Decimal = Decimal("0")
    remaining_on_fee: Decimal = Decimal("0")
    invoice_fully_paid: bool = False
    fee_fully_paid: bool = False
    verified_by_id: int = 0
    verified_at: datetime = field(default_factory=_utc_now)


@dataclass
class PaymentRejected(DomainEvent):
    """
    Emitted when a payment is rejected.

    Triggers:
    - Notification to officer who recorded payment
    - Audit log entry
    """
    payment_id: int = 0
    invoice_id: int = 0
    amount: Decimal = Decimal("0")
    rejection_reason: str = ""
    rejected_by_id: int = 0


# =============================================================================
# REFUND EVENTS
# =============================================================================

@dataclass
class RefundRequested(DomainEvent):
    """
    Emitted when a refund is requested.

    Triggers:
    - Notification to manager for approval
    - Audit log entry
    """
    refund_id: int = 0
    payment_id: int = 0
    amount: Decimal = Decimal("0")
    reason: str = ""
    requested_by_id: int = 0


@dataclass
class RefundApproved(DomainEvent):
    """
    Emitted when a refund is approved.

    Triggers:
    - Notification to finance team for processing
    """
    refund_id: int = 0
    payment_id: int = 0
    amount: Decimal = Decimal("0")
    approved_by_id: int = 0


@dataclass
class RefundProcessed(DomainEvent):
    """
    Emitted when a refund is processed (money returned).

    Triggers:
    - Update invoice paid_amount (decrease)
    - Update fee paid_amount (decrease)
    - Lead status update to sts18 (Đã hoàn học phí) if full refund
    - Notification to applicant
    """
    refund_id: int = 0
    payment_id: int = 0
    invoice_id: int = 0
    fee_id: int = 0
    amount: Decimal = Decimal("0")
    refund_reference: str = ""
    processed_at: datetime = field(default_factory=_utc_now)


# =============================================================================
# ACCOUNTING PERIOD EVENTS
# =============================================================================

@dataclass
class PeriodOpened(DomainEvent):
    """
    Emitted when a new accounting period is opened.

    Triggers:
    - Close any open periods (should only be one)
    """
    period_id: int = 0
    period_month: int = 0
    period_year: int = 0


@dataclass
class PeriodClosed(DomainEvent):
    """
    Emitted when an accounting period is closed.

    Once closed, no transactions can be recorded for that period.

    Triggers:
    - Generate period summary report
    - Lock all transactions in period
    """
    period_id: int = 0
    period_month: int = 0
    period_year: int = 0
    total_payments: Decimal = Decimal("0")
    total_refunds: Decimal = Decimal("0")
    net_revenue: Decimal = Decimal("0")
    closed_by_id: int = 0


# =============================================================================
# OVERPAYMENT EVENTS
# =============================================================================

@dataclass
class OverpaymentDetected(DomainEvent):
    """
    Emitted when an overpayment is detected.

    Triggers:
    - Create overpayment record
    - Notification to accountant for resolution
    """
    overpayment_id: int = 0
    payment_id: int = 0
    invoice_id: int = 0
    admission_profile_id: int = 0
    overpayment_amount: Decimal = Decimal("0")


@dataclass
class OverpaymentResolved(DomainEvent):
    """
    Emitted when an overpayment is resolved.

    Resolution types: applied_to_next, refunded, written_off
    """
    overpayment_id: int = 0
    resolution_type: str = ""  # applied_to_next, refunded, written_off
    resolved_amount: Decimal = Decimal("0")
    resolved_by_id: int = 0


# =============================================================================
# EVENT REGISTRY
# =============================================================================

# Map event type names to classes for deserialization
EVENT_REGISTRY: Dict[str, type] = {
    "FeeCalculated": FeeCalculated,
    "FeeWaived": FeeWaived,
    "FeeCancelled": FeeCancelled,
    "FeeFullyPaid": FeeFullyPaid,
    "InvoiceIssued": InvoiceIssued,
    "InvoicePaid": InvoicePaid,
    "InvoiceOverdue": InvoiceOverdue,
    "InvoiceCancelled": InvoiceCancelled,
    "PaymentReceived": PaymentReceived,
    "PaymentVerified": PaymentVerified,
    "PaymentRejected": PaymentRejected,
    "RefundRequested": RefundRequested,
    "RefundApproved": RefundApproved,
    "RefundProcessed": RefundProcessed,
    "PeriodOpened": PeriodOpened,
    "PeriodClosed": PeriodClosed,
    "OverpaymentDetected": OverpaymentDetected,
    "OverpaymentResolved": OverpaymentResolved,
}


def get_event_class(event_type: str) -> Optional[type]:
    """Get event class by type name."""
    return EVENT_REGISTRY.get(event_type)


# =============================================================================
# EVENT EMISSION (placeholder for event bus integration)
# =============================================================================

# Event handlers registered per event type
_event_handlers: Dict[str, List[Callable]] = {}


def register_handler(event_type: type, handler: Callable) -> None:
    """
    Register an event handler.

    Args:
        event_type: Event class to handle
        handler: Async function to call when event is emitted
    """
    type_name = event_type.__name__
    if type_name not in _event_handlers:
        _event_handlers[type_name] = []
    _event_handlers[type_name].append(handler)
    log.debug("event_handler_registered", event_type=type_name, handler=handler.__name__)


def get_handlers(event_type: str) -> List[Callable]:
    """Get all handlers for an event type."""
    return _event_handlers.get(event_type, [])


async def emit_event(event: DomainEvent) -> None:
    """
    Emit a domain event to all registered handlers.

    This is a simple in-process event bus. For production,
    consider using Celery tasks or a message queue.

    Args:
        event: Domain event to emit
    """
    event_type = event.event_type
    handlers = get_handlers(event_type)

    log.info(
        "event_emitted",
        event_type=event_type,
        event_id=event.event_id,
        handler_count=len(handlers),
    )

    for handler in handlers:
        try:
            await handler(event)
        except Exception as e:
            log.error(
                "event_handler_failed",
                event_type=event_type,
                event_id=event.event_id,
                handler=handler.__name__,
                error=str(e),
            )
            # Continue to next handler - don't fail entire emit


def event_handler(event_type: type):
    """
    Decorator to register an event handler.

    Usage:
        @event_handler(FeeFullyPaid)
        async def on_fee_fully_paid(event: FeeFullyPaid):
            # Handle event
            pass
    """
    def decorator(func: Callable) -> Callable:
        register_handler(event_type, func)
        return func
    return decorator
