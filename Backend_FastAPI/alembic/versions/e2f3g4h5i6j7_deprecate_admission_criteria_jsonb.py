# alembic/versions/e2f3g4h5i6j7_deprecate_admission_criteria_jsonb.py
"""
Deprecate admission_criteria JSONB column.

Revision ID: e2f3g4h5i6j7
Revises: d1e2f3a4b5c6
Create Date: 2026-01-12 10:45:00.000000

WARNING: This migration DROPS the admission_criteria JSONB column.
Only run after verifying all data has been migrated to relational tables.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'e2f3g4h5i6j7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Drop the deprecated admission_criteria JSONB column.
    
    Prerequisites:
    - All data migrated to AdmissionCriteria relational table
    - LeadApplicationForm using new API (useAdmissionPathsForOffering)
    - No active code references this column
    """
    # Add column comment to mark as deprecated (for documentation)
    op.execute("""
        COMMENT ON COLUMN offering_academic_info.admission_criteria 
        IS 'DEPRECATED: Use admission_criteria table via AdmissionPath.criteria_id instead. Column kept for historical reference only.'
    """)
    
    # Note: Uncomment below to actually drop the column
    # op.drop_column('offering_academic_info', 'admission_criteria')


def downgrade() -> None:
    """
    Restore the admission_criteria JSONB column.
    """
    # If column was dropped, restore it
    # op.add_column(
    #     'offering_academic_info',
    #     sa.Column('admission_criteria', postgresql.JSON(astext_type=sa.Text()), nullable=True)
    # )
    
    # Restore original comment
    op.execute("""
        COMMENT ON COLUMN offering_academic_info.admission_criteria 
        IS 'Tiêu chí tuyển sinh (JSON)'
    """)
