"""BV-1: create payment_import_batch + payment_import_row (bulk payment verify)

Hạ tầng cho luồng import file tổng hợp → tự xác minh thanh toán hàng loạt.
Ref: Documents/BULK_PAYMENT_IMPORT_VERIFY_PLAN.md.

Revision ID: bvi20260624001
Revises: pra20260624001
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "bvi20260624001"
down_revision = "pra20260624001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_import_batch",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("semester_no", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="preview"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["user.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('preview', 'committed', 'void')",
            name="chk_payment_import_batch_status",
        ),
        sa.CheckConstraint("semester_no >= 1", name="chk_payment_import_batch_semester"),
    )
    op.create_index(
        "ix_payment_import_batch_academic_year", "payment_import_batch", ["academic_year"])
    op.create_index(
        "ix_payment_import_batch_file_sha256", "payment_import_batch", ["file_sha256"])
    op.create_index("ix_payment_import_batch_status", "payment_import_batch", ["status"])
    op.create_index(
        "ix_payment_import_batch_created_by_id", "payment_import_batch", ["created_by_id"])

    op.create_table(
        "payment_import_row",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("row_no", sa.Integer(), nullable=False),
        sa.Column("citizen_id", sa.String(length=12), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolved_profile_id", sa.Integer(), nullable=True),
        sa.Column("resolved_fee_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=True),
        sa.Column("payment_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["payment_import_batch.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('matched', 'warned', 'error')",
            name="chk_payment_import_row_status",
        ),
    )
    op.create_index("ix_payment_import_row_batch_id", "payment_import_row", ["batch_id"])


def downgrade() -> None:
    op.drop_table("payment_import_row")
    op.drop_table("payment_import_batch")
