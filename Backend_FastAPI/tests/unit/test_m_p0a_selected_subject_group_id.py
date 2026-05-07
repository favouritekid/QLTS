"""M-P0a — coverage for `phase0_add_selected_subject_group_id_to_profile`.

Three layers, all unit-level (no real DB run, no Alembic CLI):

1. **Migration revision contract** — the file declares the right
   revision id, the right ``down_revision`` (current head when M-P0a
   was authored), and exposes the canonical name constants used by both
   ``upgrade`` and ``downgrade``.
2. **Migration source idempotency** — ``upgrade`` and ``downgrade`` use
   the ``column_exists`` / ``fk_exists`` / ``index_exists`` helpers to
   guard each operation. Without these, a partial-apply re-run would
   error and the cutover runbook would have to special-case it.
3. **Model contract** — ``AdmissionProfile.selected_subject_group_id``
   exists in the SQLAlchemy table metadata with the right type, FK
   target, ``ondelete="SET NULL"``, nullable, and a backing index. Locks
   the schema decision in code so an accidental rename or relaxed FK
   policy fails loud.

Live ``alembic upgrade`` / ``downgrade`` smoke against a real DB is
deferred to staging clone D12-D14 — these unit tests are enough to lock
the migration shape and the model contract that other Phase 1 / Phase 3
work depends on.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import ForeignKey, Integer

from app.models.admission import AdmissionProfile


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "phase0sg01_add_selected_subject_group_id_to_profile.py"
)


def _load_migration_module() -> ModuleType:
    """Load the migration file by path (alembic versions are not a Python package)."""
    spec = importlib.util.spec_from_file_location(
        "phase0sg01_migration", str(MIGRATION_PATH)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Layer 1: revision chain contract
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def migration_module():
    return _load_migration_module()


def test_migration_revision_id_is_phase0sg01(migration_module):
    assert migration_module.revision == "phase0sg01"


def test_migration_down_revision_is_admstrict01(migration_module):
    """Lock the chain: M-P0a sits directly on top of `admstrict01`.

    If the parent branch advances and a new migration lands before this
    one is merged, the down_revision must be updated to that new head.
    Failing this assertion is the signal that a rebase is needed.
    """
    assert migration_module.down_revision == "admstrict01"


def test_migration_exposes_canonical_name_constants(migration_module):
    """Lock the names the downgrade depends on so a future edit cannot
    silently rename the FK / index and break the reverse path."""
    assert migration_module.TABLE == "admission_profile"
    assert migration_module.COLUMN == "selected_subject_group_id"
    assert migration_module.INDEX_NAME == "ix_admission_profile_selected_subject_group_id"
    assert migration_module.FK_NAME == "fk_admission_profile_selected_subject_group_id"
    assert migration_module.FK_TARGET_TABLE == "subject_group"
    assert migration_module.FK_TARGET_COLUMN == "id"


# ---------------------------------------------------------------------------
# Layer 2: source idempotency guards
# ---------------------------------------------------------------------------


def test_upgrade_uses_idempotent_guards():
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_src = _function_source(src, "upgrade")

    assert "column_exists(TABLE, COLUMN)" in upgrade_src, (
        "upgrade() must guard ADD COLUMN with column_exists() so a "
        "partial-apply re-run is safe"
    )
    assert "fk_exists(TABLE, FK_NAME)" in upgrade_src, (
        "upgrade() must guard CREATE FOREIGN KEY with fk_exists()"
    )
    assert "index_exists(TABLE, INDEX_NAME)" in upgrade_src, (
        "upgrade() must guard CREATE INDEX with index_exists()"
    )
    # SET NULL is the chosen ondelete behaviour — RESTRICT / CASCADE would
    # be a quiet schema-policy regression.
    assert 'ondelete="SET NULL"' in upgrade_src, (
        "ondelete must be SET NULL to match the offering_admission_config_id "
        "FK-traceability convention; CASCADE would erase submitted profiles "
        "when catalog data is cleaned up, RESTRICT would block catalog cleanup"
    )


def test_downgrade_reverses_in_correct_order_with_guards():
    src = MIGRATION_PATH.read_text(encoding="utf-8")
    downgrade_src = _function_source(src, "downgrade")

    # Guards
    assert "index_exists(TABLE, INDEX_NAME)" in downgrade_src
    assert "fk_exists(TABLE, FK_NAME)" in downgrade_src
    assert "column_exists(TABLE, COLUMN)" in downgrade_src

    # Order: drop_index appears before drop_constraint, which appears
    # before drop_column.
    drop_index_pos = downgrade_src.find("op.drop_index(")
    drop_fk_pos = downgrade_src.find("op.drop_constraint(")
    drop_col_pos = downgrade_src.find("op.drop_column(")

    assert -1 < drop_index_pos < drop_fk_pos < drop_col_pos, (
        f"downgrade() must drop index → FK → column (FKs reference the "
        f"column; the column carries the index). "
        f"Got positions: index={drop_index_pos}, fk={drop_fk_pos}, "
        f"col={drop_col_pos}"
    )


def _function_source(module_src: str, function_name: str) -> str:
    """Return the source of a top-level def, including its body."""
    lines = module_src.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith(f"def {function_name}(") or line.startswith(
            f"async def {function_name}("
        ):
            start = i
            break
    assert start is not None, f"function {function_name} not found in source"

    end = len(lines)
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line and not line.startswith((" ", "\t")) and not line.startswith("#"):
            end = j
            break
    return "\n".join(lines[start:end])


# ---------------------------------------------------------------------------
# Layer 3: SQLAlchemy model contract
# ---------------------------------------------------------------------------


def _profile_column():
    cols = AdmissionProfile.__table__.columns
    assert "selected_subject_group_id" in cols, (
        "AdmissionProfile.selected_subject_group_id missing — the model "
        "field must travel with the migration in the same PR"
    )
    return cols["selected_subject_group_id"]


def test_model_column_is_nullable_integer():
    col = _profile_column()
    assert col.nullable is True, (
        "selected_subject_group_id must be nullable — Phase 0 cannot "
        "replay history; existing rows stay valid until Phase 1 #13 "
        "backfills"
    )
    assert isinstance(col.type, Integer), f"expected Integer; got {type(col.type)}"


def test_model_column_has_fk_to_subject_group_id_with_set_null():
    col = _profile_column()
    fks = list(col.foreign_keys)
    assert len(fks) == 1, f"expected exactly 1 FK on column; got {len(fks)}"

    fk: ForeignKey = fks[0]
    target = fk.target_fullname
    assert target == "subject_group.id", (
        f"FK must target subject_group.id; got {target!r}"
    )
    assert fk.ondelete == "SET NULL", (
        f"ondelete must be SET NULL (offering_admission_config_id "
        f"convention); got {fk.ondelete!r}"
    )


def test_model_column_has_backing_index():
    indexes = AdmissionProfile.__table__.indexes
    matched = [
        idx
        for idx in indexes
        if any(c.name == "selected_subject_group_id" for c in idx.columns)
    ]
    assert matched, (
        "selected_subject_group_id must have a backing index — FK columns "
        "are conventionally indexed in this codebase, and the migration "
        "creates ix_admission_profile_selected_subject_group_id"
    )


def test_subject_group_table_target_exists_at_id_column():
    """Catalog-side sanity: the FK target table + column actually exist
    at the names the migration / model use."""
    from app.models.admission_config.subject import SubjectGroup

    assert SubjectGroup.__tablename__ == "subject_group"
    assert "id" in SubjectGroup.__table__.columns
