"""Contract + classifier tests for the ``appfee_finance_20260607`` migration.

Pattern theo ``test_docgrp_audience_backfill_migration.py`` /
``test_sl20260524_canonical_migration.py``: importlib-load the module, then
assert the revision chain + canonical-helper import parity + the pure
helper/classifier logic + downgrade SQL-body safety.

The *real* DB roundtrip (preflight RAISE on dirty data, clean-gap backfill
chain, parity backfill↔runtime reconcile) is exercised by:
  - the mandated PROD read-only preflight + manual ``alembic upgrade head`` at
    deploy time (plan Verification #4), and
  - the dev-DB ``alembic upgrade head`` the one-off test container's entrypoint
    runs before pytest.

The classifier unit-tests below pin the exact "known-valid vs anomalous"
decision logic that drives ``_preflight``'s BLOCKER set — without a live DB.
The known-valid shapes must classify True; an anomaly (e.g. fee marked paid
but missing its Payment) must classify False under ALL five recognisers, which
is precisely what makes ``_preflight`` append it as an anomalous BLOCKER.
"""
from __future__ import annotations

import importlib.util
import inspect
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.utils.fee_receipt import canonical_receipt_key

pytestmark = pytest.mark.unit

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_MIGRATION_FILE = "appfee_finance_20260607_application_fee_ledger.py"
_EXPECTED = Decimal("100000")


@pytest.fixture
def migration():
    path = _VERSIONS_DIR / _MIGRATION_FILE
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None, f"Cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def module_src(migration):
    return inspect.getsource(migration)


# --------------------------------------------------------------------------- #
# Row-dict builders mirroring the SELECT shapes the classifiers consume
# --------------------------------------------------------------------------- #
def _fee(**over):
    base = {
        "id": 7,
        "status": "paid",
        "base_amount": Decimal("100000"),
        "total_discount": Decimal("0"),
        "final_amount": Decimal("100000"),
        "paid_amount": Decimal("100000"),
        "waived_amount": Decimal("0"),
        "semester_no": None,
        "installment_plan_id": None,
    }
    base.update(over)
    return base


def _legacy_paid_rows():
    fee = _fee()
    invoices = [{
        "invoice_number": "MIG-APP-7", "status": "paid",
        "amount": Decimal("100000"), "paid_amount": Decimal("100000"),
    }]
    payments = [{
        "id": 11, "status": "verified", "method_code": "bank_transfer",
        "amount": Decimal("100000"),
    }]
    transactions = [{
        "payment_id": 11, "transaction_type": "payment",
        "amount": Decimal("100000"),
    }]
    return fee, invoices, payments, transactions


def _current_paid_rows(system_id: int = 999):
    fee = _fee()
    invoices = [{
        "invoice_number": "APP-7", "status": "paid",
        "amount": Decimal("100000"), "paid_amount": Decimal("100000"),
    }]
    payments = [{
        "id": 11, "status": "verified", "method_code": "cash",
        "verified_by_id": system_id, "created_by_id": 42,
        "amount": Decimal("100000"),
    }]
    transactions = [{
        "payment_id": 11, "transaction_type": "payment",
        "performed_by_id": system_id,
        "gateway_response": {"verification_mode": "policy_auto"},
        "amount": Decimal("100000"),
    }]
    return fee, invoices, payments, transactions


# --------------------------------------------------------------------------- #
# 1. Revision chain + seeded policy contract
# --------------------------------------------------------------------------- #
def test_revision_id(migration):
    assert migration.revision == "appfee_finance_20260607"


def test_down_revision_chains_off_gdpt01(migration):
    """Finance ledger revises off the current head ``gdpt01``. If another
    migration lands first, rebase this revision onto the new head."""
    assert migration.down_revision == "gdpt01"


def test_seeded_policy_targets_record_fee_route_with_eft(migration):
    """casbin_rule INSERT must carry v3=eft='allow' (else load_policy 500 —
    memory casbin-insert-must-include-eft)."""
    assert migration._POLICY == (
        "role:officer",
        "/api/admissions/{id}/record-fee-payment",
        "POST",
        "allow",
    )


