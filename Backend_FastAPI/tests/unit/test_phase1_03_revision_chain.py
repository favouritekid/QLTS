"""Unit tests for #184 Wave 1 PR-1B' migration
(``phase1_03_add_applicable_to_method_quota_to_path``).

Pure-text contract tests — locks the revision chain shape, the
upgrade SQL contract, the GIN index + ENUM type, and the model
field declarations so a regression in any of the four surfaces
fails CI before the migration ever runs against a real DB.

What lives here:
1. Revision-row lock — `revision`, `down_revision`.
2. Linear chain shape — ``phase1_02 → phase1_03``.
3. ENUM type contract — admission_audience with 5 values.
4. Column add contract — applicable_to ARRAY + method_quota int.
5. GIN index lock (load-bearing for query contract per PLAN
   line 2646-2657 — anti-pattern guard test for ``= ANY()`` /
   ``.any()`` lives in test_admission_path_repository_audience.py).
6. ORM model parity — applicable_to + method_quota columns exist.
7. No backfill — pure additive.

What does NOT live here (covered separately):
* End-to-end DDL apply — alembic upgrade smoke runs in dev container.
* Repository operator contract — see
  ``test_admission_path_repository_audience.py``.
* BonusRuleOverride Pydantic shape — see
  ``test_admission_path_schema_bonus_rule_override.py``.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "alembic" / "versions"
_PHASE1_03_FILE = (
    _VERSIONS_DIR / "phase1_03_add_applicable_to_method_quota_to_path.py"
)


def _load_migration(filename: str):
    path = _VERSIONS_DIR / filename
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def phase1_03():
    return _load_migration(_PHASE1_03_FILE.name)


# ---------------------------------------------------------------------------
# 1. Revision-row lock
# ---------------------------------------------------------------------------


def test_phase1_03_revision_id(phase1_03) -> None:
    assert phase1_03.revision == "phase1_03"


def test_phase1_03_down_revision_chains_off_phase1_02(phase1_03) -> None:
    """phase1_03 follows phase1_02 directly per PLAN line 2636 + 3452."""
    assert phase1_03.down_revision == "phase1_02"


def test_phase1_03_no_branch_labels(phase1_03) -> None:
    assert phase1_03.branch_labels is None


def test_phase1_03_no_extra_dependencies(phase1_03) -> None:
    assert phase1_03.depends_on is None


# ---------------------------------------------------------------------------
# 2. ENUM contract — admission_audience with 5 values
# ---------------------------------------------------------------------------


def test_phase1_03_declares_5_audience_values(phase1_03) -> None:
    """Audience values pinned to PLAN line 605-606. Adding a value =
    update migration + BE Literal + FE Zod in lockstep, never
    silently extend via ALTER TYPE."""
    assert phase1_03.ADMISSION_AUDIENCE_VALUES == (
        "POST_THCS",
        "POST_THPT",
        "LIEN_THONG_TC",
        "LIEN_THONG_CD",
        "VLVH",
    )


def test_phase1_03_creates_admission_audience_type() -> None:
    src = _PHASE1_03_FILE.read_text()
    assert 'name="admission_audience"' in src
    assert ".create(op.get_bind(), checkfirst=True)" in src


def test_phase1_03_drops_admission_audience_type_in_downgrade() -> None:
    src = _PHASE1_03_FILE.read_text()
    assert ".drop(op.get_bind(), checkfirst=True)" in src


# ---------------------------------------------------------------------------
# 3. Column add contract
# ---------------------------------------------------------------------------


def test_phase1_03_adds_applicable_to_to_admission_path() -> None:
    src = _PHASE1_03_FILE.read_text()
    assert "add_column" in src
    assert '"admission_path"' in src
    assert '"applicable_to"' in src
    # Column is ARRAY of the audience enum.
    assert "postgresql.ARRAY(audience_enum)" in src


def test_phase1_03_adds_method_quota_to_admission_path() -> None:
    src = _PHASE1_03_FILE.read_text()
    assert '"method_quota"' in src
    # Plain Integer — no length / FK.
    assert "sa.Integer()" in src


def test_phase1_03_columns_are_nullable() -> None:
    """Both columns must stay nullable in Phase 1 — Phase 3 NOT NULL
    swap is a separate migration after the validator gate completes."""
    src = _PHASE1_03_FILE.read_text()
    # Two ``nullable=True`` add_column kwargs (one per column).
    assert src.count("nullable=True") >= 2


# ---------------------------------------------------------------------------
# 4. GIN index lock (load-bearing for query contract)
# ---------------------------------------------------------------------------


def test_phase1_03_creates_gin_index_on_applicable_to() -> None:
    """GIN index is REQUIRED — without it, the ``@>`` / ``&&`` query
    contract still works correctly but burns a seq-scan on every
    storefront audience filter call. PLAN line 2656 mandates
    ``EXPLAIN ANALYZE`` show ``Bitmap Index Scan`` on this index;
    the existence check here is the static guard against accidental
    deletion in a future migration sweep."""
    src = _PHASE1_03_FILE.read_text()
    assert "ix_admission_path_applicable_to" in src
    assert 'postgresql_using="gin"' in src


def test_phase1_03_downgrade_drops_index_first() -> None:
    """Inverse order — index → column → enum. PG would error on
    drop_column if the GIN index still references the column."""
    src = _PHASE1_03_FILE.read_text()
    drop_idx_pos = src.index('drop_index(\n        "ix_admission_path_applicable_to"')
    drop_col_pos = src.index('drop_column("admission_path", "applicable_to")')
    assert drop_idx_pos < drop_col_pos


# ---------------------------------------------------------------------------
# 5. No backfill (pure additive)
# ---------------------------------------------------------------------------


def test_phase1_03_no_op_execute() -> None:
    """Pure additive — both columns nullable, no UPDATE/INSERT
    statements. ``op.execute(`` should not appear."""
    src = _PHASE1_03_FILE.read_text()
    assert "op.execute(" not in src


# ---------------------------------------------------------------------------
# 6. ORM model parity
# ---------------------------------------------------------------------------


def test_admission_path_model_declares_applicable_to() -> None:
    from app.models.admission_config.admission_path import AdmissionPath
    assert hasattr(AdmissionPath, "applicable_to")
    column = AdmissionPath.__table__.columns["applicable_to"]
    assert column.nullable is True
    # Type wraps ARRAY around an ENUM — check the outer container.
    type_repr = type(column.type).__name__
    assert "ARRAY" in type_repr.upper()


def test_admission_path_model_declares_method_quota() -> None:
    from app.models.admission_config.admission_path import AdmissionPath
    assert hasattr(AdmissionPath, "method_quota")
    column = AdmissionPath.__table__.columns["method_quota"]
    assert column.nullable is True
    type_repr = type(column.type).__name__
    assert "INTEGER" in type_repr.upper()


def test_admission_path_unique_constraint_unchanged() -> None:
    """Duplicate-check guard — Codex P1 contract: PR-1B' MUST NOT
    drop the existing ``uq_admission_path_offering_method`` unique
    constraint. Phase 2 swap is a separate migration. If this test
    breaks because someone removed the constraint name, the
    ``DuplicateResourceError`` raised by
    ``admission_path_service:144`` would silently degrade to a DB
    IntegrityError 500 in Phase 1 — bad UX, bad telemetry."""
    from app.models.admission_config.admission_path import AdmissionPath
    constraint_names = {
        c.name for c in AdmissionPath.__table__.constraints
    }
    assert "uq_admission_path_offering_method" in constraint_names


# ---------------------------------------------------------------------------
# 7. Sanity — migration imports cleanly + has both functions
# ---------------------------------------------------------------------------


def test_phase1_03_defines_upgrade_and_downgrade(phase1_03) -> None:
    assert callable(getattr(phase1_03, "upgrade", None))
    assert callable(getattr(phase1_03, "downgrade", None))
