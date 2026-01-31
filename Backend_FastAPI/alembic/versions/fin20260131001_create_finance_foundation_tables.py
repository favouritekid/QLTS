"""create finance foundation tables

Revision ID: fin20260131001
Revises: fee20260130001
Create Date: 2026-01-31

Creates 12 tables for Finance Module Phase 1:
1. installment_plan - Payment schedule configurations
2. payment_method - Payment method definitions
3. accounting_period - Ledger period tracking
4. processed_event - Idempotency tracking
5. fee - Main fee record
6. fee_applied_discount - Discount snapshots
7. invoice - Invoice records
8. payment_intent - Online payment tracking
9. payment - Confirmed payments
10. payment_transaction - Audit trail
11. refund_request - Refund requests
12. overpayment_record - Overpayment liability

Security constraints from FINANCE_MODULE_DESIGN.md Section 3.9:
- amount > 0 for payments
- no self-approval (created_by_id != verified_by_id)
- fee amounts >= 0
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'fin20260131001'
down_revision: Union[str, None] = 'fee20260130001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # =========================================================================
    # 1. INSTALLMENT_PLAN - Payment schedule configurations (standalone)
    # =========================================================================
    op.create_table(
        'installment_plan',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(50), nullable=False, unique=True,
                  comment='Unique plan code (e.g., FULL, TWO_TERM, QUARTERLY)'),
        sa.Column('name', sa.String(200), nullable=False,
                  comment='Display name'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('installment_count', sa.Integer(), nullable=False, server_default='1',
                  comment='Number of installments (1-12)'),
        sa.Column('schedule', JSONB, nullable=False,
                  comment='JSON array of installment schedule [{installment_no, due_days_offset, percent}]'),
        sa.Column('penalty_type', sa.String(20), nullable=False, server_default='percentage',
                  comment='Penalty type: percentage|fixed'),
        sa.Column('penalty_rate', sa.Numeric(5, 2), nullable=False, server_default='0',
                  comment='Penalty rate (% or fixed amount)'),
        sa.Column('grace_period_days', sa.Integer(), nullable=False, server_default='7',
                  comment='Days after due date before penalty applies'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('installment_count >= 1 AND installment_count <= 12',
                          name='chk_installment_plan_count_range'),
        sa.CheckConstraint("penalty_type IN ('percentage', 'fixed')",
                          name='chk_installment_plan_penalty_type'),
    )

    # =========================================================================
    # 2. PAYMENT_METHOD - Payment method definitions (standalone)
    # =========================================================================
    op.create_table(
        'payment_method',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(50), nullable=False, unique=True,
                  comment='Unique method code (e.g., cash, bank_transfer, vnpay)'),
        sa.Column('name', sa.String(100), nullable=False,
                  comment='Display name'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_online', sa.Boolean(), nullable=False, server_default='false',
                  comment='True for online gateways (VNPay, MoMo)'),
        sa.Column('requires_verification', sa.Boolean(), nullable=False, server_default='true',
                  comment='True for manual payments requiring maker-checker'),
        sa.Column('gateway_code', sa.String(50), nullable=True,
                  comment='Gateway identifier for online methods'),
        sa.Column('gateway_config', JSONB, nullable=True,
                  comment='Gateway-specific configuration'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # =========================================================================
    # 3. ACCOUNTING_PERIOD - Ledger period tracking (standalone)
    # =========================================================================
    op.create_table(
        'accounting_period',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('period_month', sa.Integer(), nullable=False,
                  comment='Month (1-12)'),
        sa.Column('period_year', sa.Integer(), nullable=False,
                  comment='Year (e.g., 2026)'),
        sa.Column('is_closed', sa.Boolean(), nullable=False, server_default='false',
                  comment='True if period is closed (no more transactions allowed)'),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_by_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('total_revenue', sa.Numeric(18, 2), nullable=False, server_default='0',
                  comment='Total revenue in this period'),
        sa.Column('total_payments', sa.Numeric(18, 2), nullable=False, server_default='0',
                  comment='Total payments received'),
        sa.Column('total_refunds', sa.Numeric(18, 2), nullable=False, server_default='0',
                  comment='Total refunds issued'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('period_month', 'period_year', name='uq_accounting_period_month_year'),
        sa.CheckConstraint('period_month >= 1 AND period_month <= 12',
                          name='chk_accounting_period_month_range'),
        sa.CheckConstraint('period_year >= 2020 AND period_year <= 2100',
                          name='chk_accounting_period_year_range'),
    )

    # =========================================================================
    # 4. PROCESSED_EVENT - Idempotency tracking (standalone)
    # =========================================================================
    op.create_table(
        'processed_event',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('event_id', sa.String(100), nullable=False,
                  comment='Unique event identifier (e.g., VNPay transaction ID)'),
        sa.Column('event_type', sa.String(50), nullable=False,
                  comment='Event type (e.g., vnpay_callback, momo_callback)'),
        sa.Column('event_version', sa.String(20), nullable=True,
                  comment='Event schema version'),
        sa.Column('consumer_id', sa.String(50), nullable=False,
                  comment='Consumer identifier (e.g., payment_service)'),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('processing_result', sa.String(20), nullable=False,
                  comment='Result: success|failed|skipped'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('event_payload', JSONB, nullable=True,
                  comment='Original event payload for debugging'),
        sa.UniqueConstraint('event_id', 'consumer_id', name='uq_processed_event_id_consumer'),
        sa.CheckConstraint("processing_result IN ('success', 'failed', 'skipped')",
                          name='chk_processed_event_result'),
    )
    op.create_index('ix_processed_event_event_id', 'processed_event', ['event_id'])
    op.create_index('ix_processed_event_event_type', 'processed_event', ['event_type'])

    # =========================================================================
    # 5. FEE - Main fee record (depends on admission_profile, installment_plan, user)
    # =========================================================================
    op.create_table(
        'fee',
        sa.Column('id', sa.Integer(), primary_key=True),
        # Foreign keys
        sa.Column('admission_profile_id', sa.Integer(),
                  sa.ForeignKey('admission_profile.id', ondelete='CASCADE'),
                  nullable=False, index=True,
                  comment='Link to admission profile (IDOR via profile.lead.unit_id)'),
        sa.Column('installment_plan_id', sa.Integer(),
                  sa.ForeignKey('installment_plan.id', ondelete='SET NULL'),
                  nullable=True, index=True,
                  comment='Selected installment plan (NULL = single payment)'),
        # Fee type & year
        sa.Column('fee_type', sa.String(30), nullable=False, server_default='tuition', index=True,
                  comment='Fee type: application|tuition|enrollment|insurance|dormitory|other'),
        sa.Column('academic_year', sa.Integer(), nullable=False, index=True,
                  comment='Academic year (e.g., 2026)'),
        # Amounts
        sa.Column('base_amount', sa.Numeric(15, 2), nullable=False,
                  comment='Original fee amount before discounts (VND)'),
        sa.Column('total_discount', sa.Numeric(15, 2), nullable=False, server_default='0',
                  comment='Total discount amount (VND)'),
        sa.Column('final_amount', sa.Numeric(15, 2), nullable=False,
                  comment='Final amount after discounts (VND)'),
        sa.Column('paid_amount', sa.Numeric(15, 2), nullable=False, server_default='0',
                  comment='Amount already paid (VND)'),
        sa.Column('waived_amount', sa.Numeric(15, 2), nullable=False, server_default='0',
                  comment='Amount waived (VND)'),
        # Status & lifecycle
        sa.Column('status', sa.String(20), nullable=False, server_default='pending', index=True,
                  comment='Status: pending|calculated|invoiced|partial|paid|overdue|waived|cancelled'),
        sa.Column('due_date', sa.Date(), nullable=True, index=True,
                  comment='Overall due date for this fee'),
        sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(),
                  comment='When fee was calculated'),
        sa.Column('last_payment_at', sa.DateTime(timezone=True), nullable=True,
                  comment='Timestamp of last payment'),
        # Audit
        sa.Column('calculated_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=True, index=True,
                  comment='User who calculated/created this fee'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1',
                  comment='Optimistic locking version'),
        sa.Column('notes', sa.Text(), nullable=True,
                  comment='Notes for waive/cancel/audit trail'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Constraints
        sa.UniqueConstraint('admission_profile_id', 'fee_type', 'academic_year',
                          name='uq_fee_profile_type_year'),
        sa.CheckConstraint(
            'base_amount >= 0 AND total_discount >= 0 AND final_amount >= 0 '
            'AND paid_amount >= 0 AND waived_amount >= 0',
            name='chk_fee_amounts_non_negative'),
        sa.CheckConstraint('total_discount <= base_amount',
                          name='chk_fee_discount_not_exceed_base'),
        sa.CheckConstraint(
            "fee_type IN ('application', 'tuition', 'enrollment', 'insurance', 'dormitory', 'other')",
            name='chk_fee_type_valid'),
        sa.CheckConstraint(
            "status IN ('pending', 'calculated', 'invoiced', 'partial', 'paid', 'overdue', 'waived', 'cancelled')",
            name='chk_fee_status_valid'),
    )

    # =========================================================================
    # 6. FEE_APPLIED_DISCOUNT - Discount snapshots (depends on fee, tuition_discount_policy)
    # =========================================================================
    op.create_table(
        'fee_applied_discount',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('fee_id', sa.Integer(),
                  sa.ForeignKey('fee.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('policy_id', sa.Integer(),
                  sa.ForeignKey('tuition_discount_policy.id', ondelete='SET NULL'),
                  nullable=True, index=True,
                  comment='Reference to discount policy (NULL if policy deleted)'),
        sa.Column('discount_amount', sa.Numeric(15, 2), nullable=False,
                  comment='Actual discount amount applied (VND)'),
        sa.Column('discount_percent', sa.Numeric(5, 2), nullable=True,
                  comment='Discount percentage at time of application'),
        sa.Column('calculation_snapshot', JSONB, nullable=True,
                  comment='Snapshot of calculation details for audit'),
        sa.Column('application_order', sa.Integer(), nullable=False, server_default='1',
                  comment='Order in which discount was applied (for stacking)'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('fee_id', 'policy_id', name='uq_fee_applied_discount_fee_policy'),
        sa.CheckConstraint('discount_amount >= 0', name='chk_fee_applied_discount_amount_non_negative'),
    )

    # =========================================================================
    # 7. INVOICE - Invoice records (depends on fee, user)
    # =========================================================================
    op.create_table(
        'invoice',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('fee_id', sa.Integer(),
                  sa.ForeignKey('fee.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('invoice_number', sa.String(30), nullable=False, unique=True,
                  comment='Unique invoice number (e.g., INV-2026-000001)'),
        sa.Column('installment_no', sa.Integer(), nullable=False, server_default='1',
                  comment='Installment number (1 for single payment)'),
        sa.Column('amount', sa.Numeric(15, 2), nullable=False,
                  comment='Invoice amount (VND)'),
        sa.Column('paid_amount', sa.Numeric(15, 2), nullable=False, server_default='0',
                  comment='Amount paid on this invoice'),
        sa.Column('penalty_amount', sa.Numeric(15, 2), nullable=False, server_default='0',
                  comment='Late payment penalty'),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft', index=True,
                  comment='Status: draft|issued|partial|paid|cancelled|overdue'),
        sa.Column('issued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('due_date', sa.Date(), nullable=False, index=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('cancelled_reason', sa.Text(), nullable=True),
        sa.Column('issued_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('cancelled_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('fee_id', 'installment_no', name='uq_invoice_fee_installment'),
        sa.CheckConstraint('amount > 0', name='chk_invoice_amount_positive'),
        sa.CheckConstraint('paid_amount >= 0', name='chk_invoice_paid_amount_non_negative'),
        sa.CheckConstraint('penalty_amount >= 0', name='chk_invoice_penalty_non_negative'),
        sa.CheckConstraint(
            "status IN ('draft', 'issued', 'partial', 'paid', 'cancelled', 'overdue')",
            name='chk_invoice_status_valid'),
    )

    # =========================================================================
    # 8. PAYMENT_INTENT - Online payment tracking (depends on invoice, payment_method)
    # =========================================================================
    op.create_table(
        'payment_intent',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('invoice_id', sa.Integer(),
                  sa.ForeignKey('invoice.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('method_id', sa.Integer(),
                  sa.ForeignKey('payment_method.id', ondelete='RESTRICT'),
                  nullable=False, index=True),
        sa.Column('amount', sa.Numeric(15, 2), nullable=False,
                  comment='Payment amount (VND)'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='VND'),
        sa.Column('gateway_ref', sa.String(100), nullable=True, unique=True,
                  comment='Gateway transaction reference'),
        sa.Column('gateway_status', sa.String(20), nullable=True,
                  comment='Status from gateway: created|pending|success|failed|expired'),
        sa.Column('gateway_response', JSONB, nullable=True,
                  comment='Full gateway response for debugging'),
        sa.Column('idempotency_key', sa.String(100), nullable=False,
                  comment='Client-provided idempotency key'),
        sa.Column('status', sa.String(20), nullable=False, server_default='created', index=True,
                  comment='Intent status: created|pending|completed|failed|expired|cancelled'),
        sa.Column('pay_url', sa.Text(), nullable=True,
                  comment='Gateway payment URL'),
        sa.Column('return_url', sa.Text(), nullable=True,
                  comment='Client return URL after payment'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False,
                  comment='Intent expiration time'),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('callback_received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('callback_data', JSONB, nullable=True,
                  comment='Callback payload from gateway'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('idempotency_key', 'invoice_id', name='uq_payment_intent_idempotency_invoice'),
        sa.CheckConstraint('amount > 0', name='chk_payment_intent_amount_positive'),
        sa.CheckConstraint(
            "status IN ('created', 'pending', 'completed', 'failed', 'expired', 'cancelled')",
            name='chk_payment_intent_status_valid'),
    )

    # =========================================================================
    # 9. PAYMENT - Confirmed payments (depends on invoice, payment_method, payment_intent, user)
    # =========================================================================
    op.create_table(
        'payment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('invoice_id', sa.Integer(),
                  sa.ForeignKey('invoice.id', ondelete='RESTRICT'),
                  nullable=False, index=True),
        sa.Column('method_id', sa.Integer(),
                  sa.ForeignKey('payment_method.id', ondelete='RESTRICT'),
                  nullable=False, index=True),
        sa.Column('intent_id', sa.Integer(),
                  sa.ForeignKey('payment_intent.id', ondelete='SET NULL'),
                  nullable=True, unique=True,
                  comment='Link to payment intent (for online payments)'),
        sa.Column('amount', sa.Numeric(15, 2), nullable=False,
                  comment='Payment amount (VND)'),
        sa.Column('reference_code', sa.String(100), nullable=True,
                  comment='Bank/gateway reference code'),
        sa.Column('payer_name', sa.String(200), nullable=True,
                  comment='Name of payer (for manual payments)'),
        sa.Column('payer_account', sa.String(100), nullable=True,
                  comment='Payer account number'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending', index=True,
                  comment='Status: pending|verified|rejected|refunded'),
        sa.Column('payment_date', sa.DateTime(timezone=True), nullable=True,
                  comment='Actual payment date'),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        # Maker-Checker: created_by_id MUST be different from verified_by_id
        sa.Column('created_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=False, index=True,
                  comment='User who recorded the payment (maker)'),
        sa.Column('verified_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=True, index=True,
                  comment='User who verified the payment (checker)'),
        sa.Column('rejected_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # CRITICAL: Security constraint - no self-approval
        sa.CheckConstraint(
            'verified_by_id IS NULL OR verified_by_id != created_by_id',
            name='chk_payment_no_self_approval'),
        sa.CheckConstraint('amount > 0', name='chk_payment_amount_positive'),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'rejected', 'refunded')",
            name='chk_payment_status_valid'),
    )

    # =========================================================================
    # 10. PAYMENT_TRANSACTION - Audit trail (depends on payment, fee, accounting_period, user)
    # =========================================================================
    op.create_table(
        'payment_transaction',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('payment_id', sa.Integer(),
                  sa.ForeignKey('payment.id', ondelete='RESTRICT'),
                  nullable=True, index=True,
                  comment='Source payment (NULL for adjustments)'),
        sa.Column('fee_id', sa.Integer(),
                  sa.ForeignKey('fee.id', ondelete='RESTRICT'),
                  nullable=False, index=True),
        sa.Column('period_id', sa.Integer(),
                  sa.ForeignKey('accounting_period.id', ondelete='RESTRICT'),
                  nullable=True, index=True,
                  comment='Accounting period (NULL if period not assigned)'),
        sa.Column('transaction_type', sa.String(20), nullable=False,
                  comment='Type: payment|refund|adjustment|waive|penalty|reversal'),
        sa.Column('amount', sa.Numeric(15, 2), nullable=False,
                  comment='Transaction amount (positive for credits, negative for debits)'),
        sa.Column('balance_before', sa.Numeric(15, 2), nullable=False,
                  comment='Fee balance before this transaction'),
        sa.Column('balance_after', sa.Numeric(15, 2), nullable=False,
                  comment='Fee balance after this transaction'),
        sa.Column('external_reference', sa.String(100), nullable=True,
                  comment='External reference (bank ref, gateway ID)'),
        sa.Column('gateway_response', JSONB, nullable=True,
                  comment='Gateway response snapshot'),
        sa.Column('idempotency_key', sa.String(100), nullable=True, unique=True,
                  comment='Idempotency key for deduplication'),
        sa.Column('performed_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "transaction_type IN ('payment', 'refund', 'adjustment', 'waive', 'penalty', 'reversal')",
            name='chk_payment_transaction_type_valid'),
    )

    # =========================================================================
    # 11. REFUND_REQUEST - Refund requests (depends on payment, user)
    # =========================================================================
    op.create_table(
        'refund_request',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('payment_id', sa.Integer(),
                  sa.ForeignKey('payment.id', ondelete='RESTRICT'),
                  nullable=False, index=True),
        sa.Column('reason', sa.Text(), nullable=False,
                  comment='Reason for refund request'),
        sa.Column('amount', sa.Numeric(15, 2), nullable=False,
                  comment='Refund amount (must be <= payment.amount)'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending', index=True,
                  comment='Status: pending|approved|rejected|refunded'),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('requested_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=False, index=True),
        sa.Column('approved_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('rejected_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('refund_reference', sa.String(100), nullable=True,
                  comment='External refund reference'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('amount > 0', name='chk_refund_request_amount_positive'),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'refunded')",
            name='chk_refund_request_status_valid'),
    )

    # =========================================================================
    # 12. OVERPAYMENT_RECORD - Overpayment liability tracking (v1.2)
    # =========================================================================
    op.create_table(
        'overpayment_record',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('payment_id', sa.Integer(),
                  sa.ForeignKey('payment.id', ondelete='RESTRICT'),
                  nullable=False, index=True,
                  comment='Source payment that caused overpayment'),
        sa.Column('invoice_id', sa.Integer(),
                  sa.ForeignKey('invoice.id', ondelete='RESTRICT'),
                  nullable=False, index=True,
                  comment='Invoice that was overpaid'),
        sa.Column('admission_profile_id', sa.Integer(),
                  sa.ForeignKey('admission_profile.id', ondelete='CASCADE'),
                  nullable=False, index=True,
                  comment='Student profile for tracking'),
        sa.Column('overpayment_amount', sa.Numeric(15, 2), nullable=False,
                  comment='Amount of overpayment (VND)'),
        sa.Column('currency', sa.String(3), nullable=False, server_default='VND'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending', index=True,
                  comment='Status: pending|applied|refunded|cancelled'),
        sa.Column('resolution_type', sa.String(20), nullable=True,
                  comment='How resolved: apply_to_next|refund|write_off'),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_by_id', sa.Integer(),
                  sa.ForeignKey('user.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        # If applied to another invoice
        sa.Column('applied_to_invoice_id', sa.Integer(),
                  sa.ForeignKey('invoice.id', ondelete='SET NULL'),
                  nullable=True,
                  comment='Invoice to which overpayment was applied'),
        sa.Column('applied_amount', sa.Numeric(15, 2), nullable=True,
                  comment='Amount applied to next invoice'),
        # If refunded
        sa.Column('refund_request_id', sa.Integer(),
                  sa.ForeignKey('refund_request.id', ondelete='SET NULL'),
                  nullable=True,
                  comment='Link to refund request if refunded'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('overpayment_amount > 0', name='chk_overpayment_amount_positive'),
        sa.CheckConstraint(
            "status IN ('pending', 'applied', 'refunded', 'cancelled')",
            name='chk_overpayment_status_valid'),
        sa.CheckConstraint(
            "resolution_type IS NULL OR resolution_type IN ('apply_to_next', 'refund', 'write_off')",
            name='chk_overpayment_resolution_type_valid'),
    )


def downgrade() -> None:
    # Drop in reverse order (respect foreign key dependencies)
    op.drop_table('overpayment_record')
    op.drop_table('refund_request')
    op.drop_table('payment_transaction')
    op.drop_table('payment')
    op.drop_table('payment_intent')
    op.drop_table('invoice')
    op.drop_table('fee_applied_discount')
    op.drop_table('fee')
    op.drop_table('processed_event')
    op.drop_table('accounting_period')
    op.drop_table('payment_method')
    op.drop_table('installment_plan')
