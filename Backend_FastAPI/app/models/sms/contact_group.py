# app/models/sms/contact_group.py
"""
SMS contact group — nhóm liên hệ bền vững cho SMS Marketing.

Một nhóm gom nhiều liên hệ (`sms_contact`) qua bảng N-N
`sms_contact_group_member`. Campaign chọn 1+ nhóm để build snapshot.
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.1.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsContactGroup(Base):
    """Nhóm liên hệ SMS (parent/student/teacher/lead/custom)."""

    __tablename__ = "sms_contact_group"

    __table_args__ = (
        CheckConstraint(
            "group_type IN ('parent','student','teacher','lead','custom')",
            name="chk_sms_contact_group_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, comment="slug duy nhất"
    )
    group_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="parent / student / teacher / lead / custom",
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SmsContactGroup {self.id} {self.code} ({self.group_type})>"
