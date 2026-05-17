"""Unit tests for ``phase1_08a_rename_bonus_subject_to_object`` migration.

Q9 #07 PR1 — locks the JSONB key rename contract (defensive migration;
verified 0 prod rows have the old key on 2026-05-17). Pure-text +
revision-chain contract tests.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_08A = (
    _VERSIONS_DIR / "phase1_08a_rename_bonus_subject_to_object.py"
)


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_08a():
    return _load_migration(_PHASE1_08A)


# ---------------------------------------------------------------------------
# 1. Revision row + chain
# ---------------------------------------------------------------------------


def test_revision_id_is_phase1_08a(phase1_08a) -> None:
    assert phase1_08a.revision == "phase1_08a"


def test_chains_off_qae2e02(phase1_08a) -> None:
    """qae2e02 is the current head as of 2026-05-17 (QA E2E migrations
    appended after phase1_19e). PR1 picks up from there."""
    assert phase1_08a.down_revision == "qae2e02"


# ---------------------------------------------------------------------------
# 2. Upgrade SQL surface — rename apply_subject_bonus -> apply_object_bonus
# ---------------------------------------------------------------------------


def test_upgrade_renames_key_on_admission_method() -> None:
    src = _PHASE1_08A.read_text(encoding="utf-8")
    # WHERE clause guards both NULL and missing-key (idempotent)
    assert "UPDATE admission_method" in src
    assert "default_bonus_rule IS NOT NULL" in src
    assert "default_bonus_rule ? 'apply_subject_bonus'" in src


def test_upgrade_renames_key_on_admission_path() -> None:
    src = _PHASE1_08A.read_text(encoding="utf-8")
    assert "UPDATE admission_path" in src
    assert "bonus_rule_override IS NOT NULL" in src
    assert "bonus_rule_override ? 'apply_subject_bonus'" in src


def test_upgrade_uses_jsonb_subtract_and_build() -> None:
    """The expression ``(jsonb - 'old') || jsonb_build_object('new', ...)``
    is the canonical PG JSONB rename pattern — atomic single-statement
    rewrite that preserves the value."""
    src = _PHASE1_08A.read_text(encoding="utf-8")
    assert "- 'apply_subject_bonus'" in src
    assert "jsonb_build_object" in src
    assert "'apply_object_bonus'" in src


# ---------------------------------------------------------------------------
# 3. Downgrade — inverse rename
# ---------------------------------------------------------------------------


def test_downgrade_reverses_key_on_both_tables() -> None:
    src = _PHASE1_08A.read_text(encoding="utf-8")
    # downgrade strips the new key and re-adds the old
    assert "- 'apply_object_bonus'" in src
    # The WHERE guard mirrors upgrade — idempotent
    assert "? 'apply_object_bonus'" in src


# ---------------------------------------------------------------------------
# 4. Idempotency — re-running is a no-op once the key is renamed
# ---------------------------------------------------------------------------


def test_upgrade_predicate_is_idempotent_guard() -> None:
    """The WHERE clause requires the OLD key to be present, so a
    second upgrade run finds zero rows matching and silently no-ops.
    Same for downgrade with the new key."""
    src = _PHASE1_08A.read_text(encoding="utf-8")
    # Two upgrade UPDATEs, both guarded
    assert src.count("AND default_bonus_rule ? 'apply_subject_bonus'") == 1
    assert src.count("AND bonus_rule_override ? 'apply_subject_bonus'") == 1
    # Two downgrade UPDATEs, both guarded with the inverse predicate
    assert src.count("AND default_bonus_rule ? 'apply_object_bonus'") == 1
    assert src.count("AND bonus_rule_override ? 'apply_object_bonus'") == 1
