"""Phase B: bảng lead_reopen_request + Casbin policies (officer-request flow).

Tạo bảng yêu cầu mở lại (officer xin → manager/admin duyệt) + 8 casbin policy cho
5 endpoint. v3=eft BẮT BUỘC (auth_model.conf dùng p.eft).

Revision ID: leadreopen_b_20260609
Revises: leadreopen_a_20260609
Create Date: 2026-06-09
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "leadreopen_b_20260609"
down_revision: Union[str, None] = "leadreopen_a_20260609"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TEMPLATE_ID = "_leadreopen_b_20260609"
# (v0=role, v1=obj, v2=act, v3=eft)
_POLICIES = (
    ("role:officer", "/api/leads/{lead_id}/reopen-requests", "POST", "allow"),
    ("role:officer", "/api/reopen-requests/{request_id}", "DELETE", "allow"),
    ("role:manager", "/api/reopen-requests", "GET", "allow"),
    ("role:admin", "/api/reopen-requests", "GET", "allow"),
    ("role:manager", "/api/reopen-requests/{request_id}/approve", "POST", "allow"),
    ("role:admin", "/api/reopen-requests/{request_id}/approve", "POST", "allow"),
    ("role:manager", "/api/reopen-requests/{request_id}/reject", "POST", "allow"),
    ("role:admin", "/api/reopen-requests/{request_id}/reject", "POST", "allow"),
)


def _seed_policy(conn, v0: str, v1: str, v2: str, v3: str) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
            SELECT 'p',
                   CAST(:v0 AS VARCHAR), CAST(:v1 AS VARCHAR),
                   CAST(:v2 AS VARCHAR), CAST(:v3 AS VARCHAR),
                   :tid, NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype='p'
                  AND v0=CAST(:v0 AS VARCHAR) AND v1=CAST(:v1 AS VARCHAR)
                  AND v2=CAST(:v2 AS VARCHAR) AND v3=CAST(:v3 AS VARCHAR)
            )
            """
        ),
        {"v0": v0, "v1": v1, "v2": v2, "v3": v3, "tid": _TEMPLATE_ID},
    )


def upgrade() -> None:
    op.create_table(
        "lead_reopen_request",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "lead_id", sa.Integer(), sa.ForeignKey("lead.id"), nullable=False
        ),
        sa.Column(
            "requested_by_id",
            sa.Integer(),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "reviewed_by_id",
            sa.Integer(),
            sa.ForeignKey("user.id"),
            nullable=True,
        ),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "unit_id",
            sa.Integer(),
            sa.ForeignKey("organization_unit.id"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_lead_reopen_request_status",
        ),
    )
    op.create_index(
        "ix_lead_reopen_request_lead_id", "lead_reopen_request", ["lead_id"]
    )
    op.create_index(
        "ix_lead_reopen_request_requested_by_id",
        "lead_reopen_request",
        ["requested_by_id"],
    )
    op.create_index(
        "ix_lead_reopen_request_status", "lead_reopen_request", ["status"]
    )
    # KHÔNG tạo single index unit_id: composite (unit_id, status) bên dưới đã phủ
    # (unit_id là cột dẫn đầu) → tránh index dư (chi phí ghi/space).
    op.create_index(
        "ix_lead_reopen_request_unit_status",
        "lead_reopen_request",
        ["unit_id", "status"],
    )
    op.create_index(
        "uq_reopen_one_pending_per_lead",
        "lead_reopen_request",
        ["lead_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    conn = op.get_bind()
    for v0, v1, v2, v3 in _POLICIES:
        _seed_policy(conn, v0, v1, v2, v3)


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("DELETE FROM casbin_rule WHERE template_id = :tid"),
        {"tid": _TEMPLATE_ID},
    )
    op.drop_table("lead_reopen_request")
