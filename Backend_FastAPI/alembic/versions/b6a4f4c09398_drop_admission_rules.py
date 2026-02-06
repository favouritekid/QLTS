"""drop_admission_rules_from_program_offering

Revision ID: drop_admission_rules_col
Revises: c1d2e3f4g5h6
Create Date: 2026-01-12 09:10:00.000000

Schema Changes:
1. DROP COLUMN program_offering.admission_rules (JSONB)
2. This column is deprecated in favor of relational tables:
   - DocumentGroup (offering_type + admission_method)
   - DocumentGroupItem (document requirements)
   - AdmissionPath (offering + method linkage)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b6a4f4c09398'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4g5h6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop admission_rules JSONB column from program_offering.
    
    This column is no longer used after refactoring:
    - create_profile() now uses AdmissionPath + DocumentGroup
    - Cascade update logic in config_service removed
    - All document configuration managed via relational tables
    """
    op.drop_column('program_offering', 'admission_rules')


def downgrade() -> None:
    """Re-add admission_rules column if rollback needed."""
    op.add_column(
        'program_offering',
        sa.Column(
            'admission_rules',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='Admission rules JSON: {min_gpa, mandatory_docs[], admission_method}'
        )
    )
