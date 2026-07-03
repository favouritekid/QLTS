"""sms phase2 P2-3 consult officer — sms_consult_link + session.consult_link_id

Viết TAY (không autogenerate — nhiễm drift dev DB). Tạo bảng
``sms_consult_link`` (link tư vấn officer↔lead) + thêm cột
``consult_link_id`` vào ``sms_landing_session`` (nguồn consult). Xem §16.4.

Revision ID: smsp2consult20260702002
Revises: smsp2eng20260702001
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "smsp2consult20260702002"
down_revision: Union[str, Sequence[str], None] = "smsp2eng20260702001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. sms_consult_link
    op.create_table(
        "sms_consult_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "landing_type", sa.String(length=20),
            server_default="qlts_hosted", nullable=False,
        ),
        sa.Column("landing_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "raw_click_count", sa.Integer(),
            server_default="0", nullable=False,
        ),
        sa.Column(
            "human_click_count", sa.Integer(),
            server_default="0", nullable=False,
        ),
        sa.Column(
            "first_human_clicked_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "last_human_clicked_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["lead_id"], ["lead.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["sms_contact.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["user.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sms_consult_link_contact_id"),
        "sms_consult_link", ["contact_id"], unique=False,
    )
    op.create_index(
        op.f("ix_sms_consult_link_created_by_id"),
        "sms_consult_link", ["created_by_id"], unique=False,
    )
    op.create_index(
        "ix_sms_consult_link_lead_id",
        "sms_consult_link", ["lead_id"], unique=False,
    )
    # Partial UNIQUE token_hash — resolve /r/{code} (nhánh consult).
    op.create_index(
        "uq_sms_consult_link_token_hash",
        "sms_consult_link", ["token_hash"], unique=True,
        postgresql_where=sa.text("token_hash IS NOT NULL"),
    )

    # 2. sms_landing_session.consult_link_id (nguồn consult)
    op.add_column(
        "sms_landing_session",
        sa.Column("consult_link_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sms_landing_session_consult_link_id",
        "sms_landing_session", "sms_consult_link",
        ["consult_link_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_sms_landing_session_consult_link_id"),
        "sms_landing_session", ["consult_link_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_sms_landing_session_consult_link_id"),
        table_name="sms_landing_session",
    )
    op.drop_constraint(
        "fk_sms_landing_session_consult_link_id",
        "sms_landing_session", type_="foreignkey",
    )
    op.drop_column("sms_landing_session", "consult_link_id")

    op.drop_index(
        "uq_sms_consult_link_token_hash", table_name="sms_consult_link",
    )
    op.drop_index(
        "ix_sms_consult_link_lead_id", table_name="sms_consult_link",
    )
    op.drop_index(
        op.f("ix_sms_consult_link_created_by_id"),
        table_name="sms_consult_link",
    )
    op.drop_index(
        op.f("ix_sms_consult_link_contact_id"),
        table_name="sms_consult_link",
    )
    op.drop_table("sms_consult_link")
