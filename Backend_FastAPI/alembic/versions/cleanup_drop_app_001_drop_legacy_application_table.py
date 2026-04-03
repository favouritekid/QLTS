"""drop legacy application table

Revision ID: cleanup_drop_app_001
Revises: 1a25aa8e2984
Create Date: 2026-04-01

The Application model and all runtime code (router, service, repository)
have been removed. AdmissionProfile is the sole source of truth.
This migration drops the orphaned physical table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


# revision identifiers, used by Alembic.
revision: str = "cleanup_drop_app_001"
down_revision: Union[str, Sequence[str], None] = "1a25aa8e2984"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the legacy application table.

    PostgreSQL automatically drops all indexes, constraints, and sequences
    owned by the table when using DROP TABLE CASCADE.
    """
    op.drop_table("application")


def downgrade() -> None:
    """Recreate the application table with its final schema."""
    op.create_table(
        "application",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("major_program_id", sa.Integer(), nullable=True),
        sa.Column("program_offering_id", sa.Integer(), nullable=True),
        sa.Column("criterion_id", sa.String(length=100), nullable=True),
        sa.Column("documents", JSON(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("officer_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.id"]),
        sa.ForeignKeyConstraint(["officer_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["major_program_id"], ["major_program.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["program_offering_id"], ["program_offering.id"], ondelete="SET NULL"),
    )
    # Recreate indexes
    op.create_index("ix_application_id", "application", ["id"])
    op.create_index("ix_application_lead_id", "application", ["lead_id"], unique=True)
    op.create_index("ix_application_officer_id", "application", ["officer_id"])
    op.create_index("ix_application_major_program_id", "application", ["major_program_id"])
    op.create_index("ix_application_program_offering_id", "application", ["program_offering_id"])
    op.create_index("ix_application_criterion_id", "application", ["criterion_id"])
    op.create_index("ix_application_status", "application", ["status"])
    op.create_index("ix_application_deleted_at", "application", ["deleted_at"])
