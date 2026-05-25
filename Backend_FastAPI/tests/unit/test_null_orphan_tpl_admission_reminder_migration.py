"""Anchor test for null_orphan_tpl_admission_confirmation_reminder migration.

Locks the migration body so a future PR cannot accidentally:

* widen the WHERE predicate to touch unrelated template_codes
* drop the downgrade restore (rollback symmetry)
* break the chain link off ``sl20260524_canonical``

Pattern-based assertions (no DB needed) — same approach as
``test_phase1_19c5_lowercase_migration.py``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


ALEMBIC_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
MIGRATION_FILE = ALEMBIC_VERSIONS / "null_orphan_tpl_admission_confirmation_reminder.py"


@pytest.fixture(scope="module")
def migration_source() -> str:
    assert MIGRATION_FILE.exists(), f"migration file missing: {MIGRATION_FILE}"
    return MIGRATION_FILE.read_text(encoding="utf-8")


def test_revision_id(migration_source: str) -> None:
    assert re.search(
        r'^revision: str = "null_orphan_admission_reminder_tpl"',
        migration_source, re.M,
    )


def test_down_revision_chains_off_sl20260524_canonical(migration_source: str) -> None:
    assert re.search(
        r'down_revision[^=]*=\s*"sl20260524_canonical"',
        migration_source,
    )


def test_upgrade_targets_exact_two_template_codes(migration_source: str) -> None:
    """Predicate must match exactly the 2 known orphan codes — nothing else."""
    upgrade = migration_source.split("def upgrade()")[1].split("def downgrade()")[0]
    assert "'TPL_ADMISSION_CONFIRMATION_REMINDER_24H_V1'" in upgrade
    assert "'TPL_ADMISSION_CONFIRMATION_REMINDER_6H_V1'" in upgrade
    assert "template_code = NULL" in upgrade
    # Scope guard — must not touch other tables or wider patterns
    forbidden = ("LIKE", "%", "notification_rule", "notification_template", "DELETE")
    for token in forbidden:
        assert token not in upgrade, f"upgrade unexpectedly contains {token!r}"


def test_downgrade_restores_both_codes_with_rule_id_scope(migration_source: str) -> None:
    """Downgrade must use rule_id + channel scope (not blanket UPDATE)."""
    downgrade = migration_source.split("def downgrade()")[1]
    assert "rule_id = 51" in downgrade
    assert "rule_id = 52" in downgrade
    assert "channel = 'email'" in downgrade
    assert "template_code IS NULL" in downgrade  # restore only NULL rows
    assert "TPL_ADMISSION_CONFIRMATION_REMINDER_24H_V1" in downgrade
    assert "TPL_ADMISSION_CONFIRMATION_REMINDER_6H_V1" in downgrade
