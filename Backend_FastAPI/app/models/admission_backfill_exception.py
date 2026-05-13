# app/models/admission_backfill_exception.py
"""Thin ORM model for `_admission_backfill_exceptions` (Phase 1 #07b).

Phase 3 PR-3D-B BE-2 (#184 Q-P3-09 admin backfill queue UI):
Phase 1 created the table with raw SQL (leading underscore = internal /
ops-only convention). PR-3D-B BE-2 promotes it to an ORM model so the
admin backfill queue endpoints can use the repository + service pattern
(parity với V3.0 architecture).

The model deliberately mirrors `phase1_07b_create_backfill_exceptions_table.py`
schema column-for-column. ``__tablename__`` keeps the leading underscore.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AdmissionBackfillException(Base):
    """Audit row written by Phase 1/2/3 backfill scripts when a profile
    can't be auto-mapped to an unambiguous outcome (e.g. selected_subject_group
    matched >1 path config, GPA out of range, unparseable graduation year).

    Admin queue UI consumes these rows: list filter + per-row resolve OR
    bulk-resolve via PATCH/POST endpoints.
    """

    __tablename__ = "_admission_backfill_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exception_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment=(
            "Caller-defined tag (e.g. selected_subject_group_ambiguous, "
            "gpa_out_of_range, grad_year_unparseable)."
        ),
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
        comment="Caller-defined payload (input snapshot, rule, suggested resolution)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    profile = relationship("AdmissionProfile", foreign_keys=[profile_id])
    resolved_by = relationship("User", foreign_keys=[resolved_by_user_id])

    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "exception_type",
            name="uq_admission_backfill_exceptions_profile_type",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AdmissionBackfillException id={self.id} "
            f"profile={self.profile_id} type={self.exception_type} "
            f"resolved={self.resolved_at is not None}>"
        )
