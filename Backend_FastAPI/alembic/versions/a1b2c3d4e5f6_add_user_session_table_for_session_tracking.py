"""add user_session table for session tracking (MERGED)

Revision ID: a1b2c3d4e5f6
Revises: ec2713f8825b
Create Date: 2025-11-03 14:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "ec2713f8825b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add user_session table for tracking active sessions and detecting unauthorized access."""
    op.create_table(
        "user_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        # Session identification
        sa.Column("refresh_jti", sa.String(length=36), nullable=False),
        # Device/Browser info
        sa.Column("ip_address", sa.String(length=45), nullable=True),  # IPv6 support
        sa.Column(
            "user_agent", sa.Text(), nullable=True
        ),  # Lấy từ 20250103 (tốt hơn String(512))
        sa.Column(
            "device_type", sa.String(length=50), nullable=True
        ),  # mobile, desktop, tablet
        sa.Column("browser", sa.String(length=100), nullable=True),
        sa.Column("os", sa.String(length=100), nullable=True),
        # Location (optional, requires IP geolocation service)
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        # Session lifecycle
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # Security flags
        sa.Column(
            "is_suspicious", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        # Constraints
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for performance (từ file a1b2c3d4e5f6)
    op.create_index(op.f("ix_user_session_id"), "user_session", ["id"], unique=False)
    op.create_index(
        op.f("ix_user_session_user_id"), "user_session", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_user_session_refresh_jti"),
        "user_session",
        ["refresh_jti"],
        unique=True,
    )
    op.create_index(
        op.f("ix_user_session_created_at"), "user_session", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_user_session_last_activity_at"),
        "user_session",
        ["last_activity_at"],
        unique=False,
    )

    # Composite index for common queries (từ file a1b2c3d4e5f6)
    op.create_index(
        "ix_user_session_user_active",
        "user_session",
        ["user_id", "revoked_at", "expires_at"],
        unique=False,
    )

    # Thêm các index còn thiếu từ file 20250103_session
    op.create_index("ix_user_session_expires_at", "user_session", ["expires_at"])
    op.create_index("ix_user_session_revoked_at", "user_session", ["revoked_at"])


def downgrade() -> None:
    """Remove user_session table."""
    # Thêm lệnh drop cho 2 index mới (ngược với upgrade)
    op.drop_index("ix_user_session_revoked_at", table_name="user_session")
    op.drop_index("ix_user_session_expires_at", table_name="user_session")

    # Các lệnh drop cũ từ file a1b2c3d4e5f6
    op.drop_index("ix_user_session_user_active", table_name="user_session")
    op.drop_index(op.f("ix_user_session_last_activity_at"), table_name="user_session")
    op.drop_index(op.f("ix_user_session_created_at"), table_name="user_session")
    op.drop_index(op.f("ix_user_session_refresh_jti"), table_name="user_session")
    op.drop_index(op.f("ix_user_session_user_id"), table_name="user_session")
    op.drop_index(op.f("ix_user_session_id"), table_name="user_session")

    op.drop_table("user_session")
