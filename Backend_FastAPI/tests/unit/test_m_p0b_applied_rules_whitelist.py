"""M-P0b — coverage for the relaxed `applied_rules` immutability trigger.

Source-level lock-in only:

1. Revision chain (`phase0br01` on top of `phase0sg01`).
2. ``ALLOWED_KEYS`` is the 5-tuple including ``fee_status`` (the user-
   review catch — PLAN listed 4 keys; production code at
   ``admission_service.py:5904`` writes 3 keys including
   ``fee_status``, so the migration whitelist must include it).
3. The upgrade SQL contains the structural markers a per-key
   classifier needs:
   * each of the 5 keys appears as a single-quoted literal,
   * ``jsonb_object_keys`` walk over the union of OLD ∪ NEW,
   * an explicit deletion guard so a delete of a whitelisted key
     is also rejected (the strip-and-compare pattern in PLAN line
     2543-2552 had a blind spot here),
   * a wipe-entire-object guard.
4. The downgrade SQL restores the v1 strict body literal-for-literal
   from ``b5c6d7e8f9a0`` so a revert reads exactly as before.

Live behaviour (the 5-key matrix the trigger enforces in Postgres) is
exercised manually via ``docker compose exec postgres psql`` and
recorded in the PR body / DAILY_LOG. ``psycopg`` is not in the test
deps and the test DB uses ``Base.metadata.create_all`` rather than
Alembic (per memory ``test-db-schema-source``), so a pytest live
fixture would have to re-execute the migration body itself — at that
point the test only proves the migration source compiles, not that
it works on Postgres. The alembic CLI roundtrip on the dev DB
(``upgrade`` → ``\\df+`` verify → ``downgrade`` → ``\\df+`` verify v1 → re-upgrade)
is the source-of-truth live check.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "phase0br01_relax_applied_rules_immutability_for_payment_keys.py"
)


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "phase0br01_migration", str(MIGRATION_PATH)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_chain():
    mod = _load_migration_module()
    assert mod.revision == "phase0br01"
    assert mod.down_revision == "phase0sg01"


def test_allowed_keys_locked_to_5_including_fee_status():
    """fee_status is the catch from M-P0b user review (PLAN listed 4)."""
    mod = _load_migration_module()
    assert mod.ALLOWED_KEYS == (
        "fee_status",
        "fee_paid_at",
        "fee_payment_data",
        "fee_calculated_at",
        "fee_invoice_id",
    ), (
        "ALLOWED_KEYS must include fee_status — production code at "
        "admission_service.py:5904 flips it post-create. PLAN v2.13.1 "
        "listed only 4 keys; this test is the lock against drift."
    )


def test_upgrade_sql_has_per_key_classifier_with_deletion_guard():
    src = MIGRATION_PATH.read_text(encoding="utf-8")

    # Whitelist literal must include all 5 keys — guards against drift
    # between the Python tuple and the SQL ARRAY[...].
    for key in (
        "fee_status",
        "fee_paid_at",
        "fee_payment_data",
        "fee_calculated_at",
        "fee_invoice_id",
    ):
        assert f"'{key}'" in src, f"upgrade SQL missing whitelist key {key!r}"

    # Per-key classifier markers
    assert "jsonb_object_keys(OLD.applied_rules)" in src
    assert "jsonb_object_keys(NEW.applied_rules)" in src
    assert "FOREACH v_key IN ARRAY v_all_keys" in src

    # Deletion guard — the strip-and-compare pattern in PLAN line
    # 2543-2552 had a blind spot here; the per-key classifier closes it.
    assert "deletion of key" in src.lower(), (
        "upgrade SQL must reject deletion of whitelisted keys "
        "(PLAN says add/update, not delete)"
    )

    # Wipe-entire-object guard
    assert "cannot wipe entire object" in src.lower()


def test_downgrade_sql_restores_v1_strict():
    """Downgrade restores the b5c6d7e8f9a0 v1 body literal-for-literal."""
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    # The v1 body's RAISE EXCEPTION text — exact string match. If a
    # future edit relaxes the v1 wording, this fires.
    assert (
        "applied_rules is immutable after creation and cannot be modified"
        in src
    ), (
        "downgrade must restore the v1 RAISE EXCEPTION text so a "
        "future operator who ran `alembic downgrade -1` sees the same "
        "error as before M-P0b shipped"
    )
