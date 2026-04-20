"""AdmissionSurveyFeedback — user_feedback webhook store.

Receives one row per submitted rating from ZNS template 426903
("Khảo sát dịch vụ tư vấn", fired 30d post-approval). Zalo echoes the
``tracking_id`` we sent so we can map feedback → profile; the row is
unique on tracking_id so a re-delivered webhook updates in place.

``profile_id`` is nullable on purpose: if tracking_id doesn't match any
known profile (ghost delivery, manual test, or stale template), we
still persist the feedback for ops review rather than drop it silently.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
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
from sqlalchemy.sql import func

from .base import Base


class AdmissionSurveyFeedback(Base):
    __tablename__ = "admission_survey_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Unique declared once via named UniqueConstraint in __table_args__ so
    # ORM-bootstrapped test schema matches the migration exactly (repo tests
    # use metadata.create_all; a second ``unique=True`` here would create an
    # unnamed duplicate index that prod never gets).
    tracking_id: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    zalo_msg_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    rate: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feedback_tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    submit_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tracking_id", name="uq_admission_survey_feedback_tracking_id"
        ),
        CheckConstraint("rate BETWEEN 1 AND 5", name="ck_survey_rate_range"),
        CheckConstraint(
            "jsonb_typeof(feedback_tags) = 'array'",
            name="ck_survey_feedback_tags_is_array",
        ),
    )

    profile = relationship("AdmissionProfile", lazy="select")

    def __repr__(self) -> str:
        return (
            f"<AdmissionSurveyFeedback id={self.id} tracking={self.tracking_id} "
            f"rate={self.rate} profile_id={self.profile_id}>"
        )
