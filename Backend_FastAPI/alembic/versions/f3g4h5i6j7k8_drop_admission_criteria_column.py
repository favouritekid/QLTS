# alembic/versions/f3g4h5i6j7k8_drop_admission_criteria_column.py
"""
Drop admission_criteria JSONB column from offering_academic_info.

Revision ID: f3g4h5i6j7k8
Revises: e2f3g4h5i6j7
Create Date: 2026-01-12

Phase B.3 COMPLETE: Full cleanup of JSONB column.
Data has been migrated to relational AdmissionPath.criteria_id.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'f3g4h5i6j7k8'
down_revision = 'e2f3g4h5i6j7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Drop the deprecated admission_criteria JSONB column.
    
    Prerequisites verified:
    - Frontend migrated to useAdmissionPathsForOffering hook
    - Schema removed from organization.py
    - Model removed from offering_academic_info.py
    - Seed scripts updated
    - Tests updated
    """
    op.drop_column('offering_academic_info', 'admission_criteria')


def downgrade() -> None:
    """
    Restore the admission_criteria JSONB column.
    
    NOTE: This only restores the column structure, not the data.
    To restore data, you would need a separate data migration.
    """
    op.add_column(
        'offering_academic_info',
        sa.Column(
            'admission_criteria',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='DEPRECATED: Tiêu chí tuyển sinh (JSON) - Use AdmissionPath.criteria_id'
        )
    )
