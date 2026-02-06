"""add phase and selectable_by_user columns to consultation_status

Revision ID: d5e6f7a8b9c0
Revises: c9a2b7e0f599
Create Date: 2026-01-24
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5e6f7a8b9c0'
down_revision = 'c9a2b7e0f599'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add phase column
    op.add_column(
        'consultation_status',
        sa.Column(
            'phase',
            sa.String(20),
            nullable=False,
            server_default='consultation',
            comment='Phase: consultation, admission, fee, enrolled, universal'
        )
    )
    
    # Add selectable_by_user column
    op.add_column(
        'consultation_status',
        sa.Column(
            'selectable_by_user',
            sa.String(20),
            nullable=False,
            server_default='true',
            comment='true = officer can select, false = system only, role-based = manager/admin only'
        )
    )


def downgrade() -> None:
    op.drop_column('consultation_status', 'selectable_by_user')
    op.drop_column('consultation_status', 'phase')
