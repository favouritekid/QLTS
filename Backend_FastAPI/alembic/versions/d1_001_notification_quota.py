"""Phase D1: create notification_quota table

Revision ID: d1_001_quota_v1
Revises: c2_001a1b2c3d4
Create Date: 2026-03-26

Phase D1:
  - Per-channel/provider quota tracking
  - Daily quotas for Zalo ZNS, SMS
  - Unique constraint on (channel, provider, period, period_start)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1_001_quota_v1"
down_revision: Union[str, None] = "c2_001a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_quota",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False, server_default="default"),
        sa.Column("period", sa.String(20), nullable=False, server_default="daily"),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("quota_limit", sa.Integer(), nullable=False),
        sa.Column("quota_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quota_remaining", sa.Integer(), nullable=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "channel", "provider", "period", "period_start",
            name="uq_quota_channel_provider_period",
        ),
    )

    op.create_index(
        "ix_quota_channel_period",
        "notification_quota",
        ["channel", "period_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_quota_channel_period", table_name="notification_quota")
    op.drop_table("notification_quota")
