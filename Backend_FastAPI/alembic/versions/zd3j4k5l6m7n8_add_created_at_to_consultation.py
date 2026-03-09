"""Add created_at to consultation table

Revision ID: zd3j4k5l6m7n8
Revises: zc2i3j4k5l6m7
Create Date: 2026-03-09

M6: Add created_at column to consultation for accurate 24h edit window.
Backfill from consultation_date for existing rows.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "zd3j4k5l6m7n8"
down_revision = "zc2i3j4k5l6m7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Add column as nullable first (for backfill)
    op.add_column(
        "consultation",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
            comment="Record creation timestamp (for 24h edit window calculation)",
        ),
    )

    # Step 2: Backfill existing rows - use consultation_date as created_at
    op.execute(
        "UPDATE consultation SET created_at = consultation_date WHERE created_at IS NULL"
    )

    # Step 3: Set NOT NULL after backfill
    op.alter_column("consultation", "created_at", nullable=False)


def downgrade() -> None:
    op.drop_column("consultation", "created_at")
