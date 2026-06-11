# app/models/sms/contact_group_member.py
"""
SMS contact ↔ group membership (N-N). UNIQUE (group_id, contact_id).
Xem `Documents/SMS_MARKETING_MODULE_DESIGN.md` §4.3.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime, ForeignKey, Integer, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class SmsContactGroupMember(Base):
    """Thành viên nhóm — 1 liên hệ thuộc nhiều nhóm."""

    __tablename__ = "sms_contact_group_member"

    __table_args__ = (
        UniqueConstraint(
            "group_id", "contact_id",
            name="uq_sms_group_member_group_contact",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_contact_group.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sms_contact.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    note: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="ghi chú riêng trong nhóm này",
    )
    added_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<SmsContactGroupMember group={self.group_id} "
            f"contact={self.contact_id}>"
        )
