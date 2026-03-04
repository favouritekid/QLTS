"""add commission tables and collaborator code sequence

Revision ID: z9f0g1h2i3j4
Revises: cleanup20260216001
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'z9f0g1h2i3j4'
down_revision: Union[str, None] = 'cleanup20260216001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === Task 1.6: Create PostgreSQL sequence for collaborator codes ===
    op.execute("CREATE SEQUENCE IF NOT EXISTS collaborator_code_seq START WITH 1 INCREMENT BY 1")

    # Initialize sequence from existing max code
    op.execute("""
        DO $$
        DECLARE
            max_seq INTEGER;
        BEGIN
            SELECT COALESCE(
                MAX(CAST(SUBSTRING(code FROM '[0-9]+$') AS INTEGER)),
                0
            ) INTO max_seq
            FROM collaborator
            WHERE code LIKE 'CTV-%';

            IF max_seq > 0 THEN
                PERFORM setval('collaborator_code_seq', max_seq);
            END IF;
        END $$;
    """)

    # === Task 1.8: Commission Policy table ===
    op.create_table(
        'commission_policy',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('trigger_status_id', sa.String(50), nullable=False, index=True),
        sa.Column('calculation_type', sa.String(20), nullable=False),
        sa.Column('fixed_amount', sa.Numeric(12, 0), nullable=True),
        sa.Column('percentage', sa.Numeric(5, 2), nullable=True),
        sa.Column('unit_id', sa.Integer(), sa.ForeignKey('organization_unit.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('offering_id', sa.Integer(), sa.ForeignKey('program_offering.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', index=True),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(calculation_type = 'fixed' AND fixed_amount IS NOT NULL) OR "
            "(calculation_type = 'percentage' AND percentage IS NOT NULL)",
            name='ck_commission_policy_amount',
        ),
    )

    # === Task 1.8: Commission Record table ===
    op.create_table(
        'commission_record',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('collaborator_id', sa.Integer(), sa.ForeignKey('collaborator.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('lead.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('policy_id', sa.Integer(), sa.ForeignKey('commission_policy.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('amount', sa.Numeric(12, 0), nullable=False),
        sa.Column('calculation_detail', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending', index=True),
        sa.Column('trigger_status_id', sa.String(50), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('approved_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('cancellation_reason', sa.String(500), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('payment_reference', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('lead_id', 'policy_id', name='uq_commission_lead_policy'),
    )


def downgrade() -> None:
    op.drop_table('commission_record')
    op.drop_table('commission_policy')
    op.execute("DROP SEQUENCE IF EXISTS collaborator_code_seq")
