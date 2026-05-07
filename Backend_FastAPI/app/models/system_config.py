# app/models/system_config.py
"""System Config Model.

phase1_13 (#184 Wave 1 PR-1D) — closes B4 P0 blocker. Single-table
key/value store for runtime config that needs admin mutability
without a redeploy. Keys are caller-defined; values are JSONB so
the same table holds bools, ints, lists, nested objects.

Use cases (current + planned):
* ``current_intake_year`` (int) — default year on FE storefront
  + admin Phase 3 wizard. Seeded to 2026 by phase1_13.
* ``cutover_freeze_active`` (bool) — runtime check by ADMISSION_FROZEN
  middleware (T0-2 ships the env-var version; service can promote
  to DB-backed runtime toggle later).
* ``zalo_template_approved`` (bool) — gate Q7 bypass consent for
  Zalo channel after the OA template is approved.

Service layer: ``SystemConfigService`` enforces admin-only
mutation per Q10 governance scope.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SystemConfig(Base):
    """Runtime config key/value store. PK = key (text)."""

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
        comment="Config value — any JSON shape (bool, int, list, nested object)",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Lazy relationship — admin queue UI may want to display the
    # last editor's name. Lazy because most callers just read the
    # ``value`` and don't care who set it.
    updated_by = relationship("User", foreign_keys=[updated_by_user_id])

    def __repr__(self) -> str:
        return f"<SystemConfig {self.key}={self.value!r}>"
