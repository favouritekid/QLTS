"""create_administrative_nodes_table

Revision ID: e01bc00eaf03
Revises: f3g4h5i6j7k8
Create Date: 2026-01-20 08:17:14.455004

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e01bc00eaf03'
down_revision: Union[str, Sequence[str], None] = 'f3g4h5i6j7k8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create administrative_nodes table with temporal versioning support."""
    # Create administrative_nodes table
    op.create_table('administrative_nodes',
        sa.Column('id', sa.BIGINT(), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False, comment='Mã hành chính (TCTK code)'),
        sa.Column('name', sa.String(length=255), nullable=False, comment='Tên đơn vị hành chính'),
        sa.Column('level', sa.Enum('PROVINCE', 'DISTRICT', 'WARD', name='administrativelevel'), nullable=False, comment='Cấp hành chính'),
        sa.Column('parent_id', sa.BIGINT(), nullable=True, comment='ID của node cha (NULL nếu là Province)'),
        sa.Column('path', sa.String(length=100), nullable=False, comment='Materialized path (VD: 01/001/00118)'),
        sa.Column('province_code', sa.String(length=20), nullable=False, comment='Cache mã tỉnh'),
        sa.Column('district_code', sa.String(length=20), nullable=True, comment='Cache mã quận/huyện (NULL nếu 2-cấp)'),
        sa.Column('ward_code', sa.String(length=20), nullable=True, comment='Cache mã xã/phường'),
        sa.Column('valid_from', sa.Date(), nullable=False, comment='Ngày bắt đầu hiệu lực'),
        sa.Column('valid_to', sa.Date(), nullable=True, comment='Ngày hết hiệu lực (NULL = còn hiệu lực)'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true', comment='Soft delete flag'),
        sa.Column('created_at', postgresql.TIMESTAMP(), nullable=True, server_default=sa.text('now()')),
        sa.Column('updated_at', postgresql.TIMESTAMP(), nullable=True, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['parent_id'], ['administrative_nodes.id'], name='fk_admin_node_parent'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for efficient querying
    op.create_index('idx_admin_node_code', 'administrative_nodes', ['code'], unique=False)
    op.create_index('idx_admin_node_path', 'administrative_nodes', ['path'], unique=False)
    op.create_index('idx_admin_node_province', 'administrative_nodes', ['province_code'], unique=False)
    op.create_index('idx_admin_node_district', 'administrative_nodes', ['district_code'], unique=False)
    op.create_index('idx_admin_node_valid_time', 'administrative_nodes', ['valid_from', 'valid_to'], unique=False)
    op.create_index('idx_admin_node_parent', 'administrative_nodes', ['parent_id'], unique=False)
    op.create_index('idx_admin_node_level', 'administrative_nodes', ['level'], unique=False)


def downgrade() -> None:
    """Drop administrative_nodes table."""
    op.drop_index('idx_admin_node_level', table_name='administrative_nodes')
    op.drop_index('idx_admin_node_parent', table_name='administrative_nodes')
    op.drop_index('idx_admin_node_valid_time', table_name='administrative_nodes')
    op.drop_index('idx_admin_node_district', table_name='administrative_nodes')
    op.drop_index('idx_admin_node_province', table_name='administrative_nodes')
    op.drop_index('idx_admin_node_path', table_name='administrative_nodes')
    op.drop_index('idx_admin_node_code', table_name='administrative_nodes')
    op.drop_table('administrative_nodes')
    
    # Drop the enum type
    op.execute("DROP TYPE IF EXISTS administrativelevel")
