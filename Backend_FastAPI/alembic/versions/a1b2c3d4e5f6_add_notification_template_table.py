"""add_notification_template_table

Revision ID: a1b2c3d4e5f6
Revises: 7caf68807fa8
Create Date: 2025-11-27 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '7caf68807fa8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    ✅ PHASE 3.1: Create notification_template table for reusable templates.

    This table allows administrators to create and manage reusable notification
    templates that can be referenced by multiple notification rules, reducing
    duplication and making template management easier.
    """
    op.create_table(
        'notification_template',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False, comment='Template name (unique identifier)'),
        sa.Column('description', sa.Text(), nullable=True, comment='Template description for admins'),
        sa.Column('title_template', sa.String(length=255), nullable=False, comment='Title template with {placeholders}'),
        sa.Column('message_template', sa.Text(), nullable=False, comment='Message template with {placeholders}'),
        sa.Column('link_template', sa.String(length=512), nullable=True, comment='Optional link template'),
        sa.Column('variables', postgresql.JSON(astext_type=sa.Text()), nullable=True, comment='List of available variables for this template'),
        sa.Column('category', sa.String(length=50), nullable=True, comment='Template category (e.g., "lead", "consultation", "application")'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false', comment='System template (cannot be deleted)'),
        sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0', comment='Number of rules using this template'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='User ID who created this template'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL')
    )

    # Create indexes for efficient querying
    op.create_index(op.f('ix_notification_template_id'), 'notification_template', ['id'], unique=False)
    op.create_index(op.f('ix_notification_template_name'), 'notification_template', ['name'], unique=True)  # Unique template names
    op.create_index(op.f('ix_notification_template_category'), 'notification_template', ['category'], unique=False)  # Filter by category
    op.create_index(op.f('ix_notification_template_is_system'), 'notification_template', ['is_system'], unique=False)  # Filter system templates

    # Add template_id column to notification_rule (optional reference)
    op.add_column(
        'notification_rule',
        sa.Column('template_id', sa.Integer(), nullable=True, comment='Optional reference to reusable template')
    )
    op.create_foreign_key(
        'fk_notification_rule_template',
        'notification_rule',
        'notification_template',
        ['template_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_index(
        op.f('ix_notification_rule_template_id'),
        'notification_rule',
        ['template_id'],
        unique=False
    )


def downgrade() -> None:
    """
    Rollback: Drop notification_template table and related columns.
    """
    # Remove template_id from notification_rule
    op.drop_index(op.f('ix_notification_rule_template_id'), table_name='notification_rule')
    op.drop_constraint('fk_notification_rule_template', 'notification_rule', type_='foreignkey')
    op.drop_column('notification_rule', 'template_id')

    # Drop notification_template table
    op.drop_index(op.f('ix_notification_template_is_system'), table_name='notification_template')
    op.drop_index(op.f('ix_notification_template_category'), table_name='notification_template')
    op.drop_index(op.f('ix_notification_template_name'), table_name='notification_template')
    op.drop_index(op.f('ix_notification_template_id'), table_name='notification_template')
    op.drop_table('notification_template')
