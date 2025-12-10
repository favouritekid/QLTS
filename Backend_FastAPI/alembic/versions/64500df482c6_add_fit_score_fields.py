"""add_fit_score_fields

Revision ID: 64500df482c6
Revises: 2bfffbd530e4
Create Date: 2025-12-10 02:50:26.658134

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '64500df482c6'
down_revision: Union[str, Sequence[str], None] = '2bfffbd530e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add Fit Score fields to Lead and ProgramOffering."""
    # Lead table - new fields for Fit Score calculation
    op.add_column('lead', sa.Column('birth_year', sa.Integer(), nullable=True, 
                  comment='Năm sinh (VD: 2000)'))
    op.add_column('lead', sa.Column('location_proximity', sa.Integer(), nullable=False, 
                  server_default='0', comment='Officer đánh giá: 0=Xa, 1=Lân cận, 2=Gần'))
    op.add_column('lead', sa.Column('occupation_relevance', sa.Integer(), nullable=False, 
                  server_default='0', comment='Officer đánh giá: 0=Không liên quan, 1=Gián tiếp, 2=Trực tiếp'))
    op.add_column('lead', sa.Column('academic_performance', sa.Integer(), nullable=False, 
                  server_default='0', comment='Học lực: 0=Yếu/Chưa xác định, 1=Trung bình, 2=Khá, 3=Giỏi'))
    
    # ProgramOffering table - scoring rules config
    op.add_column('program_offering', sa.Column('scoring_rules', postgresql.JSONB(astext_type=sa.Text()), 
                  nullable=True, comment='Scoring rules: {target_age_min, target_age_max, required_education, hot_level}'))


def downgrade() -> None:
    """Remove Fit Score fields."""
    op.drop_column('program_offering', 'scoring_rules')
    op.drop_column('lead', 'academic_performance')
    op.drop_column('lead', 'occupation_relevance')
    op.drop_column('lead', 'location_proximity')
    op.drop_column('lead', 'birth_year')
