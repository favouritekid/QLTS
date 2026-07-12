# app/models/finance/refund.py
"""
RefundRequest Model - Refund request workflow.

Refund workflow:
1. Officer creates refund request (status = pending)
2. Manager/Admin approves or rejects
3. If approved, refund is processed (status = refunded)

Security (Section 3.9 H6):
- Refund amount cannot exceed original payment amount
- Total refunds for a payment cannot exceed payment amount
"""
import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey,
    Integer, Numeric, String, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.finance.payment import Payment


class RefundStatusEnum(str, enum.Enum):
    """Refund request status enumeration."""
    pending = "pending"      # Request submitted
    approved = "approved"    # Request approved
    rejected = "rejected"    # Request rejected
    refunded = "refunded"    # Refund completed


class RefundSourceEnum(str, enum.Enum):
    """Origin of a refund request — distinguishes independently-managed refunds
    from those the withdraw orchestrator auto-files.

    Used by ``cancel_withdrawal``/rollback (``reject_open_refunds_for_profile``):
    only ``withdrawal``-sourced refunds are auto-rejected when a pending
    withdrawal is reverted. A pre-existing ``manual`` (finance-created) or
    ``overpayment`` refund is left untouched — it is not part of the withdrawal.
    """
    withdrawal = "withdrawal"    # Auto-filed by the withdraw orchestrator
    manual = "manual"            # Created by a finance user (POST /api/refunds)
    overpayment = "overpayment"  # Filed to return a tracked overpayment


class RefundRequest(Base):
    """
    Refund request record.

    Business Rules:
    - amount must be positive and <= payment.amount
    - Total refunds for a payment cannot exceed payment.amount
    - Rejection requires a reason
    - Refund reference stored when refund is completed
    """
    __tablename__ = "refund_request"

    __table_args__ = (
        CheckConstraint('amount > 0', name='chk_refund_request_amount_positive'),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'refunded')",
            name='chk_refund_request_status_valid'
        ),
        CheckConstraint(
            "source IN ('withdrawal', 'manual', 'overpayment')",
            name='chk_refund_request_source_valid'
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Foreign Keys
    payment_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("payment.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )

    # Request details
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Reason for refund request"
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Refund amount (must be <= payment.amount)"
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=RefundStatusEnum.pending.value,
        server_default="pending",
        index=True,
        comment="Status: pending|approved|rejected|refunded"
    )

    # Origin — drives whether cancel-withdrawal auto-rejects this refund.
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=RefundSourceEnum.manual.value,
        server_default="manual",
        index=True,
        comment="Origin: withdrawal|manual|overpayment",
    )

    # Lifecycle timestamps
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    refunded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # User tracking
    requested_by_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=False,
        index=True
    )
    approved_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True
    )
    rejected_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True
    )

    # Rejection/Refund details
    rejection_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )
    refund_reference: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="External refund reference (bank ref, gateway ID)"
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
    requested_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[requested_by_id]
    )
    approved_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[approved_by_id]
    )
    rejected_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[rejected_by_id]
    )

    def __repr__(self) -> str:
        return f"<RefundRequest {self.id}: {self.amount} VND ({self.status})>"

    @property
    def is_pending(self) -> bool:
        """Check if request is pending."""
        return self.status == RefundStatusEnum.pending.value

    @property
    def is_approved(self) -> bool:
        """Check if request is approved."""
        return self.status == RefundStatusEnum.approved.value

    @property
    def is_completed(self) -> bool:
        """Check if refund is completed."""
        return self.status == RefundStatusEnum.refunded.value

    @property
    def can_process(self) -> bool:
        """Check if refund can be processed."""
        return self.status == RefundStatusEnum.approved.value
