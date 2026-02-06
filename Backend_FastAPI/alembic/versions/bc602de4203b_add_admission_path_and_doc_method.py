"""add_admission_path_and_doc_method

Revision ID: bc602de4203b
Revises: r1s2t3u4v5w6
Create Date: 2026-01-10 08:35:43.908125

Schema Changes:
1. CREATE TABLE admission_path - Central entity for admission configuration
2. ADD COLUMN document_group.admission_method_id - Method-specific document groups
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'bc602de4203b'
down_revision: Union[str, Sequence[str], None] = 'r1s2t3u4v5w6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Create admission_path table
    op.create_table('admission_path',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('academic_info_id', sa.Integer(), nullable=False, 
                  comment='Link to offering per year (Year + Major + Offering)'),
        sa.Column('admission_method_id', sa.Integer(), nullable=False, 
                  comment='Link to admission method (hoc_ba, thpt_qg, dgnl)'),
        sa.Column('status', sa.String(length=20), nullable=False, 
                  comment='Status: draft | active | inactive | archived'),
        sa.Column('display_name', sa.String(length=255), nullable=True, 
                  comment="Human-readable name: 'CNTT 2026 – CQ – Học bạ'"),
        sa.Column('display_order', sa.Integer(), nullable=False, 
                  comment='Display order in UI'),
        sa.Column('visibility', sa.String(length=20), nullable=False, 
                  comment='Visibility: internal | public (for future portal)'),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True, 
                  comment='When was this path activated'),
        sa.Column('activated_by', sa.Integer(), nullable=True, 
                  comment='Who activated this path'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['academic_info_id'], ['offering_academic_info.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['activated_by'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['admission_method_id'], ['admission_method.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('academic_info_id', 'admission_method_id', 
                            name='uq_admission_path_offering_method')
    )
    op.create_index(op.f('ix_admission_path_academic_info_id'), 'admission_path', 
                    ['academic_info_id'], unique=False)
    op.create_index(op.f('ix_admission_path_admission_method_id'), 'admission_path', 
                    ['admission_method_id'], unique=False)
    op.create_index(op.f('ix_admission_path_id'), 'admission_path', ['id'], unique=False)
    op.create_index(op.f('ix_admission_path_status'), 'admission_path', ['status'], unique=False)
    
    # 2. Add admission_method_id to document_group
    op.add_column('document_group', 
        sa.Column('admission_method_id', sa.Integer(), nullable=True, 
                  comment='NULL = all methods, non-NULL = method-specific override'))
    op.create_index(op.f('ix_document_group_admission_method_id'), 'document_group', 
                    ['admission_method_id'], unique=False)
    op.create_index('ix_document_group_offering_method', 'document_group', 
                    ['offering_type_id', 'admission_method_id'], unique=False)
    op.create_foreign_key('fk_document_group_admission_method', 'document_group', 
                          'admission_method', ['admission_method_id'], ['id'], 
                          ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Remove admission_method_id from document_group
    op.drop_constraint('fk_document_group_admission_method', 'document_group', type_='foreignkey')
    op.drop_index('ix_document_group_offering_method', table_name='document_group')
    op.drop_index(op.f('ix_document_group_admission_method_id'), table_name='document_group')
    op.drop_column('document_group', 'admission_method_id')
    
    # 2. Drop admission_path table
    op.drop_index(op.f('ix_admission_path_status'), table_name='admission_path')
    op.drop_index(op.f('ix_admission_path_id'), table_name='admission_path')
    op.drop_index(op.f('ix_admission_path_admission_method_id'), table_name='admission_path')
    op.drop_index(op.f('ix_admission_path_academic_info_id'), table_name='admission_path')
    op.drop_table('admission_path')