# --------------------------------------------------------------------------- #
# 2. Canonical helper import parity (P1-4 single source: Python == migration)
# --------------------------------------------------------------------------- #
def test_imports_shared_canonical_receipt_key(migration):
    assert migration.canonical_receipt_key is canonical_receipt_key


def test_no_local_receipt_hash_reimplementation(module_src):
    # Migration must NOT hand-roll md5/lower()-based receipt keys — only the
    # shared NFKC+casefold+SHA-256 helper (SQL lower() ≠ Python casefold).
    assert "md5" not in module_src.lower()
    assert "hashlib" not in module_src


# --------------------------------------------------------------------------- #
# 3. Pure money / bcrypt helpers
# --------------------------------------------------------------------------- #
def test_money_eq_and_is_zero(migration):
    assert migration._money_eq("100000.00", _EXPECTED) is True
    assert migration._money_eq("100000.01", _EXPECTED) is False
    assert migration._is_zero("0.00") is True
    assert migration._is_zero("0.01") is False


def test_is_bcrypt_hash(migration):
    assert migration._is_bcrypt_hash("$2b$12$" + "a" * 53) is True
    assert migration._is_bcrypt_hash("$2y$10$" + "b" * 53) is True
    assert migration._is_bcrypt_hash("plaintext") is False
    assert migration._is_bcrypt_hash(None) is False


def test_fee_amounts_match_requires_null_semester_and_plan(migration):
    assert migration._fee_amounts_match(
        _fee(), _EXPECTED, _EXPECTED, Decimal("0")
    ) is True
    assert migration._fee_amounts_match(
        _fee(semester_no=1), _EXPECTED, _EXPECTED, Decimal("0")
    ) is False
    assert migration._fee_amounts_match(
        _fee(installment_plan_id=5), _EXPECTED, _EXPECTED, Decimal("0")
    ) is False
    assert migration._fee_amounts_match(
        _fee(total_discount=Decimal("1")), _EXPECTED, _EXPECTED, Decimal("0")
    ) is False


# --------------------------------------------------------------------------- #
# 4. Known-valid legacy / current shapes classify True
# --------------------------------------------------------------------------- #
def test_legacy_paid_accepts_canonical_shape(migration):
    assert migration._is_legacy_paid(*_legacy_paid_rows(), _EXPECTED) is True


def test_legacy_exempt_accepts_canonical_shape(migration):
    fee = _fee(paid_amount=Decimal("0"), waived_amount=Decimal("100000"))
    invoices = [{
        "invoice_number": "MIG-APP-7", "status": "paid",
        "amount": Decimal("100000"), "paid_amount": Decimal("0"),
    }]
    assert migration._is_legacy_exempt(fee, invoices, [], [], _EXPECTED) is True


def test_legacy_pending_accepts_canonical_shape(migration):
    fee = _fee(status="calculated", paid_amount=Decimal("0"))
    invoices = [{
        "invoice_number": "MIG-APP-7", "status": "issued",
        "amount": Decimal("100000"), "paid_amount": Decimal("0"),
    }]
    assert migration._is_legacy_pending(fee, invoices, [], [], _EXPECTED) is True


def test_current_paid_accepts_runtime_shape(migration):
    fee, inv, pay, txn = _current_paid_rows(999)
    assert migration._is_current_paid(fee, inv, pay, txn, _EXPECTED, 999) is True


def test_current_waived_accepts_waive_shape(migration):
    fee = _fee(status="waived", paid_amount=Decimal("0"),
               waived_amount=Decimal("100000"))
    transactions = [{
        "transaction_type": "waive", "payment_id": None,
        "performed_by_id": 999, "amount": Decimal("100000"),
    }]
    assert migration._is_current_waived(
        fee, [], [], transactions, _EXPECTED, 999
    ) is True


