"""drop processed_event table per ADR-001

Revision ID: b2_drop_processed_event
Revises: 5448988f1a77
Create Date: 2026-04-11

Removes the ``processed_event`` table per ADR-001. The table was created by
migration fin20260131001 for finance_events.py DomainEvent idempotency
tracking but never populated by production code (zero rows verified on dev
and production as of 2026-04-11).

Source cluster (finance_events.py, idempotent_handler.py, EventIdempotencyService,
ProcessedEvent ORM model) was already removed in Phase B1 (PR #107). This
migration completes the cleanup by dropping the orphan table.

DESTRUCTIVE: drops table. Down-migration recreates schema (rows lost).

Schema source: fin20260131001_create_finance_foundation_tables.py lines 129-151.
Verified 2026-04-09 by Agent 3 + 2026-04-11 by pg_dump backup DDL match.

Pinned IDs:
  B2_REVISION = b2_drop_processed_event
  B2_DOWN_REVISION = 5448988f1a77

References:
- ADR-001: docs/adr/ADR-001-remove-finance-events.md
- Audit: EVENT_AUDIT_MATRIX.md Finding 1
- Original create: alembic/versions/fin20260131001_create_finance_foundation_tables.py:129-151
- Plan: velvet-swinging-moore.md Phase B2
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'b2_drop_processed_event'
down_revision = '5448988f1a77'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop the processed_event table."""
    op.drop_index('ix_processed_event_event_id', table_name='processed_event')
    op.drop_index('ix_processed_event_event_type', table_name='processed_event')
    op.drop_table('processed_event')


def downgrade() -> None:
    """Recreate processed_event table for rollback (rows lost on drop).

    Schema mirrors fin20260131001_create_finance_foundation_tables.py:129-151
    exactly. Verified against:
    - Source file read (Agent 3, 2026-04-09)
    - pg_dump backup DDL (2026-04-11)
    - Plan v6 B2.1 section
    """
    op.create_table(
        'processed_event',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'event_id', sa.String(100), nullable=False,
            comment='Unique event identifier (e.g., VNPay transaction ID)',
        ),
        sa.Column(
            'event_type', sa.String(50), nullable=False,
            comment='Event type (e.g., vnpay_callback, momo_callback)',
        ),
        sa.Column(
            'event_version', sa.String(20), nullable=True,
            comment='Event schema version',
        ),
        sa.Column(
            'consumer_id', sa.String(50), nullable=False,
            comment='Consumer identifier (e.g., payment_service)',
        ),
        sa.Column(
            'processed_at', sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column(
            'processing_result', sa.String(20), nullable=False,
            comment='Result: success|failed|skipped',
        ),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column(
            'event_payload', JSONB, nullable=True,
            comment='Original event payload for debugging',
        ),
        sa.UniqueConstraint(
            'event_id', 'consumer_id',
            name='uq_processed_event_id_consumer',
        ),
        sa.CheckConstraint(
            "processing_result IN ('success', 'failed', 'skipped')",
            name='chk_processed_event_result',
        ),
    )
    op.create_index(
        'ix_processed_event_event_id', 'processed_event', ['event_id']
    )
    op.create_index(
        'ix_processed_event_event_type', 'processed_event', ['event_type']
    )
