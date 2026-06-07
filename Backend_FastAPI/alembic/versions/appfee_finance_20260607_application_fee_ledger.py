"""Backfill application-fee ledger and receipt replay protection.

Revision ID: appfee_finance_20260607
Revises: gdpt01
Create Date: 2026-06-07
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import secrets
from typing import Any, Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.security import get_password_hash
from app.utils.fee_receipt import canonical_receipt_key


revision: str = "appfee_finance_20260607"
down_revision: Union[str, None] = "gdpt01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POLICY = (
    "role:officer",
    "/api/admissions/{id}/record-fee-payment",
    "POST",
    "allow",
)
_SYSTEM_USERNAME = "system"
_SYSTEM_EMAIL = "system@qlts.internal"
_BACKFILL_USERNAME = "backfill"
_BACKFILL_EMAIL = "backfill@qlts.internal"
_BACKFILL_IDEMPOTENCY_PREFIX = "appfee:backfill:"


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an applied_rules ISO timestamp into a datetime for binding.

    asyncpg requires a datetime (not a str) for a timestamptz parameter, so the
    raw ``applied_rules->>'fee_paid_at'`` text must be parsed here. Unparseable /
    missing → None, which the COALESCE(..., NOW()) falls back on.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _d(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise RuntimeError(
            f"Invalid money value in application-fee migration: {value!r}"
        )


def _is_zero(value: Any) -> bool:
    return _d(value) == Decimal("0.00")


def _money_eq(actual: Any, expected: Decimal) -> bool:
    return _d(actual) == expected


def _is_bcrypt_hash(value: Any) -> bool:
    text = str(value or "")
    return len(text) >= 50 and (
        text.startswith("$2a$")
        or text.startswith("$2b$")
        or text.startswith("$2y$")
    )


def _fetch_all(
    conn,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result = conn.execute(sa.text(sql), params or {}).mappings().all()
    return [dict(row) for row in result]


def _fetch_one(
    conn,
    sql: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    row = conn.execute(sa.text(sql), params or {}).mappings().first()
    return dict(row) if row else None


def _ensure_principal(conn, username: str, email: str, full_name: str) -> int:
    row = _fetch_one(
        conn,
        'SELECT * FROM "user" WHERE username = :username',
        {"username": username},
    )
    if row is None:
        password_hash = get_password_hash(secrets.token_urlsafe(32))
        row = _fetch_one(
            conn,
            """
            INSERT INTO "user" (
                username, email, password_hash, full_name, role, status,
                unit_id, current_assignment_id, max_capacity,
                availability_status, total_lead_score,
                password_reset_required, mfa_enabled
            )
            VALUES (
                :username, :email, :password_hash, :full_name, 'user',
                'inactive', NULL, NULL, 0, 'unavailable', 0, FALSE, FALSE
            )
            RETURNING *
            """,
            {
                "username": username,
                "email": email,
                "password_hash": password_hash,
                "full_name": full_name,
            },
        )

    if not (
        row["status"] == "inactive"
        and row["role"] == "user"
        and row["email"] == email
        and row["unit_id"] is None
        and row["current_assignment_id"] is None
        and _is_bcrypt_hash(row["password_hash"])
    ):
        raise RuntimeError(
            f"[appfee] Technical principal {username!r} fingerprint mismatch"
        )

    active_assignment = _fetch_one(
        conn,
        """
        SELECT id FROM user_unit_assignment
        WHERE user_id = :user_id AND is_active = TRUE
        LIMIT 1
        """,
        {"user_id": row["id"]},
    )
    if active_assignment is not None:
        raise RuntimeError(
            f"[appfee] Technical principal {username!r} has active assignment"
        )

    return int(row["id"])


def _seed_policy(conn) -> None:
    v0, v1, v2, v3 = _POLICY
    conn.execute(
        sa.text(
            """
            INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at)
            SELECT 'p',
                   CAST(:v0 AS VARCHAR),
                   CAST(:v1 AS VARCHAR),
                   CAST(:v2 AS VARCHAR),
                   CAST(:v3 AS VARCHAR),
                   '_appfee_finance_20260607', NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM casbin_rule
                WHERE ptype='p'
                  AND v0=CAST(:v0 AS VARCHAR)
                  AND v1=CAST(:v1 AS VARCHAR)
                  AND v2=CAST(:v2 AS VARCHAR)
                  AND v3=CAST(:v3 AS VARCHAR)
            )
            """
        ),
        {"v0": v0, "v1": v1, "v2": v2, "v3": v3},
    )


def _write_candidates(conn) -> list[dict[str, Any]]:
    return _fetch_all(
        conn,
        """
        SELECT
            ap.id AS profile_id,
            ap.academic_year,
            ap.applied_rules,
            (ap.applied_rules->>'application_fee')::numeric AS expected,
            ap.applied_rules->>'fee_status' AS fee_status,
            ap.applied_rules->>'fee_paid_at' AS fee_paid_at,
            ap.applied_rules->'fee_payment_data'->>'transaction_id' AS receipt,
            ap.applied_rules->'fee_payment_data'->>'amount' AS paid_amount
        FROM admission_profile ap
        WHERE COALESCE((ap.applied_rules->>'application_fee')::numeric, 0) > 0
          AND ap.applied_rules->>'fee_status' IN ('paid', 'exempt')
          AND NOT EXISTS (
              SELECT 1 FROM fee f
              WHERE f.admission_profile_id = ap.id
                AND f.fee_type = 'application'
          )
        ORDER BY ap.id
        """,
    )


def _application_fees(conn) -> list[dict[str, Any]]:
    return _fetch_all(
        conn,
        """
        SELECT
            ap.id AS profile_id,
            ap.academic_year,
            (ap.applied_rules->>'application_fee')::numeric AS expected,
            f.*
        FROM fee f
        JOIN admission_profile ap ON ap.id = f.admission_profile_id
        WHERE f.fee_type = 'application'
          AND COALESCE((ap.applied_rules->>'application_fee')::numeric, 0) > 0
        ORDER BY ap.id, f.id
        """,
    )


def _fee_children(
    conn,
    fee_id: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    invoices = _fetch_all(
        conn,
        "SELECT * FROM invoice WHERE fee_id=:fee_id ORDER BY id",
        {"fee_id": fee_id},
    )
    payments = _fetch_all(
        conn,
        """
        SELECT p.*, pm.code AS method_code, pm.is_active AS method_is_active,
               pm.is_online AS method_is_online
        FROM payment p
        JOIN invoice i ON i.id = p.invoice_id
        JOIN payment_method pm ON pm.id = p.method_id
        WHERE i.fee_id = :fee_id
        ORDER BY p.id
        """,
        {"fee_id": fee_id},
    )
    transactions = _fetch_all(
        conn,
        "SELECT * FROM payment_transaction WHERE fee_id=:fee_id ORDER BY id",
        {"fee_id": fee_id},
    )
    return invoices, payments, transactions


def _fee_amounts_match(
    fee: dict[str, Any],
    expected: Decimal,
    paid: Decimal,
    waived: Decimal,
) -> bool:
    return (
        _money_eq(fee["base_amount"], expected)
        and _is_zero(fee["total_discount"])
        and _money_eq(fee["final_amount"], expected)
        and _money_eq(fee["paid_amount"], paid)
        and _money_eq(fee["waived_amount"], waived)
        and fee["semester_no"] is None
        and fee["installment_plan_id"] is None
    )


def _is_legacy_paid(
    fee: dict[str, Any],
    invoices: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    expected: Decimal,
) -> bool:
    if not (
        fee["status"] == "paid"
        and _fee_amounts_match(fee, expected, expected, Decimal("0"))
        and len(invoices) == len(payments) == len(transactions) == 1
    ):
        return False
    invoice, payment, transaction = invoices[0], payments[0], transactions[0]
    return (
        str(invoice["invoice_number"]).startswith("MIG-APP-")
        and invoice["status"] == "paid"
        and _money_eq(invoice["amount"], expected)
        and _money_eq(invoice["paid_amount"], expected)
        and payment["status"] == "verified"
        and payment["method_code"] == "bank_transfer"
        and _money_eq(payment["amount"], expected)
        and transaction["payment_id"] == payment["id"]
        and transaction["transaction_type"] == "payment"
        and _money_eq(transaction["amount"], expected)
    )


def _is_legacy_exempt(
    fee: dict[str, Any],
    invoices: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    expected: Decimal,
) -> bool:
    if not (
        fee["status"] == "paid"
        and _fee_amounts_match(fee, expected, Decimal("0"), expected)
        and len(invoices) == 1
        and not payments
        and not transactions
    ):
        return False
    invoice = invoices[0]
    return (
        str(invoice["invoice_number"]).startswith("MIG-APP-")
        and invoice["status"] == "paid"
        and _money_eq(invoice["amount"], expected)
        and _is_zero(invoice["paid_amount"])
    )


def _is_legacy_pending(
    fee: dict[str, Any],
    invoices: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    expected: Decimal,
) -> bool:
    if not (
        fee["status"] == "calculated"
        and _fee_amounts_match(fee, expected, Decimal("0"), Decimal("0"))
        and len(invoices) == 1
        and not payments
        and not transactions
    ):
        return False
    invoice = invoices[0]
    return (
        str(invoice["invoice_number"]).startswith("MIG-APP-")
        and invoice["status"] == "issued"
        and _money_eq(invoice["amount"], expected)
        and _is_zero(invoice["paid_amount"])
    )


def _is_current_paid(
    fee: dict[str, Any],
    invoices: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    expected: Decimal,
    system_id: int,
) -> bool:
    if not (
        fee["status"] == "paid"
        and _fee_amounts_match(fee, expected, expected, Decimal("0"))
        and len(invoices) == len(payments) == len(transactions) == 1
    ):
        return False
    invoice, payment, transaction = invoices[0], payments[0], transactions[0]
    gateway = transaction["gateway_response"] or {}
    return (
        invoice["invoice_number"] == f"APP-{fee['id']}"
        and invoice["status"] == "paid"
        and payment["status"] == "verified"
        and payment["method_code"] == "cash"
        and payment["verified_by_id"] == system_id
        and payment["created_by_id"] != payment["verified_by_id"]
        and transaction["transaction_type"] == "payment"
        and transaction["payment_id"] == payment["id"]
        and transaction["performed_by_id"] == system_id
        and gateway.get("verification_mode") in {"policy_auto", "backfill"}
    )


def _is_current_waived(
    fee: dict[str, Any],
    invoices: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    expected: Decimal,
    system_id: int,
) -> bool:
    if not (
        fee["status"] == "waived"
        and _fee_amounts_match(fee, expected, Decimal("0"), expected)
        and not invoices
        and not payments
        and len(transactions) == 1
    ):
        return False
    transaction = transactions[0]
    return (
        transaction["transaction_type"] == "waive"
        and transaction["payment_id"] is None
        and transaction["performed_by_id"] == system_id
        and _money_eq(transaction["amount"], expected)
    )


def _preflight(
    conn,
    system_id: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    Validate rows this migration will touch before writing.

    Unrelated pre-existing idempotency keys remain DB-constraint enforced.
    """
    blockers: list[str] = []
    cash_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM payment_method "
            "WHERE code='cash' AND is_active=TRUE AND is_online=FALSE"
        )
    ).scalar()
    if cash_count != 1:
        blockers.append(f"cash_method count must be 1, got {cash_count}")

    write_candidates = _write_candidates(conn)
    receipt_targets: dict[str, list[str]] = {}
    for row in write_candidates:
        expected = _d(row["expected"])
        if row["fee_status"] == "paid":
            receipt = str(row.get("receipt") or "").strip()
            if not receipt:
                blockers.append(
                    f"profile {row['profile_id']}: paid write candidate missing receipt"
                )
            else:
                receipt_targets.setdefault(canonical_receipt_key(receipt), []).append(
                    f"write:{row['profile_id']}"
                )
            if row.get("paid_amount") is None or _d(row["paid_amount"]) != expected:
                blockers.append(
                    f"profile {row['profile_id']}: paid amount != application_fee"
                )

    legacy_paid: list[dict[str, Any]] = []
    for fee in _application_fees(conn):
        expected = _d(fee["expected"])
        invoices, payments, transactions = _fee_children(conn, int(fee["id"]))
        # legacy_pending (calculated placeholder Fee + issued invoice, 0 payment
        # from fin20260131003) is a KNOWN shape but it BLOCKS runtime collection:
        # record_application_fee_payment loads the existing fee and
        # _paid_chain_state rejects status != 'paid' (ConflictError) — the repair
        # path only runs when no fee exists. Leaving it "valid" silently strands
        # the profile as uncollectible, so flag it for manual handling (clear the
        # unpaid fee+invoice or collect manually) instead. Prod is clean (0 fee
        # rows) → this is a no-op fail-closed guard at deploy.
        if _is_legacy_pending(fee, invoices, payments, transactions, expected):
            blockers.append(
                f"profile {fee['profile_id']}: legacy PENDING application fee "
                f"{fee['id']} (calculated placeholder) blocks collection — clear "
                f"the unpaid fee+invoice or collect manually, then re-run"
            )
            continue
        valid_legacy_paid = _is_legacy_paid(
            fee,
            invoices,
            payments,
            transactions,
            expected,
        )
        valid = (
            valid_legacy_paid
            or _is_legacy_exempt(fee, invoices, payments, transactions, expected)
            or _is_current_paid(
                fee,
                invoices,
                payments,
                transactions,
                expected,
                system_id,
            )
            or _is_current_waived(
                fee,
                invoices,
                payments,
                transactions,
                expected,
                system_id,
            )
        )
        if not valid:
            blockers.append(
                f"profile {fee['profile_id']}: anomalous application fee {fee['id']}"
            )
            continue
        if valid_legacy_paid:
            payment = payments[0]
            transaction = transactions[0]
            receipt = str(payment.get("reference_code") or "").strip()
            if receipt:
                key = canonical_receipt_key(receipt)
                existing_key = transaction.get("idempotency_key")
                # The runtime replay guard searches ONLY the canonical key. A
                # legacy txn carrying a non-null, non-canonical idempotency_key
                # would therefore NOT block the same receipt from being collected
                # on another profile. fin20260131003 leaves the key NULL (→ patched
                # to canonical in PHA 2), so any pre-set non-canonical key is an
                # anomaly to handle manually rather than silently skip.
                if existing_key is not None and existing_key != key:
                    blockers.append(
                        f"profile {fee['profile_id']}: legacy txn "
                        f"{transaction['id']} has a non-canonical idempotency_key "
                        f"(runtime replay guard would miss it)"
                    )
                    continue
                receipt_targets.setdefault(key, []).append(
                    f"legacy:{fee['profile_id']}:{transaction['id']}"
                )
                legacy_paid.append(
                    {
                        "profile_id": fee["profile_id"],
                        "fee_id": fee["id"],
                        "transaction_id": transaction["id"],
                        "reference_code": receipt,
                        "idempotency_key": transaction["idempotency_key"],
                    }
                )

    duplicate_keys = {
        key: targets
        for key, targets in receipt_targets.items()
        if len(targets) > 1
    }
    for key, targets in duplicate_keys.items():
        blockers.append(f"receipt collision {key}: {', '.join(targets)}")

    if blockers:
        preview = "\n".join(f"- {item}" for item in blockers[:50])
        if len(blockers) > 50:
            preview += f"\n- ... {len(blockers) - 50} more"
        raise RuntimeError(f"[appfee] Preflight blockers:\n{preview}")

    return write_candidates, legacy_paid, _fetch_all(
        conn,
        "SELECT * FROM payment_method "
        "WHERE code='cash' AND is_active=TRUE AND is_online=FALSE",
    )