# --------------------------------------------------------------------------- #
# 5. Anomalies classify False under ALL recognisers → _preflight BLOCKER
# --------------------------------------------------------------------------- #
def _all_classifiers_reject(migration, fee, inv, pay, txn, system_id=999):
    return (
        migration._is_legacy_paid(fee, inv, pay, txn, _EXPECTED) is False
        and migration._is_legacy_exempt(fee, inv, pay, txn, _EXPECTED) is False
        and migration._is_legacy_pending(fee, inv, pay, txn, _EXPECTED) is False
        and migration._is_current_paid(
            fee, inv, pay, txn, _EXPECTED, system_id
        ) is False
        and migration._is_current_waived(
            fee, inv, pay, txn, _EXPECTED, system_id
        ) is False
    )


def test_anomaly_fee_paid_without_payment_is_unclassified(migration):
    """Fee marked paid but no Payment/Txn matches none of the five valid
    shapes → preflight flags it anomalous and RAISEs."""
    fee, invoices, _, _ = _legacy_paid_rows()
    assert _all_classifiers_reject(migration, fee, invoices, [], [])


def test_anomaly_amount_drift_is_unclassified(migration):
    fee, invoices, payments, transactions = _legacy_paid_rows()
    fee["paid_amount"] = Decimal("50000")
    assert _all_classifiers_reject(
        migration, fee, invoices, payments, transactions
    )


def test_anomaly_extra_transaction_is_unclassified(migration):
    fee, invoices, payments, transactions = _legacy_paid_rows()
    transactions.append({
        "payment_id": None, "transaction_type": "adjustment",
        "amount": Decimal("0"),
    })
    assert _all_classifiers_reject(
        migration, fee, invoices, payments, transactions
    )


def test_current_paid_rejects_self_approval(migration):
    """created_by == verified_by (no maker-checker) is NOT a valid current
    paid chain."""
    fee, inv, pay, txn = _current_paid_rows(999)
    pay[0]["created_by_id"] = 999  # same as verified_by_id
    assert migration._is_current_paid(fee, inv, pay, txn, _EXPECTED, 999) is False


def test_current_paid_rejects_non_system_verifier(migration):
    fee, inv, pay, txn = _current_paid_rows(999)
    pay[0]["verified_by_id"] = 1234  # not the system principal
    assert migration._is_current_paid(fee, inv, pay, txn, _EXPECTED, 999) is False


# --------------------------------------------------------------------------- #
# 6. Downgrade is intentionally non-destructive (audit safety, P1-5)
# --------------------------------------------------------------------------- #
def test_downgrade_is_non_destructive(migration):
    src = inspect.getsource(migration.downgrade).lower()
    for forbidden in ("delete", "drop", "truncate", "update", "insert"):
        assert forbidden not in src, (
            f"downgrade must not {forbidden} — ledger rows, receipt keys, "
            "principals and Casbin policy are retained for audit"
        )


def test_preflight_hard_raises_on_blockers(module_src):
    """Preflight must RAISE (not REPORT-and-continue) and flag both receipt
    collisions and anomalous legacy fees (P0-1 + P0-2)."""
    assert '[appfee] Preflight blockers' in module_src
    assert "receipt collision" in module_src
    assert "anomalous application fee" in module_src


# --------------------------------------------------------------------------- #
# 7. Review fixes — legacy_pending blocker (P1), non-canonical key (P2),
#    historical dates (P2)
# --------------------------------------------------------------------------- #
def test_legacy_pending_is_a_preflight_blocker(migration, module_src):
    """legacy_pending is a recognised shape, but the new collection path can't
    consume a pre-existing calculated fee (_paid_chain_state rejects
    status != 'paid'). Preflight must flag it for manual handling, NOT treat it
    as valid-and-leave-it (which strands the profile as uncollectible)."""
    # The classifier still recognises the shape (used to detect → block).
    fee = _fee(status="calculated", paid_amount=Decimal("0"))
    invoices = [{
        "invoice_number": "MIG-APP-7", "status": "issued",
        "amount": Decimal("100000"), "paid_amount": Decimal("0"),
    }]
    assert migration._is_legacy_pending(fee, invoices, [], [], _EXPECTED) is True
    # Preflight emits a specific blocker for it.
    assert "legacy PENDING application fee" in module_src
    # It is NO LONGER in the valid OR-chain (`or _is_legacy_pending(...)`); it is
    # now a standalone blocker guard (`if _is_legacy_pending(...)`).
    preflight_src = inspect.getsource(migration._preflight)
    assert "or _is_legacy_pending" not in preflight_src
    assert "if _is_legacy_pending" in preflight_src


