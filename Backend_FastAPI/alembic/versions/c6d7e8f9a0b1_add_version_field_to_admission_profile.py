"""add version field to admission_profile

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2025-12-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c6d7e8f9a0b1'
down_revision: Union[str, None] = 'b5c6d7e8f9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add version field to admission_profile for optimistic locking.

    Optimistic Locking Pattern:
    - version field increments on every update/submit
    - Service layer checks version before modifying record
    - Prevents concurrent modification (lost update problem)
    - Better performance than pessimistic locking (no row locks)

    Security Benefits:
    - Prevents race conditions during concurrent submit operations
    - Detects when two officers modify same profile simultaneously
    - User-friendly error message prompts refresh and retry
    """

    # Add version column with default value 1
    op.add_column(
        'admission_profile',
        sa.Column(
            'version',
            sa.Integer(),
            nullable=False,
            server_default='1',
            comment='Optimistic locking version (incremented on update)'
        )
    )

    # Backfill existing rows with version = 1 (already done by server_default)
    # No need for explicit UPDATE since server_default='1' handles it


def downgrade() -> None:
    """
    Remove version field from admission_profile.
    """

    # Drop version column
    op.drop_column('admission_profile', 'version')