def _patch_legacy_keys(conn, legacy_paid: list[dict[str, Any]]) -> int:
    patched = 0
    for row in legacy_paid:
        if row["idempotency_key"] is not None:
            continue
        result = conn.execute(
            sa.text(
                """
                UPDATE payment_transaction
                SET idempotency_key = :key
                WHERE id = :transaction_id AND idempotency_key IS NULL
                """
            ),
            {
                "transaction_id": row["transaction_id"],
                "key": canonical_receipt_key(row["reference_code"]),
            },
        )
        patched += result.rowcount
    return patched


def _insert_fee(
    conn,
    row: dict[str, Any],
    status: str,
    paid: Decimal,
    waived: Decimal,
    actor_id: int,
) -> int:
    expected = _d(row["expected"])
    # Compute last_payment_at in Python: a paid fee keeps the historical
    # applied_rules.fee_paid_at (fallback to now); a waived/0-paid fee leaves it
    # NULL. Doing it here avoids an asyncpg ambiguous-type deduction on the
    # paid_amount bind (previously compared against an integer literal inside a
    # SQL CASE, which clashed with its numeric column usage).
    last_payment_at = None
    if paid > 0:
        last_payment_at = (
            _parse_ts(row.get("fee_paid_at")) or datetime.now(timezone.utc)
        )
    return int(
        _fetch_one(
            conn,
            """
            INSERT INTO fee (
                admission_profile_id, fee_type, academic_year, semester_no,
                base_amount, total_discount, final_amount, paid_amount,
                waived_amount, status, calculated_by_id, calculated_at,
                last_payment_at, notes, created_at, updated_at
            )
            VALUES (
                :profile_id, 'application', :academic_year, NULL,
                :expected, 0, :expected, :paid, :waived, :status, :actor_id,
                NOW(), :last_payment_at,
                'Application fee ledger backfill', NOW(), NOW()
            )
            RETURNING id
            """,
            {
                "profile_id": row["profile_id"],
                "academic_year": row["academic_year"],
                "expected": expected,
                "paid": paid,
                "waived": waived,
                "status": status,
                "actor_id": actor_id,
                "last_payment_at": last_payment_at,
            },
        )["id"]
    )


