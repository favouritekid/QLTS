"""Phase C1: create zalo_token_store table

Revision ID: zz6g7h8i9j0k1
Revises: zz5f6g7h8i9j0
Create Date: 2026-03-26

Phase C1-3:
  - Persistent backup for Zalo OAuth tokens
  - Single row per OA (currently one OA)
  - Redis is primary store; this table is crash recovery
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "zz6g7h8i9j0k1"
down_revision: Union[str, None] = "zz5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "zalo_token_store",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "oa_id",
            sa.String(50),
            nullable=False,
            unique=True,
            comment="Zalo OA ID — unique per OA",
        ),
        sa.Column(
            "access_token",
            sa.Text(),
            nullable=False,
            comment="Current Zalo OA access token",
        ),
        sa.Column(
            "refresh_token",
            sa.Text(),
            nullable=False,
            comment="Current Zalo OA refresh token (single-use, rotated on each refresh)",
        ),
        sa.Column(
            "access_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="When the access token expires (typically 25 hours after refresh)",
        ),
        sa.Column(
            "refresh_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When the refresh token expires (typically 3 months)",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("zalo_token_store")
