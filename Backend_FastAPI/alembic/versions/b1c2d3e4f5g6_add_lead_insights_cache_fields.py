"""add_lead_insights_cache_fields

Revision ID: b1c2d3e4f5g6
Revises: a9cd4ab78906
Create Date: 2024-12-13

Lead Insights Upgrade - Phase 1
Add cached fields for Lead metrics to support fast sorting/filtering in DataTable.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5g6'
down_revision = 'a9cd4ab78906'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add Lead Insights cached fields."""
    
    # 1. last_consultation_at - Ngày tư vấn cuối cùng
    op.add_column('lead', sa.Column(
        'last_consultation_at',
        sa.DateTime(timezone=True),
        nullable=True,
        comment='Ngày tư vấn cuối cùng (auto-updated)'
    ))
    op.create_index(
        'ix_lead_last_consultation_at',
        'lead',
        ['last_consultation_at'],
        unique=False
    )
    
    # 2. consultation_count - Số lần tư vấn
    op.add_column('lead', sa.Column(
        'consultation_count',
        sa.Integer(),
        nullable=False,
        server_default='0',
        comment='Số lần tư vấn (auto-updated)'
    ))
    
    # 3. cached_urgency_score - Điểm khẩn cấp 0-100
    op.add_column('lead', sa.Column(
        'cached_urgency_score',
        sa.Integer(),
        nullable=False,
        server_default='50',
        comment='Điểm khẩn cấp 0-100 (auto-calculated)'
    ))
    op.create_index(
        'ix_lead_cached_urgency_score',
        'lead',
        ['cached_urgency_score'],
        unique=False
    )
    
    # 4. is_hot_lead - Lead score >= 70
    op.add_column('lead', sa.Column(
        'is_hot_lead',
        sa.Boolean(),
        nullable=False,
        server_default='false',
        comment='Lead score >= 70'
    ))
    op.create_index(
        'ix_lead_is_hot_lead',
        'lead',
        ['is_hot_lead'],
        unique=False
    )
    
    # 5. is_overdue - next_activity_at đã quá hạn
    op.add_column('lead', sa.Column(
        'is_overdue',
        sa.Boolean(),
        nullable=False,
        server_default='false',
        comment='next_activity_at đã quá hạn'
    ))
    op.create_index(
        'ix_lead_is_overdue',
        'lead',
        ['is_overdue'],
        unique=False
    )
    
    print("✅ Added 5 cached fields to Lead model for Insights Upgrade")


def downgrade() -> None:
    """Remove Lead Insights cached fields."""
    
    # Drop indexes first
    op.drop_index('ix_lead_is_overdue', table_name='lead')
    op.drop_index('ix_lead_is_hot_lead', table_name='lead')
    op.drop_index('ix_lead_cached_urgency_score', table_name='lead')
    op.drop_index('ix_lead_last_consultation_at', table_name='lead')
    
    # Drop columns
    op.drop_column('lead', 'is_overdue')
    op.drop_column('lead', 'is_hot_lead')
    op.drop_column('lead', 'cached_urgency_score')
    op.drop_column('lead', 'consultation_count')
    op.drop_column('lead', 'last_consultation_at')
    
    print("✅ Removed Lead Insights cached fields")
