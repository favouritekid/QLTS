"""add_user_activity_log_table

Revision ID: d1e2f3g4h5i6
Revises: a1b2c3d4e5f6
Create Date: 2025-01-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3g4h5i6'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create user_activity_log table
    op.create_table(
        'user_activity_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('target_user_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('resource_type', sa.String(length=50), nullable=False),
        sa.Column('resource_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('changes', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=256), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['target_user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for better query performance
    op.create_index(op.f('ix_user_activity_log_id'), 'user_activity_log', ['id'], unique=False)
    op.create_index(op.f('ix_user_activity_log_actor_id'), 'user_activity_log', ['actor_id'], unique=False)
    op.create_index(op.f('ix_user_activity_log_target_user_id'), 'user_activity_log', ['target_user_id'], unique=False)
    op.create_index(op.f('ix_user_activity_log_action'), 'user_activity_log', ['action'], unique=False)
    op.create_index(op.f('ix_user_activity_log_resource_type'), 'user_activity_log', ['resource_type'], unique=False)
    op.create_index(op.f('ix_user_activity_log_created_at'), 'user_activity_log', ['created_at'], unique=False)


def downgrade() -> None:
    # Drop indexes
    op.drop_index(op.f('ix_user_activity_log_created_at'), table_name='user_activity_log')
    op.drop_index(op.f('ix_user_activity_log_resource_type'), table_name='user_activity_log')
    op.drop_index(op.f('ix_user_activity_log_action'), table_name='user_activity_log')
    op.drop_index(op.f('ix_user_activity_log_target_user_id'), table_name='user_activity_log')
    op.drop_index(op.f('ix_user_activity_log_actor_id'), table_name='user_activity_log')
    op.drop_index(op.f('ix_user_activity_log_id'), table_name='user_activity_log')

    # Drop table
    op.drop_table('user_activity_log')
