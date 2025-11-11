"""add temporal models and soft delete

Revision ID: j5k6l7m8n9o0
Revises: i4j5k6l7m8n9
Create Date: 2025-11-10 10:00:00.000000

This migration implements:
1. UserUnitAssignment table (temporal assignment history)
2. MajorAcademicInfo table (year-versioned academic data)
3. Soft delete support (is_active columns)
4. Update User model (add current_assignment_id)

IMPORTANT: This is a breaking schema change but preserves all data.
Run the data migration script AFTER this migration succeeds.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'j5k6l7m8n9o0'
down_revision: Union[str, None] = 'i4j5k6l7m8n9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =====================================================================
    # STEP 1: Create user_unit_assignment table (temporal history)
    # =====================================================================
    op.create_table(
        'user_unit_assignment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.Column('assigned_by_user_id', sa.Integer(), nullable=True),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('start_date', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('end_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['assigned_by_user_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['unit_id'], ['organization_unit.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='Temporal history of user assignments to organizational units'
    )

    # Indexes for user_unit_assignment
    op.create_index('ix_user_assignment_active', 'user_unit_assignment', ['user_id', 'is_active'])
    op.create_index('ix_unit_assignment_active', 'user_unit_assignment', ['unit_id', 'is_active'])
    op.create_index('ix_assignment_dates', 'user_unit_assignment', ['start_date', 'end_date'])
    op.create_index('ix_unit_role_active', 'user_unit_assignment', ['unit_id', 'role', 'is_active'])
    op.create_index(op.f('ix_user_unit_assignment_id'), 'user_unit_assignment', ['id'])

    # =====================================================================
    # STEP 2: Create major_academic_info table (year-versioned academic data)
    # =====================================================================
    op.create_table(
        'major_academic_info',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('major_id', sa.Integer(), nullable=False),
        sa.Column('academic_year', sa.Integer(), nullable=False),
        sa.Column('target_audience', sa.Text(), nullable=True),
        sa.Column('detailed_info', sa.Text(), nullable=True),
        sa.Column('current_year_benefits', sa.Text(), nullable=True),
        sa.Column('tuition_fee_per_year', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('annual_admission_quota', sa.Integer(), nullable=True),
        sa.Column('is_published', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['major_id'], ['major.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('major_id', 'academic_year', name='uq_major_academic_year'),
        comment='Year-versioned academic information for majors'
    )

    # Indexes for major_academic_info
    op.create_index('ix_major_year_published', 'major_academic_info', ['major_id', 'academic_year', 'is_published'])
    op.create_index('ix_year_published', 'major_academic_info', ['academic_year', 'is_published'])
    op.create_index(op.f('ix_major_academic_info_id'), 'major_academic_info', ['id'])
    op.create_index(op.f('ix_major_academic_info_major_id'), 'major_academic_info', ['major_id'])
    op.create_index(op.f('ix_major_academic_info_academic_year'), 'major_academic_info', ['academic_year'])

    # =====================================================================
    # STEP 3: Add soft delete column to organization_unit
    # =====================================================================
    op.add_column(
        'organization_unit',
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False,
                  comment='Soft delete flag - never hard delete organizational units')
    )
    op.create_index(op.f('ix_organization_unit_is_active'), 'organization_unit', ['is_active'])

    # =====================================================================
    # STEP 4: Add soft delete column to major
    # =====================================================================
    op.add_column(
        'major',
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False,
                  comment='Soft delete flag - preserve historical major data')
    )
    op.create_index(op.f('ix_major_is_active'), 'major', ['is_active'])

    # =====================================================================
    # STEP 5: Add current_assignment_id to user (without FK first)
    # =====================================================================
    # Add column without foreign key constraint first (chicken-egg problem)
    op.add_column(
        'user',
        sa.Column('current_assignment_id', sa.Integer(), nullable=True,
                  comment='FK to current active UserUnitAssignment (cache sync point)')
    )
    op.create_index(op.f('ix_user_current_assignment_id'), 'user', ['current_assignment_id'])

    # =====================================================================
    # STEP 6: Add foreign key constraint AFTER data migration
    # =====================================================================
    # NOTE: This FK will be added by data migration script after populating
    # user_unit_assignment table with initial data. Otherwise we have a
    # chicken-egg problem: user.current_assignment_id references a table
    # that doesn't have any rows yet.
    #
    # The data migration script will:
    # 1. Create initial UserUnitAssignment records from existing user.role/unit_id
    # 2. Update user.current_assignment_id to point to those records
    # 3. Add the FK constraint
    #
    # For now, we just add the column and index.


def downgrade() -> None:
    """
    Downgrade migration - DANGEROUS!

    This will DROP the temporal history tables and remove soft delete flags.
    ALL HISTORICAL DATA WILL BE LOST.

    Only use this in development/testing environments.
    """
    # Remove FK constraint if it was added
    # (data migration script adds this, so we try to remove it)
    try:
        op.drop_constraint('fk_user_current_assignment', 'user', type_='foreignkey')
    except:
        pass  # FK might not exist yet

    # Remove columns from user
    op.drop_index(op.f('ix_user_current_assignment_id'), table_name='user')
    op.drop_column('user', 'current_assignment_id')

    # Remove is_active from major
    op.drop_index(op.f('ix_major_is_active'), table_name='major')
    op.drop_column('major', 'is_active')

    # Remove is_active from organization_unit
    op.drop_index(op.f('ix_organization_unit_is_active'), table_name='organization_unit')
    op.drop_column('organization_unit', 'is_active')

    # Drop major_academic_info table
    op.drop_index(op.f('ix_major_academic_info_academic_year'), table_name='major_academic_info')
    op.drop_index(op.f('ix_major_academic_info_major_id'), table_name='major_academic_info')
    op.drop_index(op.f('ix_major_academic_info_id'), table_name='major_academic_info')
    op.drop_index('ix_year_published', table_name='major_academic_info')
    op.drop_index('ix_major_year_published', table_name='major_academic_info')
    op.drop_table('major_academic_info')

    # Drop user_unit_assignment table
    op.drop_index(op.f('ix_user_unit_assignment_id'), table_name='user_unit_assignment')
    op.drop_index('ix_unit_role_active', table_name='user_unit_assignment')
    op.drop_index('ix_assignment_dates', table_name='user_unit_assignment')
    op.drop_index('ix_unit_assignment_active', table_name='user_unit_assignment')
    op.drop_index('ix_user_assignment_active', table_name='user_unit_assignment')
    op.drop_table('user_unit_assignment')
