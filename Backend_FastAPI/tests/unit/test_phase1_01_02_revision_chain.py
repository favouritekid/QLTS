"""Unit tests for #184 Wave 1 PR-1A migrations
(``phase1_01_add_degree_level_fk_to_major_program`` +
``phase1_02_add_bonus_rule_to_method_and_path``).

Pure-text contract tests — locks the revision chain shape, the
upgrade SQL contract, and the model field declarations so a
regression in any of the three surfaces fails CI before the
migration ever runs against a real DB.

What lives here:
1. Revision-row lock — `revision`, `down_revision` for both files.
2. Linear chain shape — ``phase1_19b → phase1_01 → phase1_02``.
3. Backfill SQL contract — phase1_01 must include the per-row
   ``WHERE degree_level_id IS NULL`` idempotency guard, plus the
   ``lower(trim(...))`` JOIN predicate the spec mandates.
4. Bonus-rule shape — phase1_02 adds JSONB columns on both
   ``admission_method`` and ``admission_path``.
5. Model parity — the ORM declarations match the new columns so
   downstream queries see the schema.

What does NOT live here (covered separately):
* End-to-end DDL apply — ``alembic upgrade head`` smoke runs in
  the dev container; fixture-driven integration tests live under
  ``tests/integration/`` and exercise actual data shape.
* Backfill correctness on real data — the dev DB roundtrip
  ``upgrade → downgrade → upgrade`` covers that manually pre-PR;
  CI integration suite covers it post-merge.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Module loading — load each migration as a regular Python module so we can
# pick out ``revision``, ``down_revision``, and inspect the upgrade body
# source directly. Alembic's ``ScriptDirectory.walk_revisions`` is the
# canonical way but it requires the live env; pytest unit scope skips it
# in favor of plain importlib for speed + isolation.
# ---------------------------------------------------------------------------


_VERSIONS_DIR = (
    Path(__file__).resolve().parents[2] / "alembic" / "versions"
)


def _load_migration(filename: str):
    """Import an alembic migration file by stem. Returns the module."""
    path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None, (
        f"Cannot load migration {path}"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_01():
    return _load_migration("phase1_01_add_degree_level_fk_to_major_program.py")


@pytest.fixture
def phase1_02():
    return _load_migration("phase1_02_add_bonus_rule_to_method_and_path.py")


# ---------------------------------------------------------------------------
# 1. Revision-row lock
# ---------------------------------------------------------------------------


def test_phase1_01_revision_id(phase1_01) -> None:
    assert phase1_01.revision == "phase1_01"


def test_phase1_01_down_revision_chains_off_b1(phase1_01) -> None:
    """phase1_01 chains off the chronological head when authored —
    ``phase1_19b`` (B1 Casbin deny-first backfill). PLAN's nominal
    ``phase0 → phase1_01`` ordering refers to *naming intent*; the
    Alembic linear chain follows ship order.
    """
    assert phase1_01.down_revision == "phase1_19b"


def test_phase1_02_revision_id(phase1_02) -> None:
    assert phase1_02.revision == "phase1_02"


def test_phase1_02_down_revision_chains_off_phase1_01(phase1_02) -> None:
    """phase1_02 follows phase1_01 directly per PLAN line 2632."""
    assert phase1_02.down_revision == "phase1_01"


def test_neither_migration_has_branch_labels(phase1_01, phase1_02) -> None:
    """Linear chain — no branching."""
    assert phase1_01.branch_labels is None
    assert phase1_02.branch_labels is None


def test_neither_migration_has_extra_dependencies(phase1_01, phase1_02) -> None:
    """``depends_on`` is for cross-branch dependencies; PR-1A is
    plain linear so both stay None."""
    assert phase1_01.depends_on is None
    assert phase1_02.depends_on is None


# ---------------------------------------------------------------------------
# 2. phase1_01 backfill SQL contract
# ---------------------------------------------------------------------------


def test_phase1_01_adds_degree_level_id_column(phase1_01) -> None:
    """Source must include the ``add_column`` call for
    ``degree_level_id`` — locks the column name + table."""
    src = Path(_VERSIONS_DIR / "phase1_01_add_degree_level_fk_to_major_program.py").read_text()
    assert 'add_column' in src
    assert '"major_program"' in src
    assert '"degree_level_id"' in src


def test_phase1_01_creates_index_on_fk(phase1_01) -> None:
    """FK column needs btree for join queries against
    config_degree_level. Lock the index name + column."""
    src = Path(_VERSIONS_DIR / "phase1_01_add_degree_level_fk_to_major_program.py").read_text()
    assert "ix_major_program_degree_level_id" in src
    assert 'create_index' in src


def test_phase1_01_backfill_uses_lower_trim_join(phase1_01) -> None:
    """Spec mandates JOIN on ``lower(trim(name)) = lower(trim(name))``
    so cosmetic whitespace / casing differences in the legacy text
    column don't drop the row from the backfill."""
    src = Path(_VERSIONS_DIR / "phase1_01_add_degree_level_fk_to_major_program.py").read_text()
    assert "lower(trim(mp.degree_level))" in src
    assert "lower(trim(cdl.name))" in src


