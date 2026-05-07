# app/models/admission_config/subject.py
"""
Subject Domain Models.

Tables:
- Subject: Individual subjects (math, physics, chemistry...)
- SubjectGroup: Subject combinations (A00, D01, B00...)
- SubjectGroupSubject: Join table mapping subjects to groups
"""

from decimal import Decimal

from sqlalchemy import Column, Integer, Numeric, String, Boolean, ForeignKey, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import relationship

from app.models.base import Base


# phase1_05 (#184 Wave 1 PR-1C') — subject_kind ENUM mirror.
# ``create_type=False`` because the migration owns the DDL.
# Adding a new value requires migration ALTER TYPE + this tuple
# in lockstep — no silent extension via direct DB access.
SUBJECT_KIND_VALUES: tuple[str, ...] = (
    "ACADEMIC_SUBJECT",
    "TERM_AVERAGE",
    "ABILITY_TEST",
    "CERTIFICATE",
)


class Subject(Base):
    """
    Môn học đơn lẻ.
    
    Examples:
        - code: "math", name_vi: "Toán"
        - code: "physics", name_vi: "Vật lý"
        - code: "chemistry", name_vi: "Hóa học"
    """
    __tablename__ = "subject"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
        comment="Subject code: math, physics, chemistry..."
    )
    name_vi = Column(
        String(100),
        nullable=False,
        comment="Vietnamese name: Toán, Vật lý, Hóa học..."
    )
    display_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Display order in UI"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True
    )

    # phase1_05 (#184 Wave 1 PR-1C') — subject category. Backfilled
    # to ``ACADEMIC_SUBJECT`` for all legacy rows via server default
    # at ALTER TIME; seeded virtual subjects (TB_HK1_L12 / DGNL /
    # IELTS / V_ACT / ...) carry the proper non-academic kind. Service
    # uses this to gate routing: ``ACADEMIC_SUBJECT`` flows through
    # legacy single-NV ProfileSubjectScore (CHECK 0..10), non-academic
    # MUST go through Phase 3 multi-NV choice engine (no CHECK).
    subject_kind = Column(
        ENUM(
            *SUBJECT_KIND_VALUES,
            name="subject_kind",
            create_type=False,
        ),
        nullable=False,
        server_default=text("'ACADEMIC_SUBJECT'::subject_kind"),
        comment=(
            "Subject category. ACADEMIC_SUBJECT for legacy / Toán / "
            "Lý / Hóa; TERM_AVERAGE / ABILITY_TEST / CERTIFICATE for "
            "virtual subjects."
        ),
    )

    # phase1_05 — score ceiling. NULL = service falls back to 10
    # for ACADEMIC_SUBJECT. Seeded values: 10 (academic), 150
    # (DGNL_DHQGHN), 1200 (V_ACT), 9 (IELTS).
    max_score = Column(
        Numeric(precision=6, scale=2),
        nullable=True,
        comment=(
            "Score ceiling. NULL = service default 10 for ACADEMIC_SUBJECT."
        ),
    )

    # phase1_05 — score floor. NULL = service treats as 0.
    min_possible_score = Column(
        Numeric(precision=6, scale=2),
        nullable=True,
        comment="Score floor. NULL = 0.",
    )

    # Relationships
    group_mappings = relationship(
        "SubjectGroupSubject",
        back_populates="subject",
        cascade="all, delete-orphan"
    )
    profile_scores = relationship(
        "ProfileSubjectScore",
        back_populates="subject",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Subject {self.code}: {self.name_vi}>"


class SubjectGroup(Base):
    """
    Tổ hợp môn xét tuyển.
    
    Examples:
        - code: "A00", name: "Toán, Vật lý, Hóa học"
        - code: "D01", name: "Toán, Văn, Tiếng Anh"
    """
    __tablename__ = "subject_group"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(
        String(10),
        nullable=False,
        unique=True,
        index=True,
        comment="Group code: A00, D01, B00..."
    )
    name = Column(
        String(255),
        nullable=False,
        comment="Full name: Toán, Vật lý, Hóa học"
    )
    display_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Display order in UI"
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True
    )

    # Relationships
    subject_mappings = relationship(
        "SubjectGroupSubject",
        back_populates="subject_group",
        cascade="all, delete-orphan",
        order_by="SubjectGroupSubject.position"
    )
    criteria_mappings = relationship(
        "CriteriaSubjectGroup",
        back_populates="subject_group",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<SubjectGroup {self.code}: {self.name}>"


class SubjectGroupSubject(Base):
    """
    Join table: Subject belongs to SubjectGroup with position.
    
    Example for A00:
        - position 1: math
        - position 2: physics
        - position 3: chemistry
    """
    __tablename__ = "subject_group_subject"

    id = Column(Integer, primary_key=True, index=True)
    subject_group_id = Column(
        Integer,
        ForeignKey("subject_group.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    subject_id = Column(
        Integer,
        ForeignKey("subject.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    position = Column(
        Integer,
        nullable=False,
        default=1,
        comment="Position in group (1, 2, 3)"
    )
    # PR6 (2026-04-19): per-subject weight. Raw coefficient; default 1.0
    # means "no weighting" (plain sum). See
    # project_pr6_weighted_scoring_unblock for rationale. Scoring logic
    # that actually consumes this column will land in PR6 Step 2.
    weight = Column(
        Numeric(precision=3, scale=2),
        nullable=False,
        default=Decimal("1.0"),
        server_default="1.0",
        comment=(
            "Per-subject weight coefficient (raw, default 1.0 = plain sum)."
        ),
    )

    # Relationships
    subject_group = relationship("SubjectGroup", back_populates="subject_mappings")
    subject = relationship("Subject", back_populates="group_mappings")

    __table_args__ = (
        UniqueConstraint(
            "subject_group_id", "subject_id",
            name="uq_subject_group_subject"
        ),
    )

    def __repr__(self):
        return f"<SubjectGroupSubject group={self.subject_group_id} subject={self.subject_id} pos={self.position}>"
