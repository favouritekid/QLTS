# app/models/offering_semester_tuition.py
"""
Offering Semester Tuition - Canonical per-semester tuition catalog.

Introduced by PR 1 of the semester_tuition epic (ADR-002). One row per
(academic_info_id, semester_no). Replaces the single-scalar
OfferingAcademicInfo.tuition_fee_per_year as the canonical source of
tuition data, with a transition window during which both coexist.

Business rules:
- semester_no >= 1 (HK1 = 1)
- One row per (academic_info_id, semester_no)
- amount is stored as VND with two decimal places (NUMERIC(15,2))

Non-goals for PR 1:
- No is_published / effective_from / effective_to (lean; add later if
  consumers need publish/window semantics). OfferingAcademicInfo already
  has is_published at the parent level.
- No soft-delete column.

Related:
- docs/adr/ADR-002-semester-tuition-refactor.md
  (Closed Decisions > Decision 3, Gap A, Deferred Decisions D1-D3)
- docs/SEMESTER_TUITION_SPEC.md Section 2
"""
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey,
    Integer, Numeric, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from .base import Base

if TYPE_CHECKING:
    from .offering_academic_info import OfferingAcademicInfo
    from .user import User


class OfferingSemesterTuition(Base):
    """Per-semester tuition catalog row."""

    __tablename__ = "offering_semester_tuition"

    __table_args__ = (
        UniqueConstraint(
            'academic_info_id', 'semester_no',
            name='uq_offering_semester_tuition_info_semester',
        ),
        CheckConstraint(
            'semester_no >= 1',
            name='chk_offering_semester_tuition_semester_no_positive',
        ),
        CheckConstraint(
            'amount >= 0',
            name='chk_offering_semester_tuition_amount_non_negative',
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    academic_info_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("offering_academic_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Link to the parent OfferingAcademicInfo (program-year)",
    )
    semester_no: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
        comment="Semester index within the full course, 1-based (HK1=1)",
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2),
        nullable=False,
        comment="Tuition amount for this semester (VND)",
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )

    academic_info: Mapped["OfferingAcademicInfo"] = relationship(
        "OfferingAcademicInfo",
        back_populates="semester_tuitions",
    )
    created_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[created_by_user_id]
    )
    updated_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[updated_by_user_id]
    )

    def __repr__(self) -> str:
        return (
            f"<OfferingSemesterTuition "
            f"academic_info_id={self.academic_info_id} "
            f"HK{self.semester_no} amount={self.amount}>"
        )
