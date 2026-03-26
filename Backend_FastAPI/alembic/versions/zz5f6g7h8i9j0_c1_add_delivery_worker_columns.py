"""Phase C1: add delivery worker columns (scheduled_for, attempt_count, last_attempt_at)

Revision ID: zz5f6g7h8i9j0
Revises: zy4e5f6g7h8i9
Create Date: 2026-03-26

Phase C1-2:
  - scheduled_for: when delivery should execute (NULL = immediate)
  - attempt_count: number of execution attempts
  - last_attempt_at: when last execution attempt was made
  - Partial index for worker polling: queued deliveries past scheduled_for
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "zz5f6g7h8i9j0"
down_revision: Union[str, None] = "zy4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Add worker scheduling columns to notification_delivery --
    op.add_column(
        "notification_delivery",
        sa.Column(
            "scheduled_for",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When this delivery should execute (NULL = immediate)",
        ),
    )
    op.add_column(
        "notification_delivery",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="Number of execution attempts",
        ),
    )
    op.add_column(
        "notification_delivery",
        sa.Column(
            "last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When last execution attempt was made",
        ),
    )

    # Partial index for worker polling: find queued deliveries ready to execute.
    # Worker queries: WHERE status='queued' AND (scheduled_for IS NULL OR scheduled_for <= now())
    op.create_index(
        "ix_delivery_worker_poll",
        "notification_delivery",
        ["scheduled_for", "status"],
        postgresql_where=sa.text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_worker_poll", table_name="notification_delivery")
    op.drop_column("notification_delivery", "last_attempt_at")
    op.drop_column("notification_delivery", "attempt_count")
    op.drop_column("notification_delivery", "scheduled_for")