def test_phase1_01_backfill_idempotency_guard(phase1_01) -> None:
    """The ``WHERE degree_level_id IS NULL`` per-row guard makes the
    backfill safe to re-run after a partial-replay (PLAN line 2630)."""
    src = Path(_VERSIONS_DIR / "phase1_01_add_degree_level_fk_to_major_program.py").read_text()
    assert "WHERE mp.degree_level_id IS NULL" in src


def test_phase1_01_downgrade_drops_index_then_column(phase1_01) -> None:
    """Inverse order — drop index first (FK constraint cascades on
    column drop). Locks the symmetric DDL surface."""
    src = Path(_VERSIONS_DIR / "phase1_01_add_degree_level_fk_to_major_program.py").read_text()
    drop_idx_pos = src.index('drop_index(\n        "ix_major_program_degree_level_id"')
    drop_col_pos = src.index('drop_column("major_program", "degree_level_id")')
    assert drop_idx_pos < drop_col_pos, (
        "drop_index must precede drop_column in downgrade"
    )


# ---------------------------------------------------------------------------
# 3. phase1_02 bonus_rule contract
# ---------------------------------------------------------------------------


def test_phase1_02_adds_default_bonus_rule_to_method(phase1_02) -> None:
    src = Path(_VERSIONS_DIR / "phase1_02_add_bonus_rule_to_method_and_path.py").read_text()
    # Source must include both add_column calls — admission_method
    # gets the default, admission_path gets the override.
    assert '"admission_method"' in src
    assert '"default_bonus_rule"' in src


def test_phase1_02_adds_bonus_rule_override_to_path(phase1_02) -> None:
    src = Path(_VERSIONS_DIR / "phase1_02_add_bonus_rule_to_method_and_path.py").read_text()
    assert '"admission_path"' in src
    assert '"bonus_rule_override"' in src


def test_phase1_02_columns_use_jsonb_type(phase1_02) -> None:
    """JSONB (not plain JSON) — needed for GIN index support + faster
    containment queries the engine will issue downstream."""
    src = Path(_VERSIONS_DIR / "phase1_02_add_bonus_rule_to_method_and_path.py").read_text()
    assert "from sqlalchemy.dialects.postgresql import JSONB" in src
    assert "JSONB()" in src


def test_phase1_02_no_backfill(phase1_02) -> None:
    """Pure additive — both columns nullable; existing rows keep
    NULL = bonus disabled fallback per the precedence rule. No
    backfill SQL should be in the body."""
    src = Path(_VERSIONS_DIR / "phase1_02_add_bonus_rule_to_method_and_path.py").read_text()
    # ``op.execute(`` is only used for raw SQL; phase1_02 should not
    # have any. (op.add_column doesn't go through execute.)
    assert "op.execute(" not in src


def test_phase1_02_downgrade_drops_path_override_then_method_default(phase1_02) -> None:
    """Inverse insertion order — path override drops before method
    default. No FK between them so order is documentation only."""
    src = Path(_VERSIONS_DIR / "phase1_02_add_bonus_rule_to_method_and_path.py").read_text()
    drop_path_pos = src.index('drop_column("admission_path", "bonus_rule_override")')
    drop_method_pos = src.index('drop_column("admission_method", "default_bonus_rule")')
    assert drop_path_pos < drop_method_pos


# ---------------------------------------------------------------------------
# 4. ORM model parity
# ---------------------------------------------------------------------------


def test_major_program_model_declares_degree_level_id() -> None:
    """ORM must know about the new FK; otherwise downstream queries
    that try to filter / select ``degree_level_id`` get an
    ``AttributeError`` at query construction time."""
    from app.models.major_program import MajorProgram
    assert hasattr(MajorProgram, "degree_level_id")
    column = MajorProgram.__table__.columns["degree_level_id"]
    assert column.nullable is True
    assert column.foreign_keys, "degree_level_id must declare an FK"
    fk = next(iter(column.foreign_keys))
    assert fk.column.table.name == "config_degree_level"
    assert fk.column.name == "id"


def test_admission_method_model_declares_default_bonus_rule() -> None:
    from app.models.admission_config.method import AdmissionMethod
    assert hasattr(AdmissionMethod, "default_bonus_rule")
    column = AdmissionMethod.__table__.columns["default_bonus_rule"]
    assert column.nullable is True
    # Type is JSONB — check via the sqlalchemy dialect class name.
    type_repr = type(column.type).__name__
    assert "JSON" in type_repr.upper(), (
        f"default_bonus_rule type should be JSONB, got {type_repr}"
    )


def test_admission_path_model_declares_bonus_rule_override() -> None:
    from app.models.admission_config.admission_path import AdmissionPath
    assert hasattr(AdmissionPath, "bonus_rule_override")
    column = AdmissionPath.__table__.columns["bonus_rule_override"]
    assert column.nullable is True
    type_repr = type(column.type).__name__
    assert "JSON" in type_repr.upper()


# ---------------------------------------------------------------------------
# 5. Sanity — both migrations import cleanly
# ---------------------------------------------------------------------------


def test_both_migrations_define_upgrade_and_downgrade(phase1_01, phase1_02) -> None:
    """Alembic requires both functions to exist; absence is a
    runtime error during ``alembic upgrade``. Lock the signature
    early so a malformed copy-paste fails CI."""
    for module in (phase1_01, phase1_02):
        assert callable(getattr(module, "upgrade", None))
        assert callable(getattr(module, "downgrade", None))
