"""Add entity_audit_log table for generic field tracking

Revision ID: audit20260126002
Revises: perf20260126001
Create Date: 2026-01-26

Purpose:
    Creates a generic audit log table for tracking field-level changes
    across any entity in the system. Complements specialized audit logs
    (LeadStatusHistory, DocumentAuditLog) with a flexible, queryable
    audit trail for all models.

Analysis Source: LEAD_ADMISSION_AUDIT_REPORT.md Issue #5
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'audit20260126002'
down_revision = 'perf20260126001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'entity_audit_log',
        # Primary key
        sa.Column('id', sa.Integer(), nullable=False),

        # Entity identification (polymorphic)
        sa.Column('entity_type', sa.String(100), nullable=False,
                  comment="Model/table name (e.g., 'AdmissionProfile', 'NotificationRule')"),
        sa.Column('entity_id', sa.Integer(), nullable=False,
                  comment="Primary key of the affected record"),

        # Action type
        sa.Column('action', sa.String(50), nullable=False,
                  comment="Action type: created, updated, deleted, status_changed, etc."),

        # Actor (who made the change)
        sa.Column('actor_user_id', sa.Integer(), nullable=True,
                  comment="User who performed the action (NULL for system actions)"),

        # Change details - single field
        sa.Column('field_name', sa.String(100), nullable=True,
                  comment="Specific field changed (NULL for bulk/create/delete)"),
        sa.Column('old_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="Previous value(s) - JSON for complex types"),
        sa.Column('new_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="New value(s) - JSON for complex types"),

        # Bulk changes (for updates touching multiple fields)
        sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="Full changeset: {field: {old: x, new: y}, ...}"),

        # Context
        sa.Column('reason', sa.Text(), nullable=True,
                  comment="Human-readable reason for the change"),
        sa.Column('source', sa.String(50), nullable=True,
                  comment="Change source: api, admin_panel, system, migration, etc."),

        # Request metadata
        sa.Column('ip_address', sa.String(45), nullable=True,
                  comment="Client IP address (IPv4 or IPv6)"),
        sa.Column('user_agent', sa.String(500), nullable=True,
                  comment="Client user agent string"),

        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()'),
                  comment="When the change occurred"),

        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['actor_user_id'], ['user.id'],
            ondelete='SET NULL',
            name='fk_entity_audit_log_actor_user_id'
        ),
    )

    # Single-column indexes
    op.create_index('ix_entity_audit_log_id', 'entity_audit_log', ['id'])
    op.create_index('ix_entity_audit_log_entity_type', 'entity_audit_log', ['entity_type'])
    op.create_index('ix_entity_audit_log_entity_id', 'entity_audit_log', ['entity_id'])
    op.create_index('ix_entity_audit_log_action', 'entity_audit_log', ['action'])
    op.create_index('ix_entity_audit_log_actor_user_id', 'entity_audit_log', ['actor_user_id'])
    op.create_index('ix_entity_audit_log_field_name', 'entity_audit_log', ['field_name'])
    op.create_index('ix_entity_audit_log_created_at', 'entity_audit_log', ['created_at'])

    # Composite indexes for common query patterns
    # Query: "All changes to entity X"
    op.create_index(
        'ix_entity_audit_entity_lookup',
        'entity_audit_log',
        ['entity_type', 'entity_id', 'created_at']
    )
    # Query: "All changes by user X"
    op.create_index(
        'ix_entity_audit_user_date',
        'entity_audit_log',
        ['actor_user_id', 'created_at']
    )
    # Query: "All changes to field X across entities"
    op.create_index(
        'ix_entity_audit_field_type',
        'entity_audit_log',
        ['entity_type', 'field_name', 'created_at']
    )
    # Query: "Recent changes by action type"
    op.create_index(
        'ix_entity_audit_action_date',
        'entity_audit_log',
        ['action', 'created_at']
    )


def downgrade() -> None:
    # Drop composite indexes
    op.drop_index('ix_entity_audit_action_date', table_name='entity_audit_log')
    op.drop_index('ix_entity_audit_field_type', table_name='entity_audit_log')
    op.drop_index('ix_entity_audit_user_date', table_name='entity_audit_log')
    op.drop_index('ix_entity_audit_entity_lookup', table_name='entity_audit_log')

    # Drop single-column indexes
    op.drop_index('ix_entity_audit_log_created_at', table_name='entity_audit_log')
    op.drop_index('ix_entity_audit_log_field_name', table_name='entity_audit_log')
    op.drop_index('ix_entity_audit_log_actor_user_id', table_name='entity_audit_log')
    op.drop_index('ix_entity_audit_log_action', table_name='entity_audit_log')
    op.drop_index('ix_entity_audit_log_entity_id', table_name='entity_audit_log')
    op.drop_index('ix_entity_audit_log_entity_type', table_name='entity_audit_log')
    op.drop_index('ix_entity_audit_log_id', table_name='entity_audit_log')

    # Drop table
    op.drop_table('entity_audit_log')
