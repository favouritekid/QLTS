"""Unit tests for ``cleanup_uppercase_orphan_notification_rows`` migration.

PR-1 Commit 2 (2026-05-23) — verify the cleanup migration:
1. Loads with the expected revision chain identifiers.
2. Declares both required predicates (rule + template).
3. Touches all three tables in the correct FK-safe order
   (notification_action child first, then notification_rule parent,
   then notification_template — which has no FK back into rule).
4. ``downgrade()`` is a no-op (the deleted rows had no business meaning).

Pattern follows ``test_phase1_01_02_revision_chain.py`` — importlib-load
the migration as a plain module, contract-assert revision / body
predicates / SQL ordering. The real upgrade/downgrade run lives in the
dev-DB roundtrip pre-PR + the CI integration sweep post-merge.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest


_VERSIONS_DIR = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions"
)


@pytest.fixture
def migration():
    path = _VERSIONS_DIR / "cleanup_uppercase_orphan_notification_rows.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None, (
        f"Cannot load migration {path}"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 1. Revision chain lock
# ---------------------------------------------------------------------------


def test_revision_id(migration):
    assert migration.revision == "cleanup_upper_notif", (
        "Revision ID is part of the alembic chain — renaming breaks any "
        "downstream migration that lists this as down_revision."
    )


def test_down_revision_chains_off_qa20260522(migration):
    """Migration revises off the prior head ``qa20260522_tighten_lead_denies``.

    If a NEW migration lands between this commit and merge, that migration
    would also need to bump its down_revision to point to ``cleanup_upper_notif``
    OR this revision must be rebased to chain off the new head.
    """
    assert migration.down_revision == "qa20260522_tighten_lead_denies"


# ---------------------------------------------------------------------------
# 2. Predicate constants — single source of truth for delete + count
# ---------------------------------------------------------------------------


def test_rule_predicate_uses_escape_clause(migration):
    """SQL LIKE ``ADMISSION_%`` without ESCAPE matches single-char underscore
    wildcard → false positives on patterns like ``ADMISSIONX``. Migration
    MUST use explicit ESCAPE so the literal underscore is matched.
    """
    pred = migration._RULE_PREDICATE
    assert "ESCAPE '\\'" in pred, (
        "Rule predicate must escape the literal underscore in LIKE."
    )
    assert "event != lower(event)" in pred, (
        "Rule predicate must require at least one uppercase character "
        "to avoid deleting lowercase (live) rows."
    )
    assert pred.startswith("event LIKE 'ADMISSION\\_%'"), (
        "Rule predicate target — uppercase ADMISSION_* event names — "
        "must be the LIKE pattern."
    )


def test_template_predicate_uses_escape_clause(migration):
    pred = migration._TEMPLATE_PREDICATE
    assert "ESCAPE '\\'" in pred
    assert "template_code != lower(template_code)" in pred
    assert pred.startswith("template_code LIKE 'TPL\\_ADMISSION\\_%'"), (
        "Template predicate target — uppercase TPL_ADMISSION_* template "
        "codes (per phase1_19c _template_code helper) — must be the "
        "LIKE pattern."
    )


# ---------------------------------------------------------------------------
# 3. Upgrade body — FK-safe ordering + 3 table coverage
# ---------------------------------------------------------------------------


def test_upgrade_body_covers_three_tables_in_fk_safe_order(migration):
    """Upgrade body MUST:
      - DELETE from notification_action BEFORE notification_rule (FK).
      - DELETE notification_template independently (no FK from rule).
      - Use the predicate constants (no inline string drift).
    """
    src = inspect.getsource(migration.upgrade)

    action_idx = src.find("DELETE FROM notification_action")
    rule_idx = src.find("DELETE FROM notification_rule")
    template_idx = src.find("DELETE FROM notification_template")

    assert action_idx >= 0, "Missing DELETE FROM notification_action"
    assert rule_idx >= 0, "Missing DELETE FROM notification_rule"
    assert template_idx >= 0, "Missing DELETE FROM notification_template"

    assert action_idx < rule_idx, (
        "FK order violation: notification_action (child) must be deleted "
        "BEFORE notification_rule (parent). Schema has no ON DELETE CASCADE."
    )

    # Predicate constants must be referenced (no inline string drift).
    assert "_RULE_PREDICATE" in src
    assert "_TEMPLATE_PREDICATE" in src


def test_upgrade_logs_counts(migration):
    """Upgrade should print rule/action/template counts so the alembic
    output trail captures the row impact (per memory ``migration-predicate-safety``
    audit trail requirement).
    """
    src = inspect.getsource(migration.upgrade)
    assert "print(" in src, "Upgrade body should log row counts"
    for key in ("rule=", "action=", "template="):
        assert key in src, f"Expected count log key {key!r} in upgrade output"


# ---------------------------------------------------------------------------
# 4. Downgrade no-op contract
# ---------------------------------------------------------------------------


def test_downgrade_is_noop(migration):
    """Downgrade docstring + body must encode "no-op" intent — the deleted
    rows were dead weight, re-creating them would only restore the noise.
    """
    src = inspect.getsource(migration.downgrade)
    # Body must NOT execute any DELETE / INSERT / op.execute call.
    for forbidden in ("op.execute", "INSERT INTO", "DELETE FROM", "UPDATE "):
        assert forbidden not in src, (
            f"downgrade() must be a no-op; found forbidden token {forbidden!r}"
        )
    # ``pass`` (the no-op statement) MUST be present.
    assert "pass" in src
