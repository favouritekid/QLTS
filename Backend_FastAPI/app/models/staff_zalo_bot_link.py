"""Zalo Bot Platform link record (staff ↔ chat_id).

One row per staff user. ``user_id`` is unique so the row is reused on
relink — never INSERT a second row for the same user.

``chat_id`` is intentionally **not** unique at the model level: a chat_id
may bounce between users if a staff hands their phone to a colleague.
The migration is expected to add a *partial* unique index over
``(chat_id) WHERE is_active = true`` so only one active binding per
chat_id exists at a time, while inactive history rows are kept for audit.
"""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from .base import Base


class StaffZaloBotLink(Base):
    __tablename__ = "staff_zalo_bot_link"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("user.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    chat_id = Column(String(100), nullable=False)
    display_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    linked_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
