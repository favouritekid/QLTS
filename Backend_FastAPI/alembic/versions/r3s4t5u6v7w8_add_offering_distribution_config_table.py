"""Add offering_distribution_config table for weighted lead distribution

Revision ID: r3s4t5u6v7w8
Revises: 80e02a48e91e
Create Date: 2025-11-15 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'r3s4t5u6v7w8'
down_revision: Union[str, Sequence[str], None] = '80e02a48e91e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create offering_distribution_config table for Weighted Round Robin distribution.

    This table enables:
    - Fair lead distribution across multiple units sharing an offering
    - Weighted allocation based on unit capacity
    - Priority-based routing for special cases
    """
    op.create_table(
        'offering_distribution_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('offering_id', sa.Integer(), nullable=False, comment='ProgramOffering being distributed'),
        sa.Column('unit_id', sa.Integer(), nullable=False, comment='OrganizationUnit receiving leads'),
        sa.Column('weight', sa.Integer(), nullable=False, server_default='1',
                  comment='Distribution weight (higher = more leads). Range: 1-100'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='1',
                  comment='Priority level (lower number = higher priority). Range: 1-10'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true',
                  comment='Toggle to temporarily exclude unit from receiving leads'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False, comment='Timestamp when config was created'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False, comment='Timestamp when config was last updated'),
        sa.ForeignKeyConstraint(['offering_id'], ['program_offering.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['unit_id'], ['organization_unit.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('offering_id', 'unit_id', name='uq_offering_unit_distribution')
    )

    # Create indexes for fast lookups
    op.create_index(op.f('ix_offering_distribution_config_id'),
                    'offering_distribution_config', ['id'], unique=False)
    op.create_index(op.f('ix_offering_distribution_config_offering_id'),
                    'offering_distribution_config', ['offering_id'], unique=False)
    op.create_index(op.f('ix_offering_distribution_config_unit_id'),
                    'offering_distribution_config', ['unit_id'], unique=False)
    op.create_index(op.f('ix_offering_distribution_config_is_active'),
                    'offering_distribution_config', ['is_active'], unique=False)


def downgrade() -> None:
    """Drop offering_distribution_config table and indexes."""
    op.drop_index(op.f('ix_offering_distribution_config_is_active'),
                  table_name='offering_distribution_config')
    op.drop_index(op.f('ix_offering_distribution_config_unit_id'),
                  table_name='offering_distribution_config')
    op.drop_index(op.f('ix_offering_distribution_config_offering_id'),
                  table_name='offering_distribution_config')
    op.drop_index(op.f('ix_offering_distribution_config_id'),
                  table_name='offering_distribution_config')
    op.drop_table('offering_distribution_config')
