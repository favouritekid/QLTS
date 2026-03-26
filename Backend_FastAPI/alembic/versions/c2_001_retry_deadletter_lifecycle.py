"""Phase C2: retry + dead-letter columns, replace worker poll index

Revision ID: c2_001a1b2c3d4
Revises: zz6g7h8i9j0k1
Create Date: 2026-03-26

Phase C2-1:
  - next_retry_at: when next retry should execute
  - max_retries: per-delivery retry limit (default 5)
  - dead_lettered_at: when permanently failed
  - Replace ix_delivery_worker_poll with ix_delivery_retry_poll (superset)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2_001a1b2c3d4"
down_revision: Union[str, None] = "zz6g7h8i9j0k1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notification_delivery",
        sa.Column(
            "next_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When next retry should execute (NULL = not scheduled)",
        ),
    )
    op.add_column(
        "notification_delivery",
        sa.Column(
            "max_retries",
            sa.Integer(),
            nullable=False,
            server_default="5",
            comment="Max retry attempts before dead-lettering",
        ),
    )
    op.add_column(
        "notification_delivery",
        sa.Column(
            "dead_lettered_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When delivery was permanently failed (dead-lettered)",
        ),
    )

    # Replace C1's worker poll index with C2's retry poll (superset)
    op.drop_index("ix_delivery_worker_poll", table_name="notification_delivery")
    op.create_index(
        "ix_delivery_retry_poll",
        "notification_delivery",
        ["next_retry_at"],
        postgresql_where=sa.text(
            "status IN ('queued', 'failed') AND next_retry_at IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_retry_poll", table_name="notification_delivery")
    # Restore C1 index
    op.create_index(
        "ix_delivery_worker_poll",
        "notification_delivery",
        ["scheduled_for", "status"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.drop_column("notification_delivery", "dead_lettered_at")
    op.drop_column("notification_delivery", "max_retries")
    op.drop_column("notification_delivery", "next_retry_at")
