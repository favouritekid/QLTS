# app/models/sms/contact_program_interest.py
"""
SMS contact ↔ program interest (Phase 2 §16.4) — hồ sơ sở thích TỔNG HỢP per
contact per ngành (giá trị nghiệp vụ chính). Trả lời "liên hệ X quan tâm ngành
gì nhất" xuyên mọi phiên/nguồn. Cập nhật khi chốt dwell 1 program_view.

`interest_score` (§16.10-P2-Q2): normalize(Σ dwell_factor × recency_weight),
config `SMS_INTEREST_DWELL_CAP/_HALF_LIFE/_K`. Ranking theo `total_dwell_seconds`
(hoặc score) desc. UNIQUE(contact_id, major_program_id) = 1 hàng/ngành/contact.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime, Float, ForeignKey, Index, Integer,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsContactProgramInterest(Base):
    """Sở thích tổng hợp 1 contact với 1 ngành (aggregate qua mọi phiên)."""

    __tablename__ = "sms_contact_program_interest"

    __table_args__ = (
        Index(
            "uq_sms_contact_program_interest",
            "contact_id", "major_program_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_contact.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    major_program_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("major_program.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    view_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    total_dwell_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="tổng dwell mọi phiên — tín hiệu quan tâm chính (rank desc)",
    )
    first_interest_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    last_interest_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    interest_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0",
        comment="normalize(Σ dwell_factor×recency) ∈ [0,1); config-driven",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<SmsContactProgramInterest contact={self.contact_id} "
            f"program={self.major_program_id} dwell={self.total_dwell_seconds}s "
            f"score={self.interest_score:.3f}>"
        )