def test_preflight_blocks_non_canonical_legacy_key(module_src):
    """A legacy paid txn whose existing idempotency_key != canonical would be
    missed by the runtime replay guard → must be a preflight blocker, not a
    silent skip (P2)."""
    assert "non-canonical idempotency_key" in module_src


def test_backfill_preserves_historical_paid_date(migration):
    """Backfilled paid rows must stamp the historical applied_rules.fee_paid_at
    (fallback NOW()), not the migration date — else finance reports skew (P2)."""
    assert "fee_paid_at" in inspect.getsource(migration._write_candidates)
    paid_src = inspect.getsource(migration._backfill_paid)
    # payment_date / verified_at / invoice dates / txn created_at all coalesce.
    # CAST(... AS timestamptz) — NOT `:paid_at::timestamptz` (SQLAlchemy bind
    # `:name` collides with the `::` cast operator → syntax error).
    assert paid_src.count("COALESCE(CAST(:paid_at AS timestamptz), NOW())") >= 5
    assert "::timestamptz" not in paid_src
    # asyncpg needs a datetime (not str) for a timestamptz bind → parsed first.
    assert "_parse_ts(" in paid_src
    # _insert_fee computes last_payment_at in Python (no `:paid > 0` in SQL →
    # avoids asyncpg ambiguous-type deduction on :paid).
    fee_src = inspect.getsource(migration._insert_fee)
    assert "_parse_ts(" in fee_src
    assert ":paid > 0" not in fee_src


def test_backfill_avoids_asyncpg_ambiguous_binds(migration):
    """Regression guard for the asyncpg ambiguous-type bugs surfaced by the live
    backfill e2e (alembic runs under asyncpg, which infers one type per bind):
      - gateway_response built via json.dumps + CAST(:gateway AS jsonb), NOT
        jsonb_build_object with per-value binds (VARIADIC "any" → no type hint);
      - no `:paid > 0` SQL comparison (the paid_amount bind clashing numeric vs
        integer) — last_payment_at is computed in Python.
    These never ran in entrypoint tests (no write_candidates in dev DB) so only a
    real backfill execution catches them."""
    for fn in (migration._backfill_paid, migration._backfill_exempt):
        src = inspect.getsource(fn)
        assert "jsonb_build_object" not in src, "use json.dumps + CAST(:gateway)"
        assert "CAST(:gateway AS jsonb)" in src
    assert ":paid > 0" not in inspect.getsource(migration._insert_fee)


def test_parse_ts_handles_iso_null_and_garbage(migration):
    """_parse_ts: ISO str → datetime; None/empty/garbage → None (→ NOW())."""
    assert migration._parse_ts(None) is None
    assert migration._parse_ts("") is None
    assert migration._parse_ts("not-a-timestamp") is None
    parsed = migration._parse_ts("2026-02-15T09:30:00+00:00")
    assert isinstance(parsed, datetime)
    assert (parsed.year, parsed.month, parsed.day) == (2026, 2, 15)


def test_no_destructive_ops_in_upgrade(migration):
    """The review fixes use blockers + COALESCE, NOT row deletion — the
    migration stays additive (legacy rows are never dropped)."""
    up_src = inspect.getsource(migration.upgrade).lower()
    for fn in ("_preflight", "_patch_legacy_keys", "_backfill_paid",
               "_backfill_exempt", "_insert_fee"):
        body = inspect.getsource(getattr(migration, fn)).lower()
        assert "delete from" not in body, f"{fn} must not DELETE"
        assert "drop " not in body, f"{fn} must not DROP"
    assert "delete from" not in up_src
