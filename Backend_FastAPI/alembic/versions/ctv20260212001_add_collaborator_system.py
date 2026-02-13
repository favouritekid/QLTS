"""add collaborator system tables and lead columns

Revision ID: ctv20260212001
Revises: z8e9f0g1h2i3
Create Date: 2026-02-12

Phase 1: Core CTV + Lead Attribution
- Create collaborator table
- Create lead_claim table
- Add lead.referrer_id, lead.validity_status, lead.created_via columns
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ctv20260212001'
down_revision: Union[str, None] = 'z8e9f0g1h2i3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === 1. Create collaborator table ===
    op.create_table(
        'collaborator',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(20), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=True),
        sa.Column('phone', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.Column('id_card_number', sa.String(20), nullable=True),
        sa.Column('bank_account', sa.String(50), nullable=True),
        sa.Column('bank_name', sa.String(100), nullable=True),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('managed_by_officer_id', sa.Integer(), nullable=True,
                  comment='NULL=independent CTV (auto-assign), officer_id=leads assigned directly to officer'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("(now() at time zone 'utc')")),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("(now() at time zone 'utc')")),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['unit_id'], ['organization_unit.id']),
        sa.ForeignKeyConstraint(['managed_by_officer_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approved_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_collaborator_id', 'collaborator', ['id'])
    op.create_index('ix_collaborator_code', 'collaborator', ['code'], unique=True)
    op.create_index('ix_collaborator_email', 'collaborator', ['email'])
    op.create_index('ix_collaborator_phone', 'collaborator', ['phone'])
    op.create_index('ix_collaborator_status', 'collaborator', ['status'])
    op.create_index('ix_collaborator_user_id', 'collaborator', ['user_id'])
    op.create_index('ix_collaborator_unit_id', 'collaborator', ['unit_id'])
    op.create_index('ix_collaborator_managed_by_officer_id', 'collaborator', ['managed_by_officer_id'])
    op.create_index('ix_collaborator_deleted_at', 'collaborator', ['deleted_at'])

    # === 2. Create lead_claim table ===
    op.create_table(
        'lead_claim',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collaborator_id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('claim_data', sa.JSON(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("(now() at time zone 'utc')")),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['collaborator_id'], ['collaborator.id']),
        sa.ForeignKeyConstraint(['lead_id'], ['lead.id']),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['user.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('collaborator_id', 'lead_id', name='uq_claim_collaborator_lead'),
    )
    op.create_index('ix_lead_claim_id', 'lead_claim', ['id'])
    op.create_index('ix_lead_claim_collaborator_id', 'lead_claim', ['collaborator_id'])
    op.create_index('ix_lead_claim_lead_id', 'lead_claim', ['lead_id'])
    op.create_index('ix_lead_claim_status', 'lead_claim', ['status'])

    # === 3. Add columns to lead table ===
    op.add_column('lead', sa.Column(
        'referrer_id', sa.Integer(), nullable=True,
        comment='CTV who referred this lead',
    ))
    op.add_column('lead', sa.Column(
        'validity_status', sa.String(20), nullable=False,
        server_default='raw',
        comment='Lead quality status: raw, duplicate, invalid, valid, qualified',
    ))
    op.add_column('lead', sa.Column(
        'created_via', sa.String(20), nullable=False,
        server_default='manual',
        comment='How lead was created: manual, claim, import',
    ))

    # Add FK and indexes for new lead columns
    op.create_foreign_key(
        'fk_lead_referrer_id', 'lead', 'collaborator',
        ['referrer_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_lead_referrer_id', 'lead', ['referrer_id'])
    op.create_index('ix_lead_validity_status', 'lead', ['validity_status'])


def downgrade() -> None:
    # Drop lead columns
    op.drop_index('ix_lead_validity_status', table_name='lead')
    op.drop_index('ix_lead_referrer_id', table_name='lead')
    op.drop_constraint('fk_lead_referrer_id', 'lead', type_='foreignkey')
    op.drop_column('lead', 'created_via')
    op.drop_column('lead', 'validity_status')
    op.drop_column('lead', 'referrer_id')

    # Drop lead_claim table
    op.drop_index('ix_lead_claim_status', table_name='lead_claim')
    op.drop_index('ix_lead_claim_lead_id', table_name='lead_claim')
    op.drop_index('ix_lead_claim_collaborator_id', table_name='lead_claim')
    op.drop_index('ix_lead_claim_id', table_name='lead_claim')
    op.drop_table('lead_claim')

    # Drop collaborator table
    op.drop_index('ix_collaborator_deleted_at', table_name='collaborator')
    op.drop_index('ix_collaborator_managed_by_officer_id', table_name='collaborator')
    op.drop_index('ix_collaborator_unit_id', table_name='collaborator')
    op.drop_index('ix_collaborator_user_id', table_name='collaborator')
    op.drop_index('ix_collaborator_status', table_name='collaborator')
    op.drop_index('ix_collaborator_phone', table_name='collaborator')
    op.drop_index('ix_collaborator_email', table_name='collaborator')
    op.drop_index('ix_collaborator_code', table_name='collaborator')
    op.drop_index('ix_collaborator_id', table_name='collaborator')
    op.drop_table('collaborator')
