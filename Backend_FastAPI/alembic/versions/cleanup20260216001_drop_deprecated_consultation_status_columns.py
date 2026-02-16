"""drop deprecated consultation_status columns

Revision ID: cleanup20260216001
Revises: idor20260216002
Create Date: 2026-02-16 12:00:00.000000

Drop 3 deprecated columns from consultation_status that have been replaced
by FSM v3.0 equivalents:
- is_final_status → is_final
- selectable_by_user → selectable_mode
- counts_for_kpi → counts_for_funnel
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cleanup20260216001'
down_revision = 'idor20260216002'
branch_labels = None
depends_on = None


def upgrade():
    """Drop deprecated columns from consultation_status."""
    # Ensure data is synced before dropping (safety net)
    op.execute("""
        UPDATE consultation_status
        SET is_final = COALESCE(is_final_status, is_final)
        WHERE is_final_status IS NOT NULL AND is_final_status <> is_final
    """)
    op.execute("""
        UPDATE consultation_status
        SET counts_for_funnel = COALESCE(counts_for_kpi, counts_for_funnel)
        WHERE counts_for_kpi IS NOT NULL AND counts_for_kpi <> counts_for_funnel
    """)

    # Drop columns
    op.drop_column('consultation_status', 'is_final_status')
    op.drop_column('consultation_status', 'selectable_by_user')
    op.drop_column('consultation_status', 'counts_for_kpi')


def downgrade():
    """Re-add deprecated columns and backfill from new columns."""
    op.add_column('consultation_status',
        sa.Column('counts_for_kpi', sa.Boolean(), nullable=True,
                  comment="DEPRECATED: Use counts_for_funnel instead")
    )
    op.add_column('consultation_status',
        sa.Column('selectable_by_user', sa.String(20), nullable=True,
                  comment="DEPRECATED: Use selectable_mode instead")
    )
    op.add_column('consultation_status',
        sa.Column('is_final_status', sa.Boolean(), nullable=True,
                  comment="DEPRECATED: Use is_final instead")
    )

    # Backfill from new columns
    op.execute("UPDATE consultation_status SET is_final_status = is_final")
    op.execute("UPDATE consultation_status SET counts_for_kpi = counts_for_funnel")
    op.execute("""
        UPDATE consultation_status
        SET selectable_by_user = selectable_mode::text
    """)
