"""add kpi configuration tables

Revision ID: q1r2s3t4u5v6
Revises: 91129728ac99
Create Date: 2024-12-18 10:00:00.000000

This migration adds KPI configuration tables for:
1. kpi_config: Configurable KPI targets per unit/officer (Phase 1)
2. kpi_target: Annual targets with YTD tracking (Phase 6)
3. kpi_monthly_snapshot: Monthly historical snapshots (Phase 6)

Supports inheritance hierarchy:
- Global default (unit_id IS NULL, officer_id IS NULL)
- Unit-level (unit_id != NULL, officer_id IS NULL)
- Officer-specific (officer_id != NULL)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'q1r2s3t4u5v6'
down_revision: Union[str, None] = 'b1c2d3e4f5g6'  # add_lead_insights_cache_fields (current head)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create KPI configuration tables.
    """
    # =========================================================================
    # STEP 1: Create kpi_config table
    # =========================================================================
    op.create_table(
        'kpi_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=True, comment='NULL = global default, otherwise unit-specific'),
        sa.Column('officer_id', sa.Integer(), nullable=True, comment='NULL = unit-wide, otherwise officer-specific'),
        sa.Column('kpi_code', sa.String(length=50), nullable=False, comment='KPI identifier: consultations_daily, conversion_rate, etc.'),
        sa.Column('target_value', sa.Integer(), nullable=False, comment='Target value (interpretation depends on kpi_code)'),
        sa.Column('period_type', sa.String(length=20), nullable=False, server_default='daily', comment='Period: daily, weekly, monthly, quarterly, annual'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['unit_id'], ['organization_unit.id'], name='fk_kpi_config_unit', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['officer_id'], ['user.id'], name='fk_kpi_config_officer', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Indexes
    op.create_index('ix_kpi_config_id', 'kpi_config', ['id'], unique=False)
    op.create_index('ix_kpi_config_unit_id', 'kpi_config', ['unit_id'], unique=False)
    op.create_index('ix_kpi_config_officer_id', 'kpi_config', ['officer_id'], unique=False)
    op.create_index('ix_kpi_config_kpi_code', 'kpi_config', ['kpi_code'], unique=False)
    
    # Unique index with partial filter for active configs
    op.create_index(
        'uq_kpi_config_scope',
        'kpi_config',
        ['unit_id', 'officer_id', 'kpi_code', 'period_type'],
        unique=True,
        postgresql_where=sa.text('is_active = true')
    )

    # =========================================================================
    # STEP 2: Create kpi_target table (for annual targets with YTD tracking)
    # =========================================================================
    op.create_table(
        'kpi_target',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=True, comment='NULL = organization-wide'),
        sa.Column('officer_id', sa.Integer(), nullable=True, comment='NULL = unit-wide target'),
        sa.Column('kpi_code', sa.String(length=50), nullable=False, comment='e.g., enrollments, revenue'),
        sa.Column('annual_target', sa.Integer(), nullable=False, comment='Annual target value'),
        sa.Column('fiscal_year', sa.Integer(), nullable=False, comment='Fiscal year: 2024, 2025, etc.'),
        sa.Column('achieved_ytd', sa.Integer(), nullable=False, server_default='0', comment='Year-to-date actual achievement'),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True, comment='Last time achieved_ytd was synced'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['unit_id'], ['organization_unit.id'], name='fk_kpi_target_unit', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['officer_id'], ['user.id'], name='fk_kpi_target_officer', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Indexes
    op.create_index('ix_kpi_target_id', 'kpi_target', ['id'], unique=False)
    op.create_index('ix_kpi_target_unit_id', 'kpi_target', ['unit_id'], unique=False)
    op.create_index('ix_kpi_target_officer_id', 'kpi_target', ['officer_id'], unique=False)
    op.create_index('ix_kpi_target_kpi_code', 'kpi_target', ['kpi_code'], unique=False)
    op.create_index('ix_kpi_target_fiscal_year', 'kpi_target', ['fiscal_year'], unique=False)
    
    # Unique: one target per officer/unit per kpi per year
    op.create_index(
        'uq_kpi_target_scope_year',
        'kpi_target',
        ['unit_id', 'officer_id', 'kpi_code', 'fiscal_year'],
        unique=True
    )

    # =========================================================================
    # STEP 3: Create kpi_monthly_snapshot table
    # =========================================================================
    op.create_table(
        'kpi_monthly_snapshot',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kpi_target_id', sa.Integer(), nullable=False),
        sa.Column('month', sa.Integer(), nullable=False, comment='Month: 1-12'),
        sa.Column('year', sa.Integer(), nullable=False, comment='Year: 2024, 2025, etc.'),
        sa.Column('target_value', sa.Integer(), nullable=True, comment='Calculated rolling target for this month'),
        sa.Column('actual_value', sa.Integer(), nullable=True, comment='Actual achieved in this month'),
        sa.Column('gap', sa.Integer(), nullable=True, comment='target - actual (negative = exceeded)'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['kpi_target_id'], ['kpi_target.id'], name='fk_kpi_snapshot_target', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Indexes
    op.create_index('ix_kpi_monthly_snapshot_id', 'kpi_monthly_snapshot', ['id'], unique=False)
    op.create_index('ix_kpi_monthly_snapshot_target_id', 'kpi_monthly_snapshot', ['kpi_target_id'], unique=False)
    
    # Unique: one snapshot per target per month
    op.create_index(
        'uq_kpi_snapshot_month',
        'kpi_monthly_snapshot',
        ['kpi_target_id', 'month', 'year'],
        unique=True
    )

    # =========================================================================
    # STEP 4: Seed default global KPI configs
    # =========================================================================
    op.execute(text("""
        INSERT INTO kpi_config (unit_id, officer_id, kpi_code, target_value, period_type, is_active) VALUES
        (NULL, NULL, 'consultations_daily', 10, 'daily', true),
        (NULL, NULL, 'conversion_rate', 15, 'monthly', true),
        (NULL, NULL, 'response_time_hours', 2, 'daily', true),
        (NULL, NULL, 'enrollments_monthly', 7, 'monthly', true)
        ON CONFLICT DO NOTHING;
    """))


def downgrade() -> None:
    """
    Drop KPI configuration tables.
    """
    # Drop in reverse order (child tables first)
    op.drop_table('kpi_monthly_snapshot')
    op.drop_table('kpi_target')
    op.drop_table('kpi_config')
