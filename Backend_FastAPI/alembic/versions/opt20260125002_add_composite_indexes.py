"""Add composite indexes for common query patterns

Revision ID: opt20260125002
Revises: opt20260125001
Create Date: 2026-01-25

Performance optimization for common query patterns identified in audit:
- Leads by unit + status
- Leads by unit + officer
- Leads by unit + pipeline stage
- Consultations by lead + date (for timeline queries)
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'opt20260125002'
down_revision = 'opt20260125001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add composite indexes for performance optimization."""

    # Lead composite indexes
    op.create_index(
        'ix_lead_unit_status',
        'lead',
        ['unit_id', 'status'],
        unique=False
    )
    op.create_index(
        'ix_lead_unit_officer',
        'lead',
        ['unit_id', 'assigned_officer_id'],
        unique=False
    )
    op.create_index(
        'ix_lead_unit_stage',
        'lead',
        ['unit_id', 'pipeline_stage_id'],
        unique=False
    )
    op.create_index(
        'ix_lead_unit_consultation_status',
        'lead',
        ['unit_id', 'consultation_status_id'],
        unique=False
    )
    # For sorting by updated_at within a unit (common dashboard query)
    op.create_index(
        'ix_lead_unit_updated',
        'lead',
        ['unit_id', 'updated_at'],
        unique=False
    )

    # Consultation composite indexes
    op.create_index(
        'ix_consultation_lead_date',
        'consultation',
        ['lead_id', 'consultation_date'],
        unique=False
    )
    op.create_index(
        'ix_consultation_officer_date',
        'consultation',
        ['officer_id', 'consultation_date'],
        unique=False
    )


def downgrade() -> None:
    """Remove composite indexes."""
    op.drop_index('ix_consultation_officer_date', table_name='consultation')
    op.drop_index('ix_consultation_lead_date', table_name='consultation')
    op.drop_index('ix_lead_unit_updated', table_name='lead')
    op.drop_index('ix_lead_unit_consultation_status', table_name='lead')
    op.drop_index('ix_lead_unit_stage', table_name='lead')
    op.drop_index('ix_lead_unit_officer', table_name='lead')
    op.drop_index('ix_lead_unit_status', table_name='lead')
