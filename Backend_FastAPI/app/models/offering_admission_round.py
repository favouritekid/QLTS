# app/models/offering_admission_round.py
"""OfferingAdmissionRound — Phase 2 v8.2 Option A year-level entity.

1 round = 1 row globally cho cả trường (Q1 v8.2). KHÔNG nest dưới
academic_info nữa — đó là v6 archived schema (tag
``phase2-pr-2a-v6-archived``).

Quota fields (round_quota, admit_quota, submission_count) ship trên
admission_path (PR-2B v2), KHÔNG trên này.

PLAN refs: §2.1.a (Rule 1-4 lifecycle) + §4 line 540-547 (admit_quota
semantic) + Phần 9 Phase 2 design pivot Option A.
Migration: ``alembic/versions/phase2_01_v2_create_offering_admission_round_year_level.py``.
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
    """Đợt tuyển sinh year-level (1 row per đợt globally).

    Examples (năm 2026):
    * DOT_1: Đợt 1 chính thức (Mar-Jun)
    * DOT_2: Đợt 2 bổ sung (Jul-Sep) — admin tạo khi DOT_1 chưa đủ chỉ tiêu
    * DOT_3: Đợt 3 (Sep-Oct)
    * BO_SUNG: Đợt vét tuyển cuối năm (Nov)
    * DOT_1_VLVH: Đợt 1 hệ vừa làm vừa học (Q8 — pure string convention)

    Lifecycle (per SPEC §2.1.a)
    ---------------------------
    * Rule 1 — Cutoff submit: candidate ``end_date < NOW()`` → 410 Gone
    * Rule 2 — Admin extend: ``POST /rounds/{id}/extend`` writes
      ``extended_at`` + ``extended_by_user_id`` + ``extension_reason``
    * Rule 3 — 6-month archive: cron ``archive_expired_rounds_task``
      (DEFER Phase 3) moves profiles to ``_archived_admission_profile``
    * Rule 4 — Engine scope: profiles của round có ``is_active=true``
      AND ``end_date >= NOW() - 30d``
    """

    __tablename__ = "offering_admission_round"

    id = Column(Integer, primary_key=True, index=True)

    academic_year = Column(
        Integer,
        nullable=False,
        index=True,
        comment="Year-level grouping. UNIQUE per (academic_year, round_code)",
    )

    round_code = Column(
        String(20),
        nullable=False,
        comment="Pure string Phase 2 (Q8): DOT_1 / DOT_2 / DOT_3 / BO_SUNG / DOT_1_VLVH",
    )
    round_name = Column(
        String(100),
        nullable=False,
        comment='Localized display: "Đợt 1 - 2026"',
    )

    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

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
    extended_by = relationship(
        "User",
        foreign_keys=[extended_by_user_id],
    )
    # admission_paths relationship will be added by PR-2B v2 when
    # admission_path.admission_round_id FK ships.

    __table_args__ = (
        UniqueConstraint(
            "academic_year",
            "round_code",
            name="uq_offering_admission_round_year_code",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<OfferingAdmissionRound id={self.id} "
            f"year={self.academic_year} code={self.round_code!r} "
            f"active={self.is_active}>"
        )
