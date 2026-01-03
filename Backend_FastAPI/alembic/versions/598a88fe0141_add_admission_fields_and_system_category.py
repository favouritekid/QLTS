"""add_admission_fields_and_system_category

Revision ID: 598a88fe0141
Revises: 4a1e0590423f
Create Date: 2026-01-03 09:54:16.796432

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '598a88fe0141'
down_revision: Union[str, Sequence[str], None] = '4a1e0590423f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create ConfigSystemCategory Table
    op.create_table('config_system_category',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False, comment='Category type: ethnicity, religion, nationality, disability_type'),
        sa.Column('code', sa.String(length=50), nullable=False, comment='Unique code within type'),
        sa.Column('name', sa.String(length=255), nullable=False, comment='Display name'),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    # Indexes for ConfigSystemCategory
    op.create_index(op.f('ix_config_system_category_code'), 'config_system_category', ['code'], unique=False)
    op.create_index(op.f('ix_config_system_category_id'), 'config_system_category', ['id'], unique=False)
    op.create_index(op.f('ix_config_system_category_name'), 'config_system_category', ['name'], unique=False)
    op.create_index(op.f('ix_config_system_category_type'), 'config_system_category', ['type'], unique=False)
    op.create_index('uq_config_category_type_code', 'config_system_category', ['type', 'code'], unique=True)

    # 2. Add Columns to AdmissionProfile
    op.add_column('admission_profile', sa.Column('full_name', sa.String(length=255), nullable=True))
    op.add_column('admission_profile', sa.Column('dob', sa.DateTime(), nullable=True))
    op.add_column('admission_profile', sa.Column('gender', sa.String(length=50), nullable=True, comment='Nam/Nữ/Khác'))
    op.add_column('admission_profile', sa.Column('email', sa.String(length=255), nullable=True))
    op.add_column('admission_profile', sa.Column('phone', sa.String(length=20), nullable=True))
    op.add_column('admission_profile', sa.Column('social_insurance_number', sa.String(length=50), nullable=True))
    op.add_column('admission_profile', sa.Column('nationality', sa.String(length=100), nullable=True))
    op.add_column('admission_profile', sa.Column('ethnicity', sa.String(length=100), nullable=True))
    op.add_column('admission_profile', sa.Column('religion', sa.String(length=100), nullable=True))
    op.add_column('admission_profile', sa.Column('disability_type', sa.String(length=100), nullable=True))
    op.add_column('admission_profile', sa.Column('permanent_province', sa.String(length=100), nullable=True))
    op.add_column('admission_profile', sa.Column('permanent_district', sa.String(length=100), nullable=True))
    op.add_column('admission_profile', sa.Column('permanent_ward', sa.String(length=100), nullable=True))
    op.add_column('admission_profile', sa.Column('place_of_birth', sa.String(length=255), nullable=True))
    op.add_column('admission_profile', sa.Column('native_place', sa.String(length=255), nullable=True))
    op.add_column('admission_profile', sa.Column('union_entry_date', sa.DateTime(), nullable=True))
    op.add_column('admission_profile', sa.Column('party_entry_date', sa.DateTime(), nullable=True))
    op.add_column('admission_profile', sa.Column('party_official_entry_date', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # 1. Drop AdmissionProfile Columns
    op.drop_column('admission_profile', 'party_official_entry_date')
    op.drop_column('admission_profile', 'party_entry_date')
    op.drop_column('admission_profile', 'union_entry_date')
    op.drop_column('admission_profile', 'native_place')
    op.drop_column('admission_profile', 'place_of_birth')
    op.drop_column('admission_profile', 'permanent_ward')
    op.drop_column('admission_profile', 'permanent_district')
    op.drop_column('admission_profile', 'permanent_province')
    op.drop_column('admission_profile', 'disability_type')
    op.drop_column('admission_profile', 'religion')
    op.drop_column('admission_profile', 'ethnicity')
    op.drop_column('admission_profile', 'nationality')
    op.drop_column('admission_profile', 'social_insurance_number')
    op.drop_column('admission_profile', 'phone')
    op.drop_column('admission_profile', 'email')
    op.drop_column('admission_profile', 'gender')
    op.drop_column('admission_profile', 'dob')
    op.drop_column('admission_profile', 'full_name')

    # 2. Drop ConfigSystemCategory Table
    op.drop_index('uq_config_category_type_code', table_name='config_system_category')
    op.drop_index(op.f('ix_config_system_category_type'), table_name='config_system_category')
    op.drop_index(op.f('ix_config_system_category_name'), table_name='config_system_category')
    op.drop_index(op.f('ix_config_system_category_id'), table_name='config_system_category')
    op.drop_index(op.f('ix_config_system_category_code'), table_name='config_system_category')
    op.drop_table('config_system_category')
