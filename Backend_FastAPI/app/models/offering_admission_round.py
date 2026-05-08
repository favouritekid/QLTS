# app/models/offering_admission_round.py
"""OfferingAdmissionRound — Phase 2 multi-round capability.

Top-level model under offering hierarchy (sibling of
``OfferingAcademicInfo``). Each academic_info can have multiple rounds
(DOT_1, DOT_2, BO_SUNG...) với UNIQUE(academic_info_id, round_code).

PLAN refs: §2.1 line 530-560 schema + §2.1.a line 562-611 lifecycle.
Migration: ``alembic/versions/phase2_01_create_offering_admission_round.py``.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class OfferingAdmissionRound(Base):
    """Đợt tuyển sinh per academic_info.

    Examples
    --------
    * DOT_1 - 2026: chính thức, round_quota=200, admit_quota=NULL (no cap)
    * DOT_2 - 2026: bổ sung, round_quota=50, admit_quota=30
    * BO_SUNG - 2026: vét tuyển, round_quota=20

    Lifecycle (per SPEC §2.1.a)
    ---------------------------
    * Rule 1 — Cutoff submit: candidate ``end_date < NOW()`` → 410 Gone.
    * Rule 2 — Admin extend: ``POST /rounds/{id}/extend`` writes
      ``extended_at`` + ``extended_by_user_id`` + ``extension_reason``.
    * Rule 3 — 6-month archive: cron ``archive_expired_rounds_task``
      (DEFER Phase 3) moves profiles to ``_archived_admission_profile``.
    * Rule 4 — Engine scope: profiles của round có ``is_active=true``
      AND ``end_date >= NOW() - 30d``.
    """

    __tablename__ = "offering_admission_round"

    id = Column(Integer, primary_key=True, index=True)

    academic_info_id = Column(
        Integer,
        ForeignKey("offering_academic_info.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    round_code = Column(
        String(20),
        nullable=False,
        comment="UNIQUE per academic_info: DOT_1 / DOT_2 / BO_SUNG",
    )
    round_name = Column(
        String(100),
        nullable=False,
        comment='Localized display: "Đợt 1 - 2026"',
    )

    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    round_quota = Column(
        Integer,
        nullable=True,
        comment=(
            "Submission slot cap. Sum ≤ academic_info.annual_admission_quota "
            "(PLAN §5 tier 1). NULL = no cap."
        ),
    )
    admit_quota = Column(
        Integer,
        nullable=True,
        comment=(
            "Admit slot cap. NULL = inherit round_quota. Engine T7 guard "
            "count(admitted) < admit_quota (PLAN line 540-547)."
        ),
    )
    submission_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment=(
            "Atomic high-watermark counter — increment on submit per "
            "PLAN line 4100-4107. NEVER decrement on withdraw/reject."
        ),
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    archived_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Soft-archive marker. Phase 3 future: cron will move profiles "
            "to _archived_admission_profile (phase1_16) at end_date+6mo."
        ),
    )

    # SPEC §2.1.a Rule 2 — admin extend audit fields
    extended_at = Column(DateTime(timezone=True), nullable=True)
    extended_by_user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    extension_reason = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # Relationships
    academic_info = relationship(
        "OfferingAcademicInfo",
        back_populates="admission_rounds",
    )
    extended_by = relationship(
        "User",
        foreign_keys=[extended_by_user_id],
    )

    __table_args__ = (
        UniqueConstraint(
            "academic_info_id",
            "round_code",
            name="uq_offering_admission_round_code",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<OfferingAdmissionRound id={self.id} "
            f"academic_info_id={self.academic_info_id} "
            f"code={self.round_code!r} active={self.is_active}>"
        )
