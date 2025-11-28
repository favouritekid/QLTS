"""add collaborator and commission models

Revision ID: w8x9y0z1a2b3
Revises: z3a4b5c6d7e8
Create Date: 2025-11-28 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'w8x9y0z1a2b3'
down_revision = 'z3a4b5c6d7e8'
branch_labels = None
depends_on = None


def upgrade():
    # Tạo bảng collaborators
    op.create_table(
        'collaborators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('full_name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('phone2', sa.String(length=20), nullable=True),
        sa.Column('id_number', sa.String(length=20), nullable=True),
        sa.Column('tax_code', sa.String(length=20), nullable=True),
        sa.Column('bank_account', sa.String(length=50), nullable=True),
        sa.Column('bank_name', sa.String(length=100), nullable=True),
        sa.Column('bank_branch', sa.String(length=100), nullable=True),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('district', sa.String(length=100), nullable=True),
        sa.Column('collaborator_type', sa.String(length=50), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('total_leads', sa.Integer(), nullable=True),
        sa.Column('successful_leads', sa.Integer(), nullable=True),
        sa.Column('total_commission_earned', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('pending_commission', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column('metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_collaborators_code'), 'collaborators', ['code'], unique=True)
    op.create_index(op.f('ix_collaborators_email'), 'collaborators', ['email'], unique=True)
    op.create_index(op.f('ix_collaborators_id'), 'collaborators', ['id'], unique=False)

    # Tạo bảng commission_policies
    op.create_table(
        'commission_policies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('calculation_type', sa.Enum('PERCENTAGE', 'FIXED_AMOUNT', name='calculationtype'), nullable=True),
        sa.Column('percentage_value', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('fixed_amount', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('applicable_scope', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('collaborator_categories', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('minimum_tuition', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('effective_start_date', sa.DateTime(), nullable=False),
        sa.Column('effective_end_date', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_commission_policies_code'), 'commission_policies', ['code'], unique=True)
    op.create_index(op.f('ix_commission_policies_id'), 'commission_policies', ['id'], unique=False)

    # Tạo bảng commissions
    op.create_table(
        'commissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('collaborator_id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('application_id', sa.Integer(), nullable=True),
        sa.Column('policy_id', sa.Integer(), nullable=True),
        sa.Column('commission_type', sa.Enum('ENROLLMENT', 'REFERRAL', 'BONUS', name='commissiontype'), nullable=True),
        sa.Column('base_amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('commission_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('commission_amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('status', sa.Enum('PENDING', 'APPROVED', 'PAID', 'REJECTED', 'CANCELLED', name='commissionstatus'), nullable=True),
        sa.Column('earned_at', sa.DateTime(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('paid_by_user_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column('rejection_reason', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['application_id'], ['applications.id'], ),
        sa.ForeignKeyConstraint(['approved_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['collaborator_id'], ['collaborators.id'], ),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ),
        sa.ForeignKeyConstraint(['paid_by_user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['policy_id'], ['commission_policies.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_commissions_code'), 'commissions', ['code'], unique=True)
    op.create_index(op.f('ix_commissions_collaborator_id'), 'commissions', ['collaborator_id'], unique=False)
    op.create_index(op.f('ix_commissions_id'), 'commissions', ['id'], unique=False)
    op.create_index(op.f('ix_commissions_lead_id'), 'commissions', ['lead_id'], unique=False)
    op.create_index(op.f('ix_commissions_status'), 'commissions', ['status'], unique=False)

    # Thêm cột referrer_id và referrer_code vào bảng leads
    op.add_column('leads', sa.Column('referrer_id', sa.Integer(), nullable=True))
    op.add_column('leads', sa.Column('referrer_code', sa.String(length=50), nullable=True))
    op.create_index(op.f('ix_leads_referrer_id'), 'leads', ['referrer_id'], unique=False)
    op.create_index(op.f('ix_leads_referrer_code'), 'leads', ['referrer_code'], unique=False)
    op.create_foreign_key('fk_leads_referrer_id', 'leads', 'collaborators', ['referrer_id'], ['id'])


def downgrade():
    # Xóa foreign key và indexes từ leads
    op.drop_constraint('fk_leads_referrer_id', 'leads', type_='foreignkey')
    op.drop_index(op.f('ix_leads_referrer_code'), table_name='leads')
    op.drop_index(op.f('ix_leads_referrer_id'), table_name='leads')
    op.drop_column('leads', 'referrer_code')
    op.drop_column('leads', 'referrer_id')

    # Xóa bảng commissions
    op.drop_index(op.f('ix_commissions_status'), table_name='commissions')
    op.drop_index(op.f('ix_commissions_lead_id'), table_name='commissions')
    op.drop_index(op.f('ix_commissions_id'), table_name='commissions')
    op.drop_index(op.f('ix_commissions_collaborator_id'), table_name='commissions')
    op.drop_index(op.f('ix_commissions_code'), table_name='commissions')
    op.drop_table('commissions')

    # Xóa bảng commission_policies
    op.drop_index(op.f('ix_commission_policies_id'), table_name='commission_policies')
    op.drop_index(op.f('ix_commission_policies_code'), table_name='commission_policies')
    op.drop_table('commission_policies')

    # Xóa bảng collaborators
    op.drop_index(op.f('ix_collaborators_id'), table_name='collaborators')
    op.drop_index(op.f('ix_collaborators_email'), table_name='collaborators')
    op.drop_index(op.f('ix_collaborators_code'), table_name='collaborators')
    op.drop_table('collaborators')

    # Xóa enums
    sa.Enum(name='commissionstatus').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='commissiontype').drop(op.get_bind(), checkfirst=False)
    sa.Enum(name='calculationtype').drop(op.get_bind(), checkfirst=False)
