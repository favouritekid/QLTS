# app/models/sms/program_view.py
"""
SMS program view (Phase 2 §16.4) — mỗi lượt xem 1 trang ngành `/lp/{code}/nganh/{id}`.
`dwell_seconds` chốt từ heartbeat của trang ngành → tín hiệu chính "quan tâm".
`program_name_snapshot` giữ tên ngành tại thời điểm xem (ngành có thể đổi/xóa).
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §16.4.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsProgramView(Base):
    """1 lượt xem trang 1 ngành trong 1 phiên landing (đo dwell)."""

    __tablename__ = "sms_program_view"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("sms_landing_session.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_contact.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    major_program_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("major_program.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="ngành xem (SET NULL nếu ngành bị xóa — giữ snapshot)",
    )
    program_offering_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True,
        comment="loại hình (chính quy/liên thông) — ngữ cảnh, không FK cứng",
    )
    program_name_snapshot: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="tên ngành lúc xem (audit khi ngành đổi/xóa)",
    )
    viewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    dwell_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="thời gian ở lại trang ngành (cộng dồn từ heartbeat)",
    )
    sequence_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
        comment="thứ tự xem trong phiên (1,2,3…)",
    )

    def __repr__(self) -> str:
        return (
            f"<SmsProgramView {self.id} session={self.session_id} "
            f"program={self.major_program_id} dwell={self.dwell_seconds}s>"
        )
