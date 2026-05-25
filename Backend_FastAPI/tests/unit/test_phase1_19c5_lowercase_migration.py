"""Anchor test for phase1_19c5 lowercase ADMISSION_* events migration.

Guards the chain integrity fix shipped 2026-05-25. The migration converts
``notification_rule.event`` from UPPERCASE (legacy phase1_19c seed) to
lowercase BEFORE phase3_01's pre-flight assertion runs. Without this
migration in chain, fresh DB scenarios (CI, worktree bootstrap, DR)
crash with::

    RuntimeError: Pre-flight fail: 0/5 system-critical events found
    trong notification_rule.

These tests assert the migration body has the required SQL patterns
without requiring an actual DB connection (pattern-based, fast). They
catch regression if a future PR accidentally:

* changes the predicate to not match UPPERCASE rows (e.g., removes the
  regex anchor)
* drops the downgrade reverse UPDATE
* breaks the chain link by changing phase1_16.down_revision back to
  phase1_19c (bypassing phase1_19c5)

Companion to PR #263 anchor
``test_phase3_01_c1_preflight_event_strings_match_canonical_lowercase``
(asserts phase3_01 checks LOWERCASE strings). Together they lock both
ends of the case-canon contract.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


ALEMBIC_VERSIONS = Path(__file__).resolve().parents[2] / "alembic" / "versions"
MIGRATION_FILE = ALEMBIC_VERSIONS / "phase1_19c5_lowercase_admission_events.py"
PHASE1_16_FILE = ALEMBIC_VERSIONS / "phase1_16_create_archived_admission_profile_table.py"


@pytest.fixture(scope="module")
def migration_source() -> str:
    assert MIGRATION_FILE.exists(), f"migration file missing: {MIGRATION_FILE}"
    return MIGRATION_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def phase1_16_source() -> str:
    assert PHASE1_16_FILE.exists(), f"phase1_16 file missing: {PHASE1_16_FILE}"
    return PHASE1_16_FILE.read_text(encoding="utf-8")


def test_migration_revision_id(migration_source: str) -> None:
    """Revision string must be exactly ``phase1_19c5``."""
    assert re.search(r'^revision: str = "phase1_19c5"', migration_source, re.M), \
        "phase1_19c5 must declare revision='phase1_19c5'"


def test_migration_down_revision_is_phase1_19c(migration_source: str) -> None:
    """down_revision must chain back to phase1_19c (UPPERCASE seed)."""
    assert re.search(r'down_revision[^=]*=\s*"phase1_19c"', migration_source), \
        "phase1_19c5 must chain off phase1_19c (the UPPERCASE seed migration)"


def test_phase1_16_chains_through_phase1_19c5(phase1_16_source: str) -> None:
    """phase1_16 must point to phase1_19c5, not directly back to phase1_19c.

    If a future PR reverts this to ``phase1_19c``, the lowercase
    conversion bypasses and phase3_01 will fail again on fresh DB.
    """
    assert re.search(r'down_revision[^=]*=\s*"phase1_19c5"', phase1_16_source), \
        "phase1_16 must chain through phase1_19c5 — see module docstring"


def test_upgrade_converts_uppercase_to_lowercase(migration_source: str) -> None:
    """UPDATE must use lower(event) with regex anchored predicate ``^ADMISSION_``."""
    assert "lower(event)" in migration_source, \
        "upgrade must contain SET event = lower(event)"
    # Case-sensitive regex anchor — matches UPPERCASE only, never collides with
    # lowercase admission_* events that already exist on prod.
    assert re.search(r"WHERE event ~ '\^ADMISSION_'", migration_source), \
        "upgrade WHERE predicate must be case-sensitive regex ^ADMISSION_"


def test_downgrade_reverses_to_uppercase(migration_source: str) -> None:
    """downgrade must restore UPPERCASE for rollback symmetry."""
    assert "upper(event)" in migration_source, \
        "downgrade must contain SET event = upper(event)"
    assert re.search(r"WHERE event ~ '\^admission_'", migration_source), \
        "downgrade WHERE predicate must match lowercase ^admission_"


def test_only_touches_notification_rule_table(migration_source: str) -> None:
    """Scope guard: migration MUST NOT touch notification_template /
    notification_action / other tables — those are independent cleanup
    (per phase1_19c5 module docstring scope note).
    """
    upgrade_block = migration_source.split("def upgrade()")[1].split("def downgrade()")[0]
    assert "notification_rule" in upgrade_block
    for forbidden in ("notification_template", "notification_action", "lead", "user_account"):
        assert forbidden not in upgrade_block, (
            f"upgrade unexpectedly touches {forbidden!r} — out of scope"
        )
