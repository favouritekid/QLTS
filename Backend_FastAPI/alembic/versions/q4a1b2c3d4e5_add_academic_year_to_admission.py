"""add academic_year to admission_profile and change unique constraint

✅ Multi-year admission support:
- Add academic_year column to admission_profile
- Change UNIQUE(citizen_id) to UNIQUE(citizen_id, academic_year)
- Allows same citizen to apply in different years

Revision ID: q4a1b2c3d4e5
Revises: q3a1b2c3d4e5
Create Date: 2026-01-07 20:25:00.000000

"""
from typing import Sequence, Union
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = 'q4a1b2c3d4e5'
down_revision: Union[str, None] = 'q3a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in the table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def constraint_exists(table_name: str, constraint_name: str) -> bool:
    """Check if a constraint exists."""
    bind = op.get_bind()
    inspector = inspect(bind)
    # Check unique constraints
    uniques = [uc['name'] for uc in inspector.get_unique_constraints(table_name)]
    return constraint_name in uniques


def upgrade() -> None:
    """
    Add academic_year column and change unique constraint.
    
    IDEMPOTENT: Checks if column/constraint exist before modifying.
    """
    # Step 1: Add academic_year column (if not exists)
    if not column_exists('admission_profile', 'academic_year'):
        # Default to current year for existing rows
        current_year = datetime.now().year
        op.add_column('admission_profile', sa.Column(
            'academic_year',
            sa.Integer(),
            nullable=False,
            server_default=str(current_year),  # Default for existing rows
            comment="Academic year (e.g., 2025, 2026) - snapshotted at creation"
        ))
        
        # Remove server_default after migration (only needed for existing rows)
        op.alter_column(
            'admission_profile',
            'academic_year',
            server_default=None
        )
        
        # Create index for performance
        op.create_index(
            'ix_admission_profile_academic_year',
            'admission_profile',
            ['academic_year']
        )
    
    # Step 2: Drop old UNIQUE(citizen_id) constraint (if exists)
    # PostgreSQL auto-names this constraint based on column
    try:
        op.drop_constraint(
            'admission_profile_citizen_id_key',  # PostgreSQL auto-generated name
            'admission_profile',
            type_='unique'
        )
    except Exception:
        # Constraint might already be dropped or have different name
        pass
    
    # Step 3: Create new composite UNIQUE(citizen_id, academic_year)
    if not constraint_exists('admission_profile', 'uq_citizen_academic_year'):
        op.create_unique_constraint(
            'uq_citizen_academic_year',
            'admission_profile',
            ['citizen_id', 'academic_year']
        )


def downgrade() -> None:
    """
    Revert to UNIQUE(citizen_id) only.
    
    WARNING: This will fail if there are duplicate citizen_ids across years.
    """
    # Step 1: Drop composite unique constraint
    if constraint_exists('admission_profile', 'uq_citizen_academic_year'):
        op.drop_constraint('uq_citizen_academic_year', 'admission_profile', type_='unique')
    
    # Step 2: Re-create simple UNIQUE(citizen_id)
    try:
        op.create_unique_constraint(
            'admission_profile_citizen_id_key',
            'admission_profile',
            ['citizen_id']
        )
    except Exception:
        # May fail if duplicates exist
        pass
    
    # Step 3: Drop academic_year column
    if column_exists('admission_profile', 'academic_year'):
        op.drop_index('ix_admission_profile_academic_year', table_name='admission_profile')
        op.drop_column('admission_profile', 'academic_year')
