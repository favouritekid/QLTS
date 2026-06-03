"""P0 hotfix — relax `applied_rules` immutability for document re-resolution.

## Why

The trigger function ``prevent_applied_rules_update`` (current body from
``phase0br01``) only whitelists the 5 fee-payment keys. Every other key
change on ``admission_profile.applied_rules`` post-create is rejected.

But ``_reresolve_documents_snapshot`` (``admission_service.py:3947-3950``)
**overwrites** two keys via an UPDATE whenever the document set changes —
which happens the moment an officer sets/changes
``cultural_education_level`` / ``vocational_qualification`` on a draft
profile (``admission_service.py:4282-4283``)::

    applied["mandatory_docs"] = new_mandatory   # changed -> trigger RAISE
    applied["doc_configs"]    = new_doc_configs # changed -> trigger RAISE

So the very act of choosing the candidate's education level (the field
that decides the document set) raises::

    applied_rules: key mandatory_docs is immutable after creation;
    only fee payment keys may change

The test suite never caught this: the test DB is built with
``Base.metadata.create_all`` (no trigger — memory ``test-db-schema-source``)
and prod currently has 0 profiles, so the re-resolve path has never fired
against the live trigger. Verified on dev (qlts_dev, trigger enabled) via
BEGIN/ROLLBACK: UPDATE mandatory_docs -> RAISE; UPDATE doc_configs ->
RAISE; UPDATE fee_status -> OK.

## Fix

Add ``mandatory_docs`` and ``doc_configs`` to the whitelist. These are the
ONLY two keys ``_reresolve_documents_snapshot`` writes (it MERGEs per-key,
keeping ``schema_version`` / ``allow_unverified_submission`` /
``admission_path_id`` / scoring untouched — see the docstring at
``admission_service.py:3893-3896``). Everything else stays immutable, so
the anti-tamper intent is preserved: scoring, fee toggle, audience,
path id, etc. still cannot be silently rewritten after create.

The per-key classifier, the deletion guard (whitelisted keys may be
added/updated but not deleted), and the wipe-entire-object guard are kept
from ``phase0br01`` — only the ``allowed_keys`` ARRAY grows by 2.
``_reresolve_documents_snapshot`` always assigns both keys (never
deletes), so the deletion guard does not impede it.

Trigger name ``enforce_applied_rules_immutability`` is unchanged — only
the function body is replaced.

## Downgrade

Restores the ``phase0br01`` behaviour (5 fee keys only), so a revert
reproduces the pre-hotfix behaviour exactly.

Revision ID: ardockeys01
Revises: docdl_audit_001
Create Date: 2026-06-03
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ardockeys01"
down_revision: Union[str, None] = "docdl_audit_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Stable whitelist — referenced by both the upgrade SQL and the lock-in
# tests. 5 fee keys (from phase0br01) + 2 document-resolution keys.
ALLOWED_KEYS: tuple[str, ...] = (
    "fee_status",
    "fee_paid_at",
    "fee_payment_data",
    "fee_calculated_at",
    "fee_invoice_id",
    "mandatory_docs",
    "doc_configs",
)


def upgrade() -> None:
    op.execute(
        """
CREATE OR REPLACE FUNCTION prevent_applied_rules_update()
RETURNS TRIGGER AS $$
DECLARE
    -- 5 fee-payment keys (phase0br01) + 2 document-resolution keys
    -- (mandatory_docs, doc_configs) written by re-resolve when the
    -- candidate's education level changes. Deletion still rejected.
    allowed_keys TEXT[] := ARRAY[
        'fee_status',
        'fee_paid_at',
        'fee_payment_data',
        'fee_calculated_at',
        'fee_invoice_id',
        'mandatory_docs',
        'doc_configs'
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

        -- Fast path: identical JSONB -> no change at all.
        IF OLD.applied_rules IS NOT DISTINCT FROM NEW.applied_rules THEN
            RETURN NEW;
        END IF;

        -- NEW NULL but OLD wasn't -> wholesale wipe.
        IF NEW.applied_rules IS NULL THEN
            RAISE EXCEPTION
                'applied_rules is immutable; cannot wipe entire object';
        END IF;

        -- Walk every key in OLD union NEW.
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
                -- Non-whitelisted key changed -> reject.
                IF NOT (v_key = ANY(allowed_keys)) THEN
                    RAISE EXCEPTION
                        'applied_rules: key % is immutable after '
                        'creation; only fee payment and '
                        'document-resolution keys may change',
                        v_key;
                END IF;
                -- Whitelisted key, but is this a deletion?
                IF v_old_has AND NOT v_new_has THEN
                    RAISE EXCEPTION
                        'applied_rules: deletion of key % is not '
                        'allowed; only add/update permitted',
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
    """Restore the phase0br01 behaviour (5 fee keys only)."""
    op.execute(
        """
CREATE OR REPLACE FUNCTION prevent_applied_rules_update()
RETURNS TRIGGER AS $$
DECLARE
    -- Whitelist of keys that MAY be added or updated post-create.
    -- Deletion is rejected even for whitelisted keys.
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

        -- Fast path: identical JSONB -> no change at all.
        IF OLD.applied_rules IS NOT DISTINCT FROM NEW.applied_rules THEN
            RETURN NEW;
        END IF;

        -- NEW NULL but OLD wasn't -> wholesale wipe.
        IF NEW.applied_rules IS NULL THEN
            RAISE EXCEPTION
                'applied_rules is immutable; cannot wipe entire object';
        END IF;

        -- Walk every key in OLD union NEW.
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
                -- Non-whitelisted key changed -> reject.
                IF NOT (v_key = ANY(allowed_keys)) THEN
                    RAISE EXCEPTION
                        'applied_rules: key % is immutable after '
                        'creation; only fee payment keys may change',
                        v_key;
                END IF;
                -- Whitelisted key, but is this a deletion?
                IF v_old_has AND NOT v_new_has THEN
                    RAISE EXCEPTION
                        'applied_rules: deletion of key % is not '
                        'allowed; only add/update permitted',
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
