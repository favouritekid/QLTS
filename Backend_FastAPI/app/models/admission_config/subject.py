# app/models/admission_config/subject.py
"""
Subject Domain Models.

Tables:
- Subject: Individual subjects (math, physics, chemistry...)
- SubjectGroup: Subject combinations (A00, D01, B00...)
- SubjectGroupSubject: Join table mapping subjects to groups
"""

from decimal import Decimal

from sqlalchemy import Column, Integer, Numeric, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


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
