# app/models/admission_config/path_subject_group.py
"""
Path-level Subject Group Config + Item (Phase 2 v8.2 PR-2D).

Tables:
- PathSubjectGroupConfig: per-path subject group config (override above
  CriteriaSubjectGroup default — admin sets path-specific score thresholds
  + Tier 3 group_quota)
- PathSubjectGroupItem: per-item override trong config (is_principal +
  min_subject_score per subject)

Composite invariant guard (service-layer):
- subject_group_subject.subject_group_id == path_subject_group_config.subject_group_id

Tier 3 quota chain (PR-2D):
- ``∑(group_quota WHERE admission_path_id=X) ≤ path[X].admit_quota``
"""

import sqlalchemy as sa
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import Base


class PathSubjectGroupConfig(Base):
    """Path-level subject group config (Phase 2 v8.2 PR-2D)."""

    __tablename__ = "path_subject_group_config"

    id = Column(Integer, primary_key=True, index=True)
    admission_path_id = Column(
        Integer,
        ForeignKey("admission_path.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_group_id = Column(
        Integer,
        ForeignKey("subject_group.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Score thresholds — Numeric(8,2) consistent với PR-2E (V-ACT/DGNL ready)
    min_score = Column(
        Numeric(precision=8, scale=2),
        nullable=True,
        comment="Min total score (path override above criteria default)",
    )
    min_subject_score = Column(
        Numeric(precision=8, scale=2),
        nullable=True,
        comment="Min per-subject (path override; NULL = inherit từ criteria)",
    )
    group_quota = Column(
        Integer,
        nullable=True,
        comment="Tier 3 quota: ∑(group_quota in path) ≤ path.admit_quota. NULL = unbounded",
    )

    created_at = Column(DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    # Relationships
    admission_path = relationship("AdmissionPath", foreign_keys=[admission_path_id])
    subject_group = relationship("SubjectGroup", foreign_keys=[subject_group_id])
    items = relationship(
        "PathSubjectGroupItem",
        back_populates="config",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "admission_path_id", "subject_group_id",
            name="uq_path_subject_group_config_path_group",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PathSubjectGroupConfig path={self.admission_path_id} "
            f"group={self.subject_group_id}>"
        )


class PathSubjectGroupItem(Base):
    """Per-item override trong PathSubjectGroupConfig (Phase 2 v8.2 PR-2D).

    Composite invariant: ``subject_group_subject.subject_group_id`` MUST
    equal ``config.subject_group_id`` (service-layer guard, NOT DB-level).
    """

    __tablename__ = "path_subject_group_item"

    id = Column(Integer, primary_key=True, index=True)
    path_subject_group_config_id = Column(
        Integer,
        ForeignKey("path_subject_group_config.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_group_subject_id = Column(
        Integer,
        ForeignKey("subject_group_subject.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_principal = Column(
        Boolean,
        nullable=False,
        server_default=sa.false(),
        comment="Principal subject — used khi scoring_method='weighted'",
    )
    min_subject_score = Column(
        Numeric(precision=8, scale=2),
        nullable=True,
        comment="Per-item override; NULL = inherit từ config.min_subject_score",
    )

    created_at = Column(DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )

    # Relationships
    config = relationship("PathSubjectGroupConfig", back_populates="items")
    subject_group_subject = relationship(
        "SubjectGroupSubject", foreign_keys=[subject_group_subject_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "path_subject_group_config_id", "subject_group_subject_id",
            name="uq_path_subject_group_item",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<PathSubjectGroupItem config={self.path_subject_group_config_id} "
            f"sgs={self.subject_group_subject_id} principal={self.is_principal}>"
        )
