"""Phase E1: create notification_consent_history table

Revision ID: e1_001_consent_v1
Revises: d1_001_quota_v1
Create Date: 2026-03-26

Phase E1:
  - Immutable append-only consent history table
  - Tracks old_status -> new_status for every consent change
  - FK to notification_consent (nullable) and user (nullable)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1_001_consent_v1"
down_revision: Union[str, None] = "d1_001_quota_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_consent_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "consent_id",
            sa.Integer(),
            sa.ForeignKey("notification_consent.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("old_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column(
            "performed_by",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "ix_consent_history_consent_id",
        "notification_consent_history",
        ["consent_id"],
    )
    op.create_index(
        "ix_consent_history_source",
        "notification_consent_history",
        ["source_type", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_consent_history_source", table_name="notification_consent_history")
    op.drop_index("ix_consent_history_consent_id", table_name="notification_consent_history")
    op.drop_table("notification_consent_history")
