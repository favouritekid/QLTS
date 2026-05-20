# app/models/priority_audit.py
"""Q9 #07 Phase E — Priority bonus audit log (append-only).

Stores audit trail for manual interventions on candidate priority bonus
data: KV override + UT evidence verify/reject + admin bulk-fill. Replaces
the design alternative of reusing `admission_profile_status_history`,
which has CHECK ``ck_status_history_actor_consistency`` enforcing a state
transition (KV override không transition status → invariant break).

Pattern: append-only event log, FK to profile with ondelete=CASCADE so
deleting a profile (rare, admin-only) cleans up the trail. Actor SET NULL
preserves history when user account deleted.

Query patterns:
* Latest override per profile: ORDER BY profile_id, action_type, created_at DESC
  → composite index `idx_priority_audit_log_profile_action_time` covers this
* Full timeline pull: WHERE profile_id = ? ORDER BY created_at DESC
* Batch lookup by admin bulk-fill: WHERE metadata->>'batch_id' = ?

See `Documents/Q9_07_PR5_REDESIGN.md` v1.3 + plan
`humming-herding-squid.md` v2 Foundation pre-work section.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PriorityAuditLog(Base):
    """Append-only audit log for priority bonus interventions.

    Action types (CHECK constraint enforced):
    * ``kv_manual_override`` — Officer/admin overrides KV (Phase E.2)
    * ``ut_evidence_verified`` — Officer verifies UT document (Phase E.3)
    * ``ut_evidence_rejected`` — Officer rejects UT document (Phase E.3)
    * ``admin_bulk_fill`` — Admin bulk-fill on behalf (Phase F.2)
    * ``ut_evidence_untick`` — Officer unticks UT code, cascade hard delete
      file (Phase E.4 G1)
    * ``ut_evidence_warning_dismissed`` — Officer submits hồ sơ với
      missing_priority_evidence_codes non-empty (Phase E.4 Decision #2)
    """

    __tablename__ = "priority_audit_log"
    __table_args__ = (
        CheckConstraint(
            "action_type IN ("
            "'kv_manual_override',"
            "'ut_evidence_verified',"
            "'ut_evidence_rejected',"
            "'admin_bulk_fill',"
            "'ut_evidence_untick',"
            "'ut_evidence_warning_dismissed'"
            ")",
            name="ck_priority_audit_log_action_type",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("admission_profile.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
    )
    old_value: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Snapshot of mutated field BEFORE change (vd {'kv_resolved': 'KV3'})",
    )
    new_value: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Snapshot of mutated field AFTER change (vd {'kv_resolved': 'KV1', 'reason': '...'})",
    )
    audit_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        comment="Extra context: evidence_file_id, reject_reason, batch_id (admin bulk-fill UUID)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<PriorityAuditLog id={self.id} profile={self.profile_id} "
            f"action={self.action_type} actor={self.actor_id}>"
        )
