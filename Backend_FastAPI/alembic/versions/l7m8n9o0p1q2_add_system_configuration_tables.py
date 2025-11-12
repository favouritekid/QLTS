"""add system configuration tables

Revision ID: l7m8n9o0p1q2
Revises: k6l7m8n9o0p1
Create Date: 2025-11-12 00:00:00.000000

This migration adds system configuration tables for standardizing:
- Degree levels (Trình độ đào tạo)
- Offering types (Loại hình đào tạo)

These tables provide centralized management of dropdown options
and ensure data consistency across the system.

CHANGES:
1. Create config_degree_level table
2. Create config_offering_type table
3. Seed initial data for both tables

PURPOSE:
- Replace hardcoded values in frontend with database-driven configuration
- Enable admin management of degree levels and offering types
- Prevent data inconsistencies from free-text input
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'l7m8n9o0p1q2'
down_revision: Union[str, None] = 'k6l7m8n9o0p1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Create system configuration tables.
    """
    # =========================================================================
    # STEP 1: Create config_degree_level table
    # =========================================================================
    op.create_table(
        'config_degree_level',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False, comment='Mã định danh (vd: cao_dang, dai_hoc)'),
        sa.Column('name', sa.String(length=100), nullable=False, comment='Tên hiển thị (vd: Cao đẳng, Đại học)'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0', comment='Thứ tự hiển thị trong dropdown (nhỏ hơn = cao hơn)'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='Soft delete flag'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_config_degree_level_code'), 'config_degree_level', ['code'], unique=False)
    op.create_index(op.f('ix_config_degree_level_id'), 'config_degree_level', ['id'], unique=False)
    op.create_index(op.f('ix_config_degree_level_is_active'), 'config_degree_level', ['is_active'], unique=False)

    # =========================================================================
    # STEP 2: Create config_offering_type table
    # =========================================================================
    op.create_table(
        'config_offering_type',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False, comment='Mã định danh (vd: chinh_quy, lien_thong)'),
        sa.Column('name', sa.String(length=100), nullable=False, comment='Tên hiển thị (vd: Chính quy, Liên thông)'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0', comment='Thứ tự hiển thị trong dropdown (nhỏ hơn = cao hơn)'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='Soft delete flag'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_config_offering_type_code'), 'config_offering_type', ['code'], unique=False)
    op.create_index(op.f('ix_config_offering_type_id'), 'config_offering_type', ['id'], unique=False)
    op.create_index(op.f('ix_config_offering_type_is_active'), 'config_offering_type', ['is_active'], unique=False)

    # =========================================================================
    # STEP 3: Seed initial degree levels
    # =========================================================================
    op.execute(text("""
        INSERT INTO config_degree_level (code, name, display_order, is_active) VALUES
        ('trung_cap', 'Trung cấp', 1, true),
        ('cao_dang', 'Cao đẳng', 2, true),
        ('dai_hoc', 'Đại học', 3, true),
        ('thac_si', 'Thạc sĩ', 4, true),
        ('tien_si', 'Tiến sĩ', 5, true)
        ON CONFLICT (code) DO NOTHING;
    """))

    # =========================================================================
    # STEP 4: Seed initial offering types
    # =========================================================================
    op.execute(text("""
        INSERT INTO config_offering_type (code, name, display_order, is_active) VALUES
        ('chinh_quy', 'Chính quy', 1, true),
        ('lien_thong', 'Liên thông', 2, true),
        ('vua_lam_vua_hoc', 'Vừa làm vừa học', 3, true),
        ('tu_xa', 'Từ xa', 4, true),
        ('lien_ket_quoc_te', 'Liên kết quốc tế', 5, true)
        ON CONFLICT (code) DO NOTHING;
    """))


def downgrade() -> None:
    """
    Drop configuration tables.

    WARNING: This will permanently delete all configuration data!
    """
    # Drop indexes first
    op.drop_index(op.f('ix_config_offering_type_is_active'), table_name='config_offering_type')
    op.drop_index(op.f('ix_config_offering_type_id'), table_name='config_offering_type')
    op.drop_index(op.f('ix_config_offering_type_code'), table_name='config_offering_type')
    op.drop_index(op.f('ix_config_degree_level_is_active'), table_name='config_degree_level')
    op.drop_index(op.f('ix_config_degree_level_id'), table_name='config_degree_level')
    op.drop_index(op.f('ix_config_degree_level_code'), table_name='config_degree_level')

    # Drop tables
    op.drop_table('config_offering_type')
    op.drop_table('config_degree_level')
