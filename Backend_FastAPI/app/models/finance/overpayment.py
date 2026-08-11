# app/models/finance/overpayment.py
"""
OverpaymentRecord Model - Overpayment liability tracking (v1.2).

When a payment exceeds the invoice amount, an overpayment record is created.
The accountant can then resolve it by:
- apply_to_next: Apply to another invoice for the same student
- refund: Issue a refund
- write_off: Write off small amounts (requires manager approval)

Security (Section 3.3 Overpayment Policy):
- overpayment_amount must be > 0
- Resolution requires explicit action (no auto-refund)
- Audit trail for all resolutions
"""
import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.admission import AdmissionProfile
    from app.models.finance.payment import Payment
    from app.models.finance.invoice import Invoice
    from app.models.finance.refund import RefundRequest


class OverpaymentStatusEnum(str, enum.Enum):
    """Overpayment status enumeration."""
    pending = "pending"      # Awaiting resolution
    applied = "applied"      # Applied to another invoice
    refunded = "refunded"    # Refunded to student
    cancelled = "cancelled"  # Cancelled (e.g., written off)


class ResolutionTypeEnum(str, enum.Enum):
    """Overpayment resolution type enumeration."""
    apply_to_next = "apply_to_next"  # Apply to next invoice
    refund = "refund"                # Issue refund
    write_off = "write_off"          # Write off (small amounts)


class OverpaymentRecord(Base):
    """
    Records overpayment liability for a student.

    Created when payment.amount > invoice.remaining_amount.
    The excess amount is tracked here until resolved.

    Resolution Workflow:
    1. Payment recorded, overpayment detected
    2. OverpaymentRecord created (status = pending)
    3. Accountant reviews and chooses resolution:
       - apply_to_next: Select another invoice, create payment
       - refund: Create RefundRequest
       - write_off: Small amounts, requires approval
    4. Status updated to applied/refunded/cancelled
    """
    __tablename__ = "overpayment_record"

    __table_args__ = (
        CheckConstraint(
            'overpayment_amount > 0',
            name='chk_overpayment_amount_positive'
        ),
        CheckConstraint(
            "status IN ('pending', 'applied', 'refunded', 'cancelled')",
            name='chk_overpayment_status_valid'
        ),
        CheckConstraint(
            "resolution_type IS NULL OR "
            "resolution_type IN ('apply_to_next', 'refund', 'write_off')",
            name='chk_overpayment_resolution_type_valid'
        ),
        # MỘT phiếu thu chỉ sinh ĐÚNG MỘT khoản thừa. Không có ràng buộc này
        # thì mỗi lần retry (verify lại, import chạy lại, callback gateway lặp)
        # là thêm một nghĩa vụ trả nợ cho cùng số tiền — và nợ thì không tự mất
        # đi như một hàng rác.
        UniqueConstraint('payment_id', name='uq_overpayment_payment'),
        # Nguồn phát sinh, để phân biệt khoản thừa do GHI TIỀN với khoản thừa do
        # đổi giá sau thu hay do đối soát tay. NULL = hàng lịch sử: bảng cũ
        # không có cột này nên provenance của chúng không truy được, và đoán thì
        # tệ hơn để trống.
        CheckConstraint(
            "source_type IS NULL OR source_type IN "
            "('payment_settlement', 'invoice_reprice', 'manual_reconciliation')",
            name='chk_overpayment_source_type_valid'
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Foreign Keys - Source
    payment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("payment.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Source payment that caused overpayment"
    )
    invoice_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("invoice.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Invoice that was overpaid"
    )
    admission_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Student profile for tracking"
    )

    # Overpayment details
    overpayment_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Amount of overpayment (VND)"
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="VND",
        server_default="VND"
    )

    #: Nguồn phát sinh khoản thừa. NULL cho mọi hàng có trước cột này —
    #: provenance của chúng không truy được, xem CheckConstraint ở trên.
    source_type: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
        index=True,
        comment="payment_settlement | invoice_reprice | manual_reconciliation",
    )

    # Status & Resolution
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=OverpaymentStatusEnum.pending.value,
        server_default="pending",
        index=True,
        comment="Status: pending|applied|refunded|cancelled"
    )
    resolution_type: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="How resolved: apply_to_next|refund|write_off"
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    resolved_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    resolution_notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # If applied to another invoice
    applied_to_invoice_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("invoice.id", ondelete="SET NULL"),
        nullable=True,
        comment="Invoice to which overpayment was applied"
    )
    applied_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 2),
        nullable=True,
        comment="Amount applied to next invoice"
    )

    # If refunded
    refund_request_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("refund_request.id", ondelete="SET NULL"),
        nullable=True,
        comment="Link to refund request if refunded"
    )

    # Timestamps
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
    payment: Mapped["Payment"] = relationship("Payment")
    invoice: Mapped["Invoice"] = relationship(
        "Invoice",
        foreign_keys=[invoice_id]
    )
    admission_profile: Mapped["AdmissionProfile"] = relationship("AdmissionProfile")
    resolved_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[resolved_by_id]
    )
    applied_to_invoice: Mapped[Optional["Invoice"]] = relationship(
        "Invoice",
        foreign_keys=[applied_to_invoice_id]
    )
    refund_request: Mapped[Optional["RefundRequest"]] = relationship("RefundRequest")

    def __repr__(self) -> str:
        return f"<OverpaymentRecord {self.id}: {self.overpayment_amount} VND ({self.status})>"

    @property
    def is_pending(self) -> bool:
        """Check if overpayment is pending resolution."""
        return self.status == OverpaymentStatusEnum.pending.value

    @property
    def is_resolved(self) -> bool:
        """Check if overpayment has been resolved."""
        return self.status in (
            OverpaymentStatusEnum.applied.value,
            OverpaymentStatusEnum.refunded.value,
            OverpaymentStatusEnum.cancelled.value,
        )

    @property
    def can_apply_to_invoice(self) -> bool:
        """Check if overpayment can be applied to another invoice."""
        return self.is_pending

    @property
    def can_refund(self) -> bool:
        """Check if overpayment can be refunded."""
        return self.is_pending
