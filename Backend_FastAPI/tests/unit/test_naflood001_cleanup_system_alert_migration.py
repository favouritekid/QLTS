"""Contract tests for ``naflood001`` system_alert cleanup migration.

fix/notification-alert-flood Step 7 — after the health-check beat task moves
to the dedicated ``notification_health_alert`` event, the ``system_alert``
rule (a) drops the zalobot002-seeded zalo_bot action and (b) is restored to
its seed contract recipient ``all_users`` (undoing Phase 0 mitigation).

Pattern follows ``test_docgrp_audience_backfill_migration.py`` — importlib-load
the module and contract-assert revision chain + SQL body. The actual
upgrade/downgrade roundtrip is run on a real dev DB pre-PR + the CI migration
sweep post-merge.

Safety invariants asserted here:
1. Revision chains off the current head.
2. upgrade DELETE is scoped to ``system_alert`` ONLY and gated by the
   zalobot002 marker (the other 9 pilot events keep their zalo_bot actions).
3. upgrade UPDATE uses the NARROW predicate ``resolver_type = 'all_admins'``
   (only undoes Phase 0, never overwrites a custom resolver) and writes
   ``all_users`` as a ``::json`` cast (recipient_config is JSON, not JSONB).
4. downgrade re-inserts the zalo_bot action idempotently (WHERE NOT EXISTS)
   with the zalobot002 marker, scoped to ``system_alert``.
5. downgrade is non-destructive to recipient_config (no rule UPDATE).
6. Literal SQL via ``sa.text`` (no f-string interpolation from input).
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_MIGRATION_FILE = "naflood001_cleanup_system_alert_rule.py"


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


# ---------------------------------------------------------------------------
# 1. Revision chain lock
# ---------------------------------------------------------------------------


def test_revision_id(migration):
    assert migration.revision == "naflood001"


def test_down_revision_chains_off_head(migration):
    """If another migration lands between this commit and merge, bump that
    migration's down_revision onto ``naflood001`` OR rebase this onto the
    new head."""
    assert migration.down_revision == "docgrp_audience_bf_20260530"


# ---------------------------------------------------------------------------
# 2. upgrade — scoped DELETE of zalobot002 zalo_bot action
# ---------------------------------------------------------------------------


def test_upgrade_deletes_zalo_bot_action(migration):
    src = inspect.getsource(migration.upgrade)
    assert "DELETE FROM notification_action" in src
    assert "channel = 'zalo_bot'" in src


def test_upgrade_delete_gated_by_zalobot002_marker(migration):
    """Only rows the zalobot002 migration seeded are removed — hand-added or
    wizard-added zalo_bot actions carry no marker and survive."""
    src = inspect.getsource(migration.upgrade)
    assert "config->>'seeded_by' = 'zalobot002'" in src


def test_upgrade_delete_scoped_to_system_alert_only(migration):
    """DELETE must be scoped to the system_alert rule — the other 9
    zalobot002 pilot events keep their zalo_bot actions."""
    src = inspect.getsource(migration.upgrade)
    assert "WHERE event = 'system_alert'" in src, (
        "DELETE must restrict rule_id to the system_alert rule via subquery."
    )


# ---------------------------------------------------------------------------
# 3. upgrade — narrow recipient restore (undo Phase 0 only)
# ---------------------------------------------------------------------------


def test_upgrade_restores_all_users_recipient(migration):
    src = inspect.getsource(migration.upgrade)
    assert "UPDATE notification_rule" in src
    assert '"resolver_type": "all_users"' in src


def test_upgrade_recipient_predicate_is_narrow_all_admins(migration):
    """Predicate must match ONLY all_admins (Phase 0 state). A broad
    ``WHERE event='system_alert'`` would clobber a custom resolver an
    operator legitimately set."""
    src = inspect.getsource(migration.upgrade)
    assert "recipient_config->>'resolver_type' = 'all_admins'" in src


def test_upgrade_recipient_cast_is_json_not_jsonb(migration):
    """recipient_config is a JSON column (models/notification.py) — keep
    ``::json``, not ``::jsonb``."""
    src = inspect.getsource(migration.upgrade)
    assert "::json" in src
    assert "::jsonb" not in src


# ---------------------------------------------------------------------------
# 4. downgrade — idempotent re-insert, recipient untouched
# ---------------------------------------------------------------------------


def test_downgrade_reinserts_zalo_bot_idempotently(migration):
    src = inspect.getsource(migration.downgrade)
    assert "INSERT INTO notification_action" in src
    assert "NOT EXISTS" in src, "Re-insert must be guarded to avoid duplicates."
    assert '"seeded_by": "zalobot002"' in src


def test_downgrade_scoped_to_system_alert(migration):
    src = inspect.getsource(migration.downgrade)
    assert "nr.event = 'system_alert'" in src


def test_downgrade_does_not_touch_recipient_config(migration):
    """recipient all_users is the seed default — downgrade must NOT revert it
    (that is not a state needing reversal)."""
    src = inspect.getsource(migration.downgrade)
    assert "UPDATE notification_rule" not in src, (
        "Downgrade must not modify recipient_config."
    )


# ---------------------------------------------------------------------------
# 5. SQL hygiene — literal sa.text, no f-string interpolation
# ---------------------------------------------------------------------------


def test_uses_sa_text_literal_not_fstring(module_src):
    assert "sa.text(" in module_src
    # No f-string op.execute (zalobot002 used f"..."; this migration is clean).
    assert "op.execute(f" not in module_src
    assert 'op.execute(\n            f"' not in module_src
