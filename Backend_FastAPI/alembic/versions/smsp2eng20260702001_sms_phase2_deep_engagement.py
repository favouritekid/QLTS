"""sms phase2 deep engagement schema (3 bảng đo quan tâm ngành)

Viết TAY (không autogenerate) — autogenerate bị nhiễm drift dev DB (đòi drop
archive/casbin + alter comment hàng trăm cột). Chỉ tạo 3 bảng Phase 2 §16.4:
sms_landing_session, sms_program_view, sms_contact_program_interest.

Revision ID: smsp2eng20260702001
Revises: mta20260628001
Create Date: 2026-07-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "smsp2eng20260702001"
down_revision: Union[str, Sequence[str], None] = "mta20260628001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. sms_landing_session (program_view phụ thuộc → tạo trước)
    op.create_table(
        "sms_landing_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column(
            "source_type", sa.String(length=20),
            server_default="campaign", nullable=False,
        ),
        sa.Column("recipient_id", sa.Integer(), nullable=True),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "active_seconds", sa.Integer(),
            server_default="0", nullable=False,
        ),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "is_suspected_bot", sa.Boolean(),
            server_default="false", nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["sms_contact.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"], ["sms_campaign_recipient.id"], ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["sms_campaign.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_token_hash"),
    )
    op.create_index(
        op.f("ix_sms_landing_session_contact_id"),
        "sms_landing_session", ["contact_id"], unique=False,
    )
    op.create_index(
        op.f("ix_sms_landing_session_recipient_id"),
        "sms_landing_session", ["recipient_id"], unique=False,
    )
    op.create_index(
        op.f("ix_sms_landing_session_campaign_id"),
        "sms_landing_session", ["campaign_id"], unique=False,
    )

    # 2. sms_program_view (FK → session)
    op.create_table(
        "sms_program_view",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("major_program_id", sa.Integer(), nullable=True),
        sa.Column("program_offering_id", sa.Integer(), nullable=True),
        sa.Column("program_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column(
            "viewed_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "dwell_seconds", sa.Integer(),
            server_default="0", nullable=False,
        ),
        sa.Column(
            "sequence_no", sa.Integer(),
            server_default="1", nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sms_landing_session.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["sms_contact.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["major_program_id"], ["major_program.id"], ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sms_program_view_session_id"),
        "sms_program_view", ["session_id"], unique=False,
    )
    op.create_index(
        op.f("ix_sms_program_view_contact_id"),
        "sms_program_view", ["contact_id"], unique=False,
    )
    op.create_index(
        op.f("ix_sms_program_view_major_program_id"),
        "sms_program_view", ["major_program_id"], unique=False,
    )

    # 3. sms_contact_program_interest (aggregate; UNIQUE(contact, program))
    op.create_table(
        "sms_contact_program_interest",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("major_program_id", sa.Integer(), nullable=False),
        sa.Column(
            "view_count", sa.Integer(),
            server_default="0", nullable=False,
        ),
        sa.Column(
            "total_dwell_seconds", sa.Integer(),
            server_default="0", nullable=False,
        ),
        sa.Column("first_interest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_interest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "interest_score", sa.Float(),
            server_default="0", nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["sms_contact.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["major_program_id"], ["major_program.id"], ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sms_contact_program_interest_contact_id"),
        "sms_contact_program_interest", ["contact_id"], unique=False,
    )
    op.create_index(
        op.f("ix_sms_contact_program_interest_major_program_id"),
        "sms_contact_program_interest", ["major_program_id"], unique=False,
    )
    op.create_index(
        "uq_sms_contact_program_interest",
        "sms_contact_program_interest",
        ["contact_id", "major_program_id"], unique=True,
    )


def downgrade() -> None:
    # Thứ tự ngược FK: program_view (→ session) trước, rồi session; interest độc lập.
    op.drop_index(
        op.f("ix_sms_program_view_major_program_id"),
        table_name="sms_program_view",
    )
    op.drop_index(
        op.f("ix_sms_program_view_contact_id"), table_name="sms_program_view",
    )
    op.drop_index(
        op.f("ix_sms_program_view_session_id"), table_name="sms_program_view",
    )
    op.drop_table("sms_program_view")

    op.drop_index(
        "uq_sms_contact_program_interest",
        table_name="sms_contact_program_interest",
    )
    op.drop_index(
        op.f("ix_sms_contact_program_interest_major_program_id"),
        table_name="sms_contact_program_interest",
    )
    op.drop_index(
        op.f("ix_sms_contact_program_interest_contact_id"),
        table_name="sms_contact_program_interest",
    )
    op.drop_table("sms_contact_program_interest")

    op.drop_index(
        op.f("ix_sms_landing_session_campaign_id"),
        table_name="sms_landing_session",
    )
    op.drop_index(
        op.f("ix_sms_landing_session_recipient_id"),
        table_name="sms_landing_session",
    )
    op.drop_index(
        op.f("ix_sms_landing_session_contact_id"),
        table_name="sms_landing_session",
    )
    op.drop_table("sms_landing_session")
