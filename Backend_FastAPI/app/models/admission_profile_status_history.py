# app/models/admission_profile_status_history.py
"""AdmissionProfileStatusHistory model.

phase1_10 (#184 Wave 2 PR-2A) — audit trail for every status
transition on AdmissionProfile. Replaces the legacy scattered
scalar columns (``approved_at/by``, ``rejected_at/by``, ...) which
don't scale to the 17-state Phase 3 transition matrix.

Per PLAN Phần 2.7 (line 1018-1069):

* 3-column role audit chốt v2.9 (PLAN P1 fix #1 + #2):
  - ``transitioned_by_role`` (deprecated, drop Phase 4) — kept
    for 1-release backward compat with existing reports.
  - ``actor_actual_role`` (NEW v2.9) — role THẬT của actor
    (manager khi gọi T6/T10/T11 ghi 'manager'). Audit theo cột
    này cho sự thật.
  - ``effective_transition_role`` (NEW v2.9) — role sau khi
    resolve qua effective_role_for_transition(). Manager → T6
    'admin'; manager → T2 'officer'. Dùng cho RBAC trace +
    matrix verification.

* Actor model split (PLAN P2 fix #6):
  - ``transitioned_by_user_id`` — nullable; SET khi actor =
    officer/admin (có User row).
  - ``transitioned_by_lead_id`` — nullable; SET khi actor =
    candidate qua magic_link (no User row).

Service contract (PLAN line 1067): mỗi endpoint đổi
``AdmissionProfile.status`` MUST insert 1 row vào status_history
cùng transaction frame. Không có row history → giả định bug,
raise alert.
"""
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


# ENUM values mirror alembic phase1_10 — frozen here as the
# migration is the source-of-truth; ``create_type=False`` avoids
# autogenerate redeclare.
TRANSITION_ROLE_LEGACY_VALUES: tuple[str, ...] = (
    "system", "officer", "admin", "candidate",
)
ACTOR_ACTUAL_ROLE_VALUES: tuple[str, ...] = (
    "candidate", "officer", "manager", "accountant", "admin", "system",
)
EFFECTIVE_TRANSITION_ROLE_VALUES: tuple[str, ...] = (
    "candidate", "officer", "admin", "system",
)


class AdmissionProfileStatusHistory(Base):
    """One row per status transition (PLAN Phần 2.7 line 1021)."""

    __tablename__ = "admission_profile_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_status: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="NULL = lần đầu tạo profile (initial state)",
    )
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)

    transitioned_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    transitioned_by_lead_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("lead.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Legacy column — drop Phase 4 after report migration.
    transitioned_by_role: Mapped[str] = mapped_column(
        ENUM(
            *TRANSITION_ROLE_LEGACY_VALUES,
            name="transition_role_legacy",
            create_type=False,
        ),
        nullable=False,
    )
    actor_actual_role: Mapped[str] = mapped_column(
        ENUM(
            *ACTOR_ACTUAL_ROLE_VALUES,
            name="actor_actual_role",
            create_type=False,
        ),
        nullable=False,
        comment="Role THẬT của actor (audit theo cột này cho sự thật).",
    )
    effective_transition_role: Mapped[str] = mapped_column(
        ENUM(
            *EFFECTIVE_TRANSITION_ROLE_VALUES,
            name="effective_transition_role",
            create_type=False,
        ),
        nullable=False,
        comment="Role sau khi resolve qua effective_role_for_transition().",
    )

    transition_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Bắt buộc cho admin override + reject",
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
    )
    # Renamed Python attribute to ``metadata_`` because ``metadata``
    # collides with SQLAlchemy ``DeclarativeBase.metadata``. The
    # ``"metadata"`` first arg pins the actual SQL column name.
    metadata_: Mapped[Optional[Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Free-form audit payload (computed_total_score, decision_rule, ...)",
    )

    __table_args__ = (
        CheckConstraint(
            "(transitioned_by_role = 'system' "
            "AND transitioned_by_user_id IS NULL "
            "AND transitioned_by_lead_id IS NULL) "
            "OR (transitioned_by_role IN ('officer', 'admin') "
            "AND transitioned_by_user_id IS NOT NULL "
            "AND transitioned_by_lead_id IS NULL) "
            "OR (transitioned_by_role = 'candidate' "
            "AND transitioned_by_lead_id IS NOT NULL "
            "AND transitioned_by_user_id IS NULL)",
            name="ck_status_history_actor_consistency",
        ),
    )

    # Relationships — lazy because the audit table is read-heavy
    # (admin queue) but most callers only need (profile_id, status).
    # No ``back_populates`` on AdmissionProfile side because the
    # parent profile relationship doesn't need a bidirectional
    # binding (audit reads run via direct queries).
    profile = relationship(
        "AdmissionProfile",
        foreign_keys=[profile_id],
    )
    transitioned_by_user = relationship(
        "User",
        foreign_keys=[transitioned_by_user_id],
    )
    transitioned_by_lead = relationship(
        "Lead",
        foreign_keys=[transitioned_by_lead_id],
    )

    def __repr__(self) -> str:
        return (
            f"<StatusHistory profile={self.profile_id} "
            f"{self.from_status} → {self.to_status} "
            f"actor={self.actor_actual_role} at {self.occurred_at}>"
        )
