# app/models/finance/fee.py
"""
Fee Model - Main fee record for Finance Module.

Fee Types:
- application: Application/admission fee (migrated from applied_rules)
- tuition: Tuition fee (main academic fee)
- enrollment: Enrollment processing fee
- insurance: Student insurance
- dormitory: Dormitory fee
- other: Miscellaneous fees

Security Features:
- IDOR Protection: Access via admission_profile.lead.unit_id
- Optimistic Locking: version column for concurrent access
- Audit Trail: calculated_by_id, timestamps
- Amount Validation: CHECK constraints ensure amounts >= 0

Unique Constraint:
- (admission_profile_id, fee_type, academic_year) - One fee per type per year
"""
import enum
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.admission import AdmissionProfile
    from app.models.user import User
    from app.models.tuition_discount_policy import TuitionDiscountPolicy
    from app.models.finance.installment_plan import InstallmentPlan
    from app.models.finance.invoice import Invoice


class FeeTypeEnum(str, enum.Enum):
    """Fee type enumeration."""
    application = "application"
    tuition = "tuition"
    enrollment = "enrollment"
    insurance = "insurance"
    dormitory = "dormitory"
    other = "other"


class FeeStatusEnum(str, enum.Enum):
    """Fee status enumeration."""
    pending = "pending"        # Fee created, not yet calculated
    calculated = "calculated"  # Fee amount calculated
    invoiced = "invoiced"      # Invoice(s) generated
    partial = "partial"        # Partially paid
    paid = "paid"              # Fully paid
    overdue = "overdue"        # Past due date, not fully paid
    waived = "waived"          # Fee waived (by admin)
    cancelled = "cancelled"    # Fee cancelled


class Fee(Base):
    """
    Main fee record for a student's admission profile.

    Business Rules:
    - One fee per (profile, type, year) combination
    - final_amount = base_amount - total_discount
    - remaining = final_amount - paid_amount - waived_amount
    - Status transitions follow FINANCE_MODULE_DESIGN.md Section 4.1
    """
    __tablename__ = "fee"

    __table_args__ = (
        UniqueConstraint(
            'admission_profile_id', 'fee_type', 'academic_year',
            name='uq_fee_profile_type_year'
        ),
        CheckConstraint(
            'base_amount >= 0 AND total_discount >= 0 AND final_amount >= 0 '
            'AND paid_amount >= 0 AND waived_amount >= 0',
            name='chk_fee_amounts_non_negative'
        ),
        CheckConstraint(
            'total_discount <= base_amount',
            name='chk_fee_discount_not_exceed_base'
        ),
        CheckConstraint(
            "fee_type IN ('application', 'tuition', 'enrollment', "
            "'insurance', 'dormitory', 'other')",
            name='chk_fee_type_valid'
        ),
        CheckConstraint(
            "status IN ('pending', 'calculated', 'invoiced', 'partial', "
            "'paid', 'overdue', 'waived', 'cancelled')",
            name='chk_fee_status_valid'
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Foreign Keys
    admission_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Link to admission profile (IDOR via profile.lead.unit_id)"
    )
    installment_plan_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("installment_plan.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Selected installment plan (NULL = single payment)"
    )

    # Fee Type & Year
    fee_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=FeeTypeEnum.tuition.value,
        server_default="tuition",
        index=True,
        comment="Fee type: application|tuition|enrollment|insurance|dormitory|other"
    )
    academic_year: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="Academic year (e.g., 2026)"
    )

    # Amount Calculation
    base_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Original fee amount before discounts (VND)"
    )
    total_discount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Total discount amount (VND)"
    )
    final_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Final amount after discounts (VND)"
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Amount already paid (VND)"
    )
    waived_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        comment="Amount waived (VND)"
    )

    # Status & Lifecycle
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=FeeStatusEnum.pending.value,
        server_default="pending",
        index=True,
        comment="Status: pending|calculated|invoiced|partial|paid|overdue|waived|cancelled"
    )
    due_date: Mapped[Optional[date]] = mapped_column(
        Date,
        nullable=True,
        index=True,
        comment="Overall due date for this fee"
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When fee was calculated"
    )
    last_payment_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp of last payment"
    )

    # Audit
    calculated_by_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="User who calculated/created this fee"
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Optimistic locking version"
    )
    # Notes (for waive/cancel reasons, etc.)
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Notes for waive/cancel/audit trail"
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
    admission_profile: Mapped["AdmissionProfile"] = relationship(
        "AdmissionProfile",
        back_populates="fees"
    )
    installment_plan: Mapped[Optional["InstallmentPlan"]] = relationship(
        "InstallmentPlan"
    )
    calculated_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[calculated_by_id]
    )
    applied_discounts: Mapped[List["FeeAppliedDiscount"]] = relationship(
        "FeeAppliedDiscount",
        back_populates="fee",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    invoices: Mapped[List["Invoice"]] = relationship(
        "Invoice",
        back_populates="fee",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Fee {self.id}: {self.fee_type} - {self.final_amount} VND ({self.status})>"

    @property
    def remaining_amount(self) -> Decimal:
        """Calculate remaining balance (amount still owed)."""
        return self.final_amount - self.paid_amount - self.waived_amount

    @property
    def is_fully_paid(self) -> bool:
        """Check if fee is fully paid or waived."""
        return self.remaining_amount <= Decimal("0")

    @property
    def is_overdue(self) -> bool:
        """Check if fee is past due date and not fully paid."""
        if self.is_fully_paid:
            return False
        if self.due_date is None:
            return False
        return date.today() > self.due_date


class FeeAppliedDiscount(Base):
    """
    Tracks discounts applied to a fee.

    Stores a snapshot of the discount calculation at the time of application.
    This ensures the discount amount is preserved even if the policy changes.

    Business Rules:
    - One discount policy can only be applied once per fee
    - application_order determines stacking order (additive by default)
    - calculation_snapshot preserves the calculation for audit
    """
    __tablename__ = "fee_applied_discount"

    __table_args__ = (
        UniqueConstraint(
            'fee_id', 'policy_id',
            name='uq_fee_applied_discount_fee_policy'
        ),
        CheckConstraint(
            'discount_amount >= 0',
            name='chk_fee_applied_discount_amount_non_negative'
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
    policy_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("tuition_discount_policy.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Reference to discount policy (NULL if policy deleted)"
    )

    # Discount details
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Actual discount amount applied (VND)"
    )
    discount_percent: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        comment="Discount percentage at time of application"
    )
    calculation_snapshot: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Snapshot of calculation details for audit"
    )
    application_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="Order in which discount was applied (for stacking)"
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    fee: Mapped["Fee"] = relationship(
        "Fee",
        back_populates="applied_discounts"
    )
    policy: Mapped[Optional["TuitionDiscountPolicy"]] = relationship(
        "TuitionDiscountPolicy"
    )

    def __repr__(self) -> str:
        return f"<FeeAppliedDiscount fee={self.fee_id} policy={self.policy_id} amount={self.discount_amount}>"
