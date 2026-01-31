# app/models/finance/payment_intent.py
"""
PaymentIntent Model - Online payment intent tracking.

Implements the 2-phase payment pattern:
1. Create Intent: Generate payment URL for gateway
2. Complete Intent: Process gateway callback, create Payment record

Status Flow:
created → pending → completed
           ↓
        failed/expired/cancelled

Security (Section 3.9 C1):
- Verify gateway signature before processing callback
- Match amount exactly with intent amount
- Verify gateway_ref matches our records
"""
import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.finance.invoice import Invoice
    from app.models.finance.payment_method import PaymentMethod
    from app.models.finance.payment import Payment


class PaymentIntentStatusEnum(str, enum.Enum):
    """Payment intent status enumeration."""
    created = "created"      # Intent created, payment URL generated
    pending = "pending"      # User redirected to gateway
    completed = "completed"  # Payment successful, Payment record created
    failed = "failed"        # Payment failed at gateway
    expired = "expired"      # Intent expired (timeout)
    cancelled = "cancelled"  # Cancelled by user or system


class GatewayStatusEnum(str, enum.Enum):
    """Gateway-reported status enumeration."""
    created = "created"
    pending = "pending"
    success = "success"
    failed = "failed"
    expired = "expired"


class PaymentIntent(Base):
    """
    Online payment intent tracking.

    Lifecycle:
    1. Client calls POST /payments/intents with invoice_id, method_id
    2. System creates intent, generates gateway payment URL
    3. Client redirects user to pay_url
    4. User completes payment on gateway
    5. Gateway sends callback to /payments/callback/{gateway_code}
    6. System verifies callback, updates intent, creates Payment

    Security Features:
    - idempotency_key prevents duplicate intents
    - gateway_ref links to gateway transaction
    - Amount verification on callback
    """
    __tablename__ = "payment_intent"

    __table_args__ = (
        UniqueConstraint(
            'idempotency_key', 'invoice_id',
            name='uq_payment_intent_idempotency_invoice'
        ),
        CheckConstraint('amount > 0', name='chk_payment_intent_amount_positive'),
        CheckConstraint(
            "status IN ('created', 'pending', 'completed', 'failed', 'expired', 'cancelled')",
            name='chk_payment_intent_status_valid'
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Foreign Keys
    invoice_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("invoice.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    method_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("payment_method.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )

    # Payment details
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Payment amount (VND)"
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="VND",
        server_default="VND"
    )

    # Gateway tracking
    gateway_ref: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
        comment="Gateway transaction reference (e.g., vnp_TxnRef)"
    )
    gateway_status: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Status from gateway: created|pending|success|failed|expired"
    )
    gateway_response: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Full gateway response for debugging"
    )

    # Idempotency
    idempotency_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Client-provided idempotency key (UUID)"
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PaymentIntentStatusEnum.created.value,
        server_default="created",
        index=True,
        comment="Intent status: created|pending|completed|failed|expired|cancelled"
    )

    # URLs
    pay_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Gateway payment URL"
    )
    return_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Client return URL after payment"
    )

    # Lifecycle timestamps
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Intent expiration time"
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    callback_received_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    callback_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Callback payload from gateway"
    )

    # Standard timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    invoice: Mapped["Invoice"] = relationship(
        "Invoice",
        back_populates="payment_intents"
    )
    method: Mapped["PaymentMethod"] = relationship(
        "PaymentMethod"
    )
    payment: Mapped[Optional["Payment"]] = relationship(
        "Payment",
        back_populates="intent",
        uselist=False
    )

    def __repr__(self) -> str:
        return f"<PaymentIntent {self.id}: {self.amount} VND ({self.status})>"

    @property
    def is_expired(self) -> bool:
        """Check if intent has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_terminal(self) -> bool:
        """Check if intent is in a terminal state."""
        return self.status in (
            PaymentIntentStatusEnum.completed.value,
            PaymentIntentStatusEnum.failed.value,
            PaymentIntentStatusEnum.expired.value,
            PaymentIntentStatusEnum.cancelled.value,
        )

    @property
    def can_process_callback(self) -> bool:
        """Check if callback can be processed for this intent."""
        return not self.is_terminal and not self.is_expired
