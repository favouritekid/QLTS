"""Add assignment_status column to lead table

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2025-11-23

Changes:
1. Add assignment_status column to lead table
2. Migrate existing data based on current status values
3. Add index for filtering by assignment_status
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "y2z3a4b5c6d7"
down_revision: Union[str, None] = "x1y2z3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add assignment_status column and migrate existing data.

    assignment_status values:
    - pending: Lead waiting for first assignment
    - assigned: Lead successfully assigned to an officer
    - failed: Assignment failed (no officers available, all at capacity)
    - reassign_pending: Lead waiting to be reassigned (officer requested transfer)
    """
    # 1. Add assignment_status column with default 'pending'
    op.add_column(
        'lead',
        sa.Column(
            'assignment_status',
            sa.String(20),
            nullable=False,
            server_default='pending',
            comment='Assignment workflow status: pending, assigned, failed, reassign_pending'
        )
    )

    # 2. Migrate existing data based on current status field
    # Map old hardcoded statuses to new assignment_status values
    op.execute("""
        UPDATE lead SET assignment_status = CASE
            WHEN assigned_officer_id IS NOT NULL THEN 'assigned'
            WHEN status = 'unassigned_pending' THEN 'failed'
            WHEN status = 'reassigned_pending' THEN 'reassign_pending'
            WHEN status IN ('new', 'assigned') AND assigned_officer_id IS NULL THEN 'pending'
            ELSE 'pending'
        END
    """)

    # 3. Add index for efficient filtering
    op.create_index(
        'ix_lead_assignment_status',
        'lead',
        ['assignment_status'],
        unique=False
    )

    # 4. Remove server_default after migration (optional, keeps column clean)
    op.alter_column(
        'lead',
        'assignment_status',
        server_default=None
    )


def downgrade() -> None:
    """
    Remove assignment_status column.
    Note: Data migration back to old status values is not performed
    as the old status field still exists.
    """
    # 1. Drop index
    op.drop_index('ix_lead_assignment_status', table_name='lead')

    # 2. Drop column
    op.drop_column('lead', 'assignment_status')
