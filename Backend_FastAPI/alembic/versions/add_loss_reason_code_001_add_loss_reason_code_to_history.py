"""add loss_reason_code to lead_status_history

Revision ID: add_loss_reason_code_001
Revises: rbac20260131001
Create Date: 2026-02-05

SPEC: frontend/docs/LOSS_REASON_UX_SPEC.md

Adds structured loss_reason_code field to track why leads were lost.
This enables funnel analytics to aggregate loss reasons and identify
patterns for recovery campaigns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_loss_reason_code_001'
down_revision: Union[str, None] = 'rbac20260131001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add loss_reason_code column to lead_status_history
    op.add_column(
        'lead_status_history',
        sa.Column(
            'loss_reason_code',
            sa.String(50),
            nullable=True,
            comment='Structured loss reason code (e.g., PRICE_HIGH, NO_CONTACT, CHOSE_COMPETITOR)'
        )
    )

    # Add index for efficient aggregation queries
    op.create_index(
        'ix_lead_status_history_loss_reason_code',
        'lead_status_history',
        ['loss_reason_code'],
        unique=False
    )


def downgrade() -> None:
    # Remove index first
    op.drop_index('ix_lead_status_history_loss_reason_code', table_name='lead_status_history')

    # Remove column
    op.drop_column('lead_status_history', 'loss_reason_code')
