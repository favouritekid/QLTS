"""add_criteria_id_to_admission_path

Revision ID: d1e2f3a4b5c6
Revises: bc602de4203b
Create Date: 2026-01-12

Phase 0.1: Add criteria_id FK to AdmissionPath for N+1 prevention
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1e2f3a4b5c6'
down_revision = 'b6a4f4c09398'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add criteria_id column to admission_path table.
    
    Performance Fix:
    - Enables eager loading of criteria via selectinload(AdmissionPath.criteria)
    - Prevents N+1 queries when fetching paths with their criteria
    """
    # Add nullable column (draft paths may not have criteria yet)
    op.add_column(
        'admission_path',
        sa.Column(
            'criteria_id',
            sa.Integer(),
            nullable=True,
            comment='Link to admission criteria (nullable for draft paths)'
        )
    )
    
    # Add foreign key constraint
    op.create_foreign_key(
        'fk_admission_path_criteria_id',
        'admission_path',
        'admission_criteria',
        ['criteria_id'],
        ['id'],
        ondelete='SET NULL'
    )
    
    # Add index for query performance
    op.create_index(
        'ix_admission_path_criteria_id',
        'admission_path',
        ['criteria_id']
    )


def downgrade() -> None:
    """Remove criteria_id column from admission_path table."""
    op.drop_index('ix_admission_path_criteria_id', table_name='admission_path')
    op.drop_constraint('fk_admission_path_criteria_id', 'admission_path', type_='foreignkey')
    op.drop_column('admission_path', 'criteria_id')
