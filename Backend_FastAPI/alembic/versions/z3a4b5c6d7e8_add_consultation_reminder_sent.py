"""add consultation reminder_sent column

Revision ID: z3a4b5c6d7e8
Revises: y2z3a4b5c6d7
Create Date: 2025-01-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'z3a4b5c6d7e8'
down_revision: Union[str, None] = 'y2z3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add reminder_sent column to consultation table
    # This flag prevents duplicate reminder notifications
    op.add_column(
        'consultation',
        sa.Column('reminder_sent', sa.Boolean(), nullable=False, server_default='false')
    )

    # Create index for efficient querying of pending reminders
    # (scheduled_at, reminder_sent) composite index
    op.create_index(
        'ix_consultation_reminder_pending',
        'consultation',
        ['scheduled_at', 'reminder_sent'],
        unique=False
    )


def downgrade() -> None:
    # Remove index
    op.drop_index('ix_consultation_reminder_pending', table_name='consultation')

    # Remove column
    op.drop_column('consultation', 'reminder_sent')