def _backfill_paid(
    conn,
    row: dict[str, Any],
    system_id: int,
    backfill_id: int,
    cash_method_id: int,
) -> None:
    expected = _d(row["expected"])
    receipt = str(row["receipt"]).strip()
    fee_id = _insert_fee(conn, row, "paid", expected, Decimal("0"), backfill_id)
    invoice_id = int(
        _fetch_one(
            conn,
            """
            INSERT INTO invoice (
                fee_id, invoice_number, installment_no, amount, paid_amount,
                penalty_amount, due_date, status, issued_at, paid_at,
                issued_by_id, notes, created_at, updated_at
            )
            VALUES (
                :fee_id, :invoice_number, 1, :expected, :expected, 0,
                CURRENT_DATE, 'paid',
                COALESCE(CAST(:paid_at AS timestamptz), NOW()),
                COALESCE(CAST(:paid_at AS timestamptz), NOW()), :backfill_id,
                'Application fee invoice backfill', NOW(), NOW()
            )
            RETURNING id
            """,
            {
                "fee_id": fee_id,
                "invoice_number": f"APP-{fee_id}",
                "expected": expected,
                "backfill_id": backfill_id,
                "paid_at": _parse_ts(row.get("fee_paid_at")),
            },
        )["id"]
    )
    payment_id = int(
        _fetch_one(
            conn,
            """
            INSERT INTO payment (
                invoice_id, method_id, amount, reference_code, status,
                payment_date, verified_at, created_by_id, verified_by_id,
                rejected_by_id, rejection_reason, intent_id, notes,
                created_at, updated_at
            )
            VALUES (
                :invoice_id, :cash_method_id, :expected, :receipt, 'verified',
                COALESCE(CAST(:paid_at AS timestamptz), NOW()),
                COALESCE(CAST(:paid_at AS timestamptz), NOW()),
                :backfill_id, :system_id, NULL, NULL, NULL,
                'Application fee payment backfill', NOW(), NOW()
            )
            RETURNING id
            """,
            {
                "invoice_id": invoice_id,
                "cash_method_id": cash_method_id,
                "expected": expected,
                "receipt": receipt,
                "backfill_id": backfill_id,
                "system_id": system_id,
                "paid_at": _parse_ts(row.get("fee_paid_at")),
            },
        )["id"]
    )
    # Build the JSONB audit blob in Python and bind it as a single jsonb param.
    # Binding individual values into a SQL JSONB constructor made asyncpg unable
    # to deduce a single type per bind (the constructor's VARIADIC "any" gives no
    # type hint, clashing with the same bind's column usage).
    gateway = json.dumps({
        "verification_mode": "backfill",
        "receipt": receipt,
        "amount": str(expected),
        "created_by_id": backfill_id,
        "verified_by_id": system_id,
    })
    conn.execute(
        sa.text(
            """
            INSERT INTO payment_transaction (
                payment_id, fee_id, transaction_type, amount, balance_before,
                balance_after, external_reference, gateway_response,
                idempotency_key, performed_by_id, notes, created_at
            )
            VALUES (
                :payment_id, :fee_id, 'payment', :expected, :expected, 0,
                :receipt, CAST(:gateway AS jsonb), :key, :system_id,
                'Application fee payment backfill',
                COALESCE(CAST(:paid_at AS timestamptz), NOW())
            )
            """
        ),
        {
            "payment_id": payment_id,
            "fee_id": fee_id,
            "expected": expected,
            "receipt": receipt,
            "gateway": gateway,
            "key": canonical_receipt_key(receipt),
            "system_id": system_id,
            "paid_at": _parse_ts(row.get("fee_paid_at")),
        },
    )


