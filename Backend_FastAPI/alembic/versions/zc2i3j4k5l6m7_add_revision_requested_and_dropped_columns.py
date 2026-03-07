"""Add revision_requested and dropped columns to admission_profile

Revision ID: zc2i3j4k5l6m7
Revises: zb1h2i3j4k5l6
Create Date: 2026-03-07

Phase 5a: revision_requested_at, revision_requested_by_id, revision_reason
Phase 5b: is_dropped, dropped_at, dropped_by_id, dropped_reason
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "zc2i3j4k5l6m7"
down_revision = "zb1h2i3j4k5l6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Phase 5a: Revision request tracking columns
    op.add_column(
        "admission_profile",
        sa.Column("revision_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "admission_profile",
        sa.Column(
            "revision_requested_by_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "admission_profile",
        sa.Column("revision_reason", sa.Text(), nullable=True),
    )

    # Phase 5b: Drop-out tracking columns
    op.add_column(
        "admission_profile",
        sa.Column("is_dropped", sa.Boolean(), server_default="false", nullable=True),
    )
    op.add_column(
        "admission_profile",
        sa.Column("dropped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "admission_profile",
        sa.Column(
            "dropped_by_id",
            sa.Integer(),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "admission_profile",
        sa.Column("dropped_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("admission_profile", "dropped_reason")
    op.drop_column("admission_profile", "dropped_by_id")
    op.drop_column("admission_profile", "dropped_at")
    op.drop_column("admission_profile", "is_dropped")
    op.drop_column("admission_profile", "revision_reason")
    op.drop_column("admission_profile", "revision_requested_by_id")
    op.drop_column("admission_profile", "revision_requested_at")
