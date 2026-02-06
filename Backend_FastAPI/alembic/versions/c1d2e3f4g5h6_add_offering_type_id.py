"""add_offering_type_id_to_program_offering

Revision ID: c1d2e3f4g5h6
Revises: drop_config_subject_group
Create Date: 2026-01-11 20:26:00.000000

Schema Changes:
1. ADD COLUMN program_offering.offering_type_id - FK to ConfigOfferingType
2. This enables efficient DocumentGroup lookups for admission config
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4g5h6'
down_revision: Union[str, Sequence[str], None] = 'drop_config_subject_group'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add offering_type_id column to program_offering.
    
    This column links ProgramOffering to ConfigOfferingType, enabling:
    1. Efficient JOIN for DocumentGroup lookups
    2. Relational integrity instead of string matching
    
    Step 2: Run backfill script to populate existing rows:
        python -m scripts.seeds.backfill_offering_type_id
    """
    # Add nullable column first (for backward compatibility)
    op.add_column(
        'program_offering',
        sa.Column(
            'offering_type_id',
            sa.Integer(),
            nullable=True,
            comment='Link to offering type for document group lookup'
        )
    )
    
    # Add FK constraint
    op.create_foreign_key(
        'fk_program_offering_offering_type_id',
        'program_offering',
        'config_offering_type',
        ['offering_type_id'],
        ['id'],
        ondelete='SET NULL'
    )
    
    # Add index for performance
    op.create_index(
        'ix_program_offering_offering_type_id',
        'program_offering',
        ['offering_type_id'],
        unique=False
    )


def downgrade() -> None:
    """Remove offering_type_id column."""
    op.drop_index('ix_program_offering_offering_type_id', table_name='program_offering')
    op.drop_constraint('fk_program_offering_offering_type_id', 'program_offering', type_='foreignkey')
    op.drop_column('program_offering', 'offering_type_id')