def _backfill_exempt(
    conn,
    row: dict[str, Any],
    system_id: int,
    backfill_id: int,
) -> None:
    expected = _d(row["expected"])
    fee_id = _insert_fee(conn, row, "waived", Decimal("0"), expected, backfill_id)
    gateway = json.dumps({
        "verification_mode": "backfill",
        "amount": str(expected),
        "created_by_id": backfill_id,
        "verified_by_id": system_id,
    })
    conn.execute(
        sa.text(
            """
            INSERT INTO payment_transaction (
                payment_id, fee_id, transaction_type, amount, balance_before,
                balance_after, external_reference, gateway_response,
                idempotency_key, performed_by_id, notes, created_at
            )
            VALUES (
                NULL, :fee_id, 'waive', :expected, :expected, 0, NULL,
                CAST(:gateway AS jsonb),
                :key, :system_id, 'Application fee exemption backfill',
                COALESCE(CAST(:paid_at AS timestamptz), NOW())
            )
            """
        ),
        {
            "fee_id": fee_id,
            "expected": expected,
            "gateway": gateway,
            "system_id": system_id,
            "key": f"{_BACKFILL_IDEMPOTENCY_PREFIX}{fee_id}",
            "paid_at": _parse_ts(row.get("fee_paid_at")),
        },
    )


def upgrade() -> None:
    conn = op.get_bind()
    system_id = _ensure_principal(
        conn,
        _SYSTEM_USERNAME,
        _SYSTEM_EMAIL,
        "System Policy User",
    )
    backfill_id = _ensure_principal(
        conn,
        _BACKFILL_USERNAME,
        _BACKFILL_EMAIL,
        "Backfill Policy User",
    )
    _seed_policy(conn)

    write_candidates, legacy_paid, cash_methods = _preflight(conn, system_id)
    cash_method_id = int(cash_methods[0]["id"])

    patched = _patch_legacy_keys(conn, legacy_paid)
    written = 0
    for row in write_candidates:
        if row["fee_status"] == "paid":
            _backfill_paid(conn, row, system_id, backfill_id, cash_method_id)
            written += 1
        elif row["fee_status"] == "exempt":
            _backfill_exempt(conn, row, system_id, backfill_id)
            written += 1

    print(
        "[appfee] complete: "
        f"legacy_keys_patched={patched}, clean_gap_profiles_written={written}"
    )


def downgrade() -> None:
    print(
        "[appfee] downgrade is intentionally no-op: ledger rows, receipt keys, "
        "technical principals, and Casbin policy are retained for audit safety."
    )
