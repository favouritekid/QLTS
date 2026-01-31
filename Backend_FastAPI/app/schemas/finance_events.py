# app/schemas/finance_events.py
"""
Pydantic Schemas for Finance Domain Events.

These schemas are used for:
- API responses when querying processed events
- Webhook payloads (if events are sent externally)
- Event audit log display

Architecture:
- Each event schema mirrors its corresponding domain event
- ProcessedEventResponse for querying idempotency tracking
- Generic EventEnvelope for webhook delivery
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# BASE EVENT SCHEMAS
# =============================================================================

class EventBase(BaseModel):
    """Base schema for all event responses."""
    event_id: str
    event_type: str
    event_version: int = 1
    occurred_at: datetime
    correlation_id: Optional[str] = None
    caused_by_user_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class EventEnvelope(BaseModel):
    """
    Envelope for webhook event delivery.

    Used when sending events to external systems.
    """
    event_id: str
    event_type: str
    event_version: int
    occurred_at: datetime
    payload: Dict[str, Any]
    signature: Optional[str] = None  # HMAC signature for verification

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# FEE EVENT SCHEMAS
# =============================================================================

class FeeCalculatedSchema(EventBase):
    """Schema for FeeCalculated event."""
    fee_id: int
    admission_profile_id: int
    fee_type: str
    base_amount: Decimal
    total_discount: Decimal
    final_amount: Decimal
    installment_count: int
    applied_discounts: List[Dict[str, Any]] = []
    academic_year: int


class FeeWaivedSchema(EventBase):
    """Schema for FeeWaived event."""
    fee_id: int
    waived_amount: Decimal
    total_waived: Decimal
    remaining_amount: Decimal
    reason: str


class FeeCancelledSchema(EventBase):
    """Schema for FeeCancelled event."""
    fee_id: int
    admission_profile_id: int
    reason: str


class FeeFullyPaidSchema(EventBase):
    """Schema for FeeFullyPaid event."""
    fee_id: int
    admission_profile_id: int
    fee_type: str
    total_paid: Decimal
    paid_at: datetime


# =============================================================================
# INVOICE EVENT SCHEMAS
# =============================================================================

class InvoiceIssuedSchema(EventBase):
    """Schema for InvoiceIssued event."""
    invoice_id: int
    fee_id: int
    invoice_number: str
    installment_no: int
    amount: Decimal
    due_date: date


class InvoicePaidSchema(EventBase):
    """Schema for InvoicePaid event."""
    invoice_id: int
    fee_id: int
    invoice_number: str
    amount: Decimal
    paid_at: datetime


class InvoiceOverdueSchema(EventBase):
    """Schema for InvoiceOverdue event."""
    invoice_id: int
    fee_id: int
    invoice_number: str
    amount: Decimal
    due_date: date
    days_overdue: int


class InvoiceCancelledSchema(EventBase):
    """Schema for InvoiceCancelled event."""
    invoice_id: int
    fee_id: int
    invoice_number: str
    reason: str


# =============================================================================
# PAYMENT EVENT SCHEMAS
# =============================================================================

class PaymentReceivedSchema(EventBase):
    """Schema for PaymentReceived event."""
    payment_id: int
    invoice_id: int
    fee_id: int
    amount: Decimal
    method_code: str
    reference_code: Optional[str] = None
    is_online: bool
    requires_verification: bool


class PaymentVerifiedSchema(EventBase):
    """Schema for PaymentVerified event."""
    payment_id: int
    invoice_id: int
    fee_id: int
    amount: Decimal
    remaining_on_invoice: Decimal
    remaining_on_fee: Decimal
    invoice_fully_paid: bool
    fee_fully_paid: bool
    verified_by_id: int
    verified_at: datetime


class PaymentRejectedSchema(EventBase):
    """Schema for PaymentRejected event."""
    payment_id: int
    invoice_id: int
    amount: Decimal
    rejection_reason: str
    rejected_by_id: int


# =============================================================================
# REFUND EVENT SCHEMAS
# =============================================================================

class RefundRequestedSchema(EventBase):
    """Schema for RefundRequested event."""
    refund_id: int
    payment_id: int
    amount: Decimal
    reason: str
    requested_by_id: int


class RefundApprovedSchema(EventBase):
    """Schema for RefundApproved event."""
    refund_id: int
    payment_id: int
    amount: Decimal
    approved_by_id: int


class RefundProcessedSchema(EventBase):
    """Schema for RefundProcessed event."""
    refund_id: int
    payment_id: int
    invoice_id: int
    fee_id: int
    amount: Decimal
    refund_reference: str
    processed_at: datetime


# =============================================================================
# ACCOUNTING PERIOD EVENT SCHEMAS
# =============================================================================

class PeriodOpenedSchema(EventBase):
    """Schema for PeriodOpened event."""
    period_id: int
    period_month: int
    period_year: int


class PeriodClosedSchema(EventBase):
    """Schema for PeriodClosed event."""
    period_id: int
    period_month: int
    period_year: int
    total_payments: Decimal
    total_refunds: Decimal
    net_revenue: Decimal
    closed_by_id: int


# =============================================================================
# OVERPAYMENT EVENT SCHEMAS
# =============================================================================

class OverpaymentDetectedSchema(EventBase):
    """Schema for OverpaymentDetected event."""
    overpayment_id: int
    payment_id: int
    invoice_id: int
    admission_profile_id: int
    overpayment_amount: Decimal


class OverpaymentResolvedSchema(EventBase):
    """Schema for OverpaymentResolved event."""
    overpayment_id: int
    resolution_type: str
    resolved_amount: Decimal
    resolved_by_id: int


# =============================================================================
# PROCESSED EVENT SCHEMAS (for idempotency tracking)
# =============================================================================

class ProcessedEventResponse(BaseModel):
    """Response schema for processed event record."""
    id: int
    event_id: str
    event_type: str
    event_version: Optional[str]
    consumer_id: str
    processed_at: datetime
    processing_result: str  # success, failed, skipped
    error_message: Optional[str] = None
    event_payload: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class ProcessedEventListResponse(BaseModel):
    """Response schema for list of processed events."""
    items: List[ProcessedEventResponse]
    total: int
    page: int
    page_size: int

    model_config = ConfigDict(from_attributes=True)


class EventProcessingRequest(BaseModel):
    """Request schema for manually triggering event processing."""
    event_type: str
    event_payload: Dict[str, Any]
    correlation_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EventProcessingResponse(BaseModel):
    """Response schema for event processing result."""
    event_id: str
    consumer_id: str
    status: str  # success, failed, skipped
    result: Optional[Any] = None
    error_message: Optional[str] = None
    was_cached: bool = False

    model_config = ConfigDict(from_attributes=True)


# =============================================================================
# EVENT SCHEMA REGISTRY
# =============================================================================

EVENT_SCHEMA_REGISTRY = {
    "FeeCalculated": FeeCalculatedSchema,
    "FeeWaived": FeeWaivedSchema,
    "FeeCancelled": FeeCancelledSchema,
    "FeeFullyPaid": FeeFullyPaidSchema,
    "InvoiceIssued": InvoiceIssuedSchema,
    "InvoicePaid": InvoicePaidSchema,
    "InvoiceOverdue": InvoiceOverdueSchema,
    "InvoiceCancelled": InvoiceCancelledSchema,
    "PaymentReceived": PaymentReceivedSchema,
    "PaymentVerified": PaymentVerifiedSchema,
    "PaymentRejected": PaymentRejectedSchema,
    "RefundRequested": RefundRequestedSchema,
    "RefundApproved": RefundApprovedSchema,
    "RefundProcessed": RefundProcessedSchema,
    "PeriodOpened": PeriodOpenedSchema,
    "PeriodClosed": PeriodClosedSchema,
    "OverpaymentDetected": OverpaymentDetectedSchema,
    "OverpaymentResolved": OverpaymentResolvedSchema,
}


def get_event_schema(event_type: str):
    """Get the Pydantic schema for an event type."""
    return EVENT_SCHEMA_REGISTRY.get(event_type)
