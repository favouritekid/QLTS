# app/models/admission_profile_choice.py
"""AdmissionProfileChoice + ProfileChoiceScore models — Phase 3 PR-3A.

phase3_01 (#184 Wave 3 PR-3A) — multi-NV (multiple choices per profile)
+ per-subject score per choice. Implements PLAN line 982-1000 spec.

Per PLAN v0.6 LOCKED + UI design v0.6:

**AdmissionProfileChoice = 1 NV (Nguyện vọng)**:
- profile × admission_path × path_subject_group_config
- display_order = priority ranking (1 = top, max 10 per Q-P3-01 DB CHECK)
- decision = engine result tại T6 publish (pending/admitted/waitlisted/
  rejected/skip)
- eligibility_check_result = 6-rule engine output snapshot JSONB
- bonus_rule_snapshot = T6-time snapshot (Q-P3-11 NOT T1 submit)

**ProfileChoiceScore = điểm thí sinh per subject per choice**:
- choice × subject = 1 row (UNIQUE)
- score Numeric(8,2) precision cho V-ACT/DGNL 1200-point
- *_snapshot columns freeze max_score/min_possible/weight tại submit time

**FK ON DELETE** (GAP-18 v0.6):
- profile → choice CASCADE (profile delete clears choices)
- choice → score CASCADE (choice delete clears scores)
- path/config/subject → RESTRICT (lifecycle via archive flag)

**Sequential engine** (PLAN line 1271 + 3.3):
- Loop choices ORDER BY display_order
- Đậu NV nào → mark admitted, remaining → skip
- Waitlist → continue next NV

Service invariant (P1 fix #4 v1.3): ``path_subject_group_config.
admission_path_id == admission_profile_choice.admission_path_id``.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.admission import AdmissionProfile
    from app.models.admission_config.admission_path import AdmissionPath
    from app.models.admission_config.path_subject_group import (
        PathSubjectGroupConfig,
    )
    from app.models.subject import Subject


# Decision enum values (match phase3_01 CHECK constraint)
CHOICE_DECISIONS = ("pending", "admitted", "waitlisted", "rejected", "skip")


class AdmissionProfileChoice(Base):
    """1 NV (nguyện vọng) trong Phase 3 multi-NV flow.

    1 profile có thể có max 10 choices (DB CHECK display_order BETWEEN 1
    AND 10; system_config soft default 5 mùa 2026).

    Cùng (profile, path, config) chỉ 1 row (UNIQUE). Cùng (profile,
    display_order) chỉ 1 row (UNIQUE) — chặn 2 NV cùng priority.

    Service-layer guard ``add_choice`` (G7 v0.6) enforce:
    - ``offering_admission_round.allow_multi_nv`` per-round flag
    - ``system_config.max_choices_per_profile`` system-wide soft cap
    """

    __tablename__ = "admission_profile_choice"
    __table_args__ = (
        UniqueConstraint(
            "admission_profile_id",
            "admission_path_id",
            "path_subject_group_config_id",
            name="uq_admission_profile_choice_path_config",
        ),
        UniqueConstraint(
            "admission_profile_id",
            "display_order",
            name="uq_admission_profile_choice_display_order",
        ),
        CheckConstraint(
            "display_order BETWEEN 1 AND 10",
            name="ck_admission_profile_choice_display_order_range",
        ),
        CheckConstraint(
            "decision IN ('pending', 'admitted', 'waitlisted', "
            "'rejected', 'skip')",
            name="ck_admission_profile_choice_decision",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    admission_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    admission_path_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_path.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    path_subject_group_config_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("path_subject_group_config.id", ondelete="RESTRICT"),
        nullable=False,
    )

    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Priority 1 (cao nhất) - 10 (thấp nhất)",
    )
    decision: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="pending",
        comment="Engine output: pending/admitted/waitlisted/rejected/skip",
    )
    waitlist_rank: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="GAP-30: assigned at T6 engine, 1-based unique per path×round",
    )
    eligibility_check_result: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="6-rule engine result snapshot",
    )
    bonus_rule_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Q-P3-11: BonusRule snapshot tại T6 publish (NOT T1)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=__import__("sqlalchemy").text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=__import__("sqlalchemy").text("now()"),
    )

    # Relationships (selectinload via repository per GAP-22)
    profile: Mapped["AdmissionProfile"] = relationship(
        "AdmissionProfile",
        back_populates="choices",
    )
    admission_path: Mapped["AdmissionPath"] = relationship(
        "AdmissionPath",
        lazy="selectin",
    )
    path_subject_group_config: Mapped["PathSubjectGroupConfig"] = relationship(
        "PathSubjectGroupConfig",
        lazy="selectin",
    )
    scores: Mapped[list["ProfileChoiceScore"]] = relationship(
        "ProfileChoiceScore",
        back_populates="choice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ProfileChoiceScore(Base):
    """Điểm thí sinh cho 1 subject thuộc 1 choice.

    Mỗi choice link path_subject_group_config → list of subjects.
    Score precision Numeric(8,2) hỗ trợ V-ACT/DGNL 1200-point.

    *_snapshot columns freeze values tại submit time (admin update
    path config sau submit → existing choice giữ snapshot, KHÔNG
    affected).
    """

    __tablename__ = "profile_choice_score"
    __table_args__ = (
        UniqueConstraint(
            "admission_profile_choice_id",
            "subject_id",
            name="uq_profile_choice_score_choice_subject",
        ),
        CheckConstraint(
            "score >= 0",
            name="ck_profile_choice_score_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    admission_profile_choice_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("admission_profile_choice.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("subject.id", ondelete="RESTRICT"),
        nullable=False,
    )

    score: Mapped[Numeric] = mapped_column(
        Numeric(8, 2),
        nullable=False,
    )
    max_score_snapshot: Mapped[Numeric] = mapped_column(
        Numeric(8, 2),
        nullable=False,
    )
    min_possible_score_snapshot: Mapped[Optional[Numeric]] = mapped_column(
        Numeric(8, 2),
        nullable=True,
        comment="P2 fix #8 v1.9: default 0 cho legacy",
    )
    weight_snapshot: Mapped[Numeric] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default="1.00",
    )

    # Relationships
    choice: Mapped["AdmissionProfileChoice"] = relationship(
        "AdmissionProfileChoice",
        back_populates="scores",
    )
    subject: Mapped["Subject"] = relationship(
        "Subject",
        lazy="selectin",
    )
