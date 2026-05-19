"""q9_07_e0a: create priority_audit_log table for Phase E interventions

Revision ID: q9_07_e0a
Revises: q9_07_d0a
Create Date: 2026-05-19

Q9 #07 Phase E Foundation pre-work — append-only audit log for manual
priority bonus interventions: KV override + UT evidence verify/reject +
admin bulk-fill.

Why NEW table (not reuse admission_profile_status_history):
- ``admission_profile_status_history`` has CHECK
  ``ck_status_history_actor_consistency`` enforcing state transition
- KV override không transition status → invariant break

Composite index ``(profile_id, action_type, created_at DESC)`` covers
the "latest override per profile" query pattern + audit timeline pull.

Downgrade: DROP table + index (safe — append-only audit data lost on
downgrade acceptable for dev/staging; prod downgrade rarely run).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "q9_07_e0a"
down_revision: Union[str, None] = "q9_07_d0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "priority_audit_log",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("old_value", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("new_value", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("metadata", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action_type IN ('kv_manual_override','ut_evidence_verified',"
            "'ut_evidence_rejected','admin_bulk_fill')",
            name="ck_priority_audit_log_action_type",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["admission_profile.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["user.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Single-column index on profile_id (for FK lookup speed)
    op.create_index(
        "ix_priority_audit_log_profile_id",
        "priority_audit_log",
        ["profile_id"],
    )
    # Composite index for "latest override per profile" + audit timeline pull
    op.create_index(
        "idx_priority_audit_log_profile_action_time",
        "priority_audit_log",
        ["profile_id", "action_type", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_priority_audit_log_profile_action_time",
        table_name="priority_audit_log",
    )
    op.drop_index(
        "ix_priority_audit_log_profile_id",
        table_name="priority_audit_log",
    )
    op.drop_table("priority_audit_log")
