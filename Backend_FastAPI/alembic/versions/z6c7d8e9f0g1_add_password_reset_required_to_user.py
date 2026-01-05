"""add_password_reset_required_to_user

Revision ID: z6c7d8e9f0g1
Revises: z5b6c7d8e9f0
Create Date: 2025-12-25 19:43:00.000000

C2 Security Fix: Add password_reset_required column to force password change
after user clicks "Not Me" on suspicious login (secure_account flow).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'z6c7d8e9f0g1'
down_revision: Union[str, Sequence[str], None] = 'z5b6c7d8e9f0'  # After trusted_device migration
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    C2 Security Fix: Add password_reset_required column to user table.
    
    When True, user must change password before accessing the system.
    Set to True when user clicks "Not Me" on suspicious login (secure_account).
    """
    op.add_column(
        'user',
        sa.Column(
            'password_reset_required',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='Forces password change on next login when True'
        )
    )


def downgrade() -> None:
    """Remove password_reset_required column from user table."""
    op.drop_column('user', 'password_reset_required')
