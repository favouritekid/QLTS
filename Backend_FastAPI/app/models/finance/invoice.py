# app/models/finance/invoice.py
"""
Invoice Model - Invoice records with installment support.

Each fee can have multiple invoices (one per installment).
Invoice number format: INV-YYYY-XXXXXX (generated via DB sequence).

Status Flow:
draft → issued → partial → paid
                ↓
              overdue
                ↓
            cancelled

Security (Section 3.9 H8):
- Can only create invoice if fee.status in ('calculated', 'invoiced', 'partial')
- Invoice amount cannot exceed fee balance
"""
import enum
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.finance.fee import Fee
    from app.models.finance.payment import Payment
    from app.models.finance.payment_intent import PaymentIntent


class InvoiceStatusEnum(str, enum.Enum):
    """Invoice status enumeration."""
    draft = "draft"          # Invoice created, not yet issued
    issued = "issued"        # Invoice issued to student
    partial = "partial"      # Partially paid
    paid = "paid"            # Fully paid
    cancelled = "cancelled"  # Invoice cancelled
    overdue = "overdue"      # Past due date, not fully paid


# Single source of truth for "an invoice that can still receive money".
# Used by manual payment recording, overpayment apply, VietQR generation, and
# the debt report so the payable-status rule never diverges across the module.
PAYABLE_INVOICE_STATUSES = (
    InvoiceStatusEnum.issued.value,
    InvoiceStatusEnum.partial.value,
    InvoiceStatusEnum.overdue.value,
)


class Invoice(Base):
    """
    Invoice record for a fee installment.

    Business Rules:
    - One invoice per (fee_id, installment_no) combination
    - invoice_number is globally unique (INV-YYYY-XXXXXX)
    - amount must be positive
    - Can track late payment penalties
    """
    __tablename__ = "invoice"

    __table_args__ = (
        UniqueConstraint(
            'fee_id', 'installment_no',
            name='uq_invoice_fee_installment'
        ),
        CheckConstraint('amount > 0', name='chk_invoice_amount_positive'),
        CheckConstraint('paid_amount >= 0', name='chk_invoice_paid_amount_non_negative'),
        CheckConstraint('penalty_amount >= 0', name='chk_invoice_penalty_non_negative'),
        CheckConstraint(
            "status IN ('draft', 'issued', 'partial', 'paid', 'cancelled', 'overdue')",
            name='chk_invoice_status_valid'
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Foreign Keys
    fee_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fee.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Invoice identification
    invoice_number: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        unique=True,
        comment="Unique invoice number (e.g., INV-2026-000001)"
    )
    installment_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Installment number (1 for single payment)"
    )

    # Amounts
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Invoice amount (VND)"
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Amount paid on this invoice"
    )
    penalty_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Late payment penalty"
    )

    # Status & Lifecycle
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=InvoiceStatusEnum.draft.value,
        server_default="draft",
        index=True,
        comment="Status: draft|issued|partial|paid|cancelled|overdue"
    )
    due_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True
    )
    issued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # Notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    cancelled_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # Audit
    issued_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    cancelled_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True
    )
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
    fee: Mapped["Fee"] = relationship(
        "Fee",
        back_populates="invoices"
    )
    issued_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[issued_by_id]
    )
    cancelled_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[cancelled_by_id]
    )
    payments: Mapped[List["Payment"]] = relationship(
        "Payment",
        back_populates="invoice",
        lazy="selectin"
    )
    payment_intents: Mapped[List["PaymentIntent"]] = relationship(
        "PaymentIntent",
        back_populates="invoice",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Invoice {self.invoice_number}: {self.amount} VND ({self.status})>"

    @property
    def remaining_amount(self) -> Decimal:
        """Calculate remaining amount to pay on this invoice."""
        return self.amount + self.penalty_amount - self.paid_amount

    @property
    def total_due(self) -> Decimal:
        """Total amount due including penalty."""
        return self.amount + self.penalty_amount

    @property
    def is_fully_paid(self) -> bool:
        """Check if invoice is fully paid."""
        return self.remaining_amount <= Decimal("0")

    @property
    def is_overdue(self) -> bool:
        """Check if invoice is past due date and not fully paid."""
        if self.is_fully_paid:
            return False
        return date.today() > self.due_date
