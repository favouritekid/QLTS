"""Phase 0b — relax `applied_rules` immutability for the 5 fee-payment keys.

The trigger function ``prevent_applied_rules_update`` shipped in
``b5c6d7e8f9a0`` rejects every change to ``admission_profile.applied_rules``
after creation. Production code at ``admission_service.py:5904-5906``
needs to flip three keys post-create when an application fee is paid:

* ``fee_status``      ("pending" / "exempt" → "paid" / "waived")
* ``fee_paid_at``     (ISO timestamp, set when the payment is recorded)
* ``fee_payment_data`` (JSONB blob from the gateway response)

Existing test ``tests/services/test_admission_application_fee.py:340-341``
asserts both ``fee_status == "paid"`` and ``fee_paid_at is not None`` on
the updated profile, which today only passes because the trigger has not
yet been re-applied in test fixtures. As soon as Phase 1 ships, the trigger
is in force on prod and the fee endpoint breaks.

This migration replaces the trigger function with a key-level classifier:

* INSERT — always allow.
* UPDATE with ``OLD.applied_rules`` NULL — always allow (legacy snapshot).
* UPDATE with ``OLD.applied_rules`` not DISTINCT from NEW — no-op, allow.
* UPDATE otherwise — walk every key in ``OLD ∪ NEW``; if a key changed
  AND it is not in the whitelist, RAISE; if a key is in the whitelist
  but the change is a deletion (key in OLD, gone in NEW), RAISE.

That last rule is intentional. PLAN says "thêm/update", not delete; the
strip-and-compare implementation in PLAN line 2543-2552 has a blind spot
(stripping allowed keys hides deletions too). This migration uses
per-key classification so deletions of allowed keys are also rejected,
matching the stated intent.

Whitelist (verified-from-code 2026-05-02):

* ``fee_status``      — `admission_service.py:2745` init at create,
                        `5904` flip to "paid" at record_payment.
* ``fee_paid_at``     — `admission_service.py:5905`.
* ``fee_payment_data`` — `admission_service.py:5906`.
* ``fee_calculated_at`` — reserved for the future fee-calc flow (PLAN §0b).
* ``fee_invoice_id``   — reserved for the future invoice link.

Trigger name ``enforce_applied_rules_immutability`` is unchanged — only
the function body is replaced.

Downgrade restores the v1 strict body from
``alembic/versions/b5c6d7e8f9a0_add_applied_rules_immutability_trigger.py``
literal-for-literal.

Revision ID: phase0br01
Revises: phase0sg01
Create Date: 2026-05-02
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "phase0br01"
down_revision: Union[str, None] = "phase0sg01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Stable whitelist — referenced by both upgrade SQL and the lock-in tests.
ALLOWED_KEYS: tuple[str, ...] = (
    "fee_status",
    "fee_paid_at",
    "fee_payment_data",
    "fee_calculated_at",
    "fee_invoice_id",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_applied_rules_update()
        RETURNS TRIGGER AS $$
        DECLARE
            -- Whitelist of keys that MAY be added or updated post-create.
            -- Deletion is rejected even for whitelisted keys (PLAN says
            -- "thêm/update", not delete).
            allowed_keys TEXT[] := ARRAY[
                'fee_status',
                'fee_paid_at',
                'fee_payment_data',
                'fee_calculated_at',
                'fee_invoice_id'
            ];
            v_key TEXT;
            v_all_keys TEXT[];
            v_old_value JSONB;
            v_new_value JSONB;
            v_old_has BOOLEAN;
            v_new_has BOOLEAN;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;

            IF TG_OP = 'UPDATE' THEN
                -- Legacy snapshots without applied_rules: nothing to guard.
                IF OLD.applied_rules IS NULL THEN
                    RETURN NEW;
                END IF;

                -- Fast path: identical JSONB → no change at all.
                IF OLD.applied_rules IS NOT DISTINCT FROM NEW.applied_rules THEN
                    RETURN NEW;
                END IF;

                -- NEW is NULL but OLD wasn't → wholesale wipe of applied_rules.
                IF NEW.applied_rules IS NULL THEN
                    RAISE EXCEPTION
                        'applied_rules is immutable; cannot wipe entire object';
                END IF;

                -- Walk every key in OLD ∪ NEW.
                SELECT ARRAY(
                    SELECT DISTINCT k FROM (
                        SELECT jsonb_object_keys(OLD.applied_rules) AS k
                        UNION
                        SELECT jsonb_object_keys(NEW.applied_rules) AS k
                    ) sub
                ) INTO v_all_keys;

                FOREACH v_key IN ARRAY v_all_keys LOOP
                    v_old_has := OLD.applied_rules ? v_key;
                    v_new_has := NEW.applied_rules ? v_key;
                    v_old_value := OLD.applied_rules -> v_key;
                    v_new_value := NEW.applied_rules -> v_key;

                    -- Did this key actually change?
                    IF v_old_value IS DISTINCT FROM v_new_value
                       OR v_old_has <> v_new_has THEN
                        -- Non-whitelisted key changed → reject.
                        IF NOT (v_key = ANY(allowed_keys)) THEN
                            RAISE EXCEPTION
                                'applied_rules: key % is immutable after creation; only fee payment keys may change',
                                v_key;
                        END IF;
                        -- Whitelisted key, but is this a deletion?
                        IF v_old_has AND NOT v_new_has THEN
                            RAISE EXCEPTION
                                'applied_rules: deletion of key % is not allowed; only add/update permitted',
                                v_key;
                        END IF;
                    END IF;
                END LOOP;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    """Restore the v1 strict function from `b5c6d7e8f9a0`."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_applied_rules_update()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Allow insertion (NEW.applied_rules can be set)
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;

            -- On UPDATE: prevent applied_rules modification
            IF TG_OP = 'UPDATE' THEN
                -- Check if applied_rules changed
                IF OLD.applied_rules IS NOT NULL AND NEW.applied_rules IS DISTINCT FROM OLD.applied_rules THEN
                    RAISE EXCEPTION 'applied_rules is immutable after creation and cannot be modified';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
