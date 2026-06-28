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

Uniqueness (PR 1 of the semester_tuition epic, ADR-002):
- Non-tuition fees: one row per (admission_profile_id, fee_type,
  academic_year). Enforced by partial unique index
  `uq_fee_profile_type_year_nontuition` WHERE fee_type <> 'tuition'.
  Preserves pre-PR1 behavior exactly.
- Tuition fees: one row per (admission_profile_id, fee_type,
  semester_no). Enforced by partial unique index
  `uq_fee_profile_type_semester_tuition` WHERE fee_type = 'tuition'.
  Allows HK1/HK2/... to coexist on the same profile in the same
  academic_year.
- The legacy constraint `uq_fee_profile_type_year` was dropped in
  migration `st20260412001_semester_tuition_schema.py`.
"""
import enum
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint, text
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
    from app.models.major_program import MajorProgram


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
    - Non-tuition fees: one row per (profile, fee_type, academic_year).
    - Tuition fees: one row per (profile, fee_type, semester_no). HK1/HK2
      may coexist in the same academic_year. `semester_no` is NULL for
      non-tuition rows; tuition rows require a positive value.
    - final_amount = base_amount - total_discount
    - remaining = final_amount - paid_amount - waived_amount
    - Status transitions follow FINANCE_MODULE_DESIGN.md Section 4.1
      (historical — see docs/adr/ADR-002-semester-tuition-refactor.md
      for the current model direction).
    """
    __tablename__ = "fee"

    __table_args__ = (
        # Partial unique index: preserve pre-PR1 non-tuition behavior.
        # Excludes cancelled fees so a cancelled (e.g. tính nhầm) fee does NOT
        # block re-calculating a correct one. Matches
        # fee_repository.check_duplicate() semantics exactly.
        Index(
            'uq_fee_profile_type_year_nontuition',
            'admission_profile_id', 'fee_type', 'academic_year',
            unique=True,
            postgresql_where=text("fee_type <> 'tuition' AND status <> 'cancelled'"),
        ),
        # Partial unique index: new per-semester uniqueness for tuition.
        # Allows HK1/HK2/HK3/... on the same profile in the same year, and
        # allows re-calc after a cancelled (status <> 'cancelled').
        Index(
            'uq_fee_profile_type_semester_tuition',
            'admission_profile_id', 'fee_type', 'semester_no',
            unique=True,
            postgresql_where=text("fee_type = 'tuition' AND status <> 'cancelled'"),
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
        # PR 1: tuition fees must carry a positive semester_no. Non-tuition
        # fees leave semester_no NULL (no semantic). The partial index
        # above would also block invalid rows, but this CHECK is a second
        # line of defense against bugs inserting tuition rows with NULL
        # semester_no that would silently escape the index predicate.
        CheckConstraint(
            "fee_type <> 'tuition' "
            "OR (semester_no IS NOT NULL AND semester_no >= 1)",
            name='chk_fee_tuition_semester_no_required'
        ),
        # PR 1 hardening: non-tuition fees must leave semester_no NULL.
        # The partial index uq_fee_profile_type_year_nontuition keys on
        # academic_year (not semester_no), so a non-tuition row with a
        # stray semester_no value would not cause uniqueness corruption
        # but would break the "non-tuition = NULL" invariant that PR 3+
        # relies on. This CHECK closes the slack before it becomes a bug.
        CheckConstraint(
            "fee_type = 'tuition' OR semester_no IS NULL",
            name='chk_fee_nontuition_semester_no_null'
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
    semester_no: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        comment="Semester index (1..N) for tuition fees (HK1=1, HK2=2, ...). "
                "NULL for non-tuition fee types. See ADR-002 Gap A (v2 "
                "partial-index strategy). Enforced by partial unique index "
                "uq_fee_profile_type_semester_tuition and CHECK "
                "chk_fee_tuition_semester_no_required."
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

    # Resolved academic snapshot (denormalized — single source for the
    # "Thu học phí" workspace: filter + list row + drawer + status-counts).
    # Populated by ``resnapshot_fee_academic_info_for_profile`` (the SAME
    # ``resolve_fee_academic_info`` used for the tuition amount), so a multi-NV
    # profile's row/filter reflects the ADMITTED choice — never the lead's
    # intent offering. ALL nullable + fail-soft: when the resolver can't decide
    # (multi-NV not-yet-admitted / 0 / ≥2 admitted) the columns stay NULL and
    # the UI shows "(chưa chốt ngành)" rather than guessing.
    resolved_academic_info_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("offering_academic_info.id", ondelete="SET NULL"),
        nullable=True,
        comment="Snapshot: resolved OfferingAcademicInfo (trace source of major)"
    )
    resolved_major_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("major_program.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Snapshot: resolved MajorProgram (filter/display — NULL=chưa chốt)"
    )
    resolved_degree_level: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Snapshot: degree level TEXT NAME ('Cao đẳng'…) matching "
                "MajorProgram.degree_level legacy text + admissions FE filter value"
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
    # Resolved-major snapshot relationship (read-only display name source).
    resolved_major: Mapped[Optional["MajorProgram"]] = relationship(
        "MajorProgram",
        foreign_keys=[resolved_major_id],
        lazy="raise",
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
        """Check if fee is fully paid or waived.

        Under the per-semester model (ADR-002), each Fee row represents
        one semester. This property means "this semester's fee is fully
        settled", not "all tuition across all semesters is paid".

        Note: admission pipeline projection uses is_hk1_settled() from
        fee_calculation_service, which (like this property) requires the
        semester fee to be fully settled (remaining <= 0). A partial
        payment does NOT project the lead to sts10 — it stays at sts14.
        """
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
