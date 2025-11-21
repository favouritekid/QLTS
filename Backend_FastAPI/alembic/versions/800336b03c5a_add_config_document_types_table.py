"""add_config_document_types_table

Revision ID: 800336b03c5a
Revises: w8x9y0z1a2b3
Create Date: 2025-11-21 12:33:50.795205

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '800336b03c5a'
down_revision: Union[str, Sequence[str], None] = 'w8x9y0z1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create config_document_type table and seed initial data."""
    
    # Create table
    op.create_table(
        'config_document_type',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False, comment='Mã định danh (vd: "hoc_ba", "bang_tot_nghiep")'),
        sa.Column('name', sa.String(length=100), nullable=False, comment='Tên hiển thị (vd: "Học bạ", "Bằng tốt nghiệp")'),
        sa.Column('description', sa.String(length=500), nullable=True, comment='Mô tả chi tiết về loại tài liệu'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0', comment='Thứ tự hiển thị trong dropdown (nhỏ hơn = cao hơn)'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='Soft delete flag'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.UniqueConstraint('name')
    )
    
    # Create indexes
    op.create_index('idx_config_document_type_code', 'config_document_type', ['code'], unique=False)
    op.create_index('idx_config_document_type_is_active', 'config_document_type', ['is_active'], unique=False)
    
    # Seed default document types
    op.execute("""
        INSERT INTO config_document_type (code, name, description, display_order, is_active) VALUES
        ('hoc_ba_thpt', 'Học bạ THPT', 'Học bạ THPT hoặc tương đương (bản sao công chứng)', 1, true),
        ('bang_tot_nghiep_thpt', 'Bằng tốt nghiệp THPT', 'Bằng tốt nghiệp THPT hoặc tương đương (bản sao công chứng)', 3, true),
        ('hoc_ba_thcs', 'Học bạ THCS', 'Học bạ THCS hoặc tương đương (bản sao công chứng)', 2, true),
        ('bang_tot_nghiep_thcs', 'Bằng tốt nghiệp THCS', 'Bằng tốt nghiệp THCS hoặc tương đương (bản sao công chứng)', 4, true), 
        ('cccd', 'CCCD/CMND', 'Căn cước công dân hoặc chứng minh nhân dân (bản sao)', 3, true),
        ('giay_khai_sinh', 'Giấy khai sinh', 'Bản sao giấy khai sinh (công chứng)', 4, true),
        ('anh_3x4', 'Ảnh 3x4', 'Ảnh thẻ 3x4 (4 ảnh, nền trắng, chụp trong vòng 6 tháng)', 5, true),
        ('bang_diem_thpt', 'Bảng điểm THPT', 'Bảng điểm tốt nghiệp THPT hoặc tương đương', 6, true),
        ('giay_kham_suc_khoe', 'Giấy khám sức khỏe', 'Giấy khám sức khỏe', 7, true),
        ('giay_chung_nhan_uu_tien', 'Giấy chứng nhận ưu tiên', 'Giấy chứng nhận đối tượng ưu tiên (nếu có)', 8, true)
    """)


def downgrade() -> None:
    """Drop config_document_type table."""
    op.drop_index('idx_config_document_type_is_active', table_name='config_document_type')
    op.drop_index('idx_config_document_type_code', table_name='config_document_type')
    op.drop_table('config_document_type')