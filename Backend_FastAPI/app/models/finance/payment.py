# app/models/finance/payment.py
"""
Payment Model - Confirmed payment records.

Two types of payments:
1. Online Payments: Auto-verified via gateway callback
   - Created when PaymentIntent completes successfully
   - status = 'verified' immediately

2. Manual Payments: Require maker-checker verification
   - Created by officer recording cash/bank transfer
   - status = 'pending' until verified by another user
   - CRITICAL: created_by_id != verified_by_id (DB constraint)

Security (Section 3.9 C3):
- No self-approval: CHECK constraint prevents created_by_id = verified_by_id
- amount must be > 0
"""
import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey,
    Integer, Numeric, String, Text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.finance.invoice import Invoice
    from app.models.finance.payment_method import PaymentMethod
    from app.models.finance.payment_intent import PaymentIntent
    from app.models.finance.fee import Fee
    from app.models.finance.accounting import AccountingPeriod


class PaymentStatusEnum(str, enum.Enum):
    """Payment status enumeration."""
    pending = "pending"      # Manual payment awaiting verification
    verified = "verified"    # Payment verified (online or manual)
    rejected = "rejected"    # Manual payment rejected
    refunded = "refunded"    # Payment has been refunded


class TransactionTypeEnum(str, enum.Enum):
    """Payment transaction type enumeration."""
    payment = "payment"        # Regular payment
    refund = "refund"          # Refund issued
    adjustment = "adjustment"  # Manual adjustment
    waive = "waive"            # Fee waived
    penalty = "penalty"        # Late payment penalty
    reversal = "reversal"      # Transaction reversal


