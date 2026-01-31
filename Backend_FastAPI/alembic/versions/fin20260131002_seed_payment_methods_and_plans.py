# alembic/versions/fin20260131002_seed_payment_methods_and_plans.py
"""Seed payment methods and installment plans.

Revision ID: fin20260131002
Revises: fin20260131001
Create Date: 2026-01-31 12:00:00.000000

This migration seeds the initial payment methods and installment plans
required for the Finance Module to function.

Payment Methods:
- bank_transfer: Chuyển khoản ngân hàng (offline, requires verification)
- cash: Tiền mặt (offline, requires verification)
- vnpay: VNPay (online, auto-verified via gateway)

Installment Plans:
- FULL: Thanh toán 1 lần (100%)
- TWO_TERM: Thanh toán 2 đợt (50% + 50%)
- QUARTERLY: Thanh toán theo quý (25% x 4)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'fin20260131002'
down_revision = 'fin20260131001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Seed payment methods and installment plans."""

    # ===== Payment Methods =====
    # Reference: FINANCE_MODULE_DESIGN.md Section 3.2.5
    op.execute("""
        INSERT INTO payment_method (code, name, is_online, requires_verification, gateway_code, display_order, is_active)
        VALUES
            ('bank_transfer', 'Chuyển khoản ngân hàng', FALSE, TRUE, NULL, 1, TRUE),
            ('cash', 'Tiền mặt', FALSE, TRUE, NULL, 2, TRUE),
            ('vnpay', 'VNPay', TRUE, FALSE, 'vnpay', 3, TRUE)
        ON CONFLICT (code) DO NOTHING;
    """)

    # ===== Installment Plans =====
    # Reference: FINANCE_MODULE_DESIGN.md Section 3.2.2
    # Schedule format: JSON array of {installment_no, percent, due_days_offset}

    # Plan 1: Full payment (1 installment, 100%)
    op.execute("""
        INSERT INTO installment_plan (code, name, installment_count, schedule, penalty_rate, is_active)
        VALUES (
            'FULL',
            'Thanh toán 1 lần',
            1,
            '[{"installment_no": 1, "percent": 100, "due_days_offset": 0}]'::jsonb,
            0,
            TRUE
        )
        ON CONFLICT (code) DO NOTHING;
    """)

    # Plan 2: Two-term payment (2 installments, 50% each)
    op.execute("""
        INSERT INTO installment_plan (code, name, installment_count, schedule, penalty_rate, is_active)
        VALUES (
            'TWO_TERM',
            'Thanh toán 2 đợt',
            2,
            '[{"installment_no": 1, "percent": 50, "due_days_offset": 0}, {"installment_no": 2, "percent": 50, "due_days_offset": 90}]'::jsonb,
            0.5,
            TRUE
        )
        ON CONFLICT (code) DO NOTHING;
    """)

    # Plan 3: Quarterly payment (4 installments, 25% each)
    op.execute("""
        INSERT INTO installment_plan (code, name, installment_count, schedule, penalty_rate, is_active)
        VALUES (
            'QUARTERLY',
            'Thanh toán theo quý',
            4,
            '[{"installment_no": 1, "percent": 25, "due_days_offset": 0}, {"installment_no": 2, "percent": 25, "due_days_offset": 90}, {"installment_no": 3, "percent": 25, "due_days_offset": 180}, {"installment_no": 4, "percent": 25, "due_days_offset": 270}]'::jsonb,
            0.5,
            TRUE
        )
        ON CONFLICT (code) DO NOTHING;
    """)


def downgrade() -> None:
    """Remove seeded data.

    WARNING: This will delete all payment methods and installment plans,
    including any that were added after the initial seed.
    Only run this in development/testing environments.
    """
    # Delete in reverse order to avoid FK violations
    # Note: If there are fees/invoices using these, the delete will fail
    # due to RESTRICT foreign key constraints (which is the desired behavior)

    op.execute("""
        DELETE FROM installment_plan WHERE code IN ('FULL', 'TWO_TERM', 'QUARTERLY');
    """)

    op.execute("""
        DELETE FROM payment_method WHERE code IN ('bank_transfer', 'cash', 'vnpay');
    """)
