# alembic/versions/fin20260131003_migrate_application_fees.py
"""Migrate application fees from JSONB to fee table.

Revision ID: fin20260131003
Revises: fin20260131002
Create Date: 2026-01-31 13:00:00.000000

Phase 0: Application Fee Migration

This migration backfills existing application fee data from
AdmissionProfile.applied_rules JSON to the new fee table structure.

Source data structure (in applied_rules JSONB):
{
    "application_fee": 100000,
    "requires_application_fee": true,
    "fee_status": "pending|paid|exempt",
    "fee_paid_at": "2026-01-30T10:00:00Z",
    "fee_payment_data": {"transaction_id": "...", "amount": 100000}
}

Target structure:
- fee (application type)
- invoice (single installment)
- payment (if paid)

IMPORTANT: This migration is idempotent - it will skip profiles that
already have application fees in the new table.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fin20260131003'
down_revision = 'fin20260131004'  # Changed: depends on add_notes_to_fee
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Migrate application fees from JSONB to relational tables."""

    # Step 1: Create fees for all profiles with application_fee in applied_rules
    # Skip profiles that already have application fee in new table
    op.execute("""
        INSERT INTO fee (
            admission_profile_id,
            fee_type,
            academic_year,
            base_amount,
            total_discount,
            final_amount,
            paid_amount,
            waived_amount,
            status,
            notes,
            created_at,
            updated_at
        )
        SELECT
            ap.id AS admission_profile_id,
            'application' AS fee_type,
            ap.academic_year,
            COALESCE((ap.applied_rules->>'application_fee')::numeric, 0) AS base_amount,
            0 AS total_discount,
            COALESCE((ap.applied_rules->>'application_fee')::numeric, 0) AS final_amount,
            CASE
                WHEN ap.applied_rules->>'fee_status' = 'paid' THEN
                    COALESCE((ap.applied_rules->>'application_fee')::numeric, 0)
                ELSE 0
            END AS paid_amount,
            CASE
                WHEN ap.applied_rules->>'fee_status' = 'exempt' THEN
                    COALESCE((ap.applied_rules->>'application_fee')::numeric, 0)
                ELSE 0
            END AS waived_amount,
            CASE
                WHEN ap.applied_rules->>'fee_status' = 'paid' THEN 'paid'
                WHEN ap.applied_rules->>'fee_status' = 'exempt' THEN 'paid'
                WHEN ap.applied_rules->>'requires_application_fee' = 'true' THEN 'calculated'
                ELSE 'pending'
            END AS status,
            'Migrated from applied_rules JSONB' AS notes,
            COALESCE(
                (ap.applied_rules->>'fee_paid_at')::timestamp with time zone,
                ap.created_at
            ) AS created_at,
            NOW() AS updated_at
        FROM admission_profile ap
        WHERE ap.applied_rules->>'application_fee' IS NOT NULL
          AND (ap.applied_rules->>'application_fee')::numeric > 0
          AND NOT EXISTS (
              SELECT 1 FROM fee f
              WHERE f.admission_profile_id = ap.id
                AND f.fee_type = 'application'
          );
    """)

    # Step 2: Create invoices for the migrated fees
    op.execute("""
        INSERT INTO invoice (
            fee_id,
            invoice_number,
            installment_no,
            amount,
            paid_amount,
            due_date,
            status,
            issued_at,
            paid_at,
            created_at,
            updated_at
        )
        SELECT
            f.id AS fee_id,
            'MIG-APP-' || LPAD(f.id::text, 8, '0') AS invoice_number,
            1 AS installment_no,
            f.final_amount AS amount,
            f.paid_amount AS paid_amount,
            COALESCE(
                (ap.applied_rules->>'fee_paid_at')::date,
                ap.created_at::date
            ) AS due_date,
            CASE
                WHEN f.status = 'paid' THEN 'paid'
                ELSE 'issued'
            END AS status,
            ap.created_at AS issued_at,
            CASE
                WHEN f.status = 'paid' THEN
                    (ap.applied_rules->>'fee_paid_at')::timestamp with time zone
                ELSE NULL
            END AS paid_at,
            ap.created_at AS created_at,
            NOW() AS updated_at
        FROM fee f
        JOIN admission_profile ap ON ap.id = f.admission_profile_id
        WHERE f.fee_type = 'application'
          AND f.notes = 'Migrated from applied_rules JSONB'
          AND NOT EXISTS (
              SELECT 1 FROM invoice inv
              WHERE inv.fee_id = f.id
          );
    """)

    # Step 3: Create payments for paid fees
    # Note: We use bank_transfer as default method for migrated payments
    # created_by_id is set to 1 (system user) - adjust if needed
    op.execute("""
        INSERT INTO payment (
            invoice_id,
            method_id,
            amount,
            reference_code,
            status,
            payment_date,
            verified_at,
            created_by_id,
            verified_by_id,
            notes,
            created_at,
            updated_at
        )
        SELECT
            inv.id AS invoice_id,
            (SELECT id FROM payment_method WHERE code = 'bank_transfer' LIMIT 1) AS method_id,
            COALESCE(
                (ap.applied_rules->'fee_payment_data'->>'amount')::numeric,
                f.paid_amount
            ) AS amount,
            ap.applied_rules->'fee_payment_data'->>'transaction_id' AS reference_code,
            'verified' AS status,
            (ap.applied_rules->>'fee_paid_at')::timestamp with time zone AS payment_date,
            (ap.applied_rules->>'fee_paid_at')::timestamp with time zone AS verified_at,
            COALESCE(
                (SELECT id FROM "user" WHERE role = 'admin' LIMIT 1),
                1
            ) AS created_by_id,
            COALESCE(
                (SELECT id FROM "user" WHERE role = 'admin' LIMIT 1),
                1
            ) AS verified_by_id,
            'Migrated from applied_rules JSONB' AS notes,
            (ap.applied_rules->>'fee_paid_at')::timestamp with time zone AS created_at,
            NOW() AS updated_at
        FROM fee f
        JOIN admission_profile ap ON ap.id = f.admission_profile_id
        JOIN invoice inv ON inv.fee_id = f.id
        WHERE f.fee_type = 'application'
          AND f.status = 'paid'
          AND f.paid_amount > 0
          AND f.notes = 'Migrated from applied_rules JSONB'
          AND NOT EXISTS (
              SELECT 1 FROM payment p
              WHERE p.invoice_id = inv.id
          );
    """)

    # Step 4: Create payment transactions for audit trail
    op.execute("""
        INSERT INTO payment_transaction (
            payment_id,
            fee_id,
            transaction_type,
            amount,
            balance_before,
            balance_after,
            notes,
            created_at
        )
        SELECT
            p.id AS payment_id,
            f.id AS fee_id,
            'payment' AS transaction_type,
            p.amount AS amount,
            f.final_amount AS balance_before,
            f.final_amount - p.amount AS balance_after,
            'Initial payment (migrated from JSONB)' AS notes,
            p.created_at AS created_at
        FROM payment p
        JOIN invoice inv ON inv.id = p.invoice_id
        JOIN fee f ON f.id = inv.fee_id
        WHERE f.fee_type = 'application'
          AND f.notes = 'Migrated from applied_rules JSONB'
          AND NOT EXISTS (
              SELECT 1 FROM payment_transaction pt
              WHERE pt.payment_id = p.id
          );
    """)

    # Step 5: Log migration summary
    op.execute("""
        DO $$
        DECLARE
            fee_count INTEGER;
            invoice_count INTEGER;
            payment_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO fee_count
            FROM fee WHERE notes = 'Migrated from applied_rules JSONB';

            SELECT COUNT(*) INTO invoice_count
            FROM invoice inv
            JOIN fee f ON f.id = inv.fee_id
            WHERE f.notes = 'Migrated from applied_rules JSONB';

            SELECT COUNT(*) INTO payment_count
            FROM payment p
            JOIN invoice inv ON inv.id = p.invoice_id
            JOIN fee f ON f.id = inv.fee_id
            WHERE f.notes = 'Migrated from applied_rules JSONB';

            RAISE NOTICE 'Migration Summary: % fees, % invoices, % payments created',
                fee_count, invoice_count, payment_count;
        END $$;
    """)


def downgrade() -> None:
    """Remove migrated data.

    WARNING: This will delete all fees, invoices, and payments that were
    created by the migration. The original data in applied_rules JSONB
    remains intact.
    """
    # Delete in reverse order to respect foreign keys
    op.execute("""
        DELETE FROM payment_transaction pt
        WHERE pt.fee_id IN (
            SELECT f.id FROM fee f
            WHERE f.notes = 'Migrated from applied_rules JSONB'
        );
    """)

    op.execute("""
        DELETE FROM payment p
        WHERE p.invoice_id IN (
            SELECT inv.id FROM invoice inv
            JOIN fee f ON f.id = inv.fee_id
            WHERE f.notes = 'Migrated from applied_rules JSONB'
        );
    """)

    op.execute("""
        DELETE FROM invoice inv
        WHERE inv.fee_id IN (
            SELECT f.id FROM fee f
            WHERE f.notes = 'Migrated from applied_rules JSONB'
        );
    """)

    op.execute("""
        DELETE FROM fee
        WHERE notes = 'Migrated from applied_rules JSONB';
    """)
