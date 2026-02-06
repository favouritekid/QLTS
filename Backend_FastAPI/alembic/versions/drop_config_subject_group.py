"""drop_config_subject_group_table

Drop legacy config_subject_group table after migration to relational SubjectGroup.

Revision ID: drop_config_subject_group
Revises: bc602de4203b
Create Date: 2026-01-11

PREREQUISITE: Run migrate_to_relational_subject_groups.py script first!
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'drop_config_subject_group'
down_revision: Union[str, None] = 'bc602de4203b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the legacy config_subject_group table.
    
    This table has been replaced by the relational model:
    - subject (21 records)
    - subject_group (281 records)
    - subject_group_subject (N-N mapping)
    
    IMPORTANT: Ensure migrate_to_relational_subject_groups.py has been run
    before applying this migration!
    """
    # Drop indexes first
    op.drop_index('ix_config_subject_group_is_active', table_name='config_subject_group')
    op.drop_index('ix_config_subject_group_id', table_name='config_subject_group')
    op.drop_index('ix_config_subject_group_code', table_name='config_subject_group')
    
    # Drop table
    op.drop_table('config_subject_group')


def downgrade() -> None:
    """Recreate config_subject_group table (if needed for rollback)."""
    op.create_table(
        'config_subject_group',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=10), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('subjects', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, default=0),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_config_subject_group_code', 'config_subject_group', ['code'], unique=True)
    op.create_index('ix_config_subject_group_id', 'config_subject_group', ['id'], unique=False)
    op.create_index('ix_config_subject_group_is_active', 'config_subject_group', ['is_active'], unique=False)
