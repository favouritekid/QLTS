"""add FSM fields to allowed_transitions

Revision ID: a1b2c3d4e5f6
Revises: z6c7d8e9f0g1
Create Date: 2026-01-25 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'z6c7d8e9f0g1'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add FSM Engine fields to allowed_transitions table.

    New columns:
    - trigger_type: Who/what triggers this transition (user/role/system/event)
    - required_phase: Target phase (must match to_status.phase)
    - is_active: Whether this transition is currently enabled
    - description: Human-readable description
    """
    # Add trigger_type column (enum)
    op.add_column('allowed_transitions',
        sa.Column('trigger_type',
                  sa.Enum('user', 'role', 'system', 'event',
                          name='trigger_type_enum', create_type=False),
                  nullable=False,
                  server_default='user',
                  comment="Who/what triggers this transition: user/role/system/event")
    )

    # Add required_phase column
    op.add_column('allowed_transitions',
        sa.Column('required_phase',
                  sa.String(20),
                  nullable=True,
                  comment="Target phase (must match to_status.phase). NULL for same-phase transitions.")
    )

    # Add is_active column
    op.add_column('allowed_transitions',
        sa.Column('is_active',
                  sa.Boolean(),
                  nullable=False,
                  server_default='true',
                  comment="Whether this transition is currently enabled")
    )

    # Add description column
    op.add_column('allowed_transitions',
        sa.Column('description',
                  sa.Text(),
                  nullable=True,
                  comment="Human-readable description of this transition")
    )

    # Add index for common query pattern (from_status_id + is_active)
    op.create_index('ix_allowed_transitions_from_status_active',
                   'allowed_transitions',
                   ['from_status_id', 'is_active'])

    # Add index for trigger_type filtering
    op.create_index('ix_allowed_transitions_trigger_type',
                   'allowed_transitions',
                   ['trigger_type'])


def downgrade():
    """Remove FSM Engine fields from allowed_transitions table."""
    # Drop indexes
    op.drop_index('ix_allowed_transitions_trigger_type', table_name='allowed_transitions')
    op.drop_index('ix_allowed_transitions_from_status_active', table_name='allowed_transitions')

    # Drop columns
    op.drop_column('allowed_transitions', 'description')
    op.drop_column('allowed_transitions', 'is_active')
    op.drop_column('allowed_transitions', 'required_phase')
    op.drop_column('allowed_transitions', 'trigger_type')
