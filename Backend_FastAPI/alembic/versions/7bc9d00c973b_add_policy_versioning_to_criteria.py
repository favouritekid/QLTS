"""add_policy_versioning_to_criteria

Revision ID: 7bc9d00c973b
Revises: bd234d6fb095
Create Date: 2026-01-04 11:35:11.056788

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7bc9d00c973b'
down_revision: Union[str, Sequence[str], None] = 'bd234d6fb095'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add policy versioning fields to admission_criteria + restore casbin_rule."""
    
    pass  # casbin_rule managed by adapter, not Alembic

    # =========================================================================
    # Add policy versioning columns
    # =========================================================================
    
    # Add policy_version with server_default for existing rows
    op.add_column(
        'admission_criteria',
        sa.Column(
            'policy_version',
            sa.String(length=20),
            nullable=False,
            server_default='2025.1',  # Default for existing rows
            comment='Phiên bản quy chế: 2025.1, 2026.1, etc.'
        )
    )
    
    # Add effective_from (nullable)
    op.add_column(
        'admission_criteria',
        sa.Column(
            'effective_from',
            sa.Date(),
            nullable=True,
            comment='Ngày bắt đầu áp dụng (NULL = có hiệu lực ngay)'
        )
    )
    
    # Add effective_to (nullable)
    op.add_column(
        'admission_criteria',
        sa.Column(
            'effective_to',
            sa.Date(),
            nullable=True,
            comment='Ngày kết thúc hiệu lực (NULL = vẫn đang hiệu lực)'
        )
    )


def downgrade() -> None:
    """Remove policy versioning fields and drop casbin_rule."""
    op.drop_column('admission_criteria', 'effective_to')
    op.drop_column('admission_criteria', 'effective_from')
    op.drop_column('admission_criteria', 'policy_version')
    pass  # casbin_rule managed by adapter, not Alembic
