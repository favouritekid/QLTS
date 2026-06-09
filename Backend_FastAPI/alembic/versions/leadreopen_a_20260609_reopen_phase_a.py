"""Lead reopen Phase A: consultation_reengaged_at column + reopen Casbin policies.

Adds:
  - ``lead.consultation_reengaged_at`` (timestamptz, NULL) — mốc re-engage. NULL = chưa
    reopen → RULE #13.2 (fsm_engine) giữ nguyên hành vi "EVER" (backfill = no-op).
  - Casbin ``p`` policies cho ``POST /api/leads/{lead_id}/reopen`` (manager + admin).
    v3=eft BẮT BUỘC: ``auth_model.conf`` dùng ``p.eft`` → NULL eft crash load.

Revision ID: leadreopen_a_20260609
Revises: sts20_consult_giveup_20260609
Create Date: 2026-06-09
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "leadreopen_a_20260609"
down_revision: Union[str, None] = "sts20_consult_giveup_20260609"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TEMPLATE_ID = "_leadreopen_a_20260609"
_REOPEN_OBJ = "/api/leads/{lead_id}/reopen"
# (v0=role, v1=obj, v2=act, v3=eft). Officer KHÔNG có quyền ở Phase A.
_REOPEN_POLICIES = (
    ("role:manager", _REOPEN_OBJ, "POST", "allow"),
    ("role:admin", _REOPEN_OBJ, "POST", "allow"),
)


def _seed_policy(conn, v0: str, v1: str, v2: str, v3: str) -> None:
    """Idempotent INSERT của 1 casbin policy row (đủ v0..v3 + template_id)."""
    conn.execute(
        sa.text(
            """
            INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
            SELECT 'p',
                   CAST(:v0 AS VARCHAR),
                   CAST(:v1 AS VARCHAR),
                   CAST(:v2 AS VARCHAR),
                   CAST(:v3 AS VARCHAR),
                   :tid, NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype='p'
                  AND v0=CAST(:v0 AS VARCHAR)
                  AND v1=CAST(:v1 AS VARCHAR)
                  AND v2=CAST(:v2 AS VARCHAR)
                  AND v3=CAST(:v3 AS VARCHAR)
            )
            """
        ),
        {"v0": v0, "v1": v1, "v2": v2, "v3": v3, "tid": _TEMPLATE_ID},
    )


def upgrade() -> None:
    op.add_column(
        "lead",
        sa.Column(
            "consultation_reengaged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    conn = op.get_bind()
    for v0, v1, v2, v3 in _REOPEN_POLICIES:
        _seed_policy(conn, v0, v1, v2, v3)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM casbin_rule WHERE template_id = :tid"),
        {"tid": _TEMPLATE_ID},
    )
    op.drop_column("lead", "consultation_reengaged_at")