class Payment(Base):
    """
    Confirmed payment record.

    Business Rules:
    - amount must be positive
    - Online payments (with intent_id) are auto-verified
    - Manual payments require verification by a different user
    - Self-approval is blocked at DB level (chk_payment_no_self_approval)
    """
    __tablename__ = "payment"

    __table_args__ = (
        # CRITICAL: No self-approval (Section 3.9 C3)
        CheckConstraint(
            'verified_by_id IS NULL OR verified_by_id != created_by_id',
            name='chk_payment_no_self_approval'
        ),
        # Đối xứng cho nhánh TỪ CHỐI. Ràng buộc trên chỉ nói về `verified_by_id`,
        # nên suốt thời gian qua maker tự từ chối phiếu của mình được — cả tầng
        # service lẫn tầng DB đều không chặn. Hai vế phải đi cùng nhau: bỏ một
        # vế là để ngỏ đúng nửa còn lại của maker-checker.
        CheckConstraint(
            'rejected_by_id IS NULL OR rejected_by_id != created_by_id',
            name='chk_payment_no_self_reject'
        ),
        CheckConstraint('amount > 0', name='chk_payment_amount_positive'),
        CheckConstraint(
            "status IN ('pending', 'verified', 'rejected', 'refunded')",
            name='chk_payment_status_valid'
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Foreign Keys
    invoice_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("invoice.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    method_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("payment_method.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    intent_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("payment_intent.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        comment="Link to payment intent (for online payments)"
    )

    # Payment details
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Payment amount (VND)"
    )
    reference_code: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Bank/gateway reference code"
    )
    payer_name: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="Name of payer (for manual payments)"
    )
    payer_account: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Payer account number"
    )

    # Status & Lifecycle
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PaymentStatusEnum.pending.value,
        server_default="pending",
        index=True,
        comment="Status: pending|verified|rejected|refunded"
    )
    payment_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Actual payment date"
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    rejected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )

    # Maker-Checker audit
    created_by_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=False,
        index=True,
        comment="User who recorded the payment (maker)"
    )
    verified_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="User who verified the payment (checker)"
    )
    rejected_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # Notes
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # Doanh thu ghi nhận theo ngành TẠI THỜI ĐIỂM XÁC MINH (major-change).
    # Snapshot BẤT BIẾN: stamp = fee.resolved_major_id lúc payment chuyển
    # 'verified' (chỉ với TUITION fee — lệ phí xét tuyển không phân bổ ngành nên
    # để NULL). KHÔNG BAO GIỜ cập nhật khi hồ sơ đổi ngành / reprice /
    # resnapshot fee → tiền đã thu cho ngành A vẫn thuộc A vĩnh viễn; tiền thu
    # sau khi đổi sang B thuộc B. Công nợ/hóa đơn hiện tại vẫn theo
    # ``Fee.resolved_major_id``. NULL = "Chưa xác định" (thu khi fee chưa chốt
    # ngành) — KHÔNG gán hồi tố. Refund giữ nguyên field trên payment gốc nên
    # báo cáo net (payment − refund) tự trừ đúng ngành gốc.
    recognized_major_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("major_program.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Ngành ghi nhận doanh thu tại thời điểm verified (bất biến; "
                "tuition-only, NULL nếu chưa xác định). KHÔNG đổi khi reprice.",
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
    invoice: Mapped["Invoice"] = relationship(
        "Invoice",
        back_populates="payments"
    )
    method: Mapped["PaymentMethod"] = relationship(
        "PaymentMethod"
    )
    intent: Mapped[Optional["PaymentIntent"]] = relationship(
        "PaymentIntent",
        back_populates="payment"
    )
    created_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[created_by_id]
    )
    verified_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[verified_by_id]
    )
    rejected_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[rejected_by_id]
    )
    transactions: Mapped[list["PaymentTransaction"]] = relationship(
        "PaymentTransaction",
        back_populates="payment",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Payment {self.id}: {self.amount} VND ({self.status})>"

    @property
    def is_verified(self) -> bool:
        """Check if payment is verified."""
        return self.status == PaymentStatusEnum.verified.value

    @property
    def is_pending(self) -> bool:
        """Check if payment is pending verification."""
        return self.status == PaymentStatusEnum.pending.value

    @property
    def needs_verification(self) -> bool:
        """Check if payment needs manual verification."""
        return self.is_pending and self.intent_id is None


class PaymentTransaction(Base):
    """
    Audit trail for all financial transactions.

    Records every change to fee balances:
    - payment: Regular payment applied
    - refund: Refund issued
    - adjustment: Manual balance adjustment
    - waive: Fee amount waived
    - penalty: Late payment penalty applied
    - reversal: Transaction reversed

    Used for:
    - Financial reporting
    - Audit trail
    - Balance reconciliation
    """
    __tablename__ = "payment_transaction"

    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('payment', 'refund', 'adjustment', "
            "'waive', 'penalty', 'reversal')",
            name='chk_payment_transaction_type_valid'
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Foreign Keys
    payment_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("payment.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Source payment (NULL for adjustments)"
    )
    fee_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("fee.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    period_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("accounting_period.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Accounting period (NULL if not assigned)"
    )

    # Transaction details
    transaction_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Type: payment|refund|adjustment|waive|penalty|reversal"
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Transaction amount (positive for credits, negative for debits)"
    )
    balance_before: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Fee balance before this transaction"
    )
    balance_after: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Fee balance after this transaction"
    )

    # External references
    external_reference: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="External reference (bank ref, gateway ID)"
    )
    gateway_response: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Gateway response snapshot"
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
        comment="Idempotency key for deduplication"
    )

    # Audit
    performed_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    payment: Mapped[Optional["Payment"]] = relationship(
        "Payment",
        back_populates="transactions"
    )
    fee: Mapped["Fee"] = relationship("Fee")
    period: Mapped[Optional["AccountingPeriod"]] = relationship("AccountingPeriod")
    performed_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[performed_by_id]
    )

    def __repr__(self) -> str:
        return f"<PaymentTransaction {self.id}: {self.transaction_type} {self.amount} VND>"
