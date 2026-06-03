"""P0 hotfix — coverage for the doc-resolution whitelist relaxation.

Source-level lock-in only (same rationale as
``test_m_p0b_applied_rules_whitelist.py``): the test DB is built with
``Base.metadata.create_all`` (no trigger — memory ``test-db-schema-source``)
and ``psycopg`` is not in the test deps, so live trigger behaviour is
verified by the alembic CLI roundtrip on the dev DB
(``upgrade`` → BEGIN/ROLLBACK UPDATE mandatory_docs == OK →
``downgrade`` → same UPDATE == RAISE → re-``upgrade``) and recorded in the
PR body. These tests pin the migration source so a future edit can't
silently drop a key or break the revision chain.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "ardockeys01_relax_applied_rules_for_doc_resolution.py"
)


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "ardockeys01_migration", str(MIGRATION_PATH)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _section(start_marker: str, end_marker: str | None) -> str:
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    start = src.index(start_marker)
    end = len(src) if end_marker is None else src.index(end_marker)
    return src[start:end]


def test_revision_chain():
    mod = _load_migration_module()
    assert mod.revision == "ardockeys01"
    assert mod.down_revision == "docdl_audit_001"


def test_allowed_keys_adds_two_doc_resolution_keys():
    """Whitelist = 5 fee keys (phase0br01) + mandatory_docs + doc_configs."""
    mod = _load_migration_module()
    assert mod.ALLOWED_KEYS == (
        "fee_status",
        "fee_paid_at",
        "fee_payment_data",
        "fee_calculated_at",
        "fee_invoice_id",
        "mandatory_docs",
        "doc_configs",
    )
    # The 5 fee keys must survive — re-resolve relaxation must not regress
    # the application-fee flow that phase0br01 enabled.
    for key in (
        "fee_status",
        "fee_paid_at",
        "fee_payment_data",
        "fee_calculated_at",
        "fee_invoice_id",
    ):
        assert key in mod.ALLOWED_KEYS


def test_upgrade_sql_whitelists_doc_keys_with_classifier():
    up = _section("def upgrade", "def downgrade")

    # All 7 keys present as single-quoted literals in the upgrade ARRAY.
    for key in (
        "fee_status",
        "fee_paid_at",
        "fee_payment_data",
        "fee_calculated_at",
        "fee_invoice_id",
        "mandatory_docs",
        "doc_configs",
    ):
        assert f"'{key}'" in up, f"upgrade SQL missing whitelist key {key!r}"

    # Per-key classifier markers carried over from phase0br01.
    assert "jsonb_object_keys(OLD.applied_rules)" in up
    assert "jsonb_object_keys(NEW.applied_rules)" in up
    assert "FOREACH v_key IN ARRAY v_all_keys" in up
    # Deletion guard + wipe guard preserved.
    assert "deletion of key" in up.lower()
    assert "cannot wipe entire object" in up.lower()


def test_downgrade_restores_five_fee_keys_only():
    """Downgrade reverts to the phase0br01 body — no doc-resolution keys."""
    down = _section("def downgrade", None)

    # Doc-resolution keys must NOT be re-added by the downgrade body, else a
    # revert would not reproduce the pre-hotfix (5-key) behaviour.
    assert "'mandatory_docs'" not in down
    assert "'doc_configs'" not in down

    # The 5 fee keys are restored.
    for key in (
        "fee_status",
        "fee_paid_at",
        "fee_payment_data",
        "fee_calculated_at",
        "fee_invoice_id",
    ):
        assert f"'{key}'" in down, f"downgrade SQL missing fee key {key!r}"

    # Classifier + guards still present in the restored body.
    assert "FOREACH v_key IN ARRAY v_all_keys" in down
    assert "cannot wipe entire object" in down.lower()
